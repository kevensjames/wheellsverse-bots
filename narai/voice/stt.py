"""
STT adapter. Local faster-whisper or OpenAI Whisper API.

SDK imports live inside __init__ so an unconfigured provider doesn't poison
module-level imports — same rationale as tts.py.
"""
from __future__ import annotations

import io
import os
from typing import Literal, Protocol

Provider = Literal["openai", "local"]


def _sniff_audio_ext(audio_bytes: bytes) -> str:
    """Pick the right filename extension from the audio's magic bytes.
    Whisper rejects files when the extension doesn't match the actual format
    (e.g., Safari sends audio/mp4 even when MediaRecorder asks for webm)."""
    if not audio_bytes:
        return "webm"
    if audio_bytes.startswith(b"\x1aE\xdf\xa3"):  # EBML — webm/matroska
        return "webm"
    if len(audio_bytes) >= 8 and audio_bytes[4:8] == b"ftyp":  # MP4
        return "mp4"
    if audio_bytes.startswith(b"OggS"):
        return "ogg"
    if audio_bytes.startswith(b"RIFF"):
        return "wav"
    if audio_bytes.startswith(b"ID3") or audio_bytes[:2] == b"\xff\xfb":
        return "mp3"
    if audio_bytes.startswith(b"fLaC"):
        return "flac"
    return "webm"


class STTClient(Protocol):
    async def transcribe(self, audio_bytes: bytes) -> str: ...


class OpenAIWhisper:
    def __init__(self, api_key: str | None = None):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))

    async def transcribe(self, audio_bytes: bytes) -> str:
        buf = io.BytesIO(audio_bytes)
        buf.name = f"audio.{_sniff_audio_ext(audio_bytes)}"
        result = self.client.audio.transcriptions.create(
            model="whisper-1",
            file=buf,
        )
        return result.text


class LocalWhisper:
    def __init__(self, model_size: str = "base"):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")

    async def transcribe(self, audio_bytes: bytes) -> str:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(audio_bytes)
            path = f.name
        segments, _ = self.model.transcribe(path, beam_size=1)
        return " ".join(s.text for s in segments).strip()


def get_stt(provider: Provider = "openai") -> STTClient:
    if provider == "local":
        return LocalWhisper()
    return OpenAIWhisper()
