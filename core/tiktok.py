#!/usr/bin/env python3
"""
core/tiktok.py
─────────────────────────────────────────────────────────────────────────────
TikTok API integration — OAuth 2.0 + Content Posting API v2

Flow:
  1. User visits /api/tiktok/auth  →  redirected to TikTok login
  2. TikTok redirects to /api/tiktok/callback with ?code=...
  3. We exchange the code for access_token + refresh_token (stored in .env)
  4. Bots call post_video() / post_photo() to publish content

Scopes used:
  user.info.basic       — display name / avatar
  video.upload          — upload videos (Direct Post)
  video.publish         — publish uploaded videos
─────────────────────────────────────────────────────────────────────────────
"""

import base64
import hashlib
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv, set_key

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("tiktok")

# ── Constants ──────────────────────────────────────────────────────────────────

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
USER_URL = "https://open.tiktokapis.com/v2/user/info/"
POST_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/video/init/"
POST_STAT_URL = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
PHOTO_INIT_URL = "https://open.tiktokapis.com/v2/post/publish/content/init/"
REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"

# Full scopes for production (restore when app review is approved)
# SCOPES = ["user.info.basic", "video.upload", "video.publish"]
# Sandbox: only user.info.basic is approved
SCOPES = os.getenv("TIKTOK_SCOPES", "user.info.basic").split(",")

REDIRECT_URI = os.getenv("TIKTOK_REDIRECT_URI", "http://localhost:5050/api/tiktok/callback")


_CACHED_AUTH_URL: str = ""

# ── Client ─────────────────────────────────────────────────────────────────────


