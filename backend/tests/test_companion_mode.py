"""Companion sidecars (eq/relationship) must not write per-user PII to the global
untenanted stores in multi-user mode; they run only in single-operator mode."""
import app.services.eq.injection as inj
import app.services.eq.storage as eqs
import app.services.nai_brain.brain as brain
import app.services.relationship.storage as rels


def test_companion_off_in_multi_user_mode(monkeypatch):
    monkeypatch.delenv("KAI_SINGLE_OPERATOR_MODE", raising=False)
    calls = []
    monkeypatch.setattr(eqs, "record_mood", lambda *a, **k: calls.append(1))
    # even with a strongly non-neutral message, nothing is recorded
    out = brain._eq_analyze_and_record("I am absolutely thrilled today!!!")
    assert out == ""
    assert calls == []  # no untenanted PII write → account deletion stays complete


def test_companion_on_in_single_operator_mode(monkeypatch):
    monkeypatch.setenv("KAI_SINGLE_OPERATOR_MODE", "1")
    monkeypatch.setenv("KAI_SCOPE_RELATIONSHIP", "1")
    monkeypatch.setattr(inj, "analyze", lambda msg: ("happy", 0.9, "TONE-PREAMBLE"))
    monkeypatch.setattr(rels, "record_interaction", lambda *a, **k: None)
    recorded = []
    monkeypatch.setattr(eqs, "record_mood", lambda *a, **k: recorded.append(a))
    out = brain._eq_analyze_and_record("I am happy today")
    assert out == "TONE-PREAMBLE"
    assert len(recorded) == 1  # mood recorded when the operator opts in explicitly
