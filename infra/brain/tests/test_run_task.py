"""End-to-end tests for ``BrainClient.run_task`` — the full Planner →
Executor → Tools → Brain → Telemetry pipeline.

These tests are the ones that catch regressions across module boundaries:
each scenario exercises planner JSON parsing, executor dispatch, the
policy gate, and telemetry event ordering simultaneously.
"""
from __future__ import annotations

import json

import pytest

from infra.brain.interface import BrainClient
from infra.brain.tools import register_demo_tools
from infra.brain.tools.registry import Tool, default_registry

from .conftest import make_router_response


# ── Happy path ──────────────────────────────────────────────────────────────


async def test_run_task_happy_path(narai_client, router_mock):
    plan = {"steps": [
        {"type": "tool", "name": "web_search", "input": {"query": "AI trends", "n": 2}},
        {"type": "think", "content": "Summarise the search hits"},
    ]}
    router_mock.side_effect = [
        make_router_response(json.dumps(plan)),    # planner
        make_router_response("• AI is everywhere"),  # think
    ]

    register_demo_tools()
    task = await narai_client.run_task("search AI trends and summarise")

    assert task.state == "done"
    assert task.plan is not None
    assert len(task.plan["steps"]) == 2
    assert any(s["type"] == "tool" for s in task.plan["steps"])
    assert len(task.result["steps"]) == 2
    assert task.result["steps"][0]["ok"] is True
    assert task.result["steps"][1]["ok"] is True

    events = [e["event_type"] for e in narai_client.telemetry.flush()]
    # Outer task brackets
    assert events[0] == "task_start"
    assert events[-1] == "task_end"
    # Planner phase
    assert "plan_start" in events and "plan_end" in events
    # Executor phase
    assert events.count("step_start") == 2
    assert events.count("step_success") == 2


# ── Tool failure does NOT crash the task ────────────────────────────────────


async def test_run_task_tool_failure_isolated(narai_client, router_mock):
    async def _broken(input):
        raise RuntimeError("kaboom")

    default_registry().replace(Tool(
        name="broken_tool",
        description="Always fails.",
        run=_broken,
        schema={"type": "object", "properties": {}, "required": []},
    ))

    plan = {"steps": [
        {"type": "tool", "name": "broken_tool", "input": {}},
        {"type": "think", "content": "Recover and answer"},
    ]}
    router_mock.side_effect = [
        make_router_response(json.dumps(plan)),
        make_router_response("Recovering — here's a plain answer"),
    ]
    task = await narai_client.run_task("call the broken thing")

    assert task.state == "done"  # task survived
    assert task.result["steps"][0]["ok"] is False
    assert task.result["steps"][0]["error_type"] == "RuntimeError"
    assert task.result["steps"][1]["ok"] is True

    events = [e["event_type"] for e in narai_client.telemetry.flush()]
    assert "step_error" in events
    assert "step_success" in events
    assert events[-1] == "task_end"


# ── max_steps enforcement at the run_task level ────────────────────────────


async def test_run_task_truncates_oversized_plan(narai_client, router_mock):
    big = {"steps": [{"type": "think", "content": f"s{i}"} for i in range(15)]}
    router_mock.side_effect = [
        make_router_response(json.dumps(big)),
    ] + [make_router_response("ok")] * 12

    task = await narai_client.run_task("many steps", max_steps=10)

    assert task.state == "done"
    assert len(task.result["steps"]) == 10
    assert task.result["truncated"] is True
    assert task.result["original_step_count"] == 15
    assert task.result["max_steps"] == 10

    # task_end metadata reflects truncation
    events = narai_client.telemetry.flush()
    end_event = events[-1]
    assert end_event["event_type"] == "task_end"
    assert end_event["metadata"].get("truncated") is True


# ── Invalid plan: executor never runs ──────────────────────────────────────


