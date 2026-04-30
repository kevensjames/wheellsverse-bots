#!/usr/bin/env python3
"""
core/twitter.py
─────────────────────────────────────────────────────────────────────────────
Twitter/X integration — post tweets, threads, and scheduled content.

Credentials needed in .env:
  TWITTER_API_KEY          — from developer.x.com → Your App → Keys and Tokens
  TWITTER_API_SECRET
  TWITTER_ACCESS_TOKEN
  TWITTER_ACCESS_SECRET
  TWITTER_BEARER_TOKEN     — for read-only lookups (optional)
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import re
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("twitter")


class XRateLimited(RuntimeError):
    """X frontend showed a rate-limit or posting-block banner — back off, do not retry soon."""


class XLoginRequired(RuntimeError):
    """X login flow couldn't complete (creds wrong, 2FA challenge, captcha)."""


class TwitterBrowserPoster:
    """Post tweets via Playwright browser automation (fallback when API credits run out)."""

    SESSION_FILE = ROOT / "data" / "playwright" / "x_state.json"
    LEGACY_SESSION_FILE = ROOT / "data" / "twitter_session.json"
    FAILURE_SCREENSHOT_DIR = ROOT / "logs"

    # Banners that indicate temporary block / rate limit — scan page text after post attempt
    _RATE_LIMIT_PATTERNS = (
        "rate limited",
        "you are over the daily limit",
        "limit reached",
        "couldn't post",
        "unable to post",
        "try again later",
        "temporarily restricted",
    )

    # Per-action timeouts (ms). Bumped from old defaults: X load times routinely exceed 30s.
    _TIMEOUT_PAGE_LOAD = 60_000
    _TIMEOUT_EDITOR = 30_000
    _TIMEOUT_POST_BUTTON = 30_000
    _POST_RETRY_ATTEMPTS = 3

    def __init__(self):
        self.username = os.getenv("TWITTER_USERNAME", "").lstrip("@")
        self.email = os.getenv("TWITTER_EMAIL", "")
        self.password = os.getenv("TWITTER_PASSWORD", "")
        self._migrate_legacy_session()

    @classmethod
    def _migrate_legacy_session(cls) -> None:
        """One-time copy of old data/twitter_session.json to new data/playwright/x_state.json."""
        if cls.SESSION_FILE.exists() or not cls.LEGACY_SESSION_FILE.exists():
            return
        try:
            cls.SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
            cls.SESSION_FILE.write_bytes(cls.LEGACY_SESSION_FILE.read_bytes())
            logger.info(f"Migrated X session: {cls.LEGACY_SESSION_FILE} → {cls.SESSION_FILE}")
        except Exception as e:
            logger.warning(f"Session migration failed (non-fatal): {e}")

    def _is_configured(self) -> bool:
        return bool(self.username and self.password)

    @staticmethod
    def _ensure_chromium() -> None:
        """Install Playwright Chromium binary on first use if not already present.
        Runs once per container lifetime (~60s); cached in /tmp after that."""
        import subprocess, shutil
        # Check if the chromium binary already exists
        result = subprocess.run(
            ["playwright", "install", "--dry-run"],
            capture_output=True, text=True
        )
        if "chromium" in result.stdout.lower() and "already installed" in result.stdout.lower():
            return
        # Not present — install now (requires internet; Railway containers have it)
        logger.info("Installing Playwright Chromium binary (one-time, ~60s)...")
        proc = subprocess.run(
            ["playwright", "install", "chromium", "--with-deps"],
            capture_output=True, text=True, timeout=300
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"playwright install chromium failed: {proc.stderr[:500]}"
            )
        logger.info("Playwright Chromium installed.")

    def post_tweet(self, text: str) -> Dict:
        """Post a single tweet via browser, with retries + rate-limit detection.

        Raises:
            XRateLimited: page showed a rate-limit / posting-block banner
            XLoginRequired: login flow failed (creds bad, 2FA, captcha)
            RuntimeError: all retries exhausted on a transient interaction failure
        """
        if not self._is_configured():
            raise RuntimeError("TWITTER_USERNAME / TWITTER_PASSWORD not set in .env")
        self._ensure_chromium()
        from playwright.sync_api import sync_playwright
        text = text[:280]
        with sync_playwright() as p:
            browser, context = self._get_context(p)
            page = context.new_page()
            try:
                page.goto("https://x.com/compose/post", wait_until="domcontentloaded",
                          timeout=self._TIMEOUT_PAGE_LOAD)
                page.wait_for_timeout(3000)
                # Login if redirected to flow
                if "login" in page.url or "i/flow" in page.url:
                    try:
                        self._login(page)
                    except Exception as e:
                        self._save_failure_screenshot(page, "login")
                        raise XLoginRequired(f"X login failed: {e}") from e
                    page.goto("https://x.com/compose/post", wait_until="domcontentloaded",
                              timeout=self._TIMEOUT_PAGE_LOAD)
                    page.wait_for_timeout(3000)

                last_err: Optional[Exception] = None
                for attempt in range(1, self._POST_RETRY_ATTEMPTS + 1):
                    try:
                        self._do_compose_and_post(page, text)
                        # After successful click, scan for rate-limit banners — even success
                        # path can show "limit reached" if the click registers but post fails.
                        banner = self._detect_rate_limit_banner(page)
                        if banner:
                            self._save_failure_screenshot(page, "rate-limited")
                            raise XRateLimited(
                                f"X rate-limit banner detected: {banner!r} — back off ≥1h"
                            )
                        # Save session for next time
                        self.SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
                        context.storage_state(path=str(self.SESSION_FILE))
                        logger.info(
                            f"[Browser] Tweet posted (attempt {attempt}/{self._POST_RETRY_ATTEMPTS}): {text[:60]}…"
                        )
                        return {"text": text, "method": "browser",
                                "url": f"https://x.com/{self.username}", "attempts": attempt}
                    except XRateLimited:
                        # Don't retry — rate limit is a backoff signal, not transient
                        raise
                    except Exception as e:
                        last_err = e
                        logger.warning(
                            f"[Browser] Post attempt {attempt}/{self._POST_RETRY_ATTEMPTS} failed: {e}"
                        )
                        if attempt < self._POST_RETRY_ATTEMPTS:
                            page.wait_for_timeout(2000 * attempt)  # 2s, 4s backoff
                            # Re-navigate in case page is in weird state
                            try:
                                page.goto("https://x.com/compose/post",
                                          wait_until="domcontentloaded",
                                          timeout=self._TIMEOUT_PAGE_LOAD)
                                page.wait_for_timeout(2000)
                            except Exception:
                                pass

                # All retries exhausted
                self._save_failure_screenshot(page, "post-retries-exhausted")
                raise RuntimeError(
                    f"Tweet failed after {self._POST_RETRY_ATTEMPTS} attempts: {last_err}"
                )
            finally:
                browser.close()

    def _do_compose_and_post(self, page, text: str) -> None:
        """Single attempt at the compose → click flow. Raises on any interaction failure."""
        editor = page.locator('[data-testid="tweetTextarea_0"]').first
        editor.wait_for(state="visible", timeout=self._TIMEOUT_EDITOR)
        editor.click()
        editor.type(text, delay=30)
        page.wait_for_timeout(500)
        post_btn = page.locator('[data-testid="tweetButton"]').first
        post_btn.wait_for(state="visible", timeout=self._TIMEOUT_POST_BUTTON)
        # JS click bypasses overlay/aria-disabled quirks
        page.evaluate('document.querySelector(\'[data-testid="tweetButton"]\').click()')
        page.wait_for_timeout(3000)

    def _detect_rate_limit_banner(self, page) -> Optional[str]:
        """Scan page text for known rate-limit / block phrases. Returns matched phrase or None."""
        try:
            body_text = (page.locator("body").inner_text(timeout=2000) or "").lower()
        except Exception:
            return None
        for pattern in self._RATE_LIMIT_PATTERNS:
            if pattern in body_text:
                return pattern
        return None

    def _save_failure_screenshot(self, page, label: str) -> Optional[str]:
        """Save full-page screenshot for post-mortem debug. Returns saved path or None."""
        try:
            self.FAILURE_SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            fname = f"twitter_failure_{label}_{int(time.time())}.png"
            path = self.FAILURE_SCREENSHOT_DIR / fname
            page.screenshot(path=str(path), full_page=True)
            logger.error(f"[Browser] Failure screenshot saved: {path}")
            return str(path)
        except Exception as e:
            logger.warning(f"[Browser] Could not save failure screenshot: {e}")
            return None

    def _get_context(self, playwright):
        """Create a browser context that bypasses X bot detection.

        Default: headed (X blocks headless). Override with X_HEADED=0 for CI/debug
        when X may not be the target (e.g. unit-test stubs or recording sessions
        in environments without a display).
        """
        headless = os.getenv("X_HEADED", "1") == "0"
        browser = playwright.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
        # Modern Chrome UA reduces bot-detection false positives
        ua = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
        ctx_args: dict = {
            "user_agent": ua,
            "viewport": {"width": 1280, "height": 800},
            "locale": "en-US",
        }
        # Reuse saved session if available — cuts login flow on subsequent runs
        if self.SESSION_FILE.exists():
            try:
                ctx_args["storage_state"] = str(self.SESSION_FILE)
            except Exception:
                pass
        ctx = browser.new_context(**ctx_args)
        return browser, ctx

    def _login(self, page):
        """Handle X login flow."""
        page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded",
                  timeout=self._TIMEOUT_PAGE_LOAD)
        page.wait_for_selector("input", timeout=15000)
        page.wait_for_timeout(1500)
        # Step 1: email
        page.locator("input").first.fill(self.email or self.username)
        page.keyboard.press("Enter")
        page.wait_for_timeout(3000)
        # Step 2: username confirmation (if X asks)
        inp = page.locator("input").first
        if inp.get_attribute("name") == "text":
            inp.fill(self.username)
            page.keyboard.press("Enter")
            page.wait_for_timeout(3000)
        # Step 3: password
        page.wait_for_selector('input[type="password"]', timeout=10000)
        page.locator('input[type="password"]').first.fill(self.password)
        page.keyboard.press("Enter")
        page.wait_for_timeout(5000)
        logger.info("[Browser] Logged in to X")

    def post_thread(self, tweets: list) -> list:
        """Post a thread as sequential tweets via browser — most reliable approach."""
        results = []
        for i, text in enumerate(tweets):
            try:
                r = self.post_tweet(text)
                results.append(r)
                logger.info(f"[Browser] Thread tweet {i + 1}/{len(tweets)} posted")
                if i < len(tweets) - 1:
                    time.sleep(3)  # avoid rate limiting between tweets
            except Exception as e:
                logger.error(f"[Browser] Thread tweet {i + 1} failed: {e}")
                raise
        return results


