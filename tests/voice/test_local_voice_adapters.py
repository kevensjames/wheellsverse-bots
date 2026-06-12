"""Week 4-D acceptance — Whisper.cpp STT + Kokoro TTS local adapters.

Both adapters call out to external systems (subprocess for Whisper.cpp,
the kokoro-onnx package for Kokoro). Tests mock those boundaries so they
run in <100 ms without any binaries or model files on disk.

Covers:
  STT (Whisper.cpp)
    1. Factory picks WhisperCpp for provider="whisper-cpp"
    2. Factory picks LocalWhisper for provider="local" (regression)
    3. Factory picks OpenAIWhisper for default (regression)
    4. __init__ raises clear error if binary missing
    5. __init__ raises clear error if model missing
    6. __init__ raises clear error if ffmpeg missing
    7. transcribe() runs ffmpeg then whisper-cli and returns stdout

  TTS (Kokoro)
    8. Factory picks KokoroTTS for provider="kokoro"
    9. Factory picks ElevenLabsTTS for provider="elevenlabs" (regression)
   10. Factory picks EdgeTTS for default (regression)
   11. __init__ raises clear error if kokoro-onnx not installed
   12. __init__ raises clear error if model file missing
   13. __init__ raises clear error if voices file missing
   14. synthesize() returns WAV bytes via soundfile
"""
from __future__ import annotations

import asyncio
import io
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from narai.voice import stt as stt_mod
from narai.voice import tts as tts_mod


# ── STT factory ──────────────────────────────────────────────────────────────


def test_factory_picks_whisper_cpp_for_whisper_cpp(monkeypatch):
    """get_stt('whisper-cpp') instantiates WhisperCpp. Mock all 3 pre-flight
    checks so __init__ doesn't fail in the test environment."""
    monkeypatch.setattr(stt_mod.shutil, "which",
                        lambda name: "/usr/bin/" + name if name in ("whisper-cli", "ffmpeg") else None)
    monkeypatch.setattr(stt_mod.Path, "exists", lambda self: True)
    client = stt_mod.get_stt("whisper-cpp")
    assert isinstance(client, stt_mod.WhisperCpp)


def test_factory_picks_local_for_local_regression():
    """Regression: 'local' still returns LocalWhisper (don't break Week 1 paths)."""
    # LocalWhisper's __init__ imports faster_whisper which may not be installed
    # in the test env — patch it to a no-op.
    fake_module = types.ModuleType("faster_whisper")
    fake_module.WhisperModel = MagicMock(return_value=MagicMock())
    with patch.dict(sys.modules, {"faster_whisper": fake_module}):
        client = stt_mod.get_stt("local")
        assert isinstance(client, stt_mod.LocalWhisper)


