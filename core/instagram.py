#!/usr/bin/env python3
"""
core/instagram.py
─────────────────────────────────────────────────────────────────────────────
Instagram integration — Graph API first, Playwright browser fallback.

Multi-account: every class accepts `account` (default "main"). Env vars use
an account-derived prefix so a single .env can hold many IG identities:

    account="main"  → INSTAGRAM_PAGE_TOKEN, INSTAGRAM_ACCOUNT_ID, …  (no prefix)
    account="shop"  → SHOP_INSTAGRAM_PAGE_TOKEN, SHOP_INSTAGRAM_ACCOUNT_ID, …

Credentials (at least one method must be set per account):

  Method A — Graph API (recommended for Reels + scheduled):
    {PREFIX}INSTAGRAM_PAGE_TOKEN   — Facebook Page Access Token (linked IG account)
    {PREFIX}INSTAGRAM_ACCOUNT_ID   — Instagram Business Account ID
    OPENAI_API_KEY                 — for auto-generating DALL-E images when needed

  Method B — Browser automation (text + image posts via login):
    {PREFIX}INSTAGRAM_USERNAME     — Instagram username (without @)
    {PREFIX}INSTAGRAM_PASSWORD     — Instagram account password
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import time
import tempfile
from pathlib import Path
from typing import Dict, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("instagram")


def _env_prefix(account: str) -> str:
    """Empty for "main" (backward compat), "<ACCOUNT>_" otherwise."""
    return "" if account == "main" else f"{account.upper()}_"


def _session_file(account: str) -> Path:
    """Per-account browser session file so login states don't collide."""
    suffix = "" if account == "main" else f"_{account}"
    return ROOT / "data" / f"instagram_session{suffix}.json"


# ── Graph API poster ──────────────────────────────────────────────────────────

class InstagramGraphPoster:
    """Post to Instagram via Graph API (requires Business account linked to FB Page)."""

    def __init__(self, account: str = "main"):
        self.account = account
        prefix = _env_prefix(account)
        self.token = (
            os.getenv(f"{prefix}INSTAGRAM_PAGE_TOKEN", "")
            or os.getenv(f"{prefix}FACEBOOK_PAGE_TOKEN", "")
        )
        self.account_id = os.getenv(f"{prefix}INSTAGRAM_ACCOUNT_ID", "")
        self.openai_key = os.getenv("OPENAI_API_KEY", "")

    def is_configured(self) -> bool:
        return bool(self.token and self.account_id)

    def _generate_image(self, caption: str) -> Optional[str]:
        """Compose a sharp social image (HD background + Pillow text) and expose it
        via the FastAPI /social-media static mount so Meta can fetch it."""
        try:
            from core.social_image import generate_social_image, upload_to_public_url
        except Exception as e:
            logger.warning("social_image module unavailable: %s", e)
            return None
        # First sentence (or first 90 chars) makes a tighter, more readable headline
        # than the whole caption, which usually contains hashtags + CTAs.
        headline = caption.split("\n", 1)[0].split(". ", 1)[0][:90].strip() or "WheellsVerse"
        subtext = ""
        rest = caption[len(headline):].strip(" .\n")
        if rest:
            subtext = rest.split("\n", 1)[0][:120]
        local = generate_social_image(headline=headline, subtext=subtext,
                                      platform="instagram_feed")
        if not local:
            return None
        return upload_to_public_url(local)

    def post_photo(self, caption: str, image_url: Optional[str] = None) -> dict:
        """Post a photo to Instagram. Auto-generates DALL-E image if none provided."""
        import requests as _req
        if not image_url:
            image_url = self._generate_image(caption)
        if not image_url:
            return {"status": "error", "error": "No image_url and OPENAI_API_KEY not set"}

        # Step 1: Create media container
        container = _req.post(
            f"https://graph.facebook.com/v19.0/{self.account_id}/media",
            data={"image_url": image_url, "caption": caption,
                  "access_token": self.token},
            timeout=30,
        ).json()
        if "id" not in container:
            return {"status": "error",
                    "error": container.get("error", {}).get("message", str(container))}

        # Step 2: Publish
        time.sleep(2)
        publish = _req.post(
            f"https://graph.facebook.com/v19.0/{self.account_id}/media_publish",
            data={"creation_id": container["id"], "access_token": self.token},
            timeout=30,
        ).json()
        if "id" in publish:
            return {"status": "posted", "post_id": publish["id"], "method": "graph_api"}
        return {"status": "error",
                "error": publish.get("error", {}).get("message", str(publish))}

    def post_reel(self, caption: str, video_url: str) -> dict:
        """Post a Reel to Instagram via public video URL."""
        import requests as _req
        # Step 1: Create Reel container
        container = _req.post(
            f"https://graph.facebook.com/v19.0/{self.account_id}/media",
            data={"video_url": video_url, "caption": caption,
                  "media_type": "REELS", "access_token": self.token},
            timeout=30,
        ).json()
        if "id" not in container:
            return {"status": "error",
                    "error": container.get("error", {}).get("message", str(container))}

        # Step 2: Wait for IG to process video, then publish
        logger.info("Waiting for Instagram to process Reel...")
        time.sleep(30)
        publish = _req.post(
            f"https://graph.facebook.com/v19.0/{self.account_id}/media_publish",
            data={"creation_id": container["id"], "access_token": self.token},
            timeout=30,
        ).json()
        if "id" in publish:
            return {"status": "posted", "post_id": publish["id"], "method": "graph_api"}
        return {"status": "error",
                "error": publish.get("error", {}).get("message", str(publish))}

    def post_reel_file(self, caption: str, video_path: str) -> dict:
        """Post a Reel to Instagram using resumable upload (no public URL needed)."""
        import requests as _req
        video_path = str(video_path)
        file_size = Path(video_path).stat().st_size
        logger.info(f"Uploading {file_size / 1024 / 1024:.1f}MB reel to Instagram (resumable)...")

        # Step 1: Initialize resumable upload session
        init = _req.post(
            f"https://graph.facebook.com/v19.0/{self.account_id}/media",
            data={
                "media_type": "REELS",
                "upload_type": "resumable",
                "caption": caption,
                "access_token": self.token,
            },
            timeout=30,
        ).json()
        if "id" not in init or "uri" not in init:
            return {"status": "error",
                    "error": init.get("error", {}).get("message", str(init))}

        container_id = init["id"]
        upload_uri = init["uri"]
        logger.info(f"Instagram resumable upload URI: {upload_uri}")

        # Step 2: Upload video bytes
        with open(video_path, "rb") as f:
            upload_resp = _req.post(
                upload_uri,
                headers={
                    "Authorization": f"OAuth {self.token}",
                    "offset": "0",
                    "file_size": str(file_size),
                },
                data=f,
                timeout=600,
            )
        if upload_resp.status_code not in (200, 201):
            return {"status": "error", "error": f"Upload failed: {upload_resp.status_code} {upload_resp.text[:200]}"}

        # Step 3: Wait for processing + publish
        logger.info("Waiting for Instagram to process Reel...")
        for _ in range(24):  # up to 2 min
            time.sleep(5)
            status = _req.get(
                f"https://graph.facebook.com/v19.0/{container_id}",
                params={"fields": "status_code", "access_token": self.token},
                timeout=15,
            ).json()
            sc = status.get("status_code", "")
            if sc == "FINISHED":
                break
            if sc in ("ERROR", "EXPIRED"):
                return {"status": "error", "error": f"IG processing failed: {status}"}

        publish = _req.post(
            f"https://graph.facebook.com/v19.0/{self.account_id}/media_publish",
            data={"creation_id": container_id, "access_token": self.token},
            timeout=30,
        ).json()
        if "id" in publish:
            return {"status": "posted", "post_id": publish["id"], "method": "graph_api_resumable"}
        return {"status": "error",
                "error": publish.get("error", {}).get("message", str(publish))}


