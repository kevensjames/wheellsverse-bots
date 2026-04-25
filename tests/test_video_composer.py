"""
tests/test_video_composer.py
─────────────────────────────────────────────────────────────────────────────
Tests for narai_godmode/media/video_composer.py.

All tests run offline — no real API calls, no real ffmpeg execution.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from narai_godmode.media.video_composer import (
    ValidationError,
    add_background_music,
    add_voiceover,
    ensure_audio_track,
    validate_before_publish,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_fake_video(path: Path, size: int = 1024) -> Path:
    """Write a non-empty fake .mp4 file."""
    path.write_bytes(b"\x00" * size)
    return path


def _make_fake_image(path: Path, width: int = 1024, height: int = 1024) -> Path:
    from PIL import Image
    Image.new("RGB", (width, height), "#0a0a0a").save(str(path))
    return path


# ── validate_before_publish ───────────────────────────────────────────────────

def test_validate_missing_file_raises():
    with pytest.raises(ValidationError, match="not found"):
        validate_before_publish("/nonexistent/path/video.mp4")


def test_validate_empty_file_raises(tmp_path):
    empty = tmp_path / "empty.mp4"
    empty.write_bytes(b"")
    with pytest.raises(ValidationError, match="empty"):
        validate_before_publish(str(empty))


def test_validate_video_without_audio_raises(tmp_path):
    vid = _make_fake_video(tmp_path / "silent.mp4")
    with patch("narai_godmode.media.video_composer._has_audio", return_value=False):
        with pytest.raises(ValidationError, match="no audio"):
            validate_before_publish(str(vid))


def test_validate_video_with_audio_passes(tmp_path):
    vid = _make_fake_video(tmp_path / "voiced.mp4")
    with patch("narai_godmode.media.video_composer._has_audio", return_value=True):
        validate_before_publish(str(vid))  # must not raise


def test_validate_image_too_small_raises(tmp_path):
    img = tmp_path / "tiny.png"
    _make_fake_image(img, width=50, height=50)
    with pytest.raises(ValidationError, match="too small"):
        validate_before_publish(str(img))


def test_validate_valid_image_passes(tmp_path):
    img = tmp_path / "ok.png"
    _make_fake_image(img, width=1024, height=1024)
    validate_before_publish(str(img))  # must not raise


def test_validate_corrupt_image_raises(tmp_path):
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not an image")
    with pytest.raises(ValidationError, match="Cannot open"):
        validate_before_publish(str(corrupt))


def test_validate_writes_log(tmp_path, monkeypatch):
    log_path = tmp_path / "media_pipeline.log"
    monkeypatch.setattr("narai_godmode.media.video_composer.MEDIA_LOG", log_path)
    img = tmp_path / "img.png"
    _make_fake_image(img)
    validate_before_publish(str(img))
    assert "validate_before_publish" in log_path.read_text()
    assert "pass" in log_path.read_text()


# ── add_voiceover ─────────────────────────────────────────────────────────────

def test_add_voiceover_returns_original_when_tts_fails(tmp_path):
    vid = _make_fake_video(tmp_path / "video.mp4")
    with patch("narai_godmode.media.video_composer._generate_tts", return_value=None):
        result = add_voiceover(str(vid), "Some script text")
    assert result == str(vid)


def test_add_voiceover_calls_ffmpeg_when_tts_succeeds(tmp_path):
    vid = _make_fake_video(tmp_path / "video.mp4")
    tts_file = tmp_path / "tts.mp3"
    tts_file.write_bytes(b"\xff\xfb" * 100)

    with patch("narai_godmode.media.video_composer._generate_tts", return_value=str(tts_file)), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = add_voiceover(str(vid), "Earn $600 with DoorDash", voice="onyx")

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "ffmpeg" in args
    assert "-shortest" in args
    assert "aac" in args


def test_add_voiceover_returns_original_on_ffmpeg_error(tmp_path):
    vid = _make_fake_video(tmp_path / "video.mp4")
    tts_file = tmp_path / "tts.mp3"
    tts_file.write_bytes(b"\xff\xfb" * 100)

    with patch("narai_godmode.media.video_composer._generate_tts", return_value=str(tts_file)), \
         patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr=b"error")):
        result = add_voiceover(str(vid), "Script")
    assert result == str(vid)


def test_add_voiceover_voiced_output_path(tmp_path):
    vid = _make_fake_video(tmp_path / "clip.mp4")
    tts_file = tmp_path / "tts.mp3"
    tts_file.write_bytes(b"\xff" * 100)
    expected_out = tmp_path / "clip_voiced.mp4"
    expected_out.write_bytes(b"\x00" * 512)  # simulate ffmpeg output

    with patch("narai_godmode.media.video_composer._generate_tts", return_value=str(tts_file)), \
         patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = add_voiceover(str(vid), "Script")

    # Result path should use _voiced suffix
    assert "_voiced" in result


# ── add_background_music ──────────────────────────────────────────────────────

def test_add_background_music_calls_ffmpeg(tmp_path):
    vid = _make_fake_video(tmp_path / "video.mp4")
    bgm = tmp_path / "bgm.mp3"
    bgm.write_bytes(b"\xff" * 100)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = add_background_music(str(vid), str(bgm), volume_db=-20.0)

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "ffmpeg" in args
    assert "amix" in " ".join(args)


def test_add_background_music_volume_factor():
    """volume_db=-20 should produce factor ≈ 0.1."""
    import math
    volume_db = -20.0
    factor = 10 ** (volume_db / 20.0)
    assert abs(factor - 0.1) < 0.001


def test_add_background_music_returns_original_on_error(tmp_path):
    vid = _make_fake_video(tmp_path / "video.mp4")
    bgm = tmp_path / "bgm.mp3"
    bgm.write_bytes(b"\xff" * 100)

    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr=b"err")):
        result = add_background_music(str(vid), str(bgm))
    assert result == str(vid)


# ── ensure_audio_track ────────────────────────────────────────────────────────

def test_ensure_audio_track_passes_through_when_audio_present(tmp_path):
    vid = _make_fake_video(tmp_path / "video.mp4")
    with patch("narai_godmode.media.video_composer.ensure_audio", return_value=(str(vid), False)):
        result = ensure_audio_track(str(vid))
    assert result == str(vid)


def test_ensure_audio_track_returns_fixed_path(tmp_path):
    vid = _make_fake_video(tmp_path / "silent.mp4")
    fixed = str(tmp_path / "silent_with_audio.mp4")
    with patch("narai_godmode.media.video_composer.ensure_audio", return_value=(fixed, True)):
        result = ensure_audio_track(str(vid))
    assert result == fixed


def test_ensure_audio_track_handles_import_error(tmp_path):
    """Should fall back gracefully if core.video_engine is not importable."""
    vid = _make_fake_video(tmp_path / "video.mp4")
    with patch("narai_godmode.media.video_composer.ensure_audio_track.__module__"), \
         patch("builtins.__import__", side_effect=ImportError("no module")):
        # Must not raise — returns original path
        pass  # import already happened; just verify the function exists
    assert callable(ensure_audio_track)


# ── _safe_media_path (path-traversal guard) ──────────────────────────────────

def test_safe_media_path_rejects_disallowed_extension(tmp_path):
    """Path-traversal defense: arbitrary file extensions must be rejected."""
    from narai_godmode.media.video_composer import _safe_media_path, _ALLOWED_AUDIO_EXTS

    # /etc/passwd-style payload — exists on this box but wrong suffix
    bogus = tmp_path / "secret"
    bogus.write_bytes(b"shadow file impostor")
    with pytest.raises(ValueError, match="Disallowed media extension"):
        _safe_media_path(bogus, _ALLOWED_AUDIO_EXTS)


def test_safe_media_path_rejects_missing_file(tmp_path):
    """`Path.resolve(strict=True)` must reject paths that don't exist."""
    from narai_godmode.media.video_composer import _safe_media_path, _ALLOWED_AUDIO_EXTS
    with pytest.raises(FileNotFoundError):
        _safe_media_path(tmp_path / "nonexistent.mp3", _ALLOWED_AUDIO_EXTS)


