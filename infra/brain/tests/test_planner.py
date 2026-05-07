"""Unit + integration tests for the PlannerAgent and its JSON validator."""
from __future__ import annotations

import json

import pytest

from infra.brain.agents.planner import (
    ALLOWED_STEP_TYPES,
    MAX_PLAN_STEPS,
    PlannerAgent,
    parse_plan,
)
from infra.brain.agents.task import create_task
from infra.brain.tools import register_demo_tools
from infra.brain.tools.registry import default_registry

from .conftest import make_router_response


# ── parse_plan: positive cases ──────────────────────────────────────────────


def test_parse_plan_minimal():
    plan = parse_plan('{"steps": [{"type": "think", "content": "go"}]}')
    assert plan == {"steps": [{"type": "think", "content": "go"}]}


def test_parse_plan_tool_step():
    plan = parse_plan(
        '{"steps": [{"type": "tool", "name": "web_search", "input": {"q": "x"}}]}'
    )
    assert plan == {
        "steps": [{"type": "tool", "name": "web_search", "input": {"q": "x"}}]
    }


def test_parse_plan_strips_tool_name_whitespace():
    plan = parse_plan('{"steps": [{"type": "tool", "name": "  ws  ", "input": {}}]}')
    assert plan["steps"][0]["name"] == "ws"


def test_parse_plan_tool_input_defaults_to_empty_dict_when_missing():
    plan = parse_plan('{"steps": [{"type": "tool", "name": "ws"}]}')
    assert plan["steps"][0]["input"] == {}


def test_parse_plan_think_content_aliased_from_prompt():
    """Legacy planners using ``"prompt"`` still parse — normalised to ``"content"``."""
    plan = parse_plan('{"steps": [{"type": "think", "prompt": "reason"}]}')
    assert plan["steps"][0] == {"type": "think", "content": "reason"}


def test_parse_plan_accepts_code_fence():
    body = '{"steps": [{"type": "think", "content": "x"}]}'
    plan = parse_plan(f"```json\n{body}\n```")
    assert plan["steps"][0]["type"] == "think"


def test_parse_plan_accepts_embedded_json_with_preamble():
    plan = parse_plan(
        'Here is the plan: {"steps": [{"type": "think", "content": "x"}]} done.'
    )
    assert plan is not None and plan["steps"][0]["type"] == "think"


def test_parse_plan_preserves_full_step_list():
    """Truncation is the executor's responsibility, not the parser's."""
    body = json.dumps({"steps": [{"type": "think"} for _ in range(15)]})
    plan = parse_plan(body)
    assert len(plan["steps"]) == 15


# ── parse_plan: negative cases ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "",                                     # empty
        "  ",                                   # whitespace
        "not json at all",
        '{"foo": "bar"}',                       # missing steps
        '{"steps": "string-not-list"}',         # steps must be list
        '{"steps": []}',                        # empty steps invalid
        '{"steps": [42]}',                      # non-dict step
        '{"steps": [{"type": "magic"}]}',       # unknown type
        '{"steps": [{"type": "tool"}]}',        # tool without name
        '{"steps": [{"type": "tool", "name": ""}]}',           # empty name
        '{"steps": [{"type": "tool", "name": 42}]}',           # non-string name
        '{"steps": [{"type": "tool", "name": "x", "input": 1}]}',  # input not dict
    ],
)
def test_parse_plan_rejects_invalid(raw):
    assert parse_plan(raw) is None


def test_parse_plan_returns_none_on_unbalanced_json_braces():
    assert parse_plan('{"steps": [{"type": "think"]}') is None


# ── Constants ───────────────────────────────────────────────────────────────


def test_max_plan_steps_advertised_in_prompt():
    """The advertised cap is part of the planner's public contract."""
    assert MAX_PLAN_STEPS == 10
    assert ALLOWED_STEP_TYPES == frozenset({"tool", "think"})


# ── PlannerAgent integration — uses brain.chat with mocked router ───────────