# ── Browser poster ────────────────────────────────────────────────────────────

class InstagramBrowserPoster:
    """Post to Instagram via Playwright browser automation."""

    def __init__(self, account: str = "main"):
        self.account = account
        prefix = _env_prefix(account)
        self.username = os.getenv(f"{prefix}INSTAGRAM_USERNAME", "")
        self.password = os.getenv(f"{prefix}INSTAGRAM_PASSWORD", "")
        self.session_file = _session_file(account)

    def is_configured(self) -> bool:
        return bool(self.username and self.password)

    def _get_context(self, playwright):
        browser = playwright.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        ctx_args = dict(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        if self.session_file.exists():
            try:
                ctx = browser.new_context(storage_state=str(self.session_file), **ctx_args)
                return browser, ctx
            except Exception:
                pass
        return browser, browser.new_context(**ctx_args)

    def _login(self, page):
        page.goto("https://www.instagram.com/accounts/login/",
                  wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        page.locator('input[name="username"]').fill(self.username)
        page.locator('input[name="password"]').fill(self.password)
        page.locator('button[type="submit"]').click()
        page.wait_for_timeout(6000)
        # Dismiss "Save login info?" and notifications prompts
        for label in ["Not Now", "Not now", "Skip"]:
            try:
                btn = page.locator(f'button:has-text("{label}")').first
                if btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1500)
            except Exception:
                pass
        logger.info("[Browser] Logged into Instagram")

    def _save_session(self, context):
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(self.session_file))

    def _is_logged_in(self, page) -> bool:
        return "login" not in page.url and "accounts" not in page.url

    def post_photo(self, caption: str, image_url: str) -> dict:
        """Post a photo to Instagram by downloading and uploading via browser."""
        if not self.is_configured():
            raise RuntimeError("INSTAGRAM_USERNAME / INSTAGRAM_PASSWORD not set in .env")
        import requests as _req

        # Download image
        r = _req.get(image_url, timeout=30)
        r.raise_for_status()
        suffix = ".jpg"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(r.content)
            img_path = f.name

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, context = self._get_context(p)
            page = context.new_page()
            try:
                page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                if not self._is_logged_in(page):
                    self._login(page)
                    page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)

                # Click the Create (+) button
                create_btn = page.locator('svg[aria-label="New post"]').first
                if not create_btn.is_visible():
                    create_btn = page.locator('[aria-label="New post"]').first
                create_btn.click()
                page.wait_for_timeout(2000)

                # Select from computer
                select_btn = page.locator('button:has-text("Select from computer")').first
                if select_btn.is_visible():
                    # Use file input instead
                    file_input = page.locator('input[type="file"]').first
                    file_input.set_input_files(img_path)
                else:
                    file_input = page.locator('input[type="file"]').first
                    file_input.set_input_files(img_path)
                page.wait_for_timeout(3000)

                # Click Next through crop and filters
                for _ in range(2):
                    next_btn = page.locator('button:has-text("Next")').last
                    if next_btn.is_visible():
                        next_btn.click()
                        page.wait_for_timeout(2000)

                # Write caption
                caption_box = page.locator('div[aria-label="Write a caption..."]').first
                if caption_box.is_visible():
                    caption_box.click()
                    page.keyboard.type(caption[:2200], delay=10)
                    page.wait_for_timeout(1000)

                # Share
                share_btn = page.locator('button:has-text("Share")').last
                share_btn.click()
                page.wait_for_timeout(6000)

                self._save_session(context)
                logger.info("[Browser] Instagram photo posted: %s...", caption[:50])
                return {"status": "posted", "method": "browser",
                        "url": f"https://www.instagram.com/{self.username}/"}
            except Exception as e:
                logger.error("[Browser] Instagram post failed: %s", e)
                raise
            finally:
                browser.close()
                Path(img_path).unlink(missing_ok=True)

    def post_text_as_image(self, caption: str) -> dict:
        """Compose a sharp image with a clean DALL-E HD background + Pillow headline
        text, then upload via the browser flow (Instagram requires images)."""
        if not os.getenv("OPENAI_API_KEY"):
            return {"status": "error",
                    "error": "Instagram requires an image. Add OPENAI_API_KEY to auto-generate."}
        from core.social_image import generate_social_image
        headline = caption.split("\n", 1)[0].split(". ", 1)[0][:90].strip() or "WheellsVerse"
        subtext = caption[len(headline):].strip(" .\n").split("\n", 1)[0][:120]
        local = generate_social_image(headline=headline, subtext=subtext,
                                      platform="instagram_feed")
        if not local:
            return {"status": "error", "error": "Image composition failed (DALL-E or Pillow)"}
        # Browser path uploads from a local file by re-fetching via file:// URL
        # is brittle — instead read the bytes and re-use the image_url path
        # through a public HTTPS exposure.
        from core.social_image import upload_to_public_url
        image_url = upload_to_public_url(local)
        if not image_url:
            return {"status": "error",
                    "error": "RAILWAY_PUBLIC_URL not set — composed image cannot be exposed to IG"}
        return self.post_photo(caption, image_url)


