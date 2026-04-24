"""
TikTok adapter — delegates to the production `core/tiktok.py` client.

The WheellsVerse project already has a full TikTok OAuth + posting integration
at `core/tiktok.py`, backed by FastAPI endpoints in `core/api.py`:

    GET  /api/tiktok/status   — connection state + auth URL
    GET  /api/tiktok/auth     — redirect to TikTok consent screen
    GET  /api/tiktok/callback — handle OAuth code exchange
    GET  /api/tiktok/me       — whoami
    POST /api/tiktok/post/video — post from public URL
    POST /api/tiktok/post/photo — post photo carousel

To connect a fresh account: with the dashboard running on :5050, open
    http://localhost:5050/api/tiktok/auth
in a browser. Click Allow on TikTok — the running server handles the callback
and writes TIKTOK_ACCESS_TOKEN / TIKTOK_REFRESH_TOKEN / TIKTOK_OPEN_ID to .env.

This godmode wrapper exposes the same methods with a stable interface so
downstream NarAI code doesn't care whether it's using the production client
directly or through this adapter.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Production client lives at repo_root/core/tiktok.py
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _client():
    """Lazy import — avoids import-time failures if core/tiktok.py isn't present."""
    try:
        from core.tiktok import get_tiktok  # type: ignore
        return get_tiktok()
    except ImportError as e:
        raise RuntimeError(
            f"TikTok core module not importable: {e}\n"
            "Expected at core/tiktok.py with get_tiktok() factory."
        )


# ── Public API ───────────────────────────────────────────────────────────────

def whoami() -> dict:
    """Return authenticated TikTok user info. Raises if not connected."""
    c = _client()
    if not c.is_authenticated():
        raise RuntimeError(
            "TikTok not connected. Start the dashboard (port 5050) and visit\n"
            "  http://localhost:5050/api/tiktok/auth\n"
            "to run the OAuth consent flow."
        )
    return c.get_user_info()


def is_connected() -> bool:
    """Cheap check without raising — useful for conditional UI."""
    try:
        return _client().is_authenticated()
    except Exception:
        return False


def auth_url() -> str:
    """Return the TikTok OAuth consent URL (so NarAI can tell the user where to click)."""
    return _client().get_auth_url(fresh=True)


def post_video_from_url(video_url: str, caption: str = "",
                        privacy: str = "SELF_ONLY",
                        disable_comment: bool = False,
                        disable_duet: bool = False,
                        disable_stitch: bool = False) -> dict:
    """Publish a video via PULL_FROM_URL. video_url must be publicly reachable HTTPS."""
    return _client().post_video_from_url(
        video_url=video_url, caption=caption, privacy=privacy,
        disable_comment=disable_comment, disable_duet=disable_duet,
        disable_stitch=disable_stitch,
    )


def post_photo_carousel(photo_urls: list[str], caption: str = "",
                        privacy: str = "SELF_ONLY") -> dict:
    """Publish a photo carousel. photo_urls must be publicly reachable HTTPS."""
    return _client().post_photo_carousel(
        photo_urls=photo_urls, caption=caption, privacy=privacy,
    )


def refresh() -> dict:
    """Force a token refresh using the stored refresh_token."""
    return _client().refresh_access_token()


def status() -> dict:
    """Full connection status — token expiry, open_id, whether refresh is needed."""
    return _client().get_status()