async def test_run_task_invalid_plan_short_circuits(narai_client, router_mock):
    router_mock.return_value = make_router_response("not even close to JSON")
    task = await narai_client.run_task("anything")

    assert task.state == "failed"
    assert task.result["error"] == "invalid_plan"

    events = [e["event_type"] for e in narai_client.telemetry.flush()]
    # Planner ran; executor did not
    assert "plan_start" in events and "plan_end" in events
    assert "step_start" not in events
    assert events[-1] == "task_end"
    # Exactly one router call (planner only)
    assert router_mock.await_count == 1


# ── Safety: planner cannot trigger tools ────────────────────────────────────


async def test_run_task_planner_cannot_trigger_tools(narai_client, router_mock):
    """Even if the planning LLM emits what looks like a tool-call envelope,
    the brain must treat it as content (max_tool_iterations=0) and the
    parser rejects it because it has no "steps" key.

    Outcome: state=failed, zero tool_* telemetry events, exactly 1 router call.
    """
    async def _bad(input):
        raise AssertionError("tool must NOT run")

    default_registry().replace(Tool(
        name="rogue",
        description="must not run",
        run=_bad,
        schema={"type": "object", "properties": {}, "required": []},
    ))

    rogue = '{"tool": "rogue", "input": {}}'
    router_mock.return_value = make_router_response(rogue)

    task = await narai_client.run_task("trick the planner")
    events = [e["event_type"] for e in narai_client.telemetry.flush()]

    assert task.state == "failed"
    assert task.result["error"] == "invalid_plan"
    # Architecturally: zero tool events fired
    assert not any(e.startswith("tool_") for e in events)
    # Single router call — planner only
    assert router_mock.await_count == 1


# ── Safety: NAI policy denial flows through to step error ──────────────────


async def test_run_task_policy_denial_recorded_at_step_level(nai_client, router_mock):
    """NAI policy denies tools outside SAFE_TOOLS. The agent runtime must
    surface the denial as a step_error and continue."""
    async def _shell(input):
        return {"out": "should not run"}

    default_registry().replace(Tool(
        name="shell_exec",
        description="restricted",
        run=_shell,
        schema={"type": "object", "properties": {}, "required": []},
    ))

    plan = {"steps": [
        {"type": "tool", "name": "shell_exec", "input": {}},
        {"type": "think", "content": "explain why I can't"},
    ]}
    router_mock.side_effect = [
        make_router_response(json.dumps(plan)),
        make_router_response("I can't run shell commands here."),
    ]

    task = await nai_client.run_task("list files")
    assert task.state == "done"
    assert task.result["steps"][0]["ok"] is False
    assert task.result["steps"][0]["error_type"] == "permission"
    assert task.result["steps"][1]["ok"] is True

    events = [e["event_type"] for e in nai_client.telemetry.flush()]
    assert "tool_denied" in events  # ToolExecutor side
    assert "step_error" in events   # ExecutorAgent side


# ── Backwards compatibility with chat / use_tool ────────────────────────────


async def test_run_task_does_not_break_chat(narai_client, router_mock):
    """Adding run_task must not change chat()'s shape."""
    router_mock.return_value = make_router_response("plain reply")
    out = await narai_client.chat("hello", use_memory=False, use_rag=False)
    assert {"content", "model", "tokens", "tier", "tool_calls", "iterations"} <= set(out.keys())
    assert out["tool_calls"] == []
    assert out["iterations"] == 0


async def test_run_task_does_not_break_use_tool(narai_client):
    register_demo_tools()
    out = await narai_client.use_tool("web_search", {"query": "wheels", "n": 1})
    assert out["query"] == "wheels"
    assert len(out["results"]) == 1


# ── State machine progression observable via task snapshots ────────────────


async def test_run_task_state_transitions_visible(narai_client, router_mock):
    """Frozen-task design: each stage is observable via the returned object.
    ``state="done"`` only at the very end; the result carries the per-step
    history."""
    plan = {"steps": [{"type": "think", "content": "x"}]}
    router_mock.side_effect = [
        make_router_response(json.dumps(plan)),
        make_router_response("answer"),
    ]
    task = await narai_client.run_task("hi")
    assert task.state == "done"
    assert task.input == "hi"
    assert task.plan is not None
    assert task.result is not None
    assert task.id and len(task.id) == 12  # uuid4().hex[:12]