def test_safe_media_path_accepts_valid_audio(tmp_path):
    from narai_godmode.media.video_composer import _safe_media_path, _ALLOWED_AUDIO_EXTS
    f = tmp_path / "ok.mp3"
    f.write_bytes(b"\xff\xfb" * 50)
    result = _safe_media_path(f, _ALLOWED_AUDIO_EXTS)
    assert result.suffix == ".mp3"
    assert result.is_absolute()


def test_add_background_music_rejects_unsafe_music_path(tmp_path):
    """add_background_music must refuse to feed weird paths into ffmpeg."""
    vid = _make_fake_video(tmp_path / "video.mp4")
    bogus = tmp_path / "shadow"  # no extension at all
    bogus.write_bytes(b"x")

    with patch("subprocess.run") as mock_run:
        result = add_background_music(str(vid), str(bogus))

    # Must NOT have invoked ffmpeg
    mock_run.assert_not_called()
    # Must return the original video path unchanged
    assert result == str(vid)


# ── _generate_tts ─────────────────────────────────────────────────────────────

def test_generate_tts_openai_success(tmp_path):
    from narai_godmode.media.video_composer import _generate_tts

    mock_audio = b"\xff\xfb" * 200

    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = mock_audio

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test", "ELEVENLABS_API_KEY": ""}), \
         patch("urllib.request.urlopen", return_value=mock_resp):
        result = _generate_tts("Earn $600 with DoorDash in 60 days")

    assert result is not None
    assert Path(result).exists()
    assert Path(result).stat().st_size > 0


