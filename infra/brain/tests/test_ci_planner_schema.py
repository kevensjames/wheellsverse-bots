"""CI contract: planner schema integrity.

The planner output is the entire contract between the LLM and the
executor. If the planner accepts malformed shapes — or if it ever
triggers a tool — the executor's safety guarantees collapse.

These tests drive ``BrainClient.run_task`` end-to-end with crafted LLM
responses that exercise every failure mode of the schema, asserting that
each malformed plan produces ``state="failed"`` with the documented
``invalid_plan`` reason — never an internal crash, and never a tool
invocation.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from infra.brain.interface import BrainClient, Tool, register_tool
from infra.brain.tools.registry import default_registry


pytestmark = pytest.mark.asyncio


def llm_response(content: str, tokens: int = 11):
    r = MagicMock()
    r.choices[0].message.content = content
    r.usage.total_tokens = tokens
    return r


# ── (1) missing "steps" key → state=failed, invalid_plan ──────────────────


async def test_missing_steps_key_fails_with_invalid_plan(narai_client, router_mock):
    bad = json.dumps({"thing": "no steps here"})
    router_mock.return_value = llm_response(bad)
    result = await narai_client.run_task("missing steps")
    assert result is not None
    assert result.state == "failed", (
        f"expected state=failed, got {result.state!r}"
    )
    assert (result.result or {}).get("error") == "invalid_plan"


# ── (2) "steps" not a list → state=failed ─────────────────────────────────


async def test_steps_must_be_list(narai_client, router_mock):
    bad = json.dumps({"steps": "not-a-list"})
    router_mock.return_value = llm_response(bad)
    result = await narai_client.run_task("steps wrong type")
    assert result.state == "failed"
    assert (result.result or {}).get("error") == "invalid_plan"


# ── (3) step missing "type" → state=failed ────────────────────────────────


async def test_step_missing_type_fails(narai_client, router_mock):
    bad = json.dumps({"steps": [{"content": "no type field here"}]})
    router_mock.return_value = llm_response(bad)
    result = await narai_client.run_task("missing type")
    assert result.state == "failed"
    assert (result.result or {}).get("error") == "invalid_plan"


# ── (4) step with unknown "type" → state=failed ───────────────────────────


async def test_step_with_unknown_type_fails(narai_client, router_mock):
    bad = json.dumps({"steps": [{"type": "magic_step", "content": "nope"}]})
    router_mock.return_value = llm_response(bad)
    result = await narai_client.run_task("unknown type")
    assert result.state == "failed"
    assert (result.result or {}).get("error") == "invalid_plan"


# ── (5) malformed JSON (parse failure) → state=failed ─────────────────────


async def test_invalid_json_returns_failed_state(narai_client, router_mock):
    router_mock.return_value = llm_response("definitely not JSON {{{")
    result = await narai_client.run_task("not json")
    assert result is not None, "system must always return a result, even on bad JSON"
    assert result.state == "failed"
    err = (result.result or {}).get("error", "")
    assert "invalid_plan" in err, f"expected invalid_plan, got: {err!r}"


# ── (6) tool step missing "name" → state=failed ───────────────────────────


async def test_tool_step_without_name_fails(narai_client, router_mock):
    bad = json.dumps({"steps": [{"type": "tool", "input": {}}]})
    router_mock.return_value = llm_response(bad)
    result = await narai_client.run_task("tool no name")
    assert result.state == "failed"


# ── (7) tool step with non-dict "input" → state=failed ────────────────────


async def test_tool_step_with_non_dict_input_fails(narai_client, router_mock):
    bad = json.dumps({"steps": [
        {"type": "tool", "name": "x", "input": "should-be-dict"}
    ]})
    router_mock.return_value = llm_response(bad)
    result = await narai_client.run_task("tool bad input")
    assert result.state == "failed"


# ── (8) safety: planner must NEVER trigger a tool ─────────────────────────
#
# Even if the planning LLM emits a raw tool-call envelope, the brain runs
# the planner with max_tool_iterations=0 and the parser has no "steps" key
# to validate against → invalid_plan, with ZERO tool_* events fired.


async def test_planner_tool_envelope_does_not_execute(narai_client, router_mock):
    async def _bad_tool(input):
        raise AssertionError("planner-triggered tool MUST NOT run")

    register_tool(Tool(
        name="must_not_run",
        description="canary tool",
        run=_bad_tool,
        schema={"type": "object", "properties": {}, "required": []},
    ))

    rogue_envelope = json.dumps({"tool": "must_not_run", "input": {}})
    router_mock.return_value = llm_response(rogue_envelope)

    result = await narai_client.run_task("trick the planner")

    assert result.state == "failed", (
        f"planner-emitted tool envelope must not produce a 'done' run; "
        f"got state={result.state!r}"
    )
    assert (result.result or {}).get("error") == "invalid_plan"

    # The architectural invariant: zero tool_* telemetry events fired.
    events = narai_client.telemetry.flush()
    tool_events = [e for e in events if e["event_type"].startswith("tool_")]
    assert not tool_events, (
        f"planner triggered tool execution — architectural safety broken; "
        f"saw tool events: {[e['event_type'] for e in tool_events]}"
    )

    # Exactly one router call (planner only — no executor was reached)
    assert router_mock.await_count == 1, (
        f"expected exactly 1 LLM call (planner only), saw {router_mock.await_count}"
    )


# ── (9) failure must NOT carry a raw traceback in the error reason ────────


async def test_failure_error_is_not_a_raw_traceback(narai_client, router_mock):
    router_mock.return_value = llm_response("garbage")
    result = await narai_client.run_task("garbage planner output")
    err = (result.result or {}).get("error", "")
    assert err, "failed task must carry a non-empty error reason"
    assert "Traceback" not in err, (
        f"raw traceback leaked into result.error: {err!r}"
    )
