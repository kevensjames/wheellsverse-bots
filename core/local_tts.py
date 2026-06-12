"""Local TTS via Piper — drop-in for ElevenLabs / OpenAI TTS.

Renders text to MP3 bytes (same shape as the cloud TTS providers) so it slots
into the existing voice_router cascade with no shape changes. WAV is produced
internally and converted to MP3 via ffmpeg.

Activated when:
  - TTS_PROVIDER=local in env, OR
  - LLM_BACKEND=ollama (consistency with text path), unless a higher-priority
    provider is explicitly selected.

Voice model lives at data/piper_voices/<name>.onnx (+ .onnx.json sidecar).
Default model: en_US-amy-medium. Override via PIPER_VOICE env.
"""
from __future__ import annotations

import io
import logging
import os
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Optional

logger = logging.getLogger("local_tts")

_VOICES_DIR = Path(__file__).resolve().parent.parent / "data" / "piper_voices"
_VOICE_CACHE: dict[str, object] = {}


def _resolve_voice_path(voice_name: Optional[str] = None) -> Path:
    name = voice_name or os.getenv("PIPER_VOICE", "en_US-amy-medium")
    model_path = _VOICES_DIR / f"{name}.onnx"
    if not model_path.exists():
        raise FileNotFoundError(
            f"Piper voice not found: {model_path}. "
            f"Download with: curl -L -o {model_path} "
            f"'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/{name.replace('en_US-','').replace('-medium','')}/medium/{name}.onnx'"
        )
    return model_path


def _get_voice(voice_name: Optional[str] = None):
    """Load (and cache) a PiperVoice instance."""
    name = voice_name or os.getenv("PIPER_VOICE", "en_US-amy-medium")
    if name not in _VOICE_CACHE:
        from piper import PiperVoice
        _VOICE_CACHE[name] = PiperVoice.load(_resolve_voice_path(name))
        logger.info(f"Loaded Piper voice: {name}")
    return _VOICE_CACHE[name]


def synthesize_wav(text: str, voice_name: Optional[str] = None) -> bytes:
    """Return 22050 Hz mono PCM WAV bytes for the given text."""
    voice = _get_voice(voice_name)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_out:
        voice.synthesize_wav(text, wav_out)
    return buf.getvalue()


def synthesize_mp3(text: str, voice_name: Optional[str] = None) -> bytes:
    """Return MP3 bytes — what voice_router cascade expects."""
    wav_bytes = synthesize_wav(text, voice_name)
    # ffmpeg WAV → MP3 via stdin/stdout (no temp files)
    try:
        proc = subprocess.run(
            ["ffmpeg", "-loglevel", "error", "-f", "wav", "-i", "pipe:0",
             "-codec:a", "libmp3lame", "-qscale:a", "4", "-f", "mp3", "pipe:1"],
            input=wav_bytes, capture_output=True, check=True,
        )
        return proc.stdout
    except FileNotFoundError:
        logger.warning("ffmpeg not found — returning WAV instead of MP3")
        return wav_bytes
    except subprocess.CalledProcessError as e:
        logger.warning(f"ffmpeg conversion failed ({e.returncode}): {e.stderr.decode(errors='ignore')[:200]}")
        return wav_bytes


def is_available() -> bool:
    """Cheap check: voice file present + piper installed."""
    try:
        _resolve_voice_path()
        import piper  # noqa: F401
        return True
    except Exception:
        return False
