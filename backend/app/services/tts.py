"""Text-to-speech for KAI's "read response aloud" button.

Two-tier architecture: Piper local-first, OpenAI TTS-1 as fallback.

Why this shape:
  - Piper is free, fast (~300ms/sentence on M4), private (no outbound
    API call), and consistent (same voice every time). It's the
    default for the same reasons we picked Ollama as a router tier.
  - OpenAI TTS-1 is the safety net. If Piper's model load fails (disk
    missing, ONNX runtime error), or synthesis errors on weird input,
    we fall back to OpenAI so the user still hears a response. ~$0.015
    per 1k chars — irrelevant at fallback frequency.
  - The fallback is silent from the user's perspective. They click
    "read aloud", they hear audio. They don't care which backend ran.

The Piper voice model lives at models/piper/{name}.onnx + .onnx.json
(downloaded out-of-band during deployment). Loaded once per process and
cached in module state — model load is 400ms cold, irrelevant warm.

Public API:
  synthesize(text: str) -> tuple[bytes, str]
    Returns (wav_bytes, "audio/wav") on success.
    Raises TTSError if both backends fail.
"""
from __future__ import annotations

import io
import logging
import os
import wave

logger = logging.getLogger(__name__)

# Hard cap on input length — sane upper bound that prevents an LLM
# response from triggering a 5-minute TTS render. Most assistant turns
# are well under this. Longer is OK to truncate-with-marker because the
# user can re-click to hear the next chunk if we ever need that.
MAX_INPUT_CHARS = 4_000

_PIPER_MODEL_PATH = os.environ.get(
    "PIPER_MODEL_PATH",
    "/Users/jhonwheeler/wheellsverse_bots/models/piper/en_US-lessac-medium.onnx",
)

# Singleton — loaded lazily on first call.
_piper_voice = None


class TTSError(RuntimeError):
    """User-facing TTS failure — both Piper and the OpenAI fallback failed."""


def _get_piper():
    """Load + cache the Piper voice model. None means Piper is unavailable
    (model file missing, ONNX runtime broken). Caller falls back to OpenAI."""
    global _piper_voice
    if _piper_voice is not None:
        return _piper_voice
    if not os.path.exists(_PIPER_MODEL_PATH):
        logger.warning("piper model not found at %s — TTS will use OpenAI fallback", _PIPER_MODEL_PATH)
        return None
    try:
        from piper import PiperVoice
        _piper_voice = PiperVoice.load(_PIPER_MODEL_PATH)
        logger.info("piper voice loaded (sample_rate=%d)", _piper_voice.config.sample_rate)
        return _piper_voice
    except Exception as e:
        logger.exception("piper load failed: %s", e)
        return None


def _synthesize_piper(text: str) -> bytes:
    voice = _get_piper()
    if voice is None:
        raise TTSError("piper unavailable")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(voice.config.sample_rate)
        voice.synthesize_wav(text, wf)
    return buf.getvalue()


def _synthesize_openai(text: str) -> bytes:
    """OpenAI TTS-1 fallback. Returns MP3-style WAV bytes (response_format=wav
    asks for raw PCM packaged as WAV — same shape the browser <audio> tag
    decodes regardless of backend)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise TTSError("openai fallback unavailable (no OPENAI_API_KEY)")
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.audio.speech.create(
            model="tts-1",
            voice="alloy",   # neutral default; matches Whisper's expected register
            input=text,
            response_format="wav",
        )
        return resp.read()
    except Exception as e:
        raise TTSError(f"openai TTS failed: {e}")


def synthesize(text: str) -> tuple[bytes, str]:
    """Synthesize WAV audio from text. Try Piper, fall back to OpenAI.

    Returns (wav_bytes, mime_type). Raises TTSError only if BOTH backends
    fail — single-backend failure logs a warning and continues.
    """
    # §22/§24: reasoning scratchpads must NEVER be vocalized — sanitize at the TTS
    # boundary regardless of caller (finalized: text here is a complete utterance).
    from app.services.reasoning_sanitizer import strip_reasoning
    text = strip_reasoning((text or "")).strip()
    if not text:
        raise TTSError("text cannot be empty")
    if len(text) > MAX_INPUT_CHARS:
        text = text[:MAX_INPUT_CHARS]
        logger.info("tts: truncated input to %d chars", MAX_INPUT_CHARS)

    try:
        wav = _synthesize_piper(text)
        return wav, "audio/wav"
    except TTSError as piper_err:
        logger.warning("piper failed (%s); trying openai fallback", piper_err)

    try:
        wav = _synthesize_openai(text)
        return wav, "audio/wav"
    except TTSError as openai_err:
        raise TTSError(
            f"both TTS backends failed — last error: {openai_err}"
        )
