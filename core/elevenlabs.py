#!/usr/bin/env python3
"""
core/elevenlabs.py
─────────────────────────────────────────────────────────────────────────────
ElevenLabs Voice Engine — custom voice for every piece of audio WheellsVerse
produces: video narration, podcast episodes, TTS replies, shorts.

Features:
  • Text → Speech  (mp3/wav) using the configured ELEVENLABS_VOICE_ID
  • Voice clone creation from sample audio files
  • Voice library listing
  • Streaming audio for real-time TTS
  • Smart chunking for long texts (ElevenLabs limit: 5000 chars/request)

.env keys:
  ELEVENLABS_API_KEY   — from elevenlabs.io → Profile → API Key
  ELEVENLABS_VOICE_ID  — voice ID to use (your clone or a stock voice)
  ELEVENLABS_MODEL     — model ID (default: eleven_turbo_v2_5 — fastest+cheapest)

Fallback: if ElevenLabs not configured, falls back to OpenAI TTS
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import time
from pathlib import Path
from typing import Iterator, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

AUDIO_DIR = ROOT / "outputs" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("elevenlabs")

BASE_URL    = "https://api.elevenlabs.io/v1"
API_KEY     = os.getenv("ELEVENLABS_API_KEY", "")
VOICE_ID    = os.getenv("ELEVENLABS_VOICE_ID", "")
MODEL_ID    = os.getenv("ELEVENLABS_MODEL", "eleven_turbo_v2_5")
CHUNK_SIZE  = 4500   # chars per request (under 5000 limit)

# Default voice settings — tuned for NarAI's confident, warm delivery
DEFAULT_SETTINGS = {
    "stability":          0.45,   # 0=varied, 1=stable — mid keeps it natural
    "similarity_boost":   0.82,   # how close to the original voice
    "style":              0.35,   # expressiveness (0-1)
    "use_speaker_boost":  True,
}


def _headers(json_content: bool = True) -> dict:
    h = {"xi-api-key": API_KEY}
    if json_content:
        h["Content-Type"] = "application/json"
    return h


def is_configured() -> bool:
    return bool(API_KEY and VOICE_ID)


# ─── Text → Speech ────────────────────────────────────────────────────────────

def speak(text: str, voice_id: str = None, filename: str = None,
          settings: dict = None) -> Optional[Path]:
    """
    Convert text to speech. Returns path to the saved mp3 file.
    Falls back to OpenAI TTS if ElevenLabs not configured.
    """
    if not is_configured():
        logger.info("[ElevenLabs] Not configured — falling back to OpenAI TTS")
        return _openai_tts_fallback(text, filename)

    vid      = voice_id or VOICE_ID
    settings = settings or DEFAULT_SETTINGS
    text     = text.strip()

    if not text:
        return None

    # Chunk long texts
    chunks = _chunk_text(text)
    audio_parts: List[bytes] = []

    for i, chunk in enumerate(chunks):
        logger.info(f"[ElevenLabs] Chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
        try:
            resp = requests.post(
                f"{BASE_URL}/text-to-speech/{vid}",
                headers=_headers(),
                json={
                    "text":           chunk,
                    "model_id":       MODEL_ID,
                    "voice_settings": settings,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                audio_parts.append(resp.content)
            else:
                logger.warning(f"[ElevenLabs] TTS error {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.error(f"[ElevenLabs] TTS request failed: {e}")

    if not audio_parts:
        return _openai_tts_fallback(text, filename)

    audio_bytes = b"".join(audio_parts)

    # Save file
    if not filename:
        ts       = int(time.time())
        filename = f"narai_voice_{ts}.mp3"
    if not filename.endswith(".mp3"):
        filename += ".mp3"

    out_path = AUDIO_DIR / filename
    out_path.write_bytes(audio_bytes)
    logger.info(f"[ElevenLabs] Saved {len(audio_bytes):,} bytes → {out_path}")
    return out_path


def speak_stream(text: str, voice_id: str = None) -> Iterator[bytes]:
    """
    Stream audio chunks for real-time playback.
    Yields raw mp3 bytes as they arrive.
    """
    if not is_configured():
        return

    vid = voice_id or VOICE_ID
    try:
        with requests.post(
            f"{BASE_URL}/text-to-speech/{vid}/stream",
            headers=_headers(),
            json={
                "text":           text[:CHUNK_SIZE],
                "model_id":       MODEL_ID,
                "voice_settings": DEFAULT_SETTINGS,
            },
            stream=True,
            timeout=60,
        ) as resp:
            if resp.status_code == 200:
                for chunk in resp.iter_content(chunk_size=4096):
                    if chunk:
                        yield chunk
            else:
                logger.warning(f"[ElevenLabs] Stream error {resp.status_code}")
    except Exception as e:
        logger.error(f"[ElevenLabs] Stream failed: {e}")


# ─── Voice Management ─────────────────────────────────────────────────────────

def list_voices() -> List[dict]:
    """Return all voices in the account (stock + clones)."""
    if not API_KEY:
        return []
    try:
        resp = requests.get(f"{BASE_URL}/voices", headers=_headers(), timeout=15)
        if resp.status_code == 200:
            voices = resp.json().get("voices", [])
            logger.info(f"[ElevenLabs] {len(voices)} voices available")
            return voices
        return []
    except Exception as e:
        logger.error(f"[ElevenLabs] list_voices failed: {e}")
        return []


def get_voice_info(voice_id: str = None) -> Optional[dict]:
    """Get details for a specific voice."""
    vid = voice_id or VOICE_ID
    if not (API_KEY and vid):
        return None
    try:
        resp = requests.get(f"{BASE_URL}/voices/{vid}", headers=_headers(), timeout=15)
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        logger.error(f"[ElevenLabs] get_voice_info failed: {e}")
        return None


def clone_voice(name: str, description: str, audio_files: List[Path]) -> Optional[dict]:
    """
    Create a voice clone from audio sample files (mp3/wav).
    Returns the new voice dict including voice_id.

    audio_files: list of paths to sample recordings (recommend 1-5 min total)
    """
    if not API_KEY:
        logger.error("[ElevenLabs] clone_voice: API_KEY not set")
        return None

    try:
        files = [("files", (f.name, f.read_bytes(), "audio/mpeg"))
                 for f in audio_files if f.exists()]
        if not files:
            logger.error("[ElevenLabs] clone_voice: no valid audio files")
            return None

        resp = requests.post(
            f"{BASE_URL}/voices/add",
            headers={"xi-api-key": API_KEY},  # no Content-Type for multipart
            data={"name": name, "description": description},
            files=files,
            timeout=60,
        )
        if resp.status_code == 200:
            result = resp.json()
            new_id = result.get("voice_id", "")
            logger.info(f"[ElevenLabs] Voice clone created: {name} → {new_id}")
            return result
        else:
            logger.error(f"[ElevenLabs] clone_voice error {resp.status_code}: {resp.text[:300]}")
            return None
    except Exception as e:
        logger.error(f"[ElevenLabs] clone_voice failed: {e}")
        return None


def get_usage() -> dict:
    """Return character usage for the current billing period."""
    if not API_KEY:
        return {}
    try:
        resp = requests.get(f"{BASE_URL}/user/subscription",
                            headers=_headers(), timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            used  = data.get("character_count", 0)
            limit = data.get("character_limit", 0)
            return {
                "used":       used,
                "limit":      limit,
                "remaining":  limit - used,
                "pct_used":   round(used / max(limit, 1) * 100, 1),
                "tier":       data.get("tier", "unknown"),
            }
        return {}
    except Exception as e:
        logger.warning(f"[ElevenLabs] get_usage failed: {e}")
        return {}


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _chunk_text(text: str) -> List[str]:
    """Split text into chunks at sentence boundaries."""
    if len(text) <= CHUNK_SIZE:
        return [text]

    chunks, current = [], ""
    for sentence in text.replace(".\n", ". ").split(". "):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(current) + len(sentence) + 2 > CHUNK_SIZE:
            if current:
                chunks.append(current.strip())
            current = sentence + ". "
        else:
            current += sentence + ". "

    if current.strip():
        chunks.append(current.strip())

    return chunks or [text[:CHUNK_SIZE]]


def _openai_tts_fallback(text: str, filename: str = None) -> Optional[Path]:
    """Use OpenAI TTS as fallback when ElevenLabs not configured."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        audio  = client.audio.speech.create(
            model="tts-1-hd", voice="nova",
            input=text[:4000], speed=0.92,
        )
        if not filename:
            filename = f"narai_oaitts_{int(time.time())}.mp3"
        if not filename.endswith(".mp3"):
            filename += ".mp3"
        out_path = AUDIO_DIR / filename
        out_path.write_bytes(audio.content)
        logger.info(f"[ElevenLabs→OpenAI] Saved TTS fallback → {out_path}")
        return out_path
    except Exception as e:
        logger.error(f"[ElevenLabs] OpenAI TTS fallback failed: {e}")
        return None


# ─── Module self-test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    print("ElevenLabs Status:")
    print(f"  Configured: {is_configured()}")
    info = get_voice_info()
    if info:
        print(f"  Voice: {info.get('name')} ({info.get('voice_id')})")
    usage = get_usage()
    if usage:
        print(f"  Usage: {usage.get('used'):,}/{usage.get('limit'):,} chars "
              f"({usage.get('pct_used')}% used) — tier: {usage.get('tier')}")
    voices = list_voices()
    print(f"  Available voices: {len(voices)}")
    for v in voices[:5]:
        print(f"    • {v.get('name')} ({v.get('voice_id')}) — {v.get('category')}")
