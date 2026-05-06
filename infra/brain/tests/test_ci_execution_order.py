"""CI contract: execution-pipeline ordering.

The Brain pipeline MUST emit events in this strict order::

    task_start
      → plan_start / plan_end
        → step_start / (step_success | step_error)
          → ... (more steps)
      → task_end

Any deviation indicates the planner-executor-telemetry plumbing is broken.
A single CI failure here usually means a refactor changed an event order
or skipped a stage.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from infra.brain.interface import BrainClient


pytestmark = pytest.mark.asyncio


def llm_response(content: str, tokens: int = 11):
    r = MagicMock()
    r.choices[0].message.content = content
    r.usage.total_tokens = tokens
    return r


def _types(events):
    return [e["event_type"] for e in events]


def _index_of(types, name):
    """Return first index of ``name`` in ``types``; -1 if absent."""
    return next((i for i, t in enumerate(types) if t == name), -1)


# ── Setup helpers (one valid plan, one invalid plan) ───────────────────────


async def _run_valid(client: BrainClient, router_mock):
    plan = {"steps": [
        {"type": "think", "content": "Step one."},
        {"type": "think", "content": "Step two."},
    ]}
    router_mock.side_effect = [
        llm_response(json.dumps(plan)),
        llm_response("first"),
        llm_response("second"),
    ]
    result = await client.run_task("ordering check — valid plan")
    return result, client.telemetry.flush()


async def _run_invalid_plan(client: BrainClient, router_mock):
    router_mock.return_value = llm_response("not even close to JSON")
    result = await client.run_task("ordering check — invalid plan")
    return result, client.telemetry.flush()


# ── (1) full pipeline order: task → plan → step → task_end ─────────────────


async def test_pipeline_order_strict(narai_client, router_mock):
    result, events = await _run_valid(narai_client, router_mock)
    assert result.state == "done", f"valid plan did not complete (state={result.state!r})"
    types = _types(events)

    i_task_start = _index_of(types, "task_start")
    i_plan_start = _index_of(types, "plan_start")
    i_plan_end   = _index_of(types, "plan_end")
    i_step_start = _index_of(types, "step_start")
    i_task_end   = _index_of(types, "task_end")

    assert i_task_start >= 0, "missing task_start"
    assert i_plan_start >= 0, "missing plan_start"
    assert i_plan_end   >= 0, "missing plan_end"
    assert i_step_start >= 0, "missing step_start"
    assert i_task_end   >= 0, "missing task_end"

    assert i_task_start < i_plan_start, "plan_start fired before task_start"
    assert i_plan_start < i_plan_end,   "plan_end fired before plan_start"
    assert i_plan_end   < i_step_start, "step_start fired before plan_end"
    assert i_step_start < i_task_end,   "task_end fired before step_start"


# ── (2) step events MUST NEVER precede plan events ────────────────────────


async def test_step_events_never_precede_plan_events(narai_client, router_mock):
    result, events = await _run_valid(narai_client, router_mock)
    types = _types(events)
    first_plan = next((i for i, t in enumerate(types) if t.startswith("plan_")), -1)
    first_step = next((i for i, t in enumerate(types) if t.startswith("step_")), -1)
    if first_step >= 0:
        assert first_plan >= 0 and first_plan < first_step, (
            f"step_* event at index {first_step} preceded plan_* events; "
            f"order violation in: {types}"
        )


# ── (3) exactly one task_start per run ─────────────────────────────────────


async def test_exactly_one_task_start_per_run(narai_client, router_mock):
    result, events = await _run_valid(narai_client, router_mock)
    types = _types(events)
    n = sum(1 for t in types if t == "task_start")
    assert n == 1, f"expected exactly 1 task_start event, saw {n}: {types}"


# ── (4) exactly one task_end per run ───────────────────────────────────────


async def test_exactly_one_task_end_per_run(narai_client, router_mock):
    result, events = await _run_valid(narai_client, router_mock)
    types = _types(events)
    n = sum(1 for t in types if t == "task_end")
    assert n == 1, f"expected exactly 1 task_end event, saw {n}: {types}"


# ── (5) executor MUST NOT run when the plan is invalid ─────────────────────


async def test_executor_does_not_run_without_valid_plan(narai_client, router_mock):
    result, events = await _run_invalid_plan(narai_client, router_mock)
    assert result.state == "failed", (
        f"invalid plan must fail-state, got state={result.state!r}"
    )
    types = _types(events)
    step_events = [t for t in types if t.startswith("step_")]
    assert not step_events, (
        f"executor ran even though plan was invalid; saw step events: {step_events}"
    )
    # task_end must still fire — failure-path lifecycle
    assert "task_end" in types, (
        f"invalid-plan run did not emit task_end; saw: {types}"
    )


# ── (6) task_end appears AFTER all step events when plan is valid ──────────


async def test_task_end_after_all_step_events(narai_client, router_mock):
    result, events = await _run_valid(narai_client, router_mock)
    types = _types(events)
    last_step = max(
        (i for i, t in enumerate(types) if t.startswith("step_")), default=-1
    )
    i_task_end = _index_of(types, "task_end")
    if last_step >= 0:
        assert last_step < i_task_end, (
            f"task_end at {i_task_end} fired before last step_* at {last_step}: {types}"
        )
