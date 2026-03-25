#!/usr/bin/env python3
"""
core/browser.py
─────────────────────────────────────────────────────────────────────────────
Browser Automation Layer — Playwright-powered headless browser tools.

Capabilities:
  • Screenshot any URL
  • Scrape dynamic JS-rendered pages (crypto sites, social media, etc.)
  • Auto-post to Twitter/X (with credentials)
  • Auto-post to LinkedIn
  • Auto-post to Medium
  • Scrape Google Trends (full data, not just API)
  • Scrape CoinMarketCap / CoinGecko full pages
  • Fill and submit forms

All runs are headless by default. Set BROWSER_HEADLESS=false in .env to watch.
─────────────────────────────────────────────────────────────────────────────
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("browser")

SCREENSHOTS_DIR = ROOT / "outputs" / "screenshots"
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

HEADLESS    = os.getenv("BROWSER_HEADLESS", "true").lower() != "false"
SLOW_MO     = int(os.getenv("BROWSER_SLOW_MO", "0"))       # ms between actions
TIMEOUT     = int(os.getenv("BROWSER_TIMEOUT", "30000"))    # ms page load timeout


# ─── Base Browser Context ─────────────────────────────────────────────────────

class BrowserSession:
    """
    Reusable async Playwright session.
    Use as an async context manager:
        async with BrowserSession() as b:
            page = await b.new_page()
    """

    def __init__(self, browser_type: str = "chromium"):
        self.browser_type = browser_type
        self._playwright  = None
        self._browser     = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        launcher = getattr(self._playwright, self.browser_type)
        self._browser = await launcher.launch(
            headless=HEADLESS,
            slow_mo=SLOW_MO,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        return self

    async def __aexit__(self, *_):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def new_page(self, stealth: bool = True):
        ctx = await self._browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = await ctx.new_page()
        page.set_default_timeout(TIMEOUT)
        if stealth:
            # Hide automation signals
            await page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
        return page


def _run(coro):
    """Run an async coroutine from sync code."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=120)
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ─── Screenshot Tool ──────────────────────────────────────────────────────────

async def _screenshot_async(url: str, filename: str = "") -> Path:
    async with BrowserSession() as b:
        page = await b.new_page()
        await page.goto(url, wait_until="networkidle")
        fname = filename or f"screenshot_{int(time.time())}.png"
        path  = SCREENSHOTS_DIR / fname
        await page.screenshot(path=str(path), full_page=True)
        logger.info(f"Screenshot saved: {path.name}")
        return path


def screenshot(url: str, filename: str = "") -> Path:
    """Take a full-page screenshot of any URL."""
    return _run(_screenshot_async(url, filename))


# ─── Page Scraper ─────────────────────────────────────────────────────────────

async def _scrape_async(url: str, selector: str = "", wait_for: str = "") -> Dict:
    async with BrowserSession() as b:
        page = await b.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        if wait_for:
            await page.wait_for_selector(wait_for, timeout=TIMEOUT)
        title   = await page.title()
        content = await page.inner_text("body") if not selector else await page.inner_text(selector)
        html    = await page.content()
        return {
            "url":     url,
            "title":   title,
            "text":    content[:5000],
            "html_len": len(html),
            "scraped_at": datetime.now().isoformat(),
        }


def scrape_page(url: str, selector: str = "", wait_for: str = "") -> Dict:
    """Scrape a JS-rendered page and return title + text content."""
    return _run(_scrape_async(url, selector, wait_for))


# ─── Twitter / X Auto-Poster ──────────────────────────────────────────────────

