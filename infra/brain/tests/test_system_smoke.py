"""Heartbeat smoke test for the full Brain system.

Verifies that BrainClient.run_task → Planner → Executor → Telemetry runs
end-to-end without crashing. Not a correctness test: does NOT assert on
reasoning quality or tool-output accuracy.

The only mock is at the LLM transport boundary (``litellm.acompletion``).
BrainClient, PlannerAgent, ExecutorAgent and the telemetry collector are
all the real implementations.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from infra.brain.interface import BrainClient


pytestmark = pytest.mark.asyncio


SMOKE_INPUT = "Calculate something simple to verify the system works"


def llm_response(content: str, tokens: int = 11):
    """Build a minimal litellm-shaped response object for the router mock."""
    r = MagicMock()
    r.choices[0].message.content = content
    r.usage.total_tokens = tokens
    return r


async def test_brain_system_smoke(narai_client: BrainClient, router_mock):
    """Real BrainClient must complete a task end-to-end with no internal crash."""
    plan = {
        "steps": [
            {"type": "think", "content": "Compute 2 + 2 and reply with the answer."}
        ]
    }
    router_mock.side_effect = [
        llm_response(json.dumps(plan)),   # 1) planner
        llm_response("2 + 2 = 4"),        # 2) executor think step
    ]

    result = await narai_client.run_task(SMOKE_INPUT)

    # ── Result contract ─────────────────────────────────────────────────
    assert result is not None
    assert result.state in {"done", "failed"}
    assert isinstance(result.id, str) and result.id
    assert result.input == SMOKE_INPUT

    # ── Failure safety ──────────────────────────────────────────────────
    if result.state == "failed":
        err = (result.result or {}).get("error", "")
        assert err, "failed task must carry a non-empty error reason"
        assert "Traceback" not in err
        assert "Internal" not in err

    # ── Telemetry contract ──────────────────────────────────────────────
    events = narai_client.telemetry.flush()
    assert events, "run_task must record at least one telemetry event"

    types = {e["event_type"] for e in events}
    assert any(t.startswith("task_") for t in types), (
        f"expected at least one task_* event; saw: {sorted(types)}"
    )
    assert any(t.startswith("plan_") for t in types), (
        f"expected at least one plan_* event; saw: {sorted(types)}"
    )
    if result.state == "done":
        assert any(t.startswith("step_") for t in types), (
            f"a done task must emit at least one step_* event; saw: {sorted(types)}"
        )

    # ── Boundary invariant ──────────────────────────────────────────────
    task_events = [e for e in events if e["event_type"].startswith("task_")]
    assert task_events, "no task_* events recorded"
    assert task_events[0]["event_type"] == "task_start"
    assert task_events[-1]["event_type"] == "task_end"
