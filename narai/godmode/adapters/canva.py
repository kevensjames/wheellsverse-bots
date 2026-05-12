"""
Canva adapter — design management, asset uploads, auto-refresh tokens.

Credentials:
  CANVA_CLIENT_ID, CANVA_CLIENT_SECRET      — from .env (OAuth2 client)
  data/canva_token.json                     — existing user token (auto-refreshed)

Canva Connect API docs: https://www.canva.dev/docs/connect/
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import requests


API_BASE = "https://api.canva.com/rest/v1"
TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"
REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_FILE = REPO_ROOT / "data" / "canva_token.json"


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(REPO_ROOT / ".env")
    except ImportError:
        pass


def _read_token() -> dict:
    if not TOKEN_FILE.exists():
        raise RuntimeError(
            f"Canva token file not found at {TOKEN_FILE}.\n"
            "Run the OAuth authorize flow for Canva first."
        )
    return json.loads(TOKEN_FILE.read_text())


def _write_token(token: dict) -> None:
    TOKEN_FILE.write_text(json.dumps(token, indent=2))


def _refresh_if_expired(token: dict) -> dict:
    """Refresh the access_token if it's expired (or within 60s of expiring)."""
    expires_at = token.get("expires_at", 0)
    # Canva stores expires_at as seconds since epoch in our JSON format
    if isinstance(expires_at, str):
        # Occasionally stored ISO — try to parse
        from datetime import datetime
        try:
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00")).timestamp()
        except Exception:
            expires_at = 0

    if time.time() < float(expires_at) - 60:
        return token  # still valid

    # Refresh
    _load_env()
    client_id = os.environ["CANVA_CLIENT_ID"]
    client_secret = os.environ["CANVA_CLIENT_SECRET"]
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    r = requests.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": token["refresh_token"]},
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"Canva token refresh failed {r.status_code}: {r.text[:500]}")
    new_tok = r.json()
    # Canva returns expires_in (seconds) — convert to absolute timestamp
    new_tok["expires_at"] = int(time.time()) + int(new_tok.get("expires_in", 3600))
    # Refresh endpoint sometimes omits refresh_token on reuse — keep old one
    new_tok.setdefault("refresh_token", token["refresh_token"])
    _write_token(new_tok)
    return new_tok


def _headers() -> dict:
    tok = _refresh_if_expired(_read_token())
    return {"Authorization": f"Bearer {tok['access_token']}"}


def _req(method: str, path: str, **kwargs) -> dict:
    url = f"{API_BASE}/{path.lstrip('/')}"
    headers = kwargs.pop("headers", {})
    headers.update(_headers())
    r = requests.request(method, url, headers=headers, timeout=60, **kwargs)
    if not r.ok:
        raise RuntimeError(f"Canva {method} {path} → {r.status_code}: {r.text[:500]}")
    return r.json()


# ── Public API ───────────────────────────────────────────────────────────────

def whoami() -> dict:
    """Return info about the authenticated Canva user."""
    return _req("GET", "users/me").get("team_user", {})


def list_designs(limit: int = 20) -> list[dict]:
    """List the authenticated user's recent Canva designs."""
    resp = _req("GET", "designs", params={"limit": limit})
    return resp.get("items", [])


def get_design(design_id: str) -> dict:
    return _req("GET", f"designs/{design_id}").get("design", {})


# Canva Connect API only accepts these preset names for design_type.type=preset
# Full list: https://www.canva.dev/docs/connect/api-reference/designs/create-design/
_CANVA_PRESETS = {"doc", "presentation", "whiteboard", "video"}

# Well-known Canva dimensions for non-preset sizes (pixels at standard DPI)
_CANVA_CUSTOM_SIZES = {
    # (short_key,  (width_px, height_px))
    "instagram_post":         (1080, 1080),
    "instagram_portrait":     (1080, 1350),
    "instagram_story":        (1080, 1920),
    "facebook_post":          (1200, 630),
    "twitter_post":           (1600, 900),
    "x_post":                 (1600, 900),
    "book_cover":             (1800, 2700),   # 6x9 @ 300dpi
    "book_cover_paperback":   (1800, 2700),
    "poster":                 (1080, 1920),
    "flyer":                  (2100, 2700),
    "youtube_thumbnail":      (1280, 720),
    "linkedin_post":          (1200, 627),
    "tiktok_video":           (1080, 1920),
    "pinterest":              (1000, 1500),
}


def create_design(design_type: str = "presentation",
                  title: str | None = None) -> dict:
    """
    Create a blank design.

    design_type accepts either:
      • A Canva preset name: "doc", "presentation", "whiteboard", "video"
      • A custom size key from _CANVA_CUSTOM_SIZES above
        (e.g., "instagram_post", "book_cover", "facebook_post", "tiktok_video")
      • A string like "1080x1080" — interpreted as explicit width×height pixels

    Returns the created design object (with id + edit/view URLs).
    """
    key = (design_type or "").lower().replace(" ", "_").replace("-", "_")
    body: dict = {}

    if key in _CANVA_PRESETS:
        body["design_type"] = {"type": "preset", "name": key}
    elif key in _CANVA_CUSTOM_SIZES:
        w, h = _CANVA_CUSTOM_SIZES[key]
        body["design_type"] = {"type": "custom", "width": w, "height": h}
    elif "x" in key and all(p.isdigit() for p in key.split("x", 1)):
        w, h = map(int, key.split("x", 1))
        body["design_type"] = {"type": "custom", "width": w, "height": h}
    else:
        # Unknown — default to a square (safe for most social content)
        body["design_type"] = {"type": "custom", "width": 1080, "height": 1080}

    if title:
        body["title"] = title
    return _req("POST", "designs", json=body).get("design", {})


def upload_asset(file_path: str, name: str | None = None) -> dict:
    """Upload a local file as a Canva asset (image, video, audio)."""
    with open(file_path, "rb") as f:
        data = f.read()

    # Canva's asset upload is async: start job → poll status
    asset_name = name or Path(file_path).name
    metadata = {"name_base64": base64.b64encode(asset_name.encode()).decode()}

    start = _req("POST", "asset-uploads",
                 headers={"Asset-Upload-Metadata": json.dumps(metadata),
                          "Content-Type": "application/octet-stream"},
                 data=data)
    job_id = start["job"]["id"]

    # Poll for completion (up to 60s)
    for _ in range(30):
        job = _req("GET", f"asset-uploads/{job_id}")["job"]
        if job["status"] == "success":
            return job.get("asset", {"id": job_id})
        if job["status"] == "failed":
            raise RuntimeError(f"Canva asset upload failed: {job}")
        time.sleep(2)
    raise RuntimeError("Canva asset upload timed out after 60s")


def export_design(design_id: str, file_format: str = "pdf") -> str:
    """
    Export a design to PDF / PNG / JPG / PPTX. Returns a download URL.
    file_format: 'pdf', 'png', 'jpg', 'pptx', 'mp4' (for videos)
    """
    # Start export job
    job = _req("POST", "exports",
               json={"design_id": design_id,
                     "format": {"type": file_format.lower()}})["job"]
    job_id = job["id"]

    # Poll until ready
    for _ in range(30):
        job = _req("GET", f"exports/{job_id}")["job"]
        if job["status"] == "success":
            urls = job.get("urls", [])
            return urls[0] if urls else ""
        if job["status"] == "failed":
            raise RuntimeError(f"Canva export failed: {job}")
        time.sleep(2)
    raise RuntimeError("Canva export timed out after 60s")