def test_factory_picks_openai_for_default_regression(monkeypatch):
    """Regression: default (no provider arg) returns OpenAIWhisper."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-fake")
    # Patch openai SDK import
    fake_openai = types.ModuleType("openai")
    fake_openai.OpenAI = MagicMock(return_value=MagicMock())
    with patch.dict(sys.modules, {"openai": fake_openai}):
        client = stt_mod.get_stt()
        assert isinstance(client, stt_mod.OpenAIWhisper)


# ── WhisperCpp construction guards ───────────────────────────────────────────


def test_whisper_cpp_init_raises_if_binary_missing(monkeypatch):
    monkeypatch.setattr(stt_mod.shutil, "which", lambda name: None)
    monkeypatch.delenv("WHISPER_CPP_BIN", raising=False)
    with pytest.raises(RuntimeError, match=r"whisper.cpp binary not found"):
        stt_mod.WhisperCpp()


def test_whisper_cpp_init_raises_if_model_missing(monkeypatch):
    # Binary + ffmpeg present, model absent
    monkeypatch.setattr(stt_mod.shutil, "which",
                        lambda name: "/usr/bin/" + name if name in ("whisper-cli", "ffmpeg") else None)
    # Only the binary path exists; the model path doesn't
    real_exists = stt_mod.Path.exists
    monkeypatch.setattr(
        stt_mod.Path, "exists",
        lambda self: str(self).endswith("whisper-cli") or str(self).endswith("ffmpeg"),
    )
    with pytest.raises(RuntimeError, match=r"whisper.cpp model not found"):
        stt_mod.WhisperCpp(bin_path="/usr/bin/whisper-cli", model_path="/nonexistent/model.bin")


def test_whisper_cpp_init_raises_if_ffmpeg_missing(monkeypatch):
    # Binary + model present, ffmpeg absent
    monkeypatch.setattr(stt_mod.shutil, "which",
                        lambda name: "/usr/bin/whisper-cli" if name == "whisper-cli" else None)
    monkeypatch.setattr(stt_mod.Path, "exists", lambda self: True)
    with pytest.raises(RuntimeError, match=r"ffmpeg not found"):
        stt_mod.WhisperCpp()


def test_whisper_cpp_transcribe_pipes_through_ffmpeg_and_whisper_cli(monkeypatch):
    """transcribe() must run ffmpeg first (audio normalize) then whisper-cli."""
    monkeypatch.setattr(stt_mod.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(stt_mod.Path, "exists", lambda self: True)

    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(args)
        # Mimic CompletedProcess shape — whisper-cli writes transcript to stdout
        result = MagicMock()
        result.stdout = "hello world\n"
        result.returncode = 0
        return result

    monkeypatch.setattr(stt_mod.subprocess, "run", fake_run)

    client = stt_mod.WhisperCpp(
        bin_path="/usr/bin/whisper-cli",
        model_path="/models/ggml-base.en.bin",
        ffmpeg_bin="/usr/bin/ffmpeg",
    )
    # webm magic bytes
    audio = b"\x1aE\xdf\xa3" + b"\x00" * 100
    transcript = asyncio.run(client.transcribe(audio))

    assert transcript == "hello world"
    assert len(calls) == 2, f"expected 2 subprocess calls, got {len(calls)}"
    assert calls[0][0] == "/usr/bin/ffmpeg"
    assert calls[1][0] == "/usr/bin/whisper-cli"
    # whisper-cli must be invoked with the converted WAV, not the original webm.
    # Find the "-f" flag in args and confirm the value after it ends in .wav.
    whisper_args = calls[1]
    f_idx = whisper_args.index("-f")
    assert whisper_args[f_idx + 1].endswith(".wav"), (
        f"-f arg should be .wav, got {whisper_args[f_idx + 1]}"
    )


# ── TTS factory ──────────────────────────────────────────────────────────────


def test_factory_picks_kokoro_for_kokoro(monkeypatch, tmp_path):
    """get_tts('kokoro') instantiates KokoroTTS. Mock the kokoro_onnx import
    and the on-disk files."""
    # Create fake model + voices files so __init__'s existence check passes
    model_file = tmp_path / "kokoro.onnx"
    voices_file = tmp_path / "voices.bin"
    model_file.write_bytes(b"\x00")
    voices_file.write_bytes(b"\x00")
    monkeypatch.setenv("KOKORO_MODEL_PATH", str(model_file))
    monkeypatch.setenv("KOKORO_VOICES_PATH", str(voices_file))

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = MagicMock(return_value=MagicMock())
    with patch.dict(sys.modules, {"kokoro_onnx": fake_module}):
        client = tts_mod.get_tts("kokoro")
        assert isinstance(client, tts_mod.KokoroTTS)


def test_factory_picks_elevenlabs_for_elevenlabs_regression(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-test-fake")
    fake_module = types.ModuleType("elevenlabs.client")
    fake_module.ElevenLabs = MagicMock(return_value=MagicMock())
    parent = types.ModuleType("elevenlabs")
    parent.client = fake_module
    with patch.dict(sys.modules, {"elevenlabs": parent, "elevenlabs.client": fake_module}):
        client = tts_mod.get_tts("elevenlabs")
        assert isinstance(client, tts_mod.ElevenLabsTTS)


def test_factory_picks_edge_for_default_regression():
    client = tts_mod.get_tts()
    assert isinstance(client, tts_mod.EdgeTTS)


# ── KokoroTTS construction guards ────────────────────────────────────────────


def test_kokoro_init_raises_if_package_missing(monkeypatch):
    """If `pip install kokoro-onnx` wasn't run, the import fails — surface
    a useful error with the install command, not an obscure ImportError."""
    # Force ImportError on `from kokoro_onnx import Kokoro` by removing from sys.modules
    monkeypatch.delitem(sys.modules, "kokoro_onnx", raising=False)
    # Block re-import by intercepting the import machinery
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "kokoro_onnx":
            raise ImportError("No module named 'kokoro_onnx'")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=blocked_import):
        with pytest.raises(RuntimeError, match=r"kokoro-onnx not installed"):
            tts_mod.KokoroTTS()


def test_kokoro_init_raises_if_model_file_missing(monkeypatch, tmp_path):
    """Package installed, model file absent → clear error pointing at docs."""
    voices_file = tmp_path / "voices.bin"
    voices_file.write_bytes(b"\x00")
    monkeypatch.setenv("KOKORO_MODEL_PATH", "/nonexistent/kokoro.onnx")
    monkeypatch.setenv("KOKORO_VOICES_PATH", str(voices_file))

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = MagicMock()
    with patch.dict(sys.modules, {"kokoro_onnx": fake_module}):
        with pytest.raises(RuntimeError, match=r"Kokoro model not found"):
            tts_mod.KokoroTTS()


def test_kokoro_init_raises_if_voices_file_missing(monkeypatch, tmp_path):
    """Package + model present, voices absent → clear error."""
    model_file = tmp_path / "kokoro.onnx"
    model_file.write_bytes(b"\x00")
    monkeypatch.setenv("KOKORO_MODEL_PATH", str(model_file))
    monkeypatch.setenv("KOKORO_VOICES_PATH", "/nonexistent/voices.bin")

    fake_module = types.ModuleType("kokoro_onnx")
    fake_module.Kokoro = MagicMock()
    with patch.dict(sys.modules, {"kokoro_onnx": fake_module}):
        with pytest.raises(RuntimeError, match=r"Kokoro voices file not found"):
            tts_mod.KokoroTTS()


def test_kokoro_synthesize_returns_wav_bytes(monkeypatch, tmp_path):
    """End-to-end happy path: synthesize() writes WAV-shaped bytes via
    soundfile. Both kokoro_onnx AND soundfile are mocked so the test
    doesn't require either package installed."""
    model_file = tmp_path / "kokoro.onnx"
    voices_file = tmp_path / "voices.bin"
    model_file.write_bytes(b"\x00")
    voices_file.write_bytes(b"\x00")
    monkeypatch.setenv("KOKORO_MODEL_PATH", str(model_file))
    monkeypatch.setenv("KOKORO_VOICES_PATH", str(voices_file))

    # Mock kokoro_onnx.Kokoro.create → (samples, sample_rate)
    fake_kokoro_instance = MagicMock()
    fake_kokoro_instance.create.return_value = ([0.0] * 24000, 24000)
    fake_kokoro = types.ModuleType("kokoro_onnx")
    fake_kokoro.Kokoro = MagicMock(return_value=fake_kokoro_instance)

    # Mock soundfile.write to emit a minimal RIFF/WAVE-shaped payload —
    # asserts behavior (RIFF magic) without depending on real soundfile.
    fake_sf = types.ModuleType("soundfile")

    def fake_write(buf, samples, rate, format=None, subtype=None):
        # 44-byte WAV header stub: RIFF<size>WAVEfmt …
        header = b"RIFF" + b"\x00" * 4 + b"WAVEfmt " + b"\x00" * 28
        buf.write(header + b"\x00" * 4)  # +4 data bytes
    fake_sf.write = fake_write

    with patch.dict(sys.modules, {"kokoro_onnx": fake_kokoro, "soundfile": fake_sf}):
        client = tts_mod.KokoroTTS()
        wav_bytes = asyncio.run(client.synthesize("hello", voice="af_sarah"))

    # WAV files start with "RIFF" magic bytes; verify our output is WAV-shaped
    assert wav_bytes[:4] == b"RIFF", "expected WAV format output"
    assert b"WAVE" in wav_bytes[:12], "expected WAVE marker in header"
    # Verify the voice override propagated to Kokoro.create
    fake_kokoro_instance.create.assert_called_once()
    call_kwargs = fake_kokoro_instance.create.call_args.kwargs
    assert call_kwargs["voice"] == "af_sarah"