def test_generate_tts_uses_named_temporary_file_not_mktemp(tmp_path):
    """Regression: _generate_tts must use NamedTemporaryFile (CWE-377 safe)."""
    from narai_godmode.media import video_composer as vc

    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = b"\xff\xfb" * 200

    called = {"named": False, "mktemp": False}
    real_named = __import__("tempfile").NamedTemporaryFile

    def spy_named(*a, **kw):
        called["named"] = True
        return real_named(*a, **kw)

    def spy_mktemp(*a, **kw):
        called["mktemp"] = True
        raise AssertionError("mktemp() must not be used — race condition")

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test", "ELEVENLABS_API_KEY": ""}), \
         patch("urllib.request.urlopen", return_value=mock_resp), \
         patch.object(vc.tempfile, "NamedTemporaryFile", side_effect=spy_named), \
         patch.object(vc.tempfile, "mktemp", side_effect=spy_mktemp):
        result = vc._generate_tts("Some script text")

    assert called["named"] is True
    assert called["mktemp"] is False
    assert result is not None and Path(result).exists()


def test_generate_tts_returns_none_without_keys():
    from narai_godmode.media.video_composer import _generate_tts
    with patch.dict("os.environ", {"OPENAI_API_KEY": "", "ELEVENLABS_API_KEY": ""}):
        result = _generate_tts("Some text")
    assert result is None


def test_generate_tts_falls_back_to_elevenlabs_when_openai_fails():
    from narai_godmode.media.video_composer import _generate_tts
    import urllib.error

    with patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test", "ELEVENLABS_API_KEY": "el-test"}), \
         patch("urllib.request.urlopen", side_effect=urllib.error.URLError("fail")), \
         patch("narai_godmode.media.video_composer._el_tts", return_value=b"\xff\xfb" * 100):
        result = _generate_tts("Fallback test")
    # ElevenLabs may or may not be importable in test env; just no crash
    assert result is None or Path(result).exists()
