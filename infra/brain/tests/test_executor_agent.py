"""Unit + integration tests for ExecutorAgent.

Covers:
  * Constructor clamps max_steps to [1, HARD_MAX_STEPS]
  * "tool" step dispatches to brain.use_tool, errors are isolated per step
  * "think" step calls brain.chat with max_tool_iterations=0
  * Per-step ToolPermissionError / ToolNotFoundError / generic Exception
    paths are recorded with the right ``error_type`` and the run continues
  * max_steps cap truncates oversized plans + records ``truncated`` flag
  * Telemetry: ``step_start`` always fires; exactly one of
    ``step_success``/``step_error`` follows for each step
  * Empty / missing plan → state="failed"; no executor work
"""
from __future__ import annotations

import json

import pytest

from infra.brain.agents.executor import (
    DEFAULT_MAX_STEPS,
    ExecutorAgent,
    HARD_MAX_STEPS,
)
from infra.brain.agents.task import BrainTask, create_task
from infra.brain.tools import register_demo_tools
from infra.brain.tools.registry import Tool, default_registry

from .conftest import make_router_response


# ── Constructor clamps ───────────────────────────────────────────────────────


def test_executor_clamps_max_steps_lower(narai_client):
    e = ExecutorAgent(narai_client, max_steps=0)
    assert e.max_steps == 1  # min clamp


def test_executor_clamps_max_steps_upper(narai_client):
    e = ExecutorAgent(narai_client, max_steps=999)
    assert e.max_steps == HARD_MAX_STEPS  # hard cap


def test_executor_default_max_steps(narai_client):
    e = ExecutorAgent(narai_client)
    assert e.max_steps == DEFAULT_MAX_STEPS == HARD_MAX_STEPS == 10


# ── No-plan / empty-plan fail fast ───────────────────────────────────────────


async def test_executor_fails_when_no_plan(narai_client):
    task = create_task("noop")  # plan is None
    out = await ExecutorAgent(narai_client).run(task)
    assert out.state == "failed"
    assert out.result["error"] == "no_plan"


async def test_executor_fails_on_empty_steps(narai_client):
    task = BrainTask(id="t1", input="noop", plan={"steps": []}, state="planned")
    out = await ExecutorAgent(narai_client).run(task)
    assert out.state == "failed"
    assert out.result["error"] == "empty_plan"


async def test_executor_fails_on_missing_steps_key(narai_client):
    task = BrainTask(id="t1", input="noop", plan={}, state="planned")
    out = await ExecutorAgent(narai_client).run(task)
    assert out.state == "failed"
    # Missing ``steps`` key behaves the same as empty
    assert out.result["error"] == "empty_plan"


# ── Tool-step dispatch ──────────────────────────────────────────────────────


async def test_executor_runs_tool_step_via_use_tool(narai_client):
    """Tool steps must route through ``brain.use_tool`` so the policy gate
    + executor + telemetry chain still fires."""
    register_demo_tools()
    task = BrainTask(
        id="t1", input="x",
        plan={"steps": [
            {"type": "tool", "name": "web_search", "input": {"query": "x", "n": 1}},
        ]},
        state="planned",
    )
    out = await ExecutorAgent(narai_client).run(task)

    assert out.state == "done"
    step = out.result["steps"][0]
    assert step["type"] == "tool"
    assert step["name"] == "web_search"
    assert step["ok"] is True
    assert "results" in step["output"]
    assert "duration_ms" in step

    # Telemetry recorded the step + the underlying tool execution
    events = [e["event_type"] for e in narai_client.telemetry.flush()]
    assert "step_start" in events and "step_success" in events
    assert "tool_start" in events and "tool_success" in events


# ── Tool-step error isolation ───────────────────────────────────────────────


