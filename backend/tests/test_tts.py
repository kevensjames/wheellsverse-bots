"""TTS service tests — Kokoro (default primary) -> Piper -> OpenAI.

We don't load the real models in unit tests (60MB+, slow — pytest just verifies
the dispatch + fallback logic). Backends are monkey-patched.

Kokoro is now the default primary backend (KAI_TTS_BACKEND=kokoro). The fallback
tests below pin the backend to `piper` so the Piper->OpenAI chain is
deterministic regardless of whether a Kokoro model is installed; the
Kokoro-primary path has its own dedicated test.
"""
from __future__ import annotations

import pytest

from app.services import tts


@pytest.fixture(autouse=True)
def _tts_piper_first(monkeypatch):
    # Pin Piper-first for the fallback-chain tests (a test that needs Kokoro
    # overrides this).
    monkeypatch.setenv("KAI_TTS_BACKEND", "piper")


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
    monkeypatch.setattr(tts, "_synthesize_openai", lambda t, **kw: b"OPENAI_OK")

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
        lambda t, **kw: (_ for _ in ()).throw(tts.TTSError("openai down")),
    )
    with pytest.raises(tts.TTSError, match="both TTS backends failed"):
        tts.synthesize("hello")


def test_piper_missing_model_returns_none(monkeypatch):
    """If the Piper model file doesn't exist, _get_piper() returns None
    so the caller falls back gracefully — no exception thrown."""
    monkeypatch.setattr(tts, "_PIPER_MODEL_PATH", "/tmp/nonexistent-model.onnx")
    monkeypatch.setattr(tts, "_piper_voice", None)  # force re-check
    assert tts._get_piper() is None


def test_kokoro_is_default_primary(monkeypatch):
    """Default backend is Kokoro; when it succeeds, Piper/OpenAI aren't called."""
    monkeypatch.setenv("KAI_TTS_BACKEND", "kokoro")  # override the autouse piper pin
    monkeypatch.setattr(tts, "_synthesize_kokoro", lambda text, speed=0.95: b"KOKORO_OK")

    def piper_should_not_run(t):  # pragma: no cover
        raise AssertionError("piper called when kokoro succeeded")

    monkeypatch.setattr(tts, "_synthesize_piper", piper_should_not_run)
    wav, mime = tts.synthesize("hello")
    assert wav == b"KOKORO_OK"
    assert mime == "audio/wav"
