#!/usr/bin/env python3
"""
core/narai_tts.py
─────────────────────────────────────────────────────────────────────────────
NarAI Voice Engine — Edge TTS (Microsoft Ava Neural)

Voice: en-US-AvaNeural — warm, soft, emotional, loving.
Free, no API key, no quota. Mood-aware delivery.

Usage:
    from core.narai_tts import speak, speak_with_mood
    speak("Hey, I'm here.")
    speak_with_mood("I feel you.", mood="sad")
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("narai_tts")

ROOT = Path(__file__).resolve().parent.parent
AUDIO_DIR = ROOT / "outputs" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

# NarAI's voice — Ava Neural (warm, soft, emotional)
DEFAULT_VOICE = "en-US-AvaNeural"

# Mood-adapted delivery settings (rate = speed, pitch = tone)
MOOD_SETTINGS = {
    "sad": {"rate": "-15%", "pitch": "-2Hz"},   # slower, slightly lower — gentle, tender
    "happy": {"rate": "-3%", "pitch": "+4Hz"},   # livelier, brighter
    "angry": {"rate": "-8%", "pitch": "-1Hz"},   # calm, steady, grounding
    "anxious": {"rate": "-12%", "pitch": "-1Hz"},   # slow, reassuring
    "neutral": {"rate": "-10%", "pitch": "+2Hz"},   # natural, warm
}


async def _synthesize(text: str, voice: str, rate: str, pitch: str, path: Path):
    import edge_tts
    tts = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
    await tts.save(str(path))


def speak(text: str, mood: str = "neutral", filename: str = None,
          autoplay: bool = True) -> Optional[Path]:
    """
    Convert text to speech using Ava Neural voice.
    Mood adjusts delivery style. Autoplays on Mac via `afplay`.
    Returns path to the saved mp3.
    """
    if not text or not text.strip():
        return None

    settings = MOOD_SETTINGS.get(mood, MOOD_SETTINGS["neutral"])

    if not filename:
        filename = f"narai_voice_{int(time.time())}.mp3"
    if not filename.endswith(".mp3"):
        filename += ".mp3"

    out_path = AUDIO_DIR / filename

    try:
        asyncio.run(_synthesize(
            text=text.strip()[:4000],
            voice=DEFAULT_VOICE,
            rate=settings["rate"],
            pitch=settings["pitch"],
            path=out_path,
        ))
        logger.info("NarAI TTS saved (%s mood): %s", mood, out_path.name)

        if autoplay and out_path.exists():
            _play(out_path)

        return out_path

    except Exception as e:
        logger.error("NarAI TTS failed: %s", e)
        return None


def speak_with_mood(text: str, filename: str = None, autoplay: bool = True) -> Optional[Path]:
    """Speak using the current detected mood from EmotionEngine."""
    mood = "neutral"
    try:
        from core.emotion_engine import get_current_mood
        mood = get_current_mood()
    except Exception:
        pass
    return speak(text, mood=mood, filename=filename, autoplay=autoplay)


def _play(path: Path):
    """Play audio file on Mac (afplay), non-blocking."""
    try:
        subprocess.Popen(
            ["afplay", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        logger.debug("afplay failed: %s", e)