# ── Unified client ────────────────────────────────────────────────────────────

class InstagramClient:
    """Graph API first, browser fallback."""

    def __init__(self, account: str = "main"):
        self.account = account
        self._graph = InstagramGraphPoster(account=account)
        self._browser = InstagramBrowserPoster(account=account)

    def is_configured(self) -> bool:
        return self._graph.is_configured() or self._browser.is_configured()

    def post(self, caption: str, image_url: Optional[str] = None,
             video_url: Optional[str] = None,
             video_path: Optional[str] = None) -> dict:
        """Post to Instagram. Graph API first, browser fallback.
        video_path: local file path (resumable upload, no public URL needed)
        video_url: public URL for Reel
        """
        # ── Graph API ─────────────────────────────────────────────────────────
        if self._graph.is_configured():
            try:
                if video_path:
                    return self._graph.post_reel_file(caption, video_path)
                if video_url:
                    return self._graph.post_reel(caption, video_url)
                return self._graph.post_photo(caption, image_url)
            except Exception as e:
                logger.warning("[Graph %s] Failed (%s) — falling back to browser",
                               self.account, e)

        # ── Browser fallback ──────────────────────────────────────────────────
        if self._browser.is_configured():
            try:
                if image_url:
                    return self._browser.post_photo(caption, image_url)
                # Instagram needs an image — generate one with DALL-E
                return self._browser.post_text_as_image(caption)
            except Exception as e:
                return {"status": "error", "error": str(e), "method": "browser",
                        "account": self.account}

        prefix = _env_prefix(self.account)
        return {
            "status": "skipped",
            "account": self.account,
            "reason": (
                f"No Instagram credentials for account={self.account!r}. Add to .env:\n"
                f"  {prefix}INSTAGRAM_PAGE_TOKEN + {prefix}INSTAGRAM_ACCOUNT_ID  (Graph API)\n"
                "  OR\n"
                f"  {prefix}INSTAGRAM_USERNAME + {prefix}INSTAGRAM_PASSWORD  (browser)"
            ),
        }


_clients: Dict[str, InstagramClient] = {}


def get_instagram(account: str = "main") -> InstagramClient:
    """Return cached client for `account` (default "main"). Creates on first use."""
    if account not in _clients:
        _clients[account] = InstagramClient(account=account)
    return _clients[account]
