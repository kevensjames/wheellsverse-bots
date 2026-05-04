#!/usr/bin/env python3
"""
core/video_engine.py
─────────────────────────────────────────────────────────────────────────────
NarAI Video Generation Engine

Supports:
  • Runway ML Gen-3 Alpha  — cinematic / realistic AI video
  • Pika Labs 2.2          — anime, stylized, motion video
  • HeyGen                 — avatar talking-head video

NarAI picks the best tool based on the video style:
  anime / cartoon / stylized  →  Pika Labs
  cinematic / realistic       →  Runway ML
  talking head / explainer    →  HeyGen

After generation, video is auto-posted to:
  TikTok, Instagram Reels, YouTube Shorts, Facebook Video
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
VIDEO_DIR = ROOT / "outputs" / "videos"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

log = logging.getLogger("video_engine")


# ══════════════════════════════════════════════════════════════════════════════
# AUDIO GUARD — detect silent video and add audio before publishing
# ══════════════════════════════════════════════════════════════════════════════

def _has_audio(video_path: str) -> bool:
    """Return True if the video file contains at least one audio stream."""
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                str(video_path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        return bool(result.stdout.strip())
    except FileNotFoundError:
        log.warning("ffprobe not found — skipping audio check (install ffmpeg)")
        return True   # assume ok if we can't check
    except Exception as e:
        log.warning(f"Audio check failed: {e}")
        return True


def _add_audio_to_video(video_path: str, caption: str = "") -> Optional[str]:
    """
    Add real audio to a silent video. Returns the path to the new file, or
    None when no genuine audio source is available — callers must then skip
    publishing rather than ship a silent reel.

    Strategy (in order):
      1. ElevenLabs TTS of the caption → voiceover (looped if shorter than video)
      2. Royalty-free background music from a local file
      (Note: we deliberately do NOT fall back to a sine-tone beep — it sounds
       worse than no audio at all and turns viewers away.)
    """
    video_path = Path(video_path)
    out_path = video_path.parent / f"{video_path.stem}_with_audio{video_path.suffix}"

    audio_path: Optional[Path] = None
    loop_audio = False  # voiceover is usually shorter than the clip

    # ── Strategy 1: ElevenLabs TTS voiceover ──────────────────────────────────
    if caption and os.getenv("ELEVENLABS_API_KEY"):
        try:
            from core.elevenlabs import text_to_speech
            audio_bytes = text_to_speech(caption[:500])   # keep it short
            if audio_bytes:
                audio_path = video_path.parent / f"{video_path.stem}_tts.mp3"
                audio_path.write_bytes(audio_bytes)
                loop_audio = True
                log.info(f"TTS audio generated: {audio_path}")
        except Exception as e:
            log.warning(f"ElevenLabs TTS failed: {e}")

    # ── Strategy 2: local background music file ────────────────────────────────
    if audio_path is None:
        for f in (ROOT / "data" / "background_music.mp3",
                  ROOT / "data" / "bgm.mp3",
                  ROOT / "assets" / "bgm.mp3"):
            if f.exists():
                audio_path = f
                loop_audio = True   # bgm tracks are often shorter than reels
                log.info(f"Using background music: {audio_path}")
                break

    if audio_path is None:
        log.error("No audio source available (TTS unavailable and no bgm.mp3) — "
                  "cannot mux audio for %s", video_path.name)
        return None

    # ── Mix audio into video with ffmpeg ──────────────────────────────────────
    try:
        cmd = ["ffmpeg", "-y", "-i", str(video_path)]
        # Loop the audio source so a 8s voiceover doesn't dead-air a 30s clip.
        # -shortest below trims back to video length.
        if loop_audio:
            cmd += ["-stream_loop", "-1"]
        cmd += [
            "-i", str(audio_path),
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "44100",
            "-movflags", "+faststart",
            str(out_path),
        ]
        subprocess.run(cmd, capture_output=True, timeout=180, check=True)
        log.info(f"Audio added: {out_path}")
        return str(out_path)
    except subprocess.CalledProcessError as e:
        log.error(f"ffmpeg mix failed: {e.stderr.decode()[:200] if e.stderr else e}")
        return None


def ensure_audio(video_path: str, caption: str = "") -> tuple[Optional[str], bool]:
    """
    Check if a video has an audio stream. If not, add one.

    Returns (final_video_path | None, was_fixed):
      - (path, False) when the video already had audio
      - (path, True)  when we successfully muxed in TTS / bgm
      - (None, False) when audio was missing AND we could not add any —
        callers MUST treat this as "do not publish" instead of shipping silent.
    """
    if _has_audio(video_path):
        return video_path, False

    log.warning(f"Silent video detected: {video_path} — adding audio before publish")
    fixed_path = _add_audio_to_video(video_path, caption=caption)
    if fixed_path is None:
        log.error(f"Could not add audio to {video_path} — refusing to publish silently")
        return None, False
    log.info(f"Audio fix applied → {fixed_path}")
    return fixed_path, True


RUNWAY_KEY = os.getenv("RUNWAYML_API_KEY", "")
PIKA_KEY = os.getenv("PIKA_API_KEY", "")
HEYGEN_KEY = os.getenv("HEYGEN_API_KEY", "")

# Pika style presets
PIKA_STYLES = {
    "anime": "anime",
    "cartoon": "cartoon",
    "3d": "3d_animation",
    "cinematic": "cinematic",
    "watercolor": "watercolor",
    "default": "cinematic",
}

# ══════════════════════════════════════════════════════════════════════════════
# RUNWAY ML
# ══════════════════════════════════════════════════════════════════════════════


def runway_generate(prompt: str, duration: int = 5, ratio: str = "1280:768") -> dict:
    """
    Generate a video with Runway Gen-3 Alpha Turbo (text-to-video).
    Returns: {success, video_url, local_path, error}
    """
    if not RUNWAY_KEY:
        return {"success": False, "error": "RUNWAYML_API_KEY not set"}

    headers = {
        "Authorization": f"Bearer {RUNWAY_KEY}",
        "Content-Type": "application/json",
        "X-Runway-Version": "2024-11-06",
    }

    payload = {
        "model": "gen4.5",
        "promptText": prompt[:500],
        "duration": duration,    # 5 or 10 seconds
        "ratio": ratio,       # "1280:720" landscape | "720:1280" portrait (TikTok)
        "watermark": False,
    }

    try:
        r = requests.post(
            "https://api.dev.runwayml.com/v1/text_to_video",
            headers=headers,
            json=payload,
            timeout=30,
        )
        data = r.json()
        task_id = data.get("id")
        if not task_id:
            return {"success": False, "error": f"Runway submit failed ({r.status_code}): {data}"}

        log.info(f"Runway task submitted: {task_id}")

        # Poll for completion (max 5 min)
        for _ in range(60):
            time.sleep(5)
            poll = requests.get(
                f"https://api.dev.runwayml.com/v1/tasks/{task_id}",
                headers=headers,
                timeout=10,
            ).json()
            status = poll.get("status", "")
            if status == "SUCCEEDED":
                video_url = (poll.get("output") or [None])[0]
                local = _download_video(video_url, f"runway_{task_id}.mp4")
                return {"success": True, "video_url": video_url, "local_path": str(local), "source": "runway"}
            elif status in ("FAILED", "CANCELLED"):
                return {"success": False, "error": f"Runway failed: {poll.get('failure', '')}"}

        return {"success": False, "error": "Runway timed out after 5 min"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# PIKA LABS
# ══════════════════════════════════════════════════════════════════════════════

def pika_generate(prompt: str, style: str = "anime", duration: int = 5,
                  aspect_ratio: str = "9:16") -> dict:
    """
    Generate a video with Pika Labs 2.2 API.
    Returns: {success, video_url, local_path, error}
    """
    if not PIKA_KEY:
        return {"success": False, "error": "PIKA_API_KEY not set"}

    pika_style = PIKA_STYLES.get(style.lower(), PIKA_STYLES["default"])

    headers = {
        "Authorization": f"Bearer {PIKA_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "prompt": prompt[:300],
        "options": {
            "aspectRatio": aspect_ratio,   # "9:16" TikTok/Reels | "16:9" YouTube
            "frameRate": 24,
            "duration": duration,
            "motion": 2,                   # 1-4
            "guidanceScale": 12,
        },
    }
    # Add style modifier to prompt
    if style.lower() in ("anime", "cartoon", "3d", "watercolor"):
        payload["prompt"] = f"{style} style: {prompt[:280]}"

    try:
        r = requests.post(
            "https://api.pika.art/v2/videos/create",
            headers=headers,
            json=payload,
            timeout=30,
        )

        if not r.ok:
            # Fallback: try legacy endpoint
            r = requests.post(
                "https://api.pika.art/v1/generate",
                headers=headers,
                json={"promptText": prompt[:300], "style": pika_style,
                      "duration": duration, "aspectRatio": aspect_ratio},
                timeout=30,
            )

        if not r.ok:
            return {"success": False, "error": f"Pika submit failed: {r.status_code} {r.text[:200]}"}

        data = r.json()
        task_id = (data.get("data") or data).get("id") or data.get("taskId") or data.get("job_id")
        if not task_id:
            return {"success": False, "error": f"Pika no task ID: {data}"}

        log.info(f"Pika task submitted: {task_id}")

        # Poll for completion (max 5 min)
        for _ in range(60):
            time.sleep(5)
            poll = requests.get(
                f"https://api.pika.art/v2/videos/{task_id}",
                headers=headers,
                timeout=10,
            ).json()
            status = poll.get("status", "").lower()
            if status in ("completed", "succeeded", "done"):
                inner = poll.get("data") or poll
                video_url = (inner.get("videos") or inner.get("output") or [{}])[0]
                if isinstance(video_url, dict):
                    video_url = video_url.get("url", "")
                local = _download_video(video_url, f"pika_{task_id}.mp4")
                return {"success": True, "video_url": video_url, "local_path": str(local), "source": "pika"}
            elif status in ("failed", "error", "cancelled"):
                return {"success": False, "error": f"Pika failed: {poll.get('error', '')}"}

        return {"success": False, "error": "Pika timed out after 5 min"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# HEYGEN
# ══════════════════════════════════════════════════════════════════════════════

def heygen_generate(script: str, avatar_id: str = "", voice_id: str = "") -> dict:
    """
    Generate a talking-head video with HeyGen.
    Returns: {success, video_url, local_path, error}
    """
    if not HEYGEN_KEY:
        return {"success": False, "error": "HEYGEN_API_KEY not set"}

    # Use defaults from env if not provided
    avatar_id = avatar_id or os.getenv("HEYGEN_AVATAR_ID", "")
    voice_id = voice_id or os.getenv("HEYGEN_VOICE_ID", "")

    headers = {
        "X-Api-Key": HEYGEN_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "video_inputs": [{
            "character": {"type": "avatar", "avatar_id": avatar_id, "avatar_style": "normal"},
            "voice": {"type": "text", "input_text": script[:1500], "voice_id": voice_id,
                      "speed": 1.0},
        }],
        "dimension": {"width": 1080, "height": 1920},  # 9:16 portrait
        "aspect_ratio": "9:16",
    }

    try:
        r = requests.post(
            "https://api.heygen.com/v2/video/generate",
            headers=headers,
            json=payload,
            timeout=30,
        )
        data = r.json()
        video_id = data.get("data", {}).get("video_id")
        if not video_id:
            return {"success": False, "error": f"HeyGen submit failed: {data}"}

        log.info(f"HeyGen video submitted: {video_id}")

        # Poll for completion (max 10 min)
        for _ in range(120):
            time.sleep(5)
            poll = requests.get(
                f"https://api.heygen.com/v1/video_status.get?video_id={video_id}",
                headers=headers,
                timeout=10,
            ).json()
            status = poll.get("data", {}).get("status", "")
            if status == "completed":
                video_url = poll["data"].get("video_url", "")
                local = _download_video(video_url, f"heygen_{video_id}.mp4")
                return {"success": True, "video_url": video_url, "local_path": str(local), "source": "heygen"}
            elif status in ("failed", "error"):
                return {"success": False, "error": f"HeyGen failed: {poll}"}

        return {"success": False, "error": "HeyGen timed out after 10 min"}

    except Exception as e:
        return {"success": False, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SMART DISPATCHER — NarAI calls this
# ══════════════════════════════════════════════════════════════════════════════

def generate_video(prompt: str, style: str = "cinematic", platform: str = "tiktok",
                   script: str = "") -> dict:
    """
    NarAI's main video generation entry point.
    Auto-picks the best tool based on style and available API keys.

    Styles:  anime, cartoon, 3d, cinematic, realistic, talking_head, explainer
    Returns: {success, video_url, local_path, source, error}
    """
    aspect = "9:16" if platform in ("tiktok", "instagram", "reels") else "16:9"

    style_lower = style.lower()

    # Talking head / explainer → HeyGen (uses avatar + voice)
    if style_lower in ("talking_head", "explainer", "avatar") and HEYGEN_KEY:
        return heygen_generate(script or prompt)

    # ALL visual styles → Runway Gen-4.5 (Pika API access blocked on free tier)
    # Runway handles anime/cartoon/3d/cinematic via prompt engineering
    if RUNWAY_KEY:
        styled_prompt = f"{style} style, {prompt}" if style_lower not in ("cinematic", "realistic") else prompt
        return runway_generate(styled_prompt, ratio=_runway_ratio(aspect))

    # Fallback → HeyGen avatar
    if HEYGEN_KEY:
        return heygen_generate(script or prompt)

    return {"success": False, "error": "No video API keys with access. Add Runway credits at runwayml.com"}


def get_available_engines() -> dict:
    """Return which video engines are configured."""
    return {
        "runway": bool(RUNWAY_KEY),
        "pika": bool(PIKA_KEY),
        "heygen": bool(HEYGEN_KEY),
        "any": bool(RUNWAY_KEY or PIKA_KEY or HEYGEN_KEY),
    }


# ══════════════════════════════════════════════════════════════════════════════
# POST VIDEO TO PLATFORMS
# ══════════════════════════════════════════════════════════════════════════════

def post_video_to_tiktok(video_path: str, caption: str) -> dict:
    """Upload video to TikTok via TikTok Content Posting API."""
    try:
        from core.tiktok import TikTokClient
        client = TikTokClient()
        result = client.upload_video(video_path, caption)
        return {"success": True, "platform": "tiktok", "result": result}
    except Exception as e:
        return {"success": False, "platform": "tiktok", "error": str(e)}


def post_video_to_instagram(video_path: str, caption: str) -> dict:
    """Upload video/reel to Instagram via Graph API. Auto-adds audio if video is silent;
    if audio cannot be added, refuses to publish (better than a silent reel)."""
    fixed_path, audio_fixed = ensure_audio(video_path, caption=caption)
    if fixed_path is None:
        log.warning("Skipping IG publish for %s — video has no audio and TTS/bgm unavailable",
                    video_path)
        return {
            "success": False, "platform": "instagram", "audio_fixed": False,
            "error": "video has no audio and TTS/bgm unavailable — skipped to avoid silent post",
        }
    try:
        from core.instagram import InstagramClient
        client = InstagramClient()
        result = client.post(caption, video_path=fixed_path)
        return {
            "success": result.get("status") == "posted",
            "platform": "instagram",
            "result": result,
            "audio_fixed": audio_fixed,
        }
    except Exception as e:
        return {"success": False, "platform": "instagram", "error": str(e)}


def post_video_to_youtube(video_path: str, title: str, description: str,
                          tags: list = None) -> dict:
    """Upload video to YouTube Shorts via YouTube Data API."""
    try:
        from core.youtube import YouTubeClient
        client = YouTubeClient()
        result = client.upload_video(
            video_path, title, description,
            tags=tags or [], category_id="22",
            made_for_kids=False, shorts=True,
        )
        return {"success": True, "platform": "youtube", "result": result}
    except Exception as e:
        return {"success": False, "platform": "youtube", "error": str(e)}


def post_video_to_facebook(video_path: str, title: str, description: str) -> dict:
    """Upload video to Facebook Page via Graph API. Auto-adds audio if video is silent;
    if audio cannot be added, refuses to publish (better than a silent video)."""
    caption = f"{title}\n\n{description}" if title else description
    fixed_path, audio_fixed = ensure_audio(video_path, caption=caption)
    if fixed_path is None:
        log.warning("Skipping FB publish for %s — video has no audio and TTS/bgm unavailable",
                    video_path)
        return {
            "success": False, "platform": "facebook", "audio_fixed": False,
            "error": "video has no audio and TTS/bgm unavailable — skipped to avoid silent post",
        }
    try:
        from core.facebook import FacebookClient
        client = FacebookClient()
        result = client.post(caption, video_path=fixed_path)
        return {
            "success": result.get("status") == "posted",
            "platform": "facebook",
            "result": result,
            "audio_fixed": audio_fixed,
        }
    except Exception as e:
        return {"success": False, "platform": "facebook", "error": str(e)}


def repost_with_audio(video_path: str, caption: str, title: str = "",
                      platforms: list = None) -> dict:
    """
    Detect a silent video, fix it, and repost to the specified platforms.
    Use this when a previously published video had no sound.

    Returns a report of what was fixed and what was reposted.
    """
    if not platforms:
        platforms = ["instagram", "facebook"]

    had_audio = _has_audio(video_path)
    fixed_path, was_fixed = ensure_audio(video_path, caption=caption)

    results = {
        "original_path": video_path,
        "fixed_path": fixed_path,
        "had_audio": had_audio,
        "audio_added": was_fixed,
        "platforms": {},
    }

    if fixed_path is None:
        # ensure_audio refused — no point continuing per platform; the
        # individual post_video_to_* helpers would each refuse anyway.
        results["success"] = False
        results["summary"] = (
            "Repost aborted — video has no audio and TTS/bgm unavailable. "
            "Set ELEVENLABS_API_KEY or drop a track at data/background_music.mp3."
        )
        return results

    for platform in platforms:
        if platform == "instagram":
            results["platforms"]["instagram"] = post_video_to_instagram(fixed_path, caption)
        elif platform == "facebook":
            results["platforms"]["facebook"] = post_video_to_facebook(fixed_path, title, caption)
        elif platform == "tiktok":
            results["platforms"]["tiktok"] = post_video_to_tiktok(fixed_path, caption)
        elif platform == "youtube":
            results["platforms"]["youtube"] = post_video_to_youtube(fixed_path, title, caption)

    all_ok = all(v.get("success") for v in results["platforms"].values())
    results["success"] = all_ok
    results["summary"] = (
        f"Audio {'added and ' if was_fixed else ''}reposted to "
        f"{', '.join(p for p, r in results['platforms'].items() if r.get('success'))}."
        if all_ok else
        "Partial repost. Check platform errors."
    )
    return results


def publish_video_everywhere(video_path: str, title: str, caption: str,
                             platforms: list = None) -> dict:
    """Post a video to all configured platforms."""
    if not platforms:
        platforms = ["tiktok", "instagram", "youtube", "facebook"]

    results = {}
    for p in platforms:
        if p == "tiktok":
            results[p] = post_video_to_tiktok(video_path, caption)
        elif p == "instagram":
            results[p] = post_video_to_instagram(video_path, caption)
        elif p == "youtube":
            results[p] = post_video_to_youtube(video_path, title, caption)
        elif p == "facebook":
            results[p] = post_video_to_facebook(video_path, title, caption)

    published = [p for p, r in results.items() if r.get("success")]
    failed = [p for p, r in results.items() if not r.get("success")]
    return {"published": published, "failed": failed, "details": results}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _download_video(url: str, filename: str) -> Path:
    """Download a video URL to the outputs/videos directory."""
    dest = VIDEO_DIR / filename
    try:
        r = requests.get(url, timeout=120, stream=True)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        log.info(f"Video saved: {dest}")
    except Exception as e:
        log.warning(f"Download failed: {e}")
    return dest


def _runway_ratio(aspect: str) -> str:
    """Convert aspect ratio string to Runway ratio format (only 2 valid values)."""
    if aspect == "9:16":
        return "720:1280"   # portrait — TikTok, Reels, Shorts
    return "1280:720"       # landscape — YouTube, Facebook
