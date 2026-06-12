"""TTS service tests — Piper-first, OpenAI fallback.

We don't load the real Piper model in unit tests (60MB, ~400ms load
+ ~300ms synth — pytest doesn't need to verify ONNX runtime works,
just the dispatch + fallback logic). Both backends are monkey-patched.
"""
from __future__ import annotations

import pytest

from app.services import tts


def test_synthesize_empty_text_raises():
    with pytest.raises(tts.TTSError):
        tts.synthesize("")


def test_synthesize_truncates_long_input(monkeypatch):
    captured = {}

    def fake_piper(text):
        captured["text"] = text
        return b"FAKE_WAV"

    monkeypatch.setattr(tts, "_synthesize_piper", fake_piper)
    long_text = "a" * (tts.MAX_INPUT_CHARS + 500)
    wav, mime = tts.synthesize(long_text)
    assert wav == b"FAKE_WAV"
    assert mime == "audio/wav"
    assert len(captured["text"]) == tts.MAX_INPUT_CHARS


def test_piper_success_no_openai_call(monkeypatch):
    """When Piper succeeds, OpenAI must never be called."""
    monkeypatch.setattr(tts, "_synthesize_piper", lambda t: b"PIPER_OK")

    def openai_should_not_run(t):  # pragma: no cover
        raise AssertionError("openai called when piper succeeded")

    monkeypatch.setattr(tts, "_synthesize_openai", openai_should_not_run)

    wav, mime = tts.synthesize("hello")
    assert wav == b"PIPER_OK"


def test_falls_back_to_openai_when_piper_fails(monkeypatch):
    def piper_fails(t):
        raise tts.TTSError("piper unavailable in test")

    monkeypatch.setattr(tts, "_synthesize_piper", piper_fails)
    monkeypatch.setattr(tts, "_synthesize_openai", lambda t: b"OPENAI_OK")

    wav, mime = tts.synthesize("hello")
    assert wav == b"OPENAI_OK"
    assert mime == "audio/wav"


def test_raises_when_both_backends_fail(monkeypatch):
    monkeypatch.setattr(
        tts, "_synthesize_piper",
        lambda t: (_ for _ in ()).throw(tts.TTSError("piper down")),
    )
    monkeypatch.setattr(
        tts, "_synthesize_openai",
        lambda t: (_ for _ in ()).throw(tts.TTSError("openai down")),
    )
    with pytest.raises(tts.TTSError, match="both TTS backends failed"):
        tts.synthesize("hello")


def test_piper_missing_model_returns_none(monkeypatch):
    """If the Piper model file doesn't exist, _get_piper() returns None
    so the caller falls back gracefully — no exception thrown."""
    monkeypatch.setattr(tts, "_PIPER_MODEL_PATH", "/tmp/nonexistent-model.onnx")
    monkeypatch.setattr(tts, "_piper_voice", None)  # force re-check
    assert tts._get_piper() is None
