"""Property-based fuzz tests for the LLM-output parsers.

Both ``parse_tool_call`` and ``parse_plan`` consume untrusted strings (LLM
output, sometimes with prompt injection attempts). The contract is:

  * The function MUST NOT raise on any input.
  * If it returns a value, that value MUST be valid (well-formed shape).
  * If it returns ``None``, the input is treated as a final answer.

We use Hypothesis to fuzz arbitrary text and structured-but-mutated JSON
shapes against those invariants.
"""
from __future__ import annotations

import json

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from infra.brain.agents.planner import ALLOWED_STEP_TYPES, parse_plan
from infra.brain.tools.agent_loop import ToolCall, parse_tool_call


# Hypothesis runs many examples per test; bump deadline + suppress the
# function-scope-fixture warning since these tests don't use fixtures.
SETTINGS = settings(
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
    max_examples=200,
)


# ── Strategies ──────────────────────────────────────────────────────────────


# Arbitrary text — including unicode, control chars, lone braces, etc.
arbitrary_text = st.text(max_size=2000)


# Deliberately malformed JSON-shaped text: balanced braces with random innards.
malformed_json = st.builds(
    lambda head, body, tail: f"{head}{{{body}}}{tail}",
    head=st.text(max_size=80),
    body=st.text(max_size=200),
    tail=st.text(max_size=80),
)


# A JSON-encoded *tool-call* envelope, possibly with extra junk fields.
def _valid_tool_call_strategy():
    name = st.text(
        min_size=1, max_size=40,
        alphabet=st.characters(min_codepoint=33, max_codepoint=126,
                               blacklist_characters='"\\')
    ).filter(lambda s: s.strip() != "")
    input_dict = st.dictionaries(
        keys=st.text(min_size=1, max_size=20,
                     alphabet=st.characters(min_codepoint=97, max_codepoint=122)),
        values=st.one_of(
            st.text(max_size=50), st.integers(), st.booleans(), st.none()
        ),
        max_size=5,
    )
    extra = st.dictionaries(
        keys=st.text(min_size=1, max_size=10).filter(
            lambda s: s not in ("tool", "input")
        ),
        values=st.text(max_size=20),
        max_size=2,
    )

    @st.composite
    def build(draw):
        envelope = {"tool": draw(name), "input": draw(input_dict)}
        envelope.update(draw(extra))
        return envelope

    return build()


valid_tool_call_dict = _valid_tool_call_strategy()


# A JSON-encoded plan with valid-shape steps.
def _valid_plan_strategy():
    name = st.text(
        min_size=1, max_size=20,
        alphabet=st.characters(min_codepoint=97, max_codepoint=122),
    )
    tool_step = st.fixed_dictionaries({
        "type": st.just("tool"),
        "name": name,
        "input": st.dictionaries(
            keys=st.text(min_size=1, max_size=10,
                         alphabet=st.characters(min_codepoint=97, max_codepoint=122)),
            values=st.text(max_size=20),
            max_size=3,
        ),
    })
    think_step = st.fixed_dictionaries({
        "type": st.just("think"),
        "content": st.text(min_size=1, max_size=80),
    })
    return st.fixed_dictionaries({
        "steps": st.lists(st.one_of(tool_step, think_step), min_size=1, max_size=12),
    })


valid_plan_dict = _valid_plan_strategy()


# ── parse_tool_call invariants ──────────────────────────────────────────────


@given(arbitrary_text)
@SETTINGS
def test_parse_tool_call_never_raises_on_arbitrary_text(s):
    """Property: bad model output must never crash the chat loop."""
    out = parse_tool_call(s)
    assert out is None or isinstance(out, ToolCall)


@given(malformed_json)
@SETTINGS
def test_parse_tool_call_never_raises_on_malformed_json(s):
    out = parse_tool_call(s)
    assert out is None or isinstance(out, ToolCall)


@given(valid_tool_call_dict)
@SETTINGS
def test_parse_tool_call_round_trips_valid_envelopes(envelope):
    """Any valid envelope round-trips through json.dumps + parse_tool_call."""
    raw = json.dumps(envelope)
    out = parse_tool_call(raw)
    assert isinstance(out, ToolCall)
    assert out.name == envelope["tool"].strip()
    assert out.input == envelope["input"]


@given(valid_tool_call_dict)
@SETTINGS
def test_parse_tool_call_returns_strict_shape(envelope):
    """If parse_tool_call returns a ToolCall, name is non-empty + input is dict."""
    raw = json.dumps(envelope)
    out = parse_tool_call(raw)
    if out is not None:
        assert isinstance(out.name, str) and out.name.strip() == out.name
        assert out.name != ""
        assert isinstance(out.input, dict)


# ── parse_plan invariants ───────────────────────────────────────────────────


@given(arbitrary_text)
@SETTINGS
def test_parse_plan_never_raises_on_arbitrary_text(s):
    out = parse_plan(s)
    assert out is None or isinstance(out, dict)


@given(malformed_json)
@SETTINGS
def test_parse_plan_never_raises_on_malformed_json(s):
    out = parse_plan(s)
    assert out is None or isinstance(out, dict)


@given(valid_plan_dict)
@SETTINGS
def test_parse_plan_accepts_valid_plans(plan):
    raw = json.dumps(plan)
    out = parse_plan(raw)
    assert isinstance(out, dict)
    assert "steps" in out
    # Every step has the required shape
    for step in out["steps"]:
        assert step["type"] in ALLOWED_STEP_TYPES
        if step["type"] == "tool":
            assert isinstance(step["name"], str) and step["name"]
            assert isinstance(step["input"], dict)


@given(valid_plan_dict)
@SETTINGS
def test_parse_plan_preserves_step_count(plan):
    """The parser must NOT silently drop or reorder steps — that contract
    matters for the executor's truncation-detection logic."""
    raw = json.dumps(plan)
    out = parse_plan(raw)
    assert len(out["steps"]) == len(plan["steps"])


@given(valid_plan_dict)
@SETTINGS
def test_parse_plan_returns_none_when_steps_empty(plan):
    """Empty step lists are rejected — the executor would fail-state on them
    anyway, so the parser is the right place to reject."""
    plan_with_empty = dict(plan)
    plan_with_empty["steps"] = []
    raw = json.dumps(plan_with_empty)
    assert parse_plan(raw) is None


# ── Cross-property: parse_tool_call output is NEVER a valid plan envelope ──


@given(valid_tool_call_dict)
@SETTINGS
def test_tool_call_envelope_is_not_a_plan(envelope):
    """A planner that emits a raw tool-call envelope must NOT be mistaken
    for a valid plan — the safety property that lets the planner refuse to
    trigger tools even if the LLM mis-formats output."""
    raw = json.dumps(envelope)
    assert parse_plan(raw) is None
