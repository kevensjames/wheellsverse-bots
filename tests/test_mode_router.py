from narai.core.mode_router import (
    fast_intent, route, modifier_for, parse_override, ModeDecision,
)
from narai.core.identity import build_system_prompt


def test_fast_operator_code_request():
    score, _ = fast_intent("How do I debug this Python error in my script?")
    assert score > 0.4


def test_fast_companion_emotional():
    score, _ = fast_intent("Honestly I'm just exhausted, it's been a lot.")
    assert score < -0.3


def test_fast_code_block_operator():
    score, _ = fast_intent("```\ndef foo(): pass\n```\nwhy is this broken")
    assert score > 0.4


def test_short_nosignal_leans_companion():
    score, _ = fast_intent("hey")
    assert score < 0


def test_route_operator():
    d = route("Write me a function that scrapes Shopify orders.")
    assert d.mode == "operator"
    assert not d.forced


def test_route_companion():
    d = route("I feel stuck, nothing is moving forward honestly.")
    assert d.mode == "companion"


def test_route_overwhelm_forces_companion():
    d = route("Write me a 10-step plan for Nexora.", overwhelm_level="high")
    assert d.mode == "companion"
    assert d.forced
    assert "overwhelm" in d.reason


def test_route_manual_override_wins():
    d = route("I feel lost", manual_override="operator")
    assert d.mode == "operator"
    assert d.forced


def test_route_ambiguous_uses_llm():
    called = {"n": 0}
    def fake_llm(s, u):
        called["n"] += 1
        return '{"mode": "companion", "reason": "processing"}'
    # deliberately ambiguous
    d = route("thinking about the week", llm_call=fake_llm)
    assert called["n"] == 1
    assert d.mode == "companion"


def test_route_clear_skips_llm():
    called = {"n": 0}
    def fake_llm(s, u):
        called["n"] += 1
        return '{"mode": "companion", "reason": "x"}'
    d = route("Write me a deployment script for Netlify.", llm_call=fake_llm)
    assert d.mode == "operator"
    assert called["n"] == 0


def test_parse_override_operator():
    assert parse_override("stay in operator mode please") == "operator"


def test_parse_override_companion():
    assert parse_override("just listen for a sec") == "companion"


def test_parse_override_release():
    assert parse_override("release the mode") == "release"


def test_parse_override_none():
    assert parse_override("what's the weather") is None


def test_modifier_operator_has_execution():
    m = modifier_for(ModeDecision("operator", 0.5, "x", False))
    assert "OPERATOR" in m
    assert "execute" in m.lower()


def test_modifier_companion_has_listen():
    m = modifier_for(ModeDecision("companion", -0.5, "x", False))
    assert "COMPANION" in m
    assert "listen" in m.lower()


def test_integration_in_prompt():
    d = ModeDecision("companion", -0.5, "x", False)
    prompt = build_system_prompt(mode_modifier=modifier_for(d))
    assert "COMPANION" in prompt
    assert "NarAI" in prompt  # identity preserved
