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


def execute_actions(url: str, actions: list[dict]) -> dict[str, Any]:
    """Envelope B: navigate to `url` and run a SEQUENCE of write actions
    (click/type/submit/select) in ONE ephemeral session, then return the final
    page state. Re-validates policy + the write kill-switch defensively, and
    validates every action type before launching. Stops at the first failure.

    Returns {"results": [{type, selector, ok, error?}], "final": {url,title,text}}.
    """
    url = config.check_url(url)  # enabled + scheme + ssrf + allowlist
    if not config.write_enabled():
        raise config.BrowserPolicyError(
            "browser writes are disabled (set KAI_BROWSER_WRITE_ENABLED=1)"
        )
    norm: list[dict[str, Any]] = []
    for a in actions or []:
        t = (str(a.get("type") or "")).strip().lower()
        if t not in config.WRITE_ACTION_TYPES:
            raise config.BrowserPolicyError(
                f"action type {t!r} not allowed — use {config.WRITE_ACTION_TYPES}"
            )
        norm.append({
            "type": t,
            "selector": (str(a.get("selector") or "")).strip(),
            "value": a.get("value"),
        })
    if not norm:
        raise config.BrowserPolicyError("no actions to execute")
    page_to = config.page_timeout_ms()
    overall_s = page_to / 1000 + len(norm) * (config.action_timeout_ms() / 1000) + 5
    return _run_in_thread(_execute_sync, (url, norm, page_to), overall_s)


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


def _install_guard(page, allow, blocked: list[dict]) -> None:
    """Envelope-B v2 runtime guard: intercept every request and abort
    off-allowlist MAIN-FRAME navigations + any private-IP/SSRF request. Blocked
    navigations are recorded in `blocked` so the result can report them. Install
    BEFORE goto so the entry load + its redirects + sub-resources are all guarded.
    """
    def _handler(route, request):
        try:
            try:
                is_nav = request.is_navigation_request() and request.frame == page.main_frame
            except Exception:
                is_nav = False
            reason = config.request_blocked_reason(request.url, allow=allow, is_main_nav=is_nav)
            if reason is not None:
                if is_nav:
                    blocked.append({"url": request.url, "reason": reason})
                route.abort()
                return
            route.continue_()
        except Exception:  # pragma: no cover - never let the guard wedge a page
            try:
                route.continue_()
            except Exception:
                pass

    page.route("**/*", _handler)


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
                blocked: list[dict] = []
                _install_guard(page, config.allowlist(), blocked)
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
                return {"url": page.url, "title": title, "text": text,
                        "links": links, "blocked_navigations": blocked}
            finally:
                browser.close()
    except BrowserUnavailable:
        raise
    except Exception as e:
        raise BrowserUnavailable(f"navigation failed: {e}")


def _execute_sync(url: str, actions: list[dict], page_timeout_ms: int) -> dict[str, Any]:
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
                blocked: list[dict] = []
                _install_guard(page, config.allowlist(), blocked)
                page.goto(url, wait_until="domcontentloaded", timeout=page_timeout_ms)
                results: list[dict[str, Any]] = []
                for a in actions:
                    rec = {"type": a["type"], "selector": a["selector"]}
                    try:
                        _perform(page, a)
                        rec["ok"] = True
                    except Exception as e:
                        rec["ok"] = False
                        rec["error"] = str(e)[:300]
                        results.append(rec)
                        break  # stop at first failure — don't barrel through a broken flow
                    results.append(rec)
                try:
                    final = {
                        "url": page.url, "title": page.title(),
                        "text": page.inner_text("body")[: config.MAX_TEXT_CHARS],
                    }
                except Exception:
                    final = {"url": page.url, "title": "", "text": ""}
                return {"results": results, "final": final,
                        "blocked_navigations": blocked}
            finally:
                browser.close()
    except BrowserUnavailable:
        raise
    except Exception as e:
        raise BrowserUnavailable(f"execute failed: {e}")


def _perform(page, action: dict) -> None:
    """Run one validated action against the live page."""
    t, selector, value = action["type"], action["selector"], action.get("value")
    if not selector:
        raise ValueError(f"{t} requires a selector")
    if t == "type":
        page.fill(selector, "" if value is None else str(value))
    elif t == "select":
        page.select_option(selector, "" if value is None else str(value))
    elif t in ("click", "submit"):
        page.click(selector)
    else:  # pragma: no cover - guarded earlier
        raise ValueError(f"unknown action type {t}")


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
                _install_guard(page, config.allowlist(), [])
                page.goto(url, wait_until="domcontentloaded", timeout=page_timeout_ms)
                page.screenshot(path=out_path, full_page=True)
                return out_path
            finally:
                browser.close()
    except BrowserUnavailable:
        raise
    except Exception as e:
        raise BrowserUnavailable(f"screenshot failed: {e}")