async def test_executor_isolates_tool_exception(permissive_client):
    """Phase B: switched from ``narai_client`` to ``permissive_client``
    because NarAI is now a true allowlist; this test exercises executor
    mechanics with an arbitrary tool name (``broken_tool``) and would
    otherwise be blocked by the policy gate before the kaboom runs."""
    async def _broken(input):
        raise RuntimeError("kaboom")

    default_registry().replace(Tool(
        name="broken_tool",
        description="Always fails (test fixture).",
        run=_broken,
        schema={"type": "object", "properties": {}, "required": []},
    ))

    task = BrainTask(
        id="t1", input="x",
        plan={"steps": [
            {"type": "tool", "name": "broken_tool", "input": {}},
            {"type": "tool", "name": "broken_tool", "input": {}},
        ]},
        state="planned",
    )
    out = await ExecutorAgent(permissive_client).run(task)

    # Both steps recorded; task didn't crash.
    assert out.state == "done"
    assert len(out.result["steps"]) == 2
    for step in out.result["steps"]:
        assert step["ok"] is False
        assert step["error_type"] == "RuntimeError"
        assert "kaboom" in step["error"]

    events = [e["event_type"] for e in permissive_client.telemetry.flush()]
    # step_error fired for both, step_success for neither
    assert events.count("step_error") == 2
    assert "step_success" not in events


async def test_executor_surfaces_permission_error_isolated(nai_client):
    """NAI policy denies tools outside SAFE_TOOLS. Executor records the
    permission failure as a step error and continues."""
    async def _broken(input):
        return {"ok": True}

    default_registry().replace(Tool(
        name="shell_exec",
        description="Restricted (test fixture).",
        run=_broken,
        schema={"type": "object", "properties": {}, "required": []},
    ))

    task = BrainTask(
        id="t1", input="x",
        plan={"steps": [{"type": "tool", "name": "shell_exec", "input": {}}]},
        state="planned",
    )
    out = await ExecutorAgent(nai_client).run(task)

    assert out.state == "done"
    step = out.result["steps"][0]
    assert step["ok"] is False
    assert step["error_type"] == "permission"

    events = [e["event_type"] for e in nai_client.telemetry.flush()]
    assert "tool_denied" in events     # raised by ToolExecutor
    assert "step_error" in events      # propagated up to ExecutorAgent


async def test_executor_surfaces_not_found_error_isolated(narai_client):
    task = BrainTask(
        id="t1", input="x",
        plan={"steps": [{"type": "tool", "name": "no_such_tool", "input": {}}]},
        state="planned",
    )
    out = await ExecutorAgent(narai_client).run(task)
    step = out.result["steps"][0]
    assert step["ok"] is False
    assert step["error_type"] == "not_found"


async def test_executor_handles_unknown_step_type(narai_client):
    task = BrainTask(
        id="t1", input="x",
        plan={"steps": [{"type": "fly_to_moon"}]},
        state="planned",
    )
    out = await ExecutorAgent(narai_client).run(task)
    # Run completes; the step is recorded as failed.
    assert out.state == "done"
    step = out.result["steps"][0]
    assert step["ok"] is False
    # Unknown type → ValueError
    assert step["error_type"] == "ValueError"


async def test_executor_invalid_tool_input_recorded_as_error(narai_client):
    # The non-dict-input guard fires inside ``_run_tool_step`` BEFORE
    # ``use_tool`` is called, so the policy gate is irrelevant here.
    # Stays on ``narai_client`` after Phase B for that reason.
    task = BrainTask(
        id="t1", input="x",
        plan={"steps": [{"type": "tool", "name": "ws", "input": "not-a-dict"}]},
        state="planned",
    )
    out = await ExecutorAgent(narai_client).run(task)
    step = out.result["steps"][0]
    assert step["ok"] is False
    assert step["error_type"] == "ValueError"


# ── Think-step dispatch ──────────────────────────────────────────────────────


async def test_executor_think_step_uses_chat_without_tools(narai_client, router_mock):
    """Think steps must call ``brain.chat`` with ``max_tool_iterations=0``
    so they cannot side-step the executor."""
    router_mock.return_value = make_router_response("here is my answer")
    task = BrainTask(
        id="t1", input="x",
        plan={"steps": [{"type": "think", "content": "summarise"}]},
        state="planned",
    )
    out = await ExecutorAgent(narai_client).run(task)

    assert out.state == "done"
    step = out.result["steps"][0]
    assert step["type"] == "think"
    assert step["ok"] is True
    assert step["output"] == "here is my answer"

    # Inspect the system prompt — the chat-loop's tool-call protocol block
    # must NOT be injected, proving max_tool_iterations=0 took effect.
    sys_prompt = next(
        m for m in router_mock.call_args.kwargs["messages"] if m["role"] == "system"
    )["content"]
    assert "## Tool-call protocol" not in sys_prompt


