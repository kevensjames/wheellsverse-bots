#!/usr/bin/env python3
"""
narai/godmode/media/video_composer.py
─────────────────────────────────────────────────────────────────────────────
Audio layer for generated videos.

  add_voiceover()       — TTS (OpenAI → ElevenLabs fallback) merged via ffmpeg
  add_background_music()— mixes ambient track at low volume under voiceover
  ensure_audio_track()  — thin wrapper around core.video_engine.ensure_audio
  validate_before_publish() — raises ValidationError if asset isn't publish-ready

Delegates audio detection/mixing to core/video_engine.py — no duplication.

Logging: narai/godmode/logs/media_pipeline.log
Format:  timestamp | stage | status | asset_id | detail
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
MEDIA_LOG = Path(__file__).parent.parent / "logs" / "media_pipeline.log"

load_dotenv(ROOT / ".env")

log = logging.getLogger("video_composer")

_TTS_URL = "https://api.openai.com/v1/audio/speech"

_ALLOWED_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".avi", ".mkv"}
_ALLOWED_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".aac", ".flac"}


def _safe_media_path(path: str | Path, allowed_exts: set[str]) -> Path:
    """
    Resolve a media path and reject anything that isn't a real file with an
    expected media extension. Defense-in-depth against passing arbitrary
    paths (e.g. /etc/passwd, ../../secrets) into ffmpeg.
    """
    p = Path(path).resolve(strict=True)
    if p.suffix.lower() not in allowed_exts:
        raise ValueError(
            f"Disallowed media extension {p.suffix!r}; expected one of {sorted(allowed_exts)}"
        )
    return p


# Module-level optional imports — patchable in tests
try:
    from core.video_engine import _has_audio, ensure_audio
except Exception:
    _has_audio = None  # type: ignore[assignment]
    ensure_audio = None  # type: ignore[assignment]

try:
    from core.elevenlabs import text_to_speech as _el_tts
except Exception:
    _el_tts = None  # type: ignore[assignment]


# ── Public API ────────────────────────────────────────────────────────────────

def add_voiceover(
    video_path: str,
    script_text: str,
    voice: str = "onyx",
) -> str:
    """
    Generate TTS audio and merge it into the video.

    Tries OpenAI tts-1 first, then ElevenLabs if ELEVENLABS_API_KEY is set.
    Merges with ffmpeg using -c:v copy so the video stream is never re-encoded.
    Returns the output path; falls back to original if TTS or merge fails.
    """
    try:
        video_path = _safe_media_path(video_path, _ALLOWED_VIDEO_EXTS)
    except (FileNotFoundError, ValueError) as exc:
        log.error(f"add_voiceover rejected unsafe video_path: {exc}")
        _media_log("add_voiceover", "rejected", detail=str(exc)[:120])
        return str(video_path)
    out_path = video_path.parent / f"{video_path.stem}_voiced{video_path.suffix}"

    _media_log("add_voiceover", "start", detail=f"{len(script_text)} chars, voice={voice}")

    audio_path = _generate_tts(script_text, voice)
    if audio_path is None:
        log.warning("TTS generation failed — returning original video unchanged")
        _media_log("add_voiceover", "tts_failed", detail=str(video_path))
        return str(video_path)

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(audio_path),
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "128k",
                "-shortest",
                str(out_path),
            ],
            capture_output=True,
            timeout=120,
            check=True,
        )
        _media_log("add_voiceover", "ok", detail=str(out_path))
        log.info(f"[VideoComposer] Voiceover merged → {out_path}")
        return str(out_path)
    except subprocess.CalledProcessError as exc:
        stderr_text = (exc.stderr or b"").decode("utf-8", errors="replace")
        log.error(f"ffmpeg voiceover merge failed: {stderr_text[:300]}")
        _media_log("add_voiceover", "ffmpeg_error", detail=stderr_text[:120])
        return str(video_path)
    finally:
        # Clean up temp TTS file
        try:
            Path(audio_path).unlink(missing_ok=True)
        except Exception:
            pass


def add_background_music(
    video_path: str,
    music_path: str,
    volume_db: float = -20.0,
) -> str:
    """
    Mix an ambient music track under the existing audio at reduced volume.

    volume_db: dB attenuation for the music track (default -20 dB ≈ 10% volume).
    Returns the output path; falls back to original on ffmpeg error.
    Ensures Instagram detects a valid audio track even when content is visual-only.
    """
    try:
        video_path = _safe_media_path(video_path, _ALLOWED_VIDEO_EXTS)
        music_path = _safe_media_path(music_path, _ALLOWED_AUDIO_EXTS)
    except (FileNotFoundError, ValueError) as exc:
        log.error(f"add_background_music rejected unsafe path: {exc}")
        _media_log("add_background_music", "rejected", detail=str(exc)[:120])
        return str(video_path)
    out_path = video_path.parent / f"{video_path.stem}_bgm{video_path.suffix}"

    volume_factor = 10 ** (volume_db / 20.0)
    _media_log("add_background_music", "start", detail=f"{music_path.name} @ {volume_db}dB")

    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(video_path),
                "-i", str(music_path),
                "-filter_complex",
                (
                    f"[1:a]volume={volume_factor:.4f}[bgm];"
                    "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=3[aout]"
                ),
                "-map", "0:v:0",
                "-map", "[aout]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "128k",
                str(out_path),
            ],
            capture_output=True,
            timeout=180,
            check=True,
        )
        _media_log("add_background_music", "ok", detail=str(out_path))
        log.info(f"[VideoComposer] BGM mixed → {out_path}")
        return str(out_path)
    except subprocess.CalledProcessError as exc:
        stderr_text = (exc.stderr or b"").decode("utf-8", errors="replace")
        log.error(f"ffmpeg BGM mix failed: {stderr_text[:300]}")
        _media_log("add_background_music", "ffmpeg_error", detail=stderr_text[:120])
        return str(video_path)


def ensure_audio_track(video_path: str) -> str:
    """
    Guarantee the video has an audio stream before publishing.

    Delegates to core.video_engine.ensure_audio which tries (in order):
      ElevenLabs TTS → local bgm.mp3 → 1kHz sine tone placeholder.
    Returns the validated/fixed path.
    """
    if ensure_audio is None:
        log.warning("core.video_engine not importable — skipping ensure_audio")
        return video_path
    try:
        result_path, was_fixed = ensure_audio(video_path)
        status = "fixed" if was_fixed else "ok"
        _media_log("ensure_audio_track", status, detail=result_path)
        if was_fixed:
            log.info(f"[VideoComposer] Silent video fixed → {result_path}")
        return result_path
    except Exception as exc:
        log.error(f"ensure_audio_track failed: {exc}")
        _media_log("ensure_audio_track", "error", detail=str(exc)[:120])
        return video_path


class ValidationError(Exception):
    """Raised by validate_before_publish when an asset fails readiness checks."""


def validate_before_publish(asset_path: str) -> None:
    """
    Raise ValidationError with a clear reason if the asset isn't publish-ready.

    Checks:
      - File exists
      - File size > 0
      - .mp4/.mov/.webm must have an audio stream
      - .png/.jpg/.webp must open as a valid image with sane dimensions (≥100px)

    On success returns None. Callers should catch ValidationError, log to
    revenue_gate, skip the post, and continue the queue without crashing.
    """
    path = Path(asset_path)

    if not path.exists():
        raise ValidationError(f"Asset not found: {asset_path}")

    if path.stat().st_size == 0:
        raise ValidationError(f"Asset is empty (0 bytes): {asset_path}")

    suffix = path.suffix.lower()

    if suffix in {".mp4", ".mov", ".webm", ".avi"}:
        if _has_audio is not None:
            if not _has_audio(str(path)):
                raise ValidationError(f"Video has no audio stream: {asset_path}")
        else:
            log.warning("core.video_engine not importable — skipping audio check")

    elif suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        try:
            from PIL import Image
            with Image.open(str(path)) as img:
                w, h = img.size
            if w < 100 or h < 100:
                raise ValidationError(
                    f"Image dimensions too small ({w}×{h}px, min 100×100): {asset_path}"
                )
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError(f"Cannot open image {asset_path}: {exc}") from exc

    _media_log("validate_before_publish", "pass", detail=asset_path)
    log.debug(f"[VideoComposer] Validation passed: {asset_path}")


# ── TTS helpers ───────────────────────────────────────────────────────────────

def _generate_tts(text: str, voice: str = "onyx") -> Optional[str]:
    """
    Generate speech audio from text.
    Returns path to a temp .mp3 file, or None if both backends fail.
    """
    # NamedTemporaryFile creates atomically with secure perms (CWE-377 safe);
    # delete=False because the caller is responsible for cleanup after ffmpeg merge.
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as _fh:
        tmp = Path(_fh.name)

    # ── OpenAI TTS ────────────────────────────────────────────────────────────
    key = os.getenv("OPENAI_API_KEY", "")
    if key:
        try:
            body = json.dumps({
                "model": "tts-1",
                "input": text[:4096],
                "voice": voice,
            }).encode()
            req = urllib.request.Request(
                _TTS_URL,
                data=body,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                tmp.write_bytes(resp.read())
            _media_log("_generate_tts", "ok_openai", detail=f"{len(text)} chars")
            return str(tmp)
        except Exception as exc:
            log.warning(f"OpenAI TTS failed: {exc}")

    # ── ElevenLabs fallback ───────────────────────────────────────────────────
    el_key = os.getenv("ELEVENLABS_API_KEY", "")
    if el_key and _el_tts is not None:
        try:
            audio_bytes = _el_tts(text[:500])
            if audio_bytes:
                tmp.write_bytes(audio_bytes)
                _media_log("_generate_tts", "ok_elevenlabs", detail=f"{len(text)} chars")
                return str(tmp)
        except Exception as exc:
            log.warning(f"ElevenLabs TTS failed: {exc}")

    _media_log("_generate_tts", "all_failed", detail="no audio generated")
    return None


# ── Logging ───────────────────────────────────────────────────────────────────

def _media_log(
    stage: str,
    status: str,
    asset_id: str = "-",
    detail: str = "",
) -> None:
    """Append one structured line to media_pipeline.log."""
    MEDIA_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"{ts} | {stage:<30} | {status:<10} | {asset_id:<20} | {detail}\n"
    try:
        with open(MEDIA_LOG, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass
