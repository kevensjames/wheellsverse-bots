"""CI contract: telemetry integrity.

Strict invariants the telemetry layer MUST honour. Every test drives the
pipeline end-to-end via ``BrainClient.run_task`` and only stubs
``litellm.acompletion`` — no other component is mocked.

A breakage here means the observability layer is silently lying. CI MUST
fail immediately.
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


# ── Helper: drive one full run with a deterministic plan + think reply ─────


async def _run_simple(client: BrainClient, router_mock) -> tuple:
    plan = {"steps": [
        {"type": "think", "content": "Reply with a one-line answer."}
    ]}
    router_mock.side_effect = [
        llm_response(json.dumps(plan)),
        llm_response("answer"),
    ]
    result = await client.run_task("heartbeat task")
    return result, client.telemetry.flush()


# ── (1) task_start must appear FIRST among task events ─────────────────────


async def test_task_start_appears_first(narai_client, router_mock):
    result, events = await _run_simple(narai_client, router_mock)
    task_events = [e for e in events if e["event_type"].startswith("task_")]
    assert task_events, "no task_* events recorded"
    assert task_events[0]["event_type"] == "task_start", (
        f"first task_* event must be task_start; got: {task_events[0]['event_type']!r}"
    )


# ── (2) task_end must appear LAST among task events ────────────────────────


async def test_task_end_appears_last(narai_client, router_mock):
    result, events = await _run_simple(narai_client, router_mock)
    task_events = [e for e in events if e["event_type"].startswith("task_")]
    assert task_events, "no task_* events recorded"
    assert task_events[-1]["event_type"] == "task_end", (
        f"last task_* event must be task_end; got: {task_events[-1]['event_type']!r}"
    )


# ── (3) plan_* events MUST exist ───────────────────────────────────────────


async def test_plan_events_must_exist(narai_client, router_mock):
    result, events = await _run_simple(narai_client, router_mock)
    plan_events = [e for e in events if e["event_type"].startswith("plan_")]
    assert plan_events, (
        f"missing plan_* events; saw types: "
        f"{sorted({e['event_type'] for e in events})}"
    )
    types = {e["event_type"] for e in plan_events}
    assert "plan_start" in types, "plan_start MUST fire on every run_task"
    assert "plan_end" in types, "plan_end MUST fire on every run_task"


# ── (4) step_* events MUST exist when state == "done" ──────────────────────


async def test_step_events_required_when_done(narai_client, router_mock):
    result, events = await _run_simple(narai_client, router_mock)
    if result.state != "done":
        pytest.fail(f"smoke run did not complete (state={result.state!r}); "
                    f"telemetry contract cannot be verified")
    step_events = [e for e in events if e["event_type"].startswith("step_")]
    assert step_events, (
        f"a 'done' task MUST emit at least one step_* event; "
        f"saw types: {sorted({e['event_type'] for e in events})}"
    )


# ── (5) every event MUST be a non-empty dict with a non-empty event_type ───


async def test_event_shape_is_well_formed(narai_client, router_mock):
    result, events = await _run_simple(narai_client, router_mock)
    for i, e in enumerate(events):
        assert isinstance(e, dict), f"event[{i}] is {type(e).__name__}, expected dict"
        assert e, f"event[{i}] is an empty dict"
        assert "event_type" in e, f"event[{i}] missing 'event_type' key: {e!r}"
        et = e["event_type"]
        assert isinstance(et, str) and et.strip(), (
            f"event[{i}] has malformed event_type: {et!r}"
        )
        # core fields demanded by the Event schema
        for required_key in ("user_id", "mode", "timestamp", "metadata"):
            assert required_key in e, (
                f"event[{i}] ({et!r}) missing required key {required_key!r}: {e!r}"
            )


# ── (6) telemetry MUST record at least one event for any run_task ──────────


async def test_telemetry_records_at_least_one_event(narai_client, router_mock):
    result, events = await _run_simple(narai_client, router_mock)
    assert events, (
        "telemetry recorded zero events for a run_task call — "
        "the observability layer is broken"
    )
