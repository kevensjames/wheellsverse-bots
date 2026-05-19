"""Router.chat() tool-loop tests with scripted mock adapters."""
import uuid
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from app.services.router.router import Router
from app.services.router.types import CompletionResult, ToolCallSpec
from app.services.tools.base import ToolContext, ToolLoopExceededError
from app.services.tools.registry import ToolRegistry


class ScriptedAdapter:
    """Adapter whose responses follow a script you provide in order."""
    name = "openai"
    model = "scripted"

    def __init__(self, script: list[CompletionResult]):
        self._script = list(script)
        self._calls = 0

    def complete(self, messages, **kwargs):
        if self._calls >= len(self._script):
            raise RuntimeError("script exhausted")
        result = self._script[self._calls]
        self._calls += 1
        return result

    def stream(self, messages, **kwargs) -> Iterator[str]:
        yield ""


class FakeTool:
    name = "fake"
    description = "fake"
    parameters = {"type": "object", "properties": {}}

    def __init__(self, output: dict):
        self._output = output

    def execute(self, ctx, **kwargs):
        return self._output


@pytest.fixture()
def tracker():
    t = MagicMock()
    t.over_daily_cap.return_value = False
    return t


@pytest.fixture()
def ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def _final(content: str) -> CompletionResult:
    return CompletionResult(
        content=content,
        adapter="openai",
        model="scripted",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0001,
        latency_ms=10,
    )


def _tool_call(name: str, args: dict, call_id: str = "call_1") -> CompletionResult:
    return CompletionResult(
        content="",
        adapter="openai",
        model="scripted",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.0001,
        latency_ms=10,
        tool_calls=[ToolCallSpec(id=call_id, name=name, arguments=args)],
    )


def _router_with(script, tracker):
    adapter = ScriptedAdapter(script)
    adapters = {
        "openai": adapter,
        "anthropic": MagicMock(),
        "perplexity": MagicMock(),
        "ollama": MagicMock(),
    }
    return Router(adapters=adapters, spend_tracker=tracker)


def test_chat_no_tools_returns_immediately(tracker, ctx):
    router = _router_with([_final("hi")], tracker)
    reg = ToolRegistry()
    out = router.chat(
        user_id=ctx.user_id,
        messages=[{"role": "user", "content": "say hi"}],
        tool_registry=reg,
        tool_context=ctx,
    )
    assert out.content == "hi"


def test_chat_executes_tool_then_completes(tracker, ctx):
    script = [
        _tool_call("fake", {"q": 1}, call_id="c1"),
        _final("done"),
    ]
    router = _router_with(script, tracker)
    reg = ToolRegistry()
    reg.register(FakeTool({"answer": 42}))

    out = router.chat(
        user_id=ctx.user_id,
        messages=[{"role": "user", "content": "use the tool"}],
        tool_registry=reg,
        tool_context=ctx,
    )
    assert out.content == "done"
    # Spend logger called twice — one log_result per LLM call
    assert tracker.log_result.call_count == 2


def test_chat_loop_cap_raises(tracker, ctx):
    # 7 tool-call responses, cap is 5 — should raise
    script = [_tool_call("fake", {}, call_id=f"c{i}") for i in range(7)]
    router = _router_with(script, tracker)
    reg = ToolRegistry()
    reg.register(FakeTool({"ok": True}))

    with pytest.raises(ToolLoopExceededError):
        router.chat(
            user_id=ctx.user_id,
            messages=[{"role": "user", "content": "loop forever"}],
            tool_registry=reg,
            tool_context=ctx,
            max_tool_iters=5,
        )


def test_chat_requires_tool_context_when_registry_present(tracker):
    router = _router_with([_final("ok")], tracker)
    reg = ToolRegistry()
    with pytest.raises(ValueError):
        router.chat(
            user_id=uuid.uuid4(),
            messages=[{"role": "user", "content": "hi"}],
            tool_registry=reg,
            tool_context=None,
        )


def test_chat_without_registry_skips_tools(tracker, ctx):
    """No registry → no tool loop, just a single completion."""
    router = _router_with([_final("hello")], tracker)
    out = router.chat(
        user_id=ctx.user_id,
        messages=[{"role": "user", "content": "hi"}],
    )
    assert out.content == "hello"
    assert tracker.log_result.call_count == 1