class TwitterClient:
    """Post tweets and threads — API v2 first, browser fallback if credits run out."""

    MAX_TWEET_LEN = 280
    _DAILY_LIMIT_FILE = ROOT / "data" / "twitter_daily_limit.json"

    def __init__(self):
        self.api_key = os.getenv("TWITTER_API_KEY", "")
        self.api_secret = os.getenv("TWITTER_API_SECRET", "")
        self.access_token = os.getenv("TWITTER_ACCESS_TOKEN", "")
        self.access_secret = os.getenv("TWITTER_ACCESS_SECRET", "")
        self.bearer_token = os.getenv("TWITTER_BEARER_TOKEN", "")
        self.daily_limit = int(os.getenv("TWITTER_DAILY_LIMIT", "0"))  # 0 = unlimited
        self._client = None
        self._browser = TwitterBrowserPoster()

    def _check_daily_limit(self):
        """Raise if the daily post limit has been reached for today."""
        if not self.daily_limit:
            return
        today = str(date.today())
        self._DAILY_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        record = {}
        if self._DAILY_LIMIT_FILE.exists():
            try:
                record = json.loads(self._DAILY_LIMIT_FILE.read_text())
            except Exception:
                record = {}
        count = record.get(today, 0)
        if count >= self.daily_limit:
            raise RuntimeError(
                f"Daily post limit of {self.daily_limit} reached for {today}. "
                "Try again tomorrow."
            )

    def _increment_daily_count(self):
        """Increment today's post counter."""
        if not self.daily_limit:
            return
        today = str(date.today())
        self._DAILY_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        record = {}
        if self._DAILY_LIMIT_FILE.exists():
            try:
                record = json.loads(self._DAILY_LIMIT_FILE.read_text())
            except Exception:
                record = {}
        record[today] = record.get(today, 0) + 1
        self._DAILY_LIMIT_FILE.write_text(json.dumps(record))

    def _get_client(self):
        if self._client is None:
            if not all([self.api_key, self.api_secret,
                        self.access_token, self.access_secret]):
                raise RuntimeError(
                    "Twitter credentials missing. Add to .env:\n"
                    "  TWITTER_API_KEY, TWITTER_API_SECRET,\n"
                    "  TWITTER_ACCESS_TOKEN, TWITTER_ACCESS_SECRET"
                )
            import tweepy
            self._client = tweepy.Client(
                consumer_key=self.api_key,
                consumer_secret=self.api_secret,
                access_token=self.access_token,
                access_token_secret=self.access_secret,
                wait_on_rate_limit=True,
            )
        return self._client

    # ── Posting ────────────────────────────────────────────────────────────────

    def post_tweet(self, text: str) -> Dict:
        """Post a single tweet — API first, browser fallback on 402."""
        self._check_daily_limit()
        text = text[:self.MAX_TWEET_LEN]
        try:
            client = self._get_client()
            resp = client.create_tweet(text=text)
            tweet_id = resp.data["id"]
            me = client.get_me()
            username = me.data.username if me and me.data else "i"
            url = f"https://x.com/{username}/status/{tweet_id}"
            logger.info(f"Tweet posted (API): {url}")
            self._increment_daily_count()
            return {"id": tweet_id, "text": text, "url": url, "method": "api"}
        except RuntimeError:
            raise
        except Exception as e:
            err = str(e)
            logger.error("Twitter API post_tweet failed: %s", err)
            is_credits = "402" in err or "Payment Required" in err or "credits" in err.lower()
            if is_credits and self._browser._is_configured():
                logger.warning("API credits exhausted — switching to browser posting")
                result = self._browser.post_tweet(text)
                self._increment_daily_count()
                return result
            # Surface the real API error (browser not configured or not a credits issue)
            raise RuntimeError(f"Twitter API error: {err}") from e

    def post_thread(self, tweets: List[str]) -> List[Dict]:
        """Post a thread — API first, browser fallback on 402."""
        self._check_daily_limit()
        try:
            client = self._get_client()
            me = client.get_me()
            username = me.data.username if me and me.data else "i"
            results = []
            reply_to = None
            for text in tweets:
                text = text[:self.MAX_TWEET_LEN]
                kwargs = {"text": text}
                if reply_to:
                    kwargs["reply"] = {"in_reply_to_tweet_id": reply_to}
                resp = client.create_tweet(**kwargs)
                tweet_id = resp.data["id"]
                url = f"https://x.com/{username}/status/{tweet_id}"
                results.append({"id": tweet_id, "text": text, "url": url, "method": "api"})
                reply_to = tweet_id
                time.sleep(1)
            logger.info(f"Thread posted (API): {len(results)} tweets, first: {results[0]['url']}")
            self._increment_daily_count()
            return results
        except RuntimeError:
            raise
        except Exception as e:
            if "402" in str(e) or "Payment Required" in str(e) or "credits" in str(e).lower():
                logger.warning("Twitter API credits exhausted — switching to browser for thread")
                result = self._browser.post_thread(tweets)
                self._increment_daily_count()
                return result
            raise

    # ── Content formatting ─────────────────────────────────────────────────────

    @staticmethod
    def format_thread_from_markdown(md: str, max_tweets: int = 8) -> List[str]:
        """
        Convert a markdown article into a tweetable thread.
        First tweet = hook. Last tweet = CTA with affiliate link.
        """
        lines = [ln.strip() for ln in md.splitlines() if ln.strip()]

        # Extract title as hook
        title = ""
        body_lines = []
        for line in lines:
            if line.startswith("#") and not title:
                title = re.sub(r"^#+\s*", "", line)
            elif not line.startswith("#"):
                body_lines.append(line)

        tweets = []

        # Tweet 1 — hook
        if title:
            hook = f"🧵 {title[:220]}\n\n(Thread)"
            tweets.append(hook)

        # Middle tweets — key points
        chunk = ""
        tweet_num = 2
        for line in body_lines:
            # Skip markdown links/images
            line = re.sub(r"!\[.*?\]\(.*?\)", "", line)
            line = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", line)
            line = re.sub(r"\*\*(.+?)\*\*", r"\1", line)
            line = re.sub(r"`(.+?)`", r"\1", line)
            if not line or len(line) < 20:
                continue

            candidate = (chunk + "\n" + line).strip() if chunk else line
            if len(candidate) <= 250:
                chunk = candidate
            else:
                if chunk:
                    tweets.append(f"{tweet_num}/ {chunk}"[:280])
                    tweet_num += 1
                    chunk = line[:250]
                else:
                    tweets.append(f"{tweet_num}/ {line[:250]}")
                    tweet_num += 1

            if len(tweets) >= max_tweets - 1:
                break

        if chunk and len(tweets) < max_tweets - 1:
            tweets.append(f"{tweet_num}/ {chunk}"[:280])

        # Last tweet — CTA
        coinbase = os.getenv("AFFILIATE_COINBASE_URL", "")
        robinhood = os.getenv("AFFILIATE_WEBULL_URL", "")

        cta_parts = ["💰 Start earning today:"]
        if robinhood:
            cta_parts.append(f"📈 Free stocks → {robinhood[:50]}")
        if coinbase:
            cta_parts.append(f"₿ $10 crypto bonus → {coinbase[:50]}")
        cta_parts.append("🛒 Amazon deals → amzn.to/wheellsverse")
        cta_parts.append("\nFollow @wheellsverse for daily money moves 🚀")
        cta = "\n".join(cta_parts)[:280]
        tweets.append(cta)

        return tweets[:max_tweets]

    @staticmethod
    def make_single_tweet(title: str, key_point: str, hashtags: List[str]) -> str:
        """Build a punchy single tweet."""
        tags = " ".join(f"#{t.lstrip('#')}" for t in hashtags[:4])
        base = f"💡 {title}\n\n{key_point}\n\n{tags}"
        return base[:280]

    # ── Status ─────────────────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        return all([self.api_key, self.api_secret,
                    self.access_token, self.access_secret])

    def get_status(self) -> Dict:
        connected = self.is_connected()
        username = ""
        if connected:
            try:
                me = self._get_client().get_me()
                username = f"@{me.data.username}" if me and me.data else ""
            except Exception:
                pass
        return {
            "connected": connected,
            "username": username,
            "api_key": self.api_key[:8] + "..." if self.api_key else "",
        }


_client: Optional[TwitterClient] = None


def get_twitter() -> TwitterClient:
    global _client
    if _client is None:
        _client = TwitterClient()
    return _client
