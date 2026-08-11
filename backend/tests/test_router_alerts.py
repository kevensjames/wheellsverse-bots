"""The router must fire an operator alert on every provider-degradation path.

These tests stub ``alerts.provider_alert`` to record how it's called from each
fallback site, so a regression that silences degradation is caught.
"""
import uuid
from dataclasses import dataclass
from typing import Iterator
from unittest.mock import MagicMock

import pytest

from app.services import alerts
from app.services.router.router import Router
from app.services.router.types import CompletionResult


@dataclass
class MockAdapter:
    name: str
    model: str = "mock-model"

    def complete(self, messages, **kwargs):
        return CompletionResult(
            content=f"reply-{self.name}", adapter=self.name, model=self.model,
            input_tokens=1, output_tokens=1, cost_usd=0.0, latency_ms=1,
        )

    def stream(self, messages, **kwargs) -> Iterator[str]:
        yield "hi"


class BoomAdapter(MockAdapter):
    def complete(self, messages, **kwargs):
        raise RuntimeError(f"boom-{self.name}")

    def stream(self, messages, **kwargs) -> Iterator[str]:
        raise RuntimeError(f"boom-stream-{self.name}")
        yield  # noqa: unreachable — makes this a generator function


@pytest.fixture()
def tracker():
    t = MagicMock()
    t.over_daily_cap.return_value = False
    t.over_monthly_cap.return_value = False
    return t


@pytest.fixture(autouse=True)
def captured_alerts(monkeypatch):
    """Replace provider_alert with a recorder. Router looks the symbol up on
    the module at call time, so this intercepts every call site."""
    calls: list[dict] = []

    def recorder(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(alerts, "provider_alert", recorder)
    return calls


def _registry():
    reg = MagicMock()
    reg.openai_schema.return_value = []
    reg.anthropic_schema.return_value = []
    return reg


def _pairs(calls):
    return [(c["provider"], c["active_fallback"]) for c in calls]


def test_complete_local_failure_alerts(tracker, captured_alerts):
    r = Router(
        adapters={"openai": MockAdapter("openai"), "ollama": BoomAdapter("ollama")},
        spend_tracker=tracker,
    )
    res = r.complete(
        user_id=uuid.uuid4(),
        messages=[{"role": "user", "content": "hello"}],
        prefer_local=True,
    )
    assert res.content == "reply-openai"
    assert ("ollama", "openai") in _pairs(captured_alerts)


def test_complete_total_failure_alerts_no_fallback(tracker, captured_alerts):
    r = Router(
        adapters={"openai": BoomAdapter("openai"), "ollama": BoomAdapter("ollama")},
        spend_tracker=tracker,
    )
    with pytest.raises(RuntimeError):
        r.complete(
            user_id=uuid.uuid4(),
            messages=[{"role": "user", "content": "hello"}],
            prefer_local=True,
        )
    assert ("openai", None) in _pairs(captured_alerts)


def test_complete_cloud_failure_with_no_local_alerts(tracker, captured_alerts):
    # openai fails and there's no ollama to fall back to → complete() re-raises.
    # It must STILL alert (the common cloud-hard-fail path). See finding [1].
    r = Router(adapters={"openai": BoomAdapter("openai")}, spend_tracker=tracker)
    with pytest.raises(RuntimeError):
        r.complete(user_id=uuid.uuid4(), messages=[{"role": "user", "content": "hello"}])
    assert ("openai", None) in _pairs(captured_alerts)


def test_stream_failure_alerts(tracker, captured_alerts):
    r = Router(adapters={"openai": BoomAdapter("openai")}, spend_tracker=tracker)
    with pytest.raises(RuntimeError):
        list(r.stream(user_id=uuid.uuid4(), messages=[{"role": "user", "content": "hello"}]))
    assert ("openai", None) in _pairs(captured_alerts)


def test_chat_tool_failover_alerts(tracker, captured_alerts):
    r = Router(
        adapters={
            "openai": BoomAdapter("openai"),
            "anthropic": MockAdapter("anthropic"),
            "ollama": MockAdapter("ollama"),
        },
        spend_tracker=tracker,
    )
    res = r.chat(
        user_id=uuid.uuid4(),
        messages=[{"role": "user", "content": "hello"}],
        tool_registry=_registry(),
        tool_context=MagicMock(),
    )
    assert res.content == "reply-anthropic"
    assert ("openai", "anthropic") in _pairs(captured_alerts)


def test_chat_degrade_to_local_alerts(tracker, captured_alerts):
    r = Router(
        adapters={
            "openai": BoomAdapter("openai"),
            "anthropic": BoomAdapter("anthropic"),
            "ollama": MockAdapter("ollama"),
        },
        spend_tracker=tracker,
    )
    res = r.chat(
        user_id=uuid.uuid4(),
        messages=[{"role": "user", "content": "hello"}],
        tool_registry=_registry(),
        tool_context=MagicMock(),
    )
    assert res.content == "reply-ollama"
    pairs = _pairs(captured_alerts)
    assert ("openai", "anthropic") in pairs   # cloud→cloud failover
    assert ("anthropic", "ollama") in pairs   # cloud→local degrade (the silent-collapse case)
