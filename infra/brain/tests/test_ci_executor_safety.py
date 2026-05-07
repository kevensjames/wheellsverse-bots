"""CI contract: executor safety isolation.

The executor MUST:
  * be the ONLY component that calls a tool
  * isolate every step's failure (one bad step never aborts the run)
  * always return a result — never let an exception escape ``run_task``
  * cap its own work at HARD_MAX_STEPS (10), regardless of plan size

A regression here means malformed model output or a bad tool can crash
the whole agent runtime. CI MUST fail.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from infra.brain.agents.executor import HARD_MAX_STEPS
from infra.brain.interface import BrainClient, Tool, register_tool


pytestmark = pytest.mark.asyncio


def llm_response(content: str, tokens: int = 11):
    r = MagicMock()
    r.choices[0].message.content = content
    r.usage.total_tokens = tokens
    return r


# ── (1) tool failure does NOT stop the pipeline ────────────────────────────


async def test_tool_failure_does_not_stop_pipeline(narai_client, router_mock):
    async def _broken(input):
        raise RuntimeError("first-step kaboom")

    register_tool(Tool(
        name="broken_tool",
        description="always fails",
        run=_broken,
        schema={"type": "object", "properties": {}, "required": []},
    ))

    plan = {"steps": [
        {"type": "tool", "name": "broken_tool", "input": {}},
        {"type": "think", "content": "Continue regardless of the prior failure."},
    ]}
    router_mock.side_effect = [
        llm_response(json.dumps(plan)),
        llm_response("recovered, here's an answer"),
    ]

    result = await narai_client.run_task("must not stop on tool failure")

    assert result.state == "done", (
        f"task aborted on a single tool failure; state={result.state!r}"
    )
    steps = result.result.get("steps") or []
    assert len(steps) == 2, f"expected 2 steps, got {len(steps)}: {steps}"
    assert steps[0]["ok"] is False, "step 0 should be recorded as failed"
    assert steps[1]["ok"] is True,  "step 1 must still execute after step 0 failure"


# ── (2) run_task must NEVER raise — even on tool exceptions ────────────────


async def test_run_task_never_raises_on_tool_exception(narai_client, router_mock):
    async def _broken(input):
        raise RuntimeError("explosion")

    register_tool(Tool(
        name="explosive_tool",
        description="always fails",
        run=_broken,
        schema={"type": "object", "properties": {}, "required": []},
    ))

    plan = {"steps": [
        {"type": "tool", "name": "explosive_tool", "input": {}},
        {"type": "tool", "name": "explosive_tool", "input": {}},
        {"type": "tool", "name": "explosive_tool", "input": {}},
    ]}
    router_mock.return_value = llm_response(json.dumps(plan))

    # No try/except — this MUST not raise.
    result = await narai_client.run_task("all-failing chain")

    assert result is not None, "run_task must always return a result"
    assert hasattr(result, "state")
    assert result.state in {"done", "failed"}, (
        f"unexpected terminal state after all-failed plan: {result.state!r}"
    )
    # All step records survived; none crashed the run
    steps = (result.result or {}).get("steps") or []
    for s in steps:
        assert s.get("ok") is False, f"unexpected ok=True step in failed chain: {s}"


# ── (3) HARD_MAX_STEPS (10) is enforced regardless of plan size ────────────


async def test_hard_max_steps_enforced(narai_client, router_mock):
    huge_plan = {"steps": [
        {"type": "think", "content": f"step {i}"} for i in range(20)
    ]}
    # planner reply + up to 10 think replies
    router_mock.side_effect = [
        llm_response(json.dumps(huge_plan)),
    ] + [llm_response(f"r{i}") for i in range(15)]

    result = await narai_client.run_task("huge plan")

    assert result.state == "done"
    steps = result.result.get("steps") or []
    assert len(steps) <= HARD_MAX_STEPS, (
        f"executor ran {len(steps)} steps; HARD_MAX_STEPS={HARD_MAX_STEPS} violated"
    )
    assert result.result.get("truncated") is True, (
        f"oversized plan must be flagged truncated; result={result.result!r}"
    )
    assert result.result.get("max_steps") == HARD_MAX_STEPS


# ── (4) max_steps caller-override is also clamped at HARD_MAX_STEPS ───────


async def test_caller_max_steps_override_is_clamped(narai_client, router_mock):
    """Even if a caller asks for max_steps=999, the hard cap must hold."""
    huge_plan = {"steps": [
        {"type": "think", "content": f"step {i}"} for i in range(50)
    ]}
    router_mock.side_effect = [
        llm_response(json.dumps(huge_plan)),
    ] + [llm_response("r") for _ in range(20)]

    result = await narai_client.run_task("massive plan", max_steps=999)
    steps = result.result.get("steps") or []
    assert len(steps) <= HARD_MAX_STEPS, (
        f"max_steps=999 not clamped; ran {len(steps)} steps"
    )


# ── (5) tool execution MUST go through the executor ───────────────────────
#
# When the plan is invalid the executor never runs — and therefore zero
# tool_* events MUST fire even if a tool exists in the registry.


async def test_no_tool_execution_outside_executor(narai_client, router_mock):
    async def _canary(input):
        raise AssertionError("tool ran without the executor")

    register_tool(Tool(
        name="canary_tool",
        description="must never run on a failed-plan path",
        run=_canary,
        schema={"type": "object", "properties": {}, "required": []},
    ))

    router_mock.return_value = llm_response("not a JSON plan")
    result = await narai_client.run_task("invalid plan run")
    assert result.state == "failed"

    events = narai_client.telemetry.flush()
    tool_events = [e for e in events if e["event_type"].startswith("tool_")]
    assert not tool_events, (
        f"tool_* events fired with no executor pass; saw: "
        f"{[e['event_type'] for e in tool_events]}"
    )


# ── (6) result must always be returned (never raw crash) ──────────────────


async def test_run_task_always_returns_result(narai_client, router_mock):
    """Pathological planner output, an empty-string response — the system
    must absorb it and return a typed result."""
    router_mock.return_value = llm_response("")
    result = await narai_client.run_task("pathological")
    assert result is not None
    assert hasattr(result, "state")
    assert result.state in {"done", "failed"}


# ── (7) one step error MUST emit step_error AND allow continuation ────────


async def test_step_error_allows_continuation(narai_client, router_mock):
    async def _broken(input):
        raise RuntimeError("bad")

    register_tool(Tool(
        name="bad_tool",
        description="x",
        run=_broken,
        schema={"type": "object", "properties": {}, "required": []},
    ))

    plan = {"steps": [
        {"type": "tool",  "name": "bad_tool", "input": {}},
        {"type": "think", "content": "Acknowledge and continue."},
    ]}
    router_mock.side_effect = [
        llm_response(json.dumps(plan)),
        llm_response("acknowledged"),
    ]

    result = await narai_client.run_task("error-then-continue")
    assert result.state == "done", (
        f"executor short-circuited on step error; state={result.state!r}"
    )

    events = narai_client.telemetry.flush()
    types = [e["event_type"] for e in events]
    assert "step_error" in types, (
        f"expected step_error to be emitted; saw: {types}"
    )
    # And a step_success must follow (the second step did run)
    err_idx = types.index("step_error")
    later = types[err_idx + 1:]
    assert any(t == "step_success" for t in later), (
        f"no step_success after step_error; later events: {later}"
    )