async def _post_twitter_async(tweets: List[str]) -> Dict:
    """
    Post a thread to Twitter/X using stored session cookies or credentials.
    Set in .env:
      TWITTER_EMAIL    — your X login email
      TWITTER_PASSWORD — your X password
    """
    email    = os.getenv("TWITTER_EMAIL", "")
    password = os.getenv("TWITTER_PASSWORD", "")
    if not email or not password:
        return {"status": "skipped", "reason": "TWITTER_EMAIL / TWITTER_PASSWORD not set in .env"}

    results = []
    async with BrowserSession() as b:
        page = await b.new_page(stealth=True)

        # ── Login ─────────────────────────────────────────────────────────────
        await page.goto("https://twitter.com/login")
        await page.wait_for_selector('input[autocomplete="username"]', timeout=15000)
        await page.fill('input[autocomplete="username"]', email)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(2000)

        # Handle "Enter your phone/username" challenge
        try:
            challenge = page.locator('input[data-testid="ocfEnterTextTextInput"]')
            if await challenge.is_visible():
                username = os.getenv("TWITTER_USERNAME", email.split("@")[0])
                await challenge.fill(username)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(1500)
        except Exception:
            pass

        await page.fill('input[name="password"]', password)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(3000)

        # ── Post first tweet ──────────────────────────────────────────────────
        await page.goto("https://twitter.com/compose/tweet")
        await page.wait_for_selector('[data-testid="tweetTextarea_0"]', timeout=15000)

        for i, tweet in enumerate(tweets[:10]):  # X thread limit
            if i == 0:
                box = page.locator('[data-testid="tweetTextarea_0"]')
            else:
                # Add tweet to thread
                await page.click('[data-testid="addButton"]')
                await page.wait_for_timeout(800)
                boxes = page.locator('[data-testid^="tweetTextarea_"]')
                box   = boxes.last

            await box.click()
            await box.fill(tweet[:280])
            await page.wait_for_timeout(500)
            results.append({"tweet": i + 1, "text": tweet[:60], "status": "queued"})

        # ── Submit ────────────────────────────────────────────────────────────
        await page.click('[data-testid="tweetButtonInline"]')
        await page.wait_for_timeout(3000)

        # Screenshot confirmation
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SCREENSHOTS_DIR / f"twitter_post_{ts}.png"
        await page.screenshot(path=str(path))

        logger.info(f"Twitter thread posted: {len(tweets)} tweets")
        return {
            "status":   "posted",
            "tweets":   len(tweets),
            "results":  results,
            "screenshot": str(path),
        }


def post_twitter_thread(tweets: List[str]) -> Dict:
    """Post a Twitter/X thread. Requires TWITTER_EMAIL + TWITTER_PASSWORD in .env."""
    return _run(_post_twitter_async(tweets))


# ─── LinkedIn Auto-Poster ─────────────────────────────────────────────────────

async def _post_linkedin_async(content: str) -> Dict:
    """
    Post to LinkedIn. Set in .env:
      LINKEDIN_EMAIL    — your LinkedIn email
      LINKEDIN_PASSWORD — your LinkedIn password
    """
    email    = os.getenv("LINKEDIN_EMAIL", "")
    password = os.getenv("LINKEDIN_PASSWORD", "")
    if not email or not password:
        return {"status": "skipped", "reason": "LINKEDIN_EMAIL / LINKEDIN_PASSWORD not set in .env"}

    async with BrowserSession() as b:
        page = await b.new_page(stealth=True)

        # ── Login ─────────────────────────────────────────────────────────────
        await page.goto("https://www.linkedin.com/login")
        await page.fill('#username', email)
        await page.fill('#password', password)
        await page.click('[type="submit"]')
        await page.wait_for_timeout(3000)

        # ── New post ──────────────────────────────────────────────────────────
        await page.goto("https://www.linkedin.com/feed/")
        await page.click('.share-box-feed-entry__trigger')
        await page.wait_for_selector('.ql-editor', timeout=10000)
        await page.fill('.ql-editor', content[:3000])
        await page.wait_for_timeout(1000)

        # Post it
        await page.click('[data-control-name="share.post"]')
        await page.wait_for_timeout(3000)

        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SCREENSHOTS_DIR / f"linkedin_post_{ts}.png"
        await page.screenshot(path=str(path))

        logger.info("LinkedIn post published")
        return {
            "status":     "posted",
            "chars":      len(content),
            "screenshot": str(path),
        }


