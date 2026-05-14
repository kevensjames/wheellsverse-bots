"""
STT adapter. Choose one of:

  * ``openai``      — OpenAI Whisper API (~$0.006/min, requires OPENAI_API_KEY)
  * ``local``       — faster-whisper Python package (free, CPU-only)
  * ``whisper-cpp`` — whisper.cpp C++ binary (free, fastest local option)

Setup for whisper-cpp (Mac mini):
  $ brew install whisper-cpp ffmpeg
  $ mkdir -p ~/.whisper-cpp && cd ~/.whisper-cpp
  $ curl -L -o ggml-base.en.bin \\
      https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin

Env overrides:
  WHISPER_CPP_BIN    full path to the whisper-cli executable
  WHISPER_CPP_MODEL  full path to a .bin model file

SDK imports live inside __init__ so an unconfigured provider doesn't poison
module-level imports — same rationale as tts.py.
"""
from __future__ import annotations

import io
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal, Protocol

Provider = Literal["openai", "local", "whisper-cpp"]


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


class WhisperCpp:
    """whisper.cpp C++ binary adapter. Lowest latency on CPU.

    Two binaries on disk are required:
      * ``whisper-cli`` (the executable, from ``brew install whisper-cpp``)
      * ``ffmpeg`` (from ``brew install ffmpeg``) — for converting the
        browser's webm/mp4 audio into the 16 kHz mono PCM WAV that
        whisper.cpp expects.

    The audio-format conversion via ffmpeg is the same step ``faster-whisper``
    does internally via PyAV; we just call ffmpeg explicitly here.
    """

    DEFAULT_MODEL_PATH = str(Path.home() / ".whisper-cpp" / "ggml-base.en.bin")

    def __init__(
        self,
        bin_path: str | None = None,
        model_path: str | None = None,
        ffmpeg_bin: str | None = None,
    ):
        self.bin = bin_path or os.getenv("WHISPER_CPP_BIN") or (
            shutil.which("whisper-cli") or shutil.which("main") or ""
        )
        self.model = model_path or os.getenv("WHISPER_CPP_MODEL") or self.DEFAULT_MODEL_PATH
        self.ffmpeg = ffmpeg_bin or shutil.which("ffmpeg") or ""

        if not self.bin or not Path(self.bin).exists():
            raise RuntimeError(
                "whisper.cpp binary not found. Install with `brew install "
                "whisper-cpp` or set WHISPER_CPP_BIN to its full path."
            )
        if not Path(self.model).exists():
            raise RuntimeError(
                f"whisper.cpp model not found at {self.model}. "
                f"Download a model (e.g. ggml-base.en.bin) into ~/.whisper-cpp/ "
                f"or set WHISPER_CPP_MODEL."
            )
        if not self.ffmpeg:
            raise RuntimeError(
                "ffmpeg not found in PATH. Install with `brew install ffmpeg` — "
                "whisper.cpp needs it to normalize browser audio to 16 kHz mono WAV."
            )

    async def transcribe(self, audio_bytes: bytes) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            ext = _sniff_audio_ext(audio_bytes)
            in_path = Path(tmp) / f"input.{ext}"
            wav_path = Path(tmp) / "input.wav"
            in_path.write_bytes(audio_bytes)

            # Step 1: ffmpeg → 16 kHz mono PCM WAV (whisper.cpp's native format)
            subprocess.run(
                [
                    self.ffmpeg, "-y", "-loglevel", "error",
                    "-i", str(in_path),
                    "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
                    str(wav_path),
                ],
                check=True,
            )

            # Step 2: whisper-cli — transcription text on stdout via --no-prints
            result = subprocess.run(
                [
                    self.bin,
                    "-m", self.model,
                    "-f", str(wav_path),
                    "-nt",            # no timestamps in the printed text
                    "--no-prints",    # suppress progress logs (transcript only)
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()


def _resolve_default_provider() -> Provider:
    """Pick the default STT provider from env.

    Priority:
      1. NARAI_STT_PROVIDER / STT_PROVIDER explicit setting (any known value)
      2. LLM_BACKEND=ollama (or local/lmstudio/llamacpp) implies local STT,
         keeping the local-LLM workflow consistent with the text path
      3. Fall back to the OpenAI Whisper API
    """
    explicit = (os.getenv("NARAI_STT_PROVIDER") or os.getenv("STT_PROVIDER") or "").strip().lower()
    if explicit in ("local", "openai", "whisper-cpp"):
        return explicit  # type: ignore[return-value]
    if (os.getenv("LLM_BACKEND") or "").strip().lower() in ("ollama", "local", "lmstudio", "llamacpp"):
        return "local"
    return "openai"


def get_stt(provider: Provider | None = None) -> STTClient:
    """Return an STT client. If provider is None, resolve from env."""
    chosen = provider or _resolve_default_provider()
    if chosen == "whisper-cpp":
        return WhisperCpp()
    if chosen == "local":
        return LocalWhisper(model_size=os.getenv("WHISPER_MODEL_SIZE", "base"))
    return OpenAIWhisper()
