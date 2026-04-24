"""
TTS adapter. Supports ElevenLabs (premium) and Edge TTS (free).

Dependencies are imported lazily inside each provider's __init__ / synthesize
so the rest of the voice pipeline stays testable even when neither SDK is
installed — useful on local dev, CI, and when prod only configures one.
"""
from __future__ import annotations

import os
from typing import Literal, Protocol

Provider = Literal["elevenlabs", "edge"]


class TTSClient(Protocol):
    async def synthesize(self, text: str, voice: str | None = None) -> bytes: ...


class ElevenLabsTTS:
    def __init__(self, api_key: str | None = None, voice_id: str = "21m00Tcm4TlvDq8ikWAM"):
        from elevenlabs.client import ElevenLabs
        self.client = ElevenLabs(api_key=api_key or os.getenv("ELEVENLABS_API_KEY"))
        self.voice_id = voice_id

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        audio = self.client.text_to_speech.convert(
            voice_id=voice or self.voice_id,
            text=text,
            model_id="eleven_turbo_v2_5",
            output_format="mp3_44100_128",
        )
        return b"".join(audio)


class EdgeTTS:
    def __init__(self, voice: str = "en-US-GuyNeural"):
        self.voice = voice

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        import edge_tts
        communicate = edge_tts.Communicate(text, voice or self.voice)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                chunks.append(chunk["data"])
        return b"".join(chunks)


def get_tts(provider: Provider = "edge") -> TTSClient:
    if provider == "elevenlabs":
        return ElevenLabsTTS()
    return EdgeTTS()
