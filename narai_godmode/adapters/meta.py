"""
Meta Graph API adapter — Facebook Page + Instagram Business posting.

Credentials loaded from .env:
  FACEBOOK_PAGE_TOKEN, FACEBOOK_PAGE_ID          — FB Page (long-lived page token)
  INSTAGRAM_PAGE_TOKEN, INSTAGRAM_ACCOUNT_ID     — IG Business account
  META_APP_ID, META_APP_SECRET                   — For token debugging/refresh

IG posting on Graph API requires a **publicly reachable** image URL — Meta fetches
the image itself, they don't accept file uploads for feed posts. Use Drive
(via the google adapter) to host the image and share a public link.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import requests


GRAPH_BASE = "https://graph.facebook.com/v21.0"


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    except ImportError:
        pass


def _check(key: str) -> str:
    val = os.environ.get(key, "")
    if not val:
        raise RuntimeError(f"Meta adapter needs {key} in .env")
    return val


def _req(method: str, path: str, **kwargs) -> dict:
    """Wrapped HTTPS call with consistent error surfacing."""
    url = f"{GRAPH_BASE}/{path.lstrip('/')}"
    r = requests.request(method, url, timeout=30, **kwargs)
    if not r.ok:
        raise RuntimeError(f"Graph API {method} {path} → {r.status_code}: {r.text[:500]}")
    return r.json()


# ── Identity / debug ─────────────────────────────────────────────────────────

def whoami() -> dict:
    """Return Page and IG account identity; validates all tokens are live."""
    _load_env()
    out: dict[str, Any] = {}

    # FB Page
    page = _req("GET", _check("FACEBOOK_PAGE_ID"),
                params={"fields": "id,name,category,followers_count",
                        "access_token": _check("FACEBOOK_PAGE_TOKEN")})
    out["facebook"] = {
        "id":        page.get("id"),
        "name":      page.get("name"),
        "category":  page.get("category"),
        "followers": page.get("followers_count"),
    }

    # IG Business account (reached through the Page token)
    ig_id = _check("INSTAGRAM_ACCOUNT_ID")
    ig = _req("GET", ig_id,
              params={"fields": "id,username,followers_count,media_count,name",
                      "access_token": _check("INSTAGRAM_PAGE_TOKEN")})
    out["instagram"] = {
        "id":        ig.get("id"),
        "username":  ig.get("username"),
        "name":      ig.get("name"),
        "followers": ig.get("followers_count"),
        "media":     ig.get("media_count"),
    }
    return out


# ── Facebook Page posting ───────────────────────────────────────────────────

def fb_post_text(message: str, link: str | None = None) -> dict:
    """Publish a text post (optionally with a link card) to the Facebook Page."""
    _load_env()
    data = {"message": message, "access_token": _check("FACEBOOK_PAGE_TOKEN")}
    if link:
        data["link"] = link
    resp = _req("POST", f"{_check('FACEBOOK_PAGE_ID')}/feed", data=data)
    post_id = resp.get("id", "")
    page_id = _check("FACEBOOK_PAGE_ID")
    return {
        "id":  post_id,
        "url": f"https://facebook.com/{post_id}" if post_id else "",
    }


def fb_post_photo(image_path: str, caption: str = "") -> dict:
    """Upload a photo (local file) to the Facebook Page."""
    _load_env()
    with open(image_path, "rb") as f:
        files = {"source": f}
        data = {"caption": caption, "access_token": _check("FACEBOOK_PAGE_TOKEN")}
        resp = _req("POST", f"{_check('FACEBOOK_PAGE_ID')}/photos",
                    data=data, files=files)
    return {"id": resp.get("post_id") or resp.get("id")}


# ── Instagram posting ───────────────────────────────────────────────────────

def ig_post_photo(image_url: str, caption: str = "") -> dict:
    """
    Publish a single photo to Instagram Business.
    image_url MUST be a publicly-reachable HTTPS URL (Meta fetches it).
    Local paths won't work — upload to Drive or S3 first and share the link.
    """
    _load_env()
    ig_id = _check("INSTAGRAM_ACCOUNT_ID")
    tok = _check("INSTAGRAM_PAGE_TOKEN")

    # Step 1: create container
    container = _req("POST", f"{ig_id}/media",
                     data={"image_url": image_url, "caption": caption,
                           "access_token": tok})
    creation_id = container["id"]

    # Step 2: wait briefly for media to be fetched+processed
    for _ in range(10):
        status = _req("GET", creation_id,
                      params={"fields": "status_code", "access_token": tok})
        if status.get("status_code") == "FINISHED":
            break
        time.sleep(2)

    # Step 3: publish
    publish = _req("POST", f"{ig_id}/media_publish",
                   data={"creation_id": creation_id, "access_token": tok})
    media_id = publish.get("id")
    return {"id": media_id, "creation_id": creation_id}


def ig_post_video(video_url: str, caption: str = "", is_reel: bool = True) -> dict:
    """Publish a video or Reel. video_url must be publicly reachable."""
    _load_env()
    ig_id = _check("INSTAGRAM_ACCOUNT_ID")
    tok = _check("INSTAGRAM_PAGE_TOKEN")

    data = {"video_url": video_url, "caption": caption, "access_token": tok}
    if is_reel:
        data["media_type"] = "REELS"

    container = _req("POST", f"{ig_id}/media", data=data)
    creation_id = container["id"]

    # Videos need longer to process
    for _ in range(30):
        status = _req("GET", creation_id,
                      params={"fields": "status_code", "access_token": tok})
        if status.get("status_code") == "FINISHED":
            break
        time.sleep(3)

    publish = _req("POST", f"{ig_id}/media_publish",
                   data={"creation_id": creation_id, "access_token": tok})
    return {"id": publish.get("id"), "creation_id": creation_id}


def ig_recent_media(limit: int = 10) -> list[dict]:
    """Return the most recent IG posts — caption, like/comment counts, URL."""
    _load_env()
    ig_id = _check("INSTAGRAM_ACCOUNT_ID")
    resp = _req("GET", f"{ig_id}/media",
                params={"fields": "id,caption,media_type,permalink,like_count,comments_count,timestamp",
                        "limit": limit,
                        "access_token": _check("INSTAGRAM_PAGE_TOKEN")})
    return resp.get("data", [])


def fb_recent_posts(limit: int = 10) -> list[dict]:
    """Return the most recent Facebook Page posts."""
    _load_env()
    resp = _req("GET", f"{_check('FACEBOOK_PAGE_ID')}/posts",
                params={"fields": "id,message,created_time,permalink_url",
                        "limit": limit,
                        "access_token": _check("FACEBOOK_PAGE_TOKEN")})
    return resp.get("data", [])