async def test_planner_emits_plan_and_attaches_to_task(narai_client, router_mock):
    plan = {"steps": [
        {"type": "tool", "name": "web_search", "input": {"query": "x"}},
        {"type": "think", "content": "summarise"},
    ]}
    router_mock.return_value = make_router_response(json.dumps(plan))

    register_demo_tools()  # ensure web_search is in the catalog
    task = create_task("find AI news")
    result = await PlannerAgent(narai_client).plan(task)

    assert result.state == "planned"
    assert result.plan is not None
    assert len(result.plan["steps"]) == 2
    assert result.plan["steps"][0]["name"] == "web_search"
    # Telemetry recorded plan_start + plan_end
    events = [e["event_type"] for e in narai_client.telemetry.flush()]
    assert "plan_start" in events
    assert "plan_end" in events


async def test_planner_marks_task_failed_on_invalid_json(narai_client, router_mock):
    router_mock.return_value = make_router_response("just prose, no JSON")
    task = create_task("anything")
    result = await PlannerAgent(narai_client).plan(task)

    assert result.state == "failed"
    assert result.result is not None
    assert result.result["error"] == "invalid_plan"
    assert "raw" in result.result


async def test_planner_system_prompt_reaches_router(narai_client, router_mock):
    """The planner's system prompt must reach the LLM. We inspect the
    actual messages litellm received — that's what matters, regardless of
    how the planner builds the call."""
    plan = {"steps": [{"type": "think", "content": "noop"}]}
    router_mock.return_value = make_router_response(json.dumps(plan))

    await PlannerAgent(narai_client).plan(create_task("hi"))

    # Inspect the system message that ended up at litellm
    messages = router_mock.call_args.kwargs["messages"]
    system_msg = next((m for m in messages if m["role"] == "system"), None)
    assert system_msg is not None
    assert "task planner" in system_msg["content"].lower()
    # Output protocol explicitly described
    assert '"steps"' in system_msg["content"]


async def test_planner_advertises_authorized_tools(narai_client, router_mock):
    """Planner-visible tools must appear in the system prompt so the LLM
    knows what to plan against."""
    register_demo_tools()
    plan = {"steps": [{"type": "think", "content": "noop"}]}
    router_mock.return_value = make_router_response(json.dumps(plan))

    await PlannerAgent(narai_client).plan(create_task("hi"))

    sys_prompt = next(
        m for m in router_mock.call_args.kwargs["messages"] if m["role"] == "system"
    )["content"]
    assert "web_search" in sys_prompt


async def test_planner_disables_tool_loop(narai_client, router_mock):
    """Architectural safety: the planner must NEVER trigger a tool. The
    proof is the system prompt — when ``max_tool_iterations=0``, ``chat``
    omits the tool catalog block (``## Tools`` from build_tool_use_prompt).
    Only the planner's own catalog should be present."""
    register_demo_tools()
    plan = {"steps": [{"type": "think", "content": "noop"}]}
    router_mock.return_value = make_router_response(json.dumps(plan))

    await PlannerAgent(narai_client).plan(create_task("hi"))
    sys_prompt = next(
        m for m in router_mock.call_args.kwargs["messages"] if m["role"] == "system"
    )["content"]

    # The planner has its own tool catalog ("## Available tools") but the
    # chat-loop's tool-use block ("## Tool-call protocol") must NOT be
    # injected, since that would arm the loop. Their absence is the
    # observable sign that max_tool_iterations=0 took effect.
    assert "## Available tools" in sys_prompt
    assert "## Tool-call protocol" not in sys_prompt


async def test_planner_records_latency_histogram(narai_client, router_mock):
    plan = {"steps": [{"type": "think", "content": "noop"}]}
    router_mock.return_value = make_router_response(json.dumps(plan))

    await PlannerAgent(narai_client).plan(create_task("hi"))
    lat = narai_client.telemetry.get_stats()["latencies_ms"]
    assert "plan" in lat
    assert lat["plan"]["count"] >= 1