def post_linkedin(content: str) -> Dict:
    """Post to LinkedIn. Requires LINKEDIN_EMAIL + LINKEDIN_PASSWORD in .env."""
    return _run(_post_linkedin_async(content))


# ─── CoinMarketCap Scraper ────────────────────────────────────────────────────

async def _scrape_crypto_async(coins: List[str] = None) -> Dict:
    """Scrape live prices + 24h change from CoinMarketCap (JS-rendered)."""
    async with BrowserSession() as b:
        page = await b.new_page()
        await page.goto("https://coinmarketcap.com/", wait_until="networkidle")
        await page.wait_for_selector("table", timeout=15000)

        rows = await page.query_selector_all("table tbody tr")
        prices = []
        for row in rows[:20]:
            try:
                cells = await row.query_selector_all("td")
                if len(cells) < 7:
                    continue
                name   = (await cells[2].inner_text()).strip().split("\n")[0]
                price  = (await cells[3].inner_text()).strip()
                change = (await cells[5].inner_text()).strip()
                prices.append({"name": name, "price": price, "change_24h": change})
            except Exception:
                continue

        logger.info(f"Scraped {len(prices)} coins from CoinMarketCap")
        return {
            "source":     "coinmarketcap",
            "prices":     prices,
            "scraped_at": datetime.now().isoformat(),
        }


def scrape_crypto_prices(coins: List[str] = None) -> Dict:
    """Scrape live crypto prices from CoinMarketCap."""
    return _run(_scrape_crypto_async(coins))


# ─── Google Trends Scraper ────────────────────────────────────────────────────

async def _scrape_trends_async(keywords: List[str] = None) -> Dict:
    """Scrape Google Trends for real-time trending searches."""
    async with BrowserSession() as b:
        page  = await b.new_page()
        url   = "https://trends.google.com/trending?geo=US&hours=24"
        await page.goto(url, wait_until="networkidle")
        await page.wait_for_timeout(3000)

        items = await page.query_selector_all(".mZ3RIc")
        trending = []
        for item in items[:20]:
            try:
                text = (await item.inner_text()).strip()
                if text:
                    trending.append(text)
            except Exception:
                continue

        logger.info(f"Scraped {len(trending)} trending topics from Google Trends")
        return {
            "source":     "google_trends_browser",
            "trending":   trending,
            "scraped_at": datetime.now().isoformat(),
        }


def scrape_google_trends() -> Dict:
    """Scrape Google Trends real-time trending topics."""
    return _run(_scrape_trends_async())


# ─── Form Submitter ───────────────────────────────────────────────────────────

async def _submit_form_async(url: str, fields: Dict[str, str], submit_selector: str) -> Dict:
    """Fill and submit any web form."""
    async with BrowserSession() as b:
        page = await b.new_page()
        await page.goto(url, wait_until="domcontentloaded")
        for selector, value in fields.items():
            await page.fill(selector, value)
            await page.wait_for_timeout(300)
        await page.click(submit_selector)
        await page.wait_for_timeout(2000)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SCREENSHOTS_DIR / f"form_submit_{ts}.png"
        await page.screenshot(path=str(path))
        return {"status": "submitted", "url": url, "screenshot": str(path)}


def submit_form(url: str, fields: Dict[str, str], submit_selector: str) -> Dict:
    """Fill and submit a web form. fields = {css_selector: value}."""
    return _run(_submit_form_async(url, fields, submit_selector))


# ─── Quick test ───────────────────────────────────────────────────────────────

def test_browser() -> Dict:
    """Quick smoke test — takes a screenshot of the landing page."""
    try:
        path = screenshot("http://localhost:5050/landing", "test_landing.png")
        return {"status": "ok", "screenshot": str(path)}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


# ─── Singleton convenience ────────────────────────────────────────────────────

_browser_available: Optional[bool] = None


def is_available() -> bool:
    """Check if Playwright browsers are installed and working."""
    global _browser_available
    if _browser_available is None:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                b.close()
            _browser_available = True
        except Exception:
            _browser_available = False
    return _browser_available
