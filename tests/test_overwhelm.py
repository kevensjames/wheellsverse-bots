from narai.core.overwhelm import (
    fast_score, detect, modifier_for, OverwhelmState,
)
from narai.core.identity import build_system_prompt


def test_fast_score_none():
    score, signals = fast_score("What's the best way to learn SQL?")
    assert score <= 0.15
    assert signals == []


def test_fast_score_high():
    score, _ = fast_score("I can't do this anymore, it's too much.")
    assert score >= 0.6


def test_fast_score_mild():
    score, _ = fast_score("Not sure where to start with this project, a lot to handle.")
    assert 0.15 < score < 0.6


def test_structural_many_questions():
    text = "what do i do? where do i start? is this right? am i wrong?"
    _, signals = fast_score(text)
    assert any("many_questions" in s for s in signals)


def test_detect_high_skips_llm():
    called = {"n": 0}
    def fake_llm(s, u):
        called["n"] += 1
        return '{"level": "none", "reason": "x"}'
    state = detect("I'm completely burnt out, can't keep going.", fake_llm)
    assert state.level == "high"
    assert called["n"] == 0  # skipped deep pass


def test_detect_none_skips_llm():
    called = {"n": 0}
    def fake_llm(s, u):
        called["n"] += 1
        return '{"level": "high", "reason": "x"}'
    state = detect("Hey, what's 2 + 2?", fake_llm)
    assert state.level == "none"
    assert called["n"] == 0


def test_detect_ambiguous_calls_llm():
    called = {"n": 0}
    def fake_llm(s, u):
        called["n"] += 1
        return '{"level": "mild", "reason": "stressed"}'
    state = detect("not sure what to do here honestly", fake_llm)
    assert called["n"] == 1
    assert state.level == "mild"


def test_detect_no_llm_fallback():
    state = detect("not sure where to start, a lot going on")
    assert state.level in ("mild", "none")


def test_modifier_high_forces_single_task():
    state = OverwhelmState("high", 0.8, "x", [])
    mod = modifier_for(state)
    assert "ONE task" in mod
    assert "ignore everything else" in mod.lower()


def test_modifier_none_empty():
    state = OverwhelmState("none", 0.0, "", [])
    assert modifier_for(state) == ""


def test_integration_high_in_prompt():
    state = OverwhelmState("high", 0.8, "x", [])
    prompt = build_system_prompt(overwhelm_modifier=modifier_for(state))
    assert "ONE task" in prompt
    assert "NarAI" in prompt  # identity still there


def test_integration_none_does_not_pollute():
    prompt = build_system_prompt(overwhelm_modifier=modifier_for(
        OverwhelmState("none", 0.0, "", [])
    ))
    assert "Current state override" not in prompt