async def test_executor_think_step_falls_back_to_default_prompt(narai_client, router_mock):
    """Think step without ``content`` must still execute (with a default)."""
    router_mock.return_value = make_router_response("default ok")
    task = BrainTask(
        id="t1", input="x",
        plan={"steps": [{"type": "think"}]},
        state="planned",
    )
    out = await ExecutorAgent(narai_client).run(task)
    assert out.state == "done"
    assert out.result["steps"][0]["ok"] is True


async def test_executor_think_step_includes_prior_step_context(narai_client, router_mock):
    """The second think step must see step 0's output appended to its prompt."""
    register_demo_tools()
    router_mock.return_value = make_router_response("final answer with context")
    task = BrainTask(
        id="t1", input="x",
        plan={"steps": [
            {"type": "tool", "name": "web_search", "input": {"query": "x", "n": 1}},
            {"type": "think", "content": "summarise"},
        ]},
        state="planned",
    )
    await ExecutorAgent(narai_client).run(task)

    # The second router call (think step) gets the context block
    user_msg = router_mock.call_args.kwargs["messages"][-1]
    assert user_msg["role"] == "user"
    assert "Prior step outputs" in user_msg["content"]


# ── max_steps cap ───────────────────────────────────────────────────────────


async def test_executor_truncates_oversized_plan(narai_client, router_mock):
    """A plan with more than ``max_steps`` is truncated; the result records
    the truncation."""
    router_mock.return_value = make_router_response("ok")
    big_plan = {"steps": [{"type": "think", "content": f"s{i}"} for i in range(15)]}
    task = BrainTask(id="t1", input="x", plan=big_plan, state="planned")

    out = await ExecutorAgent(narai_client, max_steps=5).run(task)

    assert out.state == "done"
    assert len(out.result["steps"]) == 5
    assert out.result["truncated"] is True
    assert out.result["original_step_count"] == 15
    assert out.result["max_steps"] == 5


async def test_executor_no_truncation_flag_when_plan_fits(narai_client, router_mock):
    router_mock.return_value = make_router_response("ok")
    task = BrainTask(
        id="t1", input="x",
        plan={"steps": [{"type": "think"}, {"type": "think"}]},
        state="planned",
    )
    out = await ExecutorAgent(narai_client, max_steps=5).run(task)
    assert out.state == "done"
    assert "truncated" not in out.result


# ── Telemetry event ordering ────────────────────────────────────────────────


async def test_executor_telemetry_pairs_step_start_with_outcome(narai_client, router_mock):
    """Every ``step_start`` must be followed by exactly one of
    ``step_success`` / ``step_error`` — the ordering invariant the
    observability layer relies on."""
    async def _broken(input):
        raise RuntimeError("nope")

    default_registry().replace(Tool(
        name="broken_tool",
        description="x", run=_broken,
        schema={"type": "object", "properties": {}, "required": []},
    ))
    register_demo_tools()  # web_search OK
    router_mock.return_value = make_router_response("thinking ok")

    task = BrainTask(
        id="t1", input="x",
        plan={"steps": [
            {"type": "tool", "name": "web_search", "input": {"query": "x", "n": 1}},
            {"type": "tool", "name": "broken_tool", "input": {}},
            {"type": "think", "content": "wrap up"},
        ]},
        state="planned",
    )
    await ExecutorAgent(narai_client).run(task)

    events = [e["event_type"] for e in narai_client.telemetry.flush()]
    step_events = [e for e in events if e.startswith("step_")]
    # Exactly 3 starts, paired with 3 outcomes
    assert step_events.count("step_start") == 3
    assert step_events.count("step_success") + step_events.count("step_error") == 3
    # Walk through and assert pairing
    pending_start = 0
    for e in step_events:
        if e == "step_start":
            pending_start += 1
        else:
            assert pending_start > 0, "outcome without preceding step_start"
            pending_start -= 1
    assert pending_start == 0
