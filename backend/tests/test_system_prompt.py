"""KAI v1 build #2 — grounding/citation directive (opt-in)."""
from app.services.nai_brain.system_prompt import build_system_prompt


def test_grounding_off_by_default(monkeypatch):
    monkeypatch.delenv("KAI_GROUNDING_ON_CHAT", raising=False)
    sp = build_system_prompt(memory_preamble="", lessons_preamble="", eq_preamble="")
    assert "GROUNDING DIRECTIVE" not in sp


def test_grounding_on_when_enabled(monkeypatch):
    monkeypatch.setenv("KAI_GROUNDING_ON_CHAT", "1")
    sp = build_system_prompt(memory_preamble="", lessons_preamble="", eq_preamble="")
    assert "GROUNDING DIRECTIVE" in sp
    # names the verify-first tools + the refuse-when-uncertain rule
    assert "verify_claim" in sp and "kg_query" in sp
    assert "I don't know" in sp
