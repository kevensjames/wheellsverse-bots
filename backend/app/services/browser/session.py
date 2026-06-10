"""Hardened browser session — the ONLY place Playwright actually runs.

Read-only by design (envelope A): navigate + extract text/links + screenshot.
No clicks, no typing, no form submits, no downloads.

Why a worker thread: the daemon is async (uvicorn). Playwright's sync API
refuses to run inside a running asyncio loop, so each op runs in a fresh
ThreadPoolExecutor thread (no loop there) with its own sync_playwright and a
hard wall-clock timeout. A wedged page dies with the thread; it can't take
down the daemon.

Isolation: plain launch() + new_context() gives an EPHEMERAL context — no
persistent user-data-dir, no saved cookies, no real Chrome profile. Nothing
from the operator's logged-in sessions (or the bots' cookies in
core/browser.py) is ever loaded.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any

from app.services.browser import config

logger = logging.getLogger(__name__)

_LAUNCH_ARGS = ["--no-sandbox", "--disable-dev-shm-usage"]


class BrowserUnavailable(Exception):
    """Playwright/chromium missing, navigation timed out, or the page errored.
    Message is operator-safe."""


def read_page(url: str) -> dict[str, Any]:
    """Navigate to `url` (re-validated against policy) and return
    {url, title, text, links}. Runs in an isolated worker thread + timeout."""
    url = config.check_url(url)  # defensive re-check — never trust the caller
    page_to = config.page_timeout_ms()
    overall_s = page_to / 1000 + 5
    return _run_in_thread(_read_sync, (url, page_to), overall_s)


def screenshot(url: str, out_path: str) -> str:
    """Navigate to `url` and save a full-page screenshot to out_path. Returns
    the path. Read-only (no interaction)."""
    url = config.check_url(url)
    page_to = config.page_timeout_ms()
    overall_s = page_to / 1000 + 5
    return _run_in_thread(_screenshot_sync, (url, out_path, page_to), overall_s)


# ─── internals (run inside the worker thread) ───────────────────────


def _run_in_thread(fn, args, overall_s):
    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(fn, *args)
        try:
            return fut.result(timeout=overall_s)
        except FuturesTimeout:
            raise BrowserUnavailable(f"browser op timed out after {overall_s:.0f}s")


def _launch(p):
    return p.chromium.launch(headless=config.headless(), args=_LAUNCH_ARGS)


def _read_sync(url: str, page_timeout_ms: int) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise BrowserUnavailable(f"playwright not available: {e}")
    try:
        with sync_playwright() as p:
            browser = _launch(p)
            try:
                ctx = browser.new_context()  # ephemeral — no profile, no cookies
                ctx.set_default_timeout(config.action_timeout_ms())
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=page_timeout_ms)
                title = page.title()
                try:
                    text = page.inner_text("body")[: config.MAX_TEXT_CHARS]
                except Exception:
                    text = ""
                try:
                    links = page.eval_on_selector_all(
                        "a[href]",
                        "els => els.slice(0,30).map(e => ({"
                        "text: (e.innerText||'').trim().slice(0,80), href: e.href}))",
                    )
                except Exception:
                    links = []
                return {"url": page.url, "title": title, "text": text, "links": links}
            finally:
                browser.close()
    except BrowserUnavailable:
        raise
    except Exception as e:
        raise BrowserUnavailable(f"navigation failed: {e}")


def _screenshot_sync(url: str, out_path: str, page_timeout_ms: int) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        raise BrowserUnavailable(f"playwright not available: {e}")
    try:
        with sync_playwright() as p:
            browser = _launch(p)
            try:
                ctx = browser.new_context()
                ctx.set_default_timeout(config.action_timeout_ms())
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=page_timeout_ms)
                page.screenshot(path=out_path, full_page=True)
                return out_path
            finally:
                browser.close()
    except BrowserUnavailable:
        raise
    except Exception as e:
        raise BrowserUnavailable(f"screenshot failed: {e}")
