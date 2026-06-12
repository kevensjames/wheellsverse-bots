#!/usr/bin/env python3
"""
core/voice_router.py
─────────────────────────────────────────────────────────────────────────────
Voice output router.
POST /api/voice/speak  → returns audio/mp3
Uses ElevenLabs if key is set, falls back to OpenAI TTS, then signals browser.
─────────────────────────────────────────────────────────────────────────────
"""

import io
import logging
import os

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logger = logging.getLogger("voice_router")
router = APIRouter(prefix="/api/voice", tags=["voice"])

VOICE_ENABLED = os.getenv("VOICE_ENABLED", "true").lower() == "true"
TTS_PROVIDER = os.getenv("TTS_PROVIDER", "auto").lower()  # auto | local | elevenlabs | openai | browser

# When LLM_BACKEND=ollama, default TTS_PROVIDER=auto should prefer local first.
_LOCAL_LLM = (os.getenv("LLM_BACKEND") or "").strip().lower() in ("ollama", "local", "lmstudio", "llamacpp")


class SpeakRequest(BaseModel):
    text: str
    voice: str = "nova"      # OpenAI: alloy/echo/fable/onyx/nova/shimmer
    speed: float = 0.9


@router.get("/status")
def voice_status():
    has_elevenlabs = bool(os.getenv("ELEVENLABS_API_KEY"))
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    from core import local_tts
    has_local = local_tts.is_available()
    provider = (
        "local" if TTS_PROVIDER == "local" and has_local else
        "local" if TTS_PROVIDER == "auto" and _LOCAL_LLM and has_local else
        "elevenlabs" if (TTS_PROVIDER == "elevenlabs" and has_elevenlabs) else
        "elevenlabs" if (TTS_PROVIDER == "auto" and has_elevenlabs) else
        "openai" if (TTS_PROVIDER == "openai" and has_openai) else
        "openai" if (TTS_PROVIDER == "auto" and has_openai) else
        "local" if has_local else
        "browser"
    )
    return {
        "enabled": VOICE_ENABLED,
        "provider": provider,
        "has_local": has_local,
        "has_elevenlabs": has_elevenlabs,
        "has_openai": has_openai,
    }


@router.post("/speak")
async def voice_speak(req: SpeakRequest):
    """
    Text → audio/mp3.
    Priority: ElevenLabs → OpenAI TTS → 204 (browser fallback).
    """
    text = req.text.strip()[:2000]
    if not text:
        raise HTTPException(status_code=400, detail="No text provided")

    if not VOICE_ENABLED:
        raise HTTPException(status_code=503, detail="Voice disabled — set VOICE_ENABLED=true")

    # ── Local Piper TTS ───────────────────────────────────────────────────────
    # Prefer local when explicitly requested OR when local-LLM mode is on
    # (LLM_BACKEND=ollama) and a Piper voice is available.
    try_local = (
        TTS_PROVIDER == "local"
        or (TTS_PROVIDER == "auto" and _LOCAL_LLM)
    )
    if try_local:
        try:
            from core import local_tts
            if local_tts.is_available():
                audio_bytes = local_tts.synthesize_mp3(text)
                return StreamingResponse(
                    io.BytesIO(audio_bytes), media_type="audio/mpeg",
                    headers={"Content-Length": str(len(audio_bytes)), "X-TTS-Provider": "local"},
                )
        except Exception as e:
            logger.warning(f"[voice] Local Piper TTS failed: {e}")

    # ── ElevenLabs ────────────────────────────────────────────────────────────
    el_key = os.getenv("ELEVENLABS_API_KEY", "")
    if el_key and TTS_PROVIDER in ("auto", "elevenlabs"):
        try:
            from core.elevenlabs import synthesize_speech
            audio_bytes = synthesize_speech(text)
            return StreamingResponse(
                io.BytesIO(audio_bytes), media_type="audio/mpeg",
                headers={"Content-Length": str(len(audio_bytes)), "X-TTS-Provider": "elevenlabs"},
            )
        except Exception as e:
            logger.warning(f"[voice] ElevenLabs failed: {e}")

    # ── OpenAI TTS ────────────────────────────────────────────────────────────
    oai_key = os.getenv("OPENAI_API_KEY", "")
    if oai_key and TTS_PROVIDER in ("auto", "openai"):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=oai_key)
            audio = client.audio.speech.create(
                model="tts-1",
                voice=req.voice,
                input=text[:600],
                speed=max(0.25, min(4.0, req.speed)),
            )
            b = audio.content
            return StreamingResponse(
                io.BytesIO(b), media_type="audio/mpeg",
                headers={"Content-Length": str(len(b)), "X-TTS-Provider": "openai"},
            )
        except Exception as e:
            logger.warning(f"[voice] OpenAI TTS failed: {e}")

    # ── Browser fallback ─────────────────────────────────────────────────────
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=200,
        content={"use_browser_tts": True, "text": text},
        headers={"X-TTS-Provider": "browser"},
    )
