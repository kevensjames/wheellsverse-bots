#!/usr/bin/env python3
"""
core/facebook.py
─────────────────────────────────────────────────────────────────────────────
Facebook integration — Graph API first, Playwright browser fallback.

Credentials (at least one method must be set):

  Method A — Graph API (recommended for video + images):
    FACEBOOK_PAGE_TOKEN   — Page Access Token from Meta Developer Console
    FACEBOOK_PAGE_ID      — Your Facebook Page ID (numeric)

  Method B — Browser automation (text + images via login):
    FACEBOOK_EMAIL        — Facebook account email
    FACEBOOK_PASSWORD     — Facebook account password
    FACEBOOK_PAGE_URL     — Your page URL (e.g. https://www.facebook.com/WheellsVerse)
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("facebook")

SESSION_FILE = ROOT / "data" / "facebook_session.json"


# ── Graph API poster ──────────────────────────────────────────────────────────

class FacebookGraphPoster:
    """Post to Facebook Page via Graph API."""

    def __init__(self):
        self.token = os.getenv("FACEBOOK_PAGE_TOKEN", "")
        self.page_id = os.getenv("FACEBOOK_PAGE_ID", "")

    def is_configured(self) -> bool:
        return bool(self.token and self.page_id)

    def post_text(self, message: str) -> dict:
        import requests
        resp = requests.post(
            f"https://graph.facebook.com/v19.0/{self.page_id}/feed",
            json={"message": message, "access_token": self.token},
            timeout=15,
        )
        data = resp.json()
        if "id" in data:
            return {"status": "posted", "post_id": data["id"], "method": "graph_api"}
        return {"status": "error", "error": data.get("error", {}).get("message", str(data))}

    def post_photo(self, message: str, image_url: str) -> dict:
        import requests
        resp = requests.post(
            f"https://graph.facebook.com/v19.0/{self.page_id}/photos",
            data={"url": image_url, "caption": message, "access_token": self.token},
            timeout=30,
        )
        data = resp.json()
        if "id" in data:
            return {"status": "posted", "post_id": data["id"], "method": "graph_api"}
        return {"status": "error", "error": data.get("error", {}).get("message", str(data))}

    def post_video(self, description: str, video_url: str) -> dict:
        import requests
        resp = requests.post(
            f"https://graph.facebook.com/v19.0/{self.page_id}/videos",
            data={"file_url": video_url, "description": description,
                  "access_token": self.token},
            timeout=60,
        )
        data = resp.json()
        if "id" in data:
            return {"status": "posted", "post_id": data["id"], "method": "graph_api"}
        return {"status": "error", "error": data.get("error", {}).get("message", str(data))}

    def post_video_file(self, description: str, video_path: str) -> dict:
        """Upload a local video file directly to Facebook via multipart form."""
        import requests
        video_path = str(video_path)
        file_size = Path(video_path).stat().st_size
        logger.info(f"Uploading {file_size / 1024 / 1024:.1f}MB video to Facebook...")
        try:
            with open(video_path, "rb") as f:
                resp = requests.post(
                    f"https://graph-video.facebook.com/v19.0/{self.page_id}/videos",
                    data={"description": description, "access_token": self.token},
                    files={"source": (Path(video_path).name, f, "video/mp4")},
                    timeout=600,
                )
            data = resp.json()
            if "id" in data:
                return {"status": "posted", "post_id": data["id"], "method": "graph_api_file"}
            return {"status": "error", "error": data.get("error", {}).get("message", str(data))}
        except Exception as e:
            return {"status": "error", "error": str(e)}


# ── Browser poster ────────────────────────────────────────────────────────────

class FacebookBrowserPoster:
    """Post to Facebook Page via Playwright browser automation."""

    def __init__(self):
        self.email = os.getenv("FACEBOOK_EMAIL", "")
        self.password = os.getenv("FACEBOOK_PASSWORD", "")
        self.page_url = os.getenv("FACEBOOK_PAGE_URL", "").rstrip("/")

    def is_configured(self) -> bool:
        return bool(self.email and self.password)

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
        if SESSION_FILE.exists():
            try:
                ctx = browser.new_context(storage_state=str(SESSION_FILE), **ctx_args)
                return browser, ctx
            except Exception:
                pass
        return browser, browser.new_context(**ctx_args)

    def _login(self, page):
        """Log into Facebook."""
        page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2000)
        page.locator('input[id="email"]').fill(self.email)
        page.locator('input[id="pass"]').fill(self.password)
        page.locator('button[name="login"]').click()
        page.wait_for_timeout(5000)
        logger.info("[Browser] Logged into Facebook")

    def _save_session(self, context):
        SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(SESSION_FILE))

    def _is_logged_in(self, page) -> bool:
        return "login" not in page.url and "checkpoint" not in page.url

    def post_text(self, message: str) -> dict:
        """Post a text update to the Facebook Page."""
        if not self.is_configured():
            raise RuntimeError("FACEBOOK_EMAIL / FACEBOOK_PASSWORD not set in .env")
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser, context = self._get_context(p)
            page = context.new_page()
            try:
                # Go to page composer
                target = self.page_url or "https://www.facebook.com"
                page.goto(target, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)

                if not self._is_logged_in(page):
                    self._login(page)
                    page.goto(target, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)

                # Click the "What's on your mind" composer box
                composer = page.locator('[aria-label="What\'s on your mind?"]').first
                if not composer.is_visible():
                    composer = page.locator('[data-testid="status-attachment-mentions-input"]').first
                if not composer.is_visible():
                    # Try clicking the "Write something..." area
                    page.locator("text=Write something...").first.click()
                    page.wait_for_timeout(1000)
                else:
                    composer.click()
                page.wait_for_timeout(1500)

                # Type the message
                page.keyboard.type(message, delay=20)
                page.wait_for_timeout(1000)

                # Click Post button
                post_btn = page.locator('[aria-label="Post"]').last
                if not post_btn.is_visible():
                    post_btn = page.locator('div[aria-label="Post"]').last
                page.evaluate('el => el.click()', post_btn.element_handle())
                page.wait_for_timeout(4000)

                self._save_session(context)
                logger.info("[Browser] Facebook post published: %s...", message[:60])
                return {"status": "posted", "method": "browser",
                        "url": self.page_url or "https://www.facebook.com"}
            except Exception as e:
                logger.error("[Browser] Facebook post failed: %s", e)
                raise
            finally:
                browser.close()

    def post_photo(self, message: str, image_url: str) -> dict:
        """Post an image to the Facebook Page (downloads and uploads it)."""
        if not self.is_configured():
            raise RuntimeError("FACEBOOK_EMAIL / FACEBOOK_PASSWORD not set in .env")
        import requests as _req
        import tempfile

        # Download image to temp file
        r = _req.get(image_url, timeout=30)
        r.raise_for_status()
        suffix = ".jpg" if "jpeg" in r.headers.get("content-type", "") else ".png"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
            f.write(r.content)
            img_path = f.name

        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, context = self._get_context(p)
            page = context.new_page()
            try:
                target = self.page_url or "https://www.facebook.com"
                page.goto(target, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)

                if not self._is_logged_in(page):
                    self._login(page)
                    page.goto(target, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)

                # Click Photo/Video button in composer
                photo_btn = page.locator('[aria-label="Photo/Video"]').first
                if photo_btn.is_visible():
                    photo_btn.click()
                else:
                    page.locator("text=Photo/Video").first.click()
                page.wait_for_timeout(1500)

                # Upload the image
                file_input = page.locator('input[type="file"]').first
                file_input.set_input_files(img_path)
                page.wait_for_timeout(3000)

                # Add caption
                caption_box = page.locator('[aria-label="Say something about this photo..."]').first
                if caption_box.is_visible():
                    caption_box.click()
                    page.keyboard.type(message, delay=15)
                page.wait_for_timeout(1000)

                # Post
                post_btn = page.locator('[aria-label="Post"]').last
                page.evaluate('el => el.click()', post_btn.element_handle())
                page.wait_for_timeout(5000)

                self._save_session(context)
                logger.info("[Browser] Facebook photo post published")
                return {"status": "posted", "method": "browser",
                        "url": self.page_url or "https://www.facebook.com"}
            except Exception as e:
                logger.error("[Browser] Facebook photo post failed: %s", e)
                raise
            finally:
                browser.close()
                Path(img_path).unlink(missing_ok=True)


# ── Unified client ────────────────────────────────────────────────────────────

class FacebookClient:
    """Graph API first, browser fallback."""

    def __init__(self):
        self._graph = FacebookGraphPoster()
        self._browser = FacebookBrowserPoster()

    def is_configured(self) -> bool:
        return self._graph.is_configured() or self._browser.is_configured()

    def post(self, message: str, image_url: Optional[str] = None,
             video_url: Optional[str] = None,
             video_path: Optional[str] = None) -> dict:
        """
        Post to Facebook. Tries Graph API first, falls back to browser.
        video_path: local file path (no public URL needed — uses multipart upload)
        video_url: public URL (uses file_url parameter)
        """
        # ── Graph API ─────────────────────────────────────────────────────────
        if self._graph.is_configured():
            try:
                if video_path:
                    return self._graph.post_video_file(message, video_path)
                if video_url:
                    return self._graph.post_video(message, video_url)
                if image_url:
                    return self._graph.post_photo(message, image_url)
                return self._graph.post_text(message)
            except Exception as e:
                logger.warning("[Graph] Failed (%s) — falling back to browser", e)

        # ── Browser fallback ──────────────────────────────────────────────────
        if self._browser.is_configured():
            try:
                if image_url:
                    return self._browser.post_photo(message, image_url)
                return self._browser.post_text(message)
            except Exception as e:
                return {"status": "error", "error": str(e), "method": "browser"}

        return {
            "status": "skipped",
            "reason": (
                "No Facebook credentials configured. Add to .env:\n"
                "  FACEBOOK_PAGE_TOKEN + FACEBOOK_PAGE_ID  (Graph API)\n"
                "  OR\n"
                "  FACEBOOK_EMAIL + FACEBOOK_PASSWORD + FACEBOOK_PAGE_URL  (browser)"
            ),
        }


_client: Optional[FacebookClient] = None


def get_facebook() -> FacebookClient:
    global _client
    if _client is None:
        _client = FacebookClient()
    return _client
