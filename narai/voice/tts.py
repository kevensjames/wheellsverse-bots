"""
TTS adapter. Choose one of:

  * ``elevenlabs`` — ElevenLabs API (~$0.30/1k chars, premium voices)
  * ``edge``       — Microsoft Edge TTS (free, calls Microsoft endpoint)
  * ``kokoro``     — Kokoro local ONNX TTS (free, fully offline)

Setup for kokoro:
  $ pip install kokoro-onnx soundfile
  # Download model + voices files (~80 MB + ~30 MB):
  $ mkdir -p ~/.kokoro && cd ~/.kokoro
  $ curl -L -o kokoro-v1.0.onnx \\
      https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
  $ curl -L -o voices-v1.0.bin \\
      https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

Env overrides:
  KOKORO_MODEL_PATH    full path to kokoro-v1.0.onnx
  KOKORO_VOICES_PATH   full path to voices-v1.0.bin
  KOKORO_DEFAULT_VOICE voice name (default: af_sarah)

Dependencies are imported lazily inside each provider's __init__ / synthesize
so the rest of the voice pipeline stays testable even when neither SDK is
installed — useful on local dev, CI, and when prod only configures one.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Literal, Protocol

Provider = Literal["elevenlabs", "edge", "kokoro"]


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


class KokoroTTS:
    """Kokoro local ONNX TTS adapter. Fully offline, ~real-time on CPU.

    Returns WAV bytes (16-bit PCM, 24 kHz mono — Kokoro's native sample rate).
    Browsers play WAV natively over WebSocket; the rest of the voice pipeline
    doesn't assume any specific audio format from synthesize().

    Initialization loads the ONNX model (~80 MB) into RAM, so we do it once
    per instance and reuse across calls. Voice can be changed per-call via
    the ``voice`` argument without reloading the model.
    """

    DEFAULT_MODEL_PATH = str(Path.home() / ".kokoro" / "kokoro-v1.0.onnx")
    DEFAULT_VOICES_PATH = str(Path.home() / ".kokoro" / "voices-v1.0.bin")
    DEFAULT_VOICE = "af_sarah"

    def __init__(
        self,
        model_path: str | None = None,
        voices_path: str | None = None,
        default_voice: str | None = None,
    ):
        try:
            from kokoro_onnx import Kokoro
        except ImportError as e:
            raise RuntimeError(
                "kokoro-onnx not installed. Run `pip install kokoro-onnx soundfile`."
            ) from e

        self.model_path = model_path or os.getenv("KOKORO_MODEL_PATH") or self.DEFAULT_MODEL_PATH
        self.voices_path = voices_path or os.getenv("KOKORO_VOICES_PATH") or self.DEFAULT_VOICES_PATH
        self.default_voice = (
            default_voice or os.getenv("KOKORO_DEFAULT_VOICE") or self.DEFAULT_VOICE
        )

        if not Path(self.model_path).exists():
            raise RuntimeError(
                f"Kokoro model not found at {self.model_path}. "
                f"See narai/voice/tts.py docstring for the download command."
            )
        if not Path(self.voices_path).exists():
            raise RuntimeError(
                f"Kokoro voices file not found at {self.voices_path}. "
                f"See narai/voice/tts.py docstring for the download command."
            )

        # Load the model once; reuse across synthesize calls
        self.kokoro = Kokoro(self.model_path, self.voices_path)

    async def synthesize(self, text: str, voice: str | None = None) -> bytes:
        try:
            import soundfile as sf
        except ImportError as e:
            raise RuntimeError(
                "soundfile not installed (needed to encode Kokoro output as WAV). "
                "Run `pip install soundfile`."
            ) from e

        samples, sample_rate = self.kokoro.create(
            text,
            voice=voice or self.default_voice,
            speed=1.0,
            lang="en-us",
        )
        buf = io.BytesIO()
        sf.write(buf, samples, sample_rate, format="WAV", subtype="PCM_16")
        return buf.getvalue()


def get_tts(provider: Provider = "edge") -> TTSClient:
    if provider == "kokoro":
        return KokoroTTS()
    if provider == "elevenlabs":
        return ElevenLabsTTS()
    return EdgeTTS()
