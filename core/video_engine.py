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

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

import httpx
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR   = ROOT / "data"
VIDEO_DIR  = ROOT / "outputs" / "videos"
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

log = logging.getLogger("video_engine")

RUNWAY_KEY  = os.getenv("RUNWAYML_API_KEY", "")
PIKA_KEY    = os.getenv("PIKA_API_KEY", "")
HEYGEN_KEY  = os.getenv("HEYGEN_API_KEY", "")

# Pika style presets
PIKA_STYLES = {
    "anime":      "anime",
    "cartoon":    "cartoon",
    "3d":         "3d_animation",
    "cinematic":  "cinematic",
    "watercolor": "watercolor",
    "default":    "cinematic",
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
        "model":       "gen4.5",
        "promptText":  prompt[:500],
        "duration":    duration,    # 5 or 10 seconds
        "ratio":       ratio,       # "1280:720" landscape | "720:1280" portrait (TikTok)
        "watermark":   False,
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
    voice_id  = voice_id  or os.getenv("HEYGEN_VOICE_ID", "")

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
        "runway":  bool(RUNWAY_KEY),
        "pika":    bool(PIKA_KEY),
        "heygen":  bool(HEYGEN_KEY),
        "any":     bool(RUNWAY_KEY or PIKA_KEY or HEYGEN_KEY),
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
    """Upload video/reel to Instagram via Graph API."""
    try:
        from core.instagram import InstagramClient
        client = InstagramClient()
        result = client.post_reel(video_path, caption)
        return {"success": True, "platform": "instagram", "result": result}
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
    """Upload video to Facebook Page via Graph API."""
    try:
        from core.facebook import FacebookClient
        client = FacebookClient()
        result = client.post_video(video_path, title, description)
        return {"success": True, "platform": "facebook", "result": result}
    except Exception as e:
        return {"success": False, "platform": "facebook", "error": str(e)}


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
    failed    = [p for p, r in results.items() if not r.get("success")]
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