class TikTokClient:
    """
    Full TikTok API client.
    Credentials are read from / written back to the .env file.
    """

    def __init__(self):
        self.client_key = os.getenv("TIKTOK_CLIENT_KEY", "")
        self.client_secret = os.getenv("TIKTOK_CLIENT_SECRET", "")
        self.access_token = os.getenv("TIKTOK_ACCESS_TOKEN", "")
        self.refresh_token = os.getenv("TIKTOK_REFRESH_TOKEN", "")
        self.open_id = os.getenv("TIKTOK_OPEN_ID", "")
        self._token_exp = int(os.getenv("TIKTOK_TOKEN_EXP", "0"))

    # ── OAuth helpers ──────────────────────────────────────────────────────────

    def _generate_pkce(self):
        """Generate PKCE code_verifier and code_challenge (S256).
        Verifier uses only A-Za-z0-9 (RFC 7636 unreserved chars, no padding issues).
        """
        import string
        alphabet = string.ascii_letters + string.digits
        verifier = "".join(secrets.choice(alphabet) for _ in range(64))
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
        return verifier, challenge

    def get_auth_url(self, fresh: bool = False) -> str:
        """Return the TikTok OAuth URL (confidential client — no PKCE)."""
        global _CACHED_AUTH_URL
        if _CACHED_AUTH_URL and not fresh:
            return _CACHED_AUTH_URL

        state = f"wv_{int(time.time())}"
        params = {
            "client_key": self.client_key,
            "response_type": "code",
            "scope": ",".join(SCOPES),
            "redirect_uri": REDIRECT_URI,
            "state": state,
        }
        _CACHED_AUTH_URL = AUTH_URL + "?" + urlencode(params)
        logger.info(f"TikTok auth URL generated — state={state}")
        return _CACHED_AUTH_URL

    def exchange_code(self, code: str, state: str = "") -> Dict:
        """Exchange an authorization code for access + refresh tokens."""
        payload = {
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        }
        logger.info(f"TikTok token POST | code[:8]={code[:8]}")
        resp = requests.post(TOKEN_URL, data=payload, timeout=15)
        data = resp.json()
        logger.info(f"TikTok token response [{resp.status_code}]: {data}")

        # Check for API-level error
        error_info = data.get("error", {})
        if isinstance(error_info, dict):
            err_code = error_info.get("code", "ok")
            if err_code not in ("ok", ""):
                raise RuntimeError(
                    f"Token exchange failed [{err_code}]: {error_info.get('message', data)}"
                )
        elif resp.status_code != 200:
            raise RuntimeError(f"Token exchange failed ({resp.status_code}): {data}")

        if "data" not in data:
            raise RuntimeError(f"No 'data' in TikTok response: {data}")

        token_data = data["data"]

        # Sandbox sometimes returns data as a JSON string — parse it
        if isinstance(token_data, str):
            import json as _json
            try:
                token_data = _json.loads(token_data)
            except Exception:
                raise RuntimeError(f"Unexpected token_data format: {token_data!r}")

        if not isinstance(token_data, dict):
            raise RuntimeError(f"Expected dict for token_data, got {type(token_data)}: {token_data!r}")

        self._store_tokens(token_data)
        return token_data

    def refresh_access_token(self) -> Dict:
        """Use the stored refresh token to get a new access token."""
        if not self.refresh_token:
            raise RuntimeError("No refresh token stored — complete OAuth first.")

        resp = requests.post(TOKEN_URL, data={
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }, timeout=15)
        data = resp.json()

        if resp.status_code != 200 or "data" not in data:
            raise RuntimeError(f"Token refresh failed: {data}")

        self._store_tokens(data["data"])
        return data["data"]

    def _store_tokens(self, token_data: Dict):
        """Persist tokens to .env so they survive restarts."""
        self.access_token = token_data.get("access_token", self.access_token)
        self.refresh_token = token_data.get("refresh_token", self.refresh_token)
        self.open_id = token_data.get("open_id", self.open_id)
        self._token_exp = int(time.time()) + int(token_data.get("expires_in", 86400))

        env_path = str(ROOT / ".env")
        for key, val in [
            ("TIKTOK_ACCESS_TOKEN", self.access_token),
            ("TIKTOK_REFRESH_TOKEN", self.refresh_token),
            ("TIKTOK_OPEN_ID", self.open_id),
            ("TIKTOK_TOKEN_EXP", str(self._token_exp)),
        ]:
            set_key(env_path, key, val)

        logger.info(f"TikTok tokens stored — open_id: {self.open_id}")

    def _ensure_valid_token(self):
        """Auto-refresh if the token is expiring within 5 minutes."""
        if not self.access_token:
            raise RuntimeError("Not authenticated — complete OAuth first.")
        if self._token_exp and time.time() > (self._token_exp - 300):
            logger.info("TikTok token expiring — refreshing...")
            self.refresh_access_token()

    # ── User info ──────────────────────────────────────────────────────────────

    def get_user_info(self) -> Dict:
        """Return the authenticated user's basic profile."""
        self._ensure_valid_token()
        resp = requests.get(
            USER_URL,
            params={"fields": "open_id,union_id,avatar_url,display_name,profile_deep_link"},
            headers={"Authorization": f"Bearer {self.access_token}"},
            timeout=10,
        )
        data = resp.json()
        if resp.status_code != 200:
            raise RuntimeError(f"User info failed: {data}")
        return data.get("data", {}).get("user", {})

    # ── Video posting ──────────────────────────────────────────────────────────

    def post_video_from_url(
        self,
        video_url: str,
        caption: str,
        privacy: str = "SELF_ONLY",
        disable_comment: bool = False,
        disable_duet: bool = False,
        disable_stitch: bool = False,
    ) -> Dict:
        """
        Publish a video to TikTok using a publicly accessible URL.

        privacy options:
          PUBLIC_TO_EVERYONE  — visible to all
          MUTUAL_FOLLOW_FRIENDS — friends only
          FOLLOWER_OF_CREATOR  — followers only
          SELF_ONLY            — draft/private (safe default for testing)
        """
        self._ensure_valid_token()

        # TikTok caption limit: 2200 chars
        caption = caption[:2200]

        payload = {
            "post_info": {
                "title": caption,
                "privacy_level": privacy,
                "disable_comment": disable_comment,
                "disable_duet": disable_duet,
                "disable_stitch": disable_stitch,
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "video_url": video_url,
            },
        }

        resp = requests.post(
            POST_INIT_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            timeout=30,
        )
        data = resp.json()

        if resp.status_code != 200:
            raise RuntimeError(f"Post video failed ({resp.status_code}): {data}")

        publish_id = data.get("data", {}).get("publish_id", "")
        logger.info(f"TikTok video queued — publish_id: {publish_id}")
        return {"publish_id": publish_id, "status": "queued", "raw": data}

    def get_post_status(self, publish_id: str) -> Dict:
        """Poll the status of a video post."""
        self._ensure_valid_token()
        resp = requests.post(
            POST_STAT_URL,
            json={"publish_id": publish_id},
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            timeout=10,
        )
        data = resp.json()
        return data.get("data", {})

    def post_photo_carousel(
        self,
        photo_urls: List[str],
        caption: str,
        privacy: str = "SELF_ONLY",
    ) -> Dict:
        """Post a photo carousel (slideshow) to TikTok."""
        self._ensure_valid_token()
        caption = caption[:2200]

        payload = {
            "post_info": {
                "title": caption,
                "privacy_level": privacy,
                "media_type": "PHOTO",
            },
            "source_info": {
                "source": "PULL_FROM_URL",
                "photo_images": photo_urls[:35],  # TikTok max 35 photos
                "photo_cover_index": 0,
            },
        }

        resp = requests.post(
            PHOTO_INIT_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json; charset=UTF-8",
            },
            timeout=30,
        )
        data = resp.json()
        if resp.status_code != 200:
            raise RuntimeError(f"Post photo failed ({resp.status_code}): {data}")

        publish_id = data.get("data", {}).get("publish_id", "")
        logger.info(f"TikTok photo carousel queued — publish_id: {publish_id}")
        return {"publish_id": publish_id, "status": "queued", "raw": data}

    # ── Connection status ──────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        return bool(self.access_token and self.open_id)

    def get_status(self) -> Dict:
        connected = self.is_connected()
        exp_ts = self._token_exp
        exp_str = ""
        if exp_ts:
            remaining = exp_ts - int(time.time())
            if remaining > 0:
                h = remaining // 3600
                exp_str = f"expires in {h}h"
            else:
                exp_str = "expired"

        return {
            "connected": connected,
            "client_key": self.client_key[:8] + "..." if self.client_key else "",
            "open_id": self.open_id[:12] + "..." if self.open_id else "",
            "token_status": exp_str if connected else "not authenticated",
            "auth_url": self.get_auth_url() if not connected else None,
            "redirect_uri": REDIRECT_URI,
            "scopes": SCOPES,
        }

    def revoke(self):
        """Revoke the current access token."""
        if not self.access_token:
            return
        requests.post(REVOKE_URL, data={
            "client_key": self.client_key,
            "client_secret": self.client_secret,
            "token": self.access_token,
        }, timeout=10)
        env_path = str(ROOT / ".env")
        for key in ("TIKTOK_ACCESS_TOKEN", "TIKTOK_REFRESH_TOKEN",
                    "TIKTOK_OPEN_ID", "TIKTOK_TOKEN_EXP"):
            set_key(env_path, key, "")
        self.access_token = self.refresh_token = self.open_id = ""
        logger.info("TikTok tokens revoked")


# ── Singleton ──────────────────────────────────────────────────────────────────

_client: Optional[TikTokClient] = None


def get_tiktok() -> TikTokClient:
    global _client
    if _client is None:
        _client = TikTokClient()
    return _client
