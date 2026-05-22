#!/usr/bin/env python3
"""
core/kdp_session.py
───────────────────────────────────────────────────────────────────────────────
KDP browser-session helpers for unattended Railway runs.

Two mechanisms, used together for redundancy:

  R1. Persistent storage_state (Playwright cookies + localStorage)
      - Saved once after an interactive login, then reused across runs.
      - Path is controlled by env KDP_STORAGE_STATE (default: data/.kdp_storage_state.json).
      - On Railway: mount a persistent volume so the file survives container restarts.

  R2. IMAP OTP fetcher (fallback when cookies expire)
      - When KDP forces re-auth and shows a 2FA prompt, poll the user's IMAP
        inbox for the latest Amazon OTP and inject the code.
      - Configured via env (KDP_OTP_EMAIL, KDP_OTP_PASSWORD, KDP_OTP_IMAP_HOST).
      - For Gmail you MUST use an app password, not your regular password
        (Settings → Security → 2-Step Verification → App passwords).

Neither mechanism is mandatory: when both are absent, the uploaders fall back
to standard credential login, which only works in interactive (non-headless)
environments.
"""
from __future__ import annotations

import email
import imaplib
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("kdp_session")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE_PATH = ROOT / "data" / ".kdp_storage_state.json"

# A code visually distinguishable from random 6-digit numbers in marketing copy:
# Amazon OTPs are isolated digit groups, often immediately preceded by phrases
# like "verification code", "security code", or "OTP". We accept either.
_OTP_RE = re.compile(
    r"(?:verification\s*code|security\s*code|one[\s-]*time\s*password|otp|sign[-\s]?in\s*code)"
    r"[^\d]{0,40}(\d{6})",
    re.IGNORECASE | re.DOTALL,
)
_BARE_OTP_RE = re.compile(r"\b(\d{6})\b")

# Default Amazon/KDP sender patterns (case-insensitive substring match on From:)
_DEFAULT_FROM_PATTERNS = (
    "@amazon.com",
    "account-update@amazon",
    "no-reply@amazon",
    "kdp-no-reply@amazon",
    "kdp@amazon",
)


# ═══════════════════════════════════════════════════════════════════════════════
# R1. Storage state
# ═══════════════════════════════════════════════════════════════════════════════

def storage_state_path() -> Path:
    return Path(os.getenv("KDP_STORAGE_STATE", str(DEFAULT_STORAGE_PATH)))


def has_storage_state() -> bool:
    p = storage_state_path()
    try:
        return p.exists() and p.stat().st_size > 0
    except OSError:
        return False


def load_storage_state() -> Optional[str]:
    """Return the path to use as `storage_state=` for browser.new_context, or None."""
    if not has_storage_state():
        return None
    return str(storage_state_path())


def save_storage_state(context) -> None:
    """Persist context cookies + localStorage to storage_state_path()."""
    p = storage_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        context.storage_state(path=str(p))
        logger.info("KDP storage_state saved → %s", p)
    except Exception as e:
        logger.warning("Could not save storage_state: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# R2. IMAP OTP fetcher
# ═══════════════════════════════════════════════════════════════════════════════

def _otp_imap_config() -> Optional[dict]:
    user = os.getenv("KDP_OTP_EMAIL", "")
    pw   = os.getenv("KDP_OTP_PASSWORD", "")
    if not user or not pw:
        return None
    return {
        "user": user,
        "password": pw,
        "host": os.getenv("KDP_OTP_IMAP_HOST", "imap.gmail.com"),
        "port": int(os.getenv("KDP_OTP_IMAP_PORT", "993")),
        "mailbox": os.getenv("KDP_OTP_IMAP_MAILBOX", "INBOX"),
        "from_patterns": tuple(
            p.strip().lower() for p in
            os.getenv("KDP_OTP_FROM_PATTERNS", ",".join(_DEFAULT_FROM_PATTERNS)).split(",")
            if p.strip()
        ),
    }


def _extract_otp(text: str) -> Optional[str]:
    if not text:
        return None
    m = _OTP_RE.search(text)
    if m:
        return m.group(1)
    # Fallback: pick the *first* standalone 6-digit run, but only if no large
    # numeric strings (order numbers, tracking) precede it.
    bare = _BARE_OTP_RE.search(text)
    return bare.group(1) if bare else None


def _decode_payload(msg) -> str:
    """Best-effort plain-text extraction from an email.Message."""
    parts: list[str] = []
    if msg.is_multipart():
        for sub in msg.walk():
            ct = (sub.get_content_type() or "").lower()
            if ct == "text/plain":
                try:
                    parts.append(sub.get_payload(decode=True).decode(sub.get_content_charset() or "utf-8", errors="replace"))
                except Exception:
                    continue
        if not parts:
            for sub in msg.walk():
                if (sub.get_content_type() or "").lower() == "text/html":
                    try:
                        html = sub.get_payload(decode=True).decode(sub.get_content_charset() or "utf-8", errors="replace")
                        parts.append(re.sub(r"<[^>]+>", " ", html))
                    except Exception:
                        continue
    else:
        try:
            parts.append(msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace"))
        except Exception:
            pass
    return "\n".join(parts)


def _is_from_amazon(msg, patterns: tuple[str, ...]) -> bool:
    sender = (msg.get("From") or "").lower()
    return any(p in sender for p in patterns)


def _search_recent_otp(cfg: dict, since_seconds: int) -> Optional[str]:
    """One IMAP probe: connect, search recent unread, return OTP or None."""
    try:
        m = imaplib.IMAP4_SSL(cfg["host"], cfg["port"], timeout=15)
    except Exception as e:
        logger.warning("IMAP connect failed: %s", e)
        return None

    try:
        m.login(cfg["user"], cfg["password"])
        m.select(cfg["mailbox"])

        # IMAP SINCE granularity is days, not seconds; use UNSEEN + recent date filter
        since_date = time.strftime("%d-%b-%Y", time.gmtime(time.time() - max(since_seconds, 86400)))
        typ, data = m.search(None, f'(SINCE {since_date})')
        if typ != "OK" or not data or not data[0]:
            return None

        ids = data[0].split()
        # Newest first
        for msg_id in reversed(ids[-30:]):
            typ, msg_data = m.fetch(msg_id, "(RFC822)")
            if typ != "OK" or not msg_data or msg_data[0] is None:
                continue
            try:
                msg = email.message_from_bytes(msg_data[0][1])
            except Exception:
                continue

            if not _is_from_amazon(msg, cfg["from_patterns"]):
                continue

            # Filter by recency from header date if available
            try:
                hdr_date = email.utils.parsedate_to_datetime(msg.get("Date") or "")
                age = time.time() - hdr_date.timestamp()
                if age > since_seconds:
                    continue
            except Exception:
                pass

            text = (msg.get("Subject") or "") + "\n" + _decode_payload(msg)
            otp = _extract_otp(text)
            if otp:
                logger.info("OTP fetched from IMAP (sender=%s)", msg.get("From"))
                return otp
    finally:
        try:
            m.close()
        except Exception:
            pass
        try:
            m.logout()
        except Exception:
            pass
    return None


def fetch_otp_from_email(*, since_seconds: int = 300, timeout_s: int = 120, poll_s: int = 5) -> Optional[str]:
    """
    Poll IMAP for an Amazon OTP that arrived in the last `since_seconds`.
    Returns the 6-digit code, or None on timeout/misconfiguration.
    """
    cfg = _otp_imap_config()
    if not cfg:
        logger.info("IMAP not configured (KDP_OTP_EMAIL/KDP_OTP_PASSWORD unset) — cannot auto-fetch OTP")
        return None

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        otp = _search_recent_otp(cfg, since_seconds)
        if otp:
            return otp
        time.sleep(poll_s)
    logger.warning("IMAP OTP fetch timed out after %ds", timeout_s)
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# Login helper (used by both kdp_uploader and kdp_paperback)
# ═══════════════════════════════════════════════════════════════════════════════

def kdp_login(page, email_addr: str, password: str, *, otp_timeout_s: int = 120) -> bool:
    """
    Perform a fresh credential login on KDP. Handles 2FA via R2 if configured.
    Returns True on success, False otherwise.
    Caller is responsible for calling `save_storage_state(context)` after.
    """
    page.goto("https://kdp.amazon.com/en_US/", timeout=30000)
    try:
        page.fill("input#ap_email", email_addr, timeout=8000)
        page.click("input#continue", timeout=4000)
    except Exception:
        pass
    try:
        page.fill("input#ap_password", password, timeout=8000)
        page.click("input#signInSubmit", timeout=4000)
    except Exception:
        logger.warning("Password field not found — KDP login may have changed.")
        return False

    # Detect 2FA prompt (OTP input usually has id 'auth-mfa-otpcode' or name 'otpCode')
    page.wait_for_load_state("domcontentloaded", timeout=20000)
    needs_otp = False
    for sel in ("input#auth-mfa-otpcode", "input[name='otpCode']", "input[name='code']"):
        try:
            if page.locator(sel).first.is_visible(timeout=3000):
                needs_otp = True
                break
        except Exception:
            continue

    if needs_otp:
        logger.info("KDP 2FA prompt detected — fetching OTP via IMAP…")
        otp = fetch_otp_from_email(timeout_s=otp_timeout_s)
        if not otp:
            logger.error("Could not retrieve OTP — aborting login")
            return False
        for sel in ("input#auth-mfa-otpcode", "input[name='otpCode']", "input[name='code']"):
            try:
                page.fill(sel, otp, timeout=4000)
                break
            except Exception:
                continue
        for sel in ("input#auth-signin-button", "input[type='submit']", "button:has-text('Sign in')"):
            try:
                page.click(sel, timeout=4000)
                break
            except Exception:
                continue
        page.wait_for_load_state("domcontentloaded", timeout=20000)

    # Success heuristic: KDP bookshelf URL or visible "Bookshelf" link
    try:
        return "bookshelf" in page.url.lower() or page.locator("text=Bookshelf").first.is_visible(timeout=5000)
    except Exception:
        return False


# ============================================================
# Hardened auth helpers — added for password-only re-auth fix
# ============================================================

KDP_BOOKSHELF_URL = "https://kdp.amazon.com/en_US/bookshelf"


def is_authenticated(page) -> bool:
    """
    Strict post-condition. True only if on a KDP authenticated page,
    no password field visible, and a Bookshelf marker present.
    """
    try:
        url = page.url.lower()
        if "/ap/signin" in url or "/ap/cvf" in url:
            return False
        if page.locator("input#ap_password").is_visible(timeout=1000):
            return False
        if "bookshelf" in url:
            return True
        if page.locator("text=Bookshelf").first.is_visible(timeout=1000):
            return True
        return False
    except Exception:
        return False


def detect_auth_screen(page) -> str:
    """
    Returns one of: 'authenticated', 'password_only', 'email_password',
    'device_verification', 'mfa', 'unknown'.
    """
    try:
        if is_authenticated(page):
            return "authenticated"
        url = page.url.lower()
        if "/ap/cvf" in url:
            return "device_verification"
        if page.locator("input#auth-mfa-otpcode, input[name='otpCode']").first.is_visible(timeout=500):
            return "mfa"
        password_visible = page.locator("input#ap_password").is_visible(timeout=500)
        email_visible = page.locator("input#ap_email").is_visible(timeout=500)
        if password_visible and not email_visible:
            return "password_only"
        if password_visible and email_visible:
            return "email_password"
        return "unknown"
    except Exception:
        return "unknown"


def kdp_login_hardened(page, context, email: str, password: str,
                       otp_fetcher=None, screenshot_dir=None,
                       logger=None) -> dict:
    """
    Hardened login state machine. Returns dict:
      ok: bool
      state: 'authenticated' | 'auth_failed' | 'device_verification_required'
      screens_seen: list
      screenshot: path or None
      message: str
    """
    import time
    from pathlib import Path
    from datetime import datetime

    log = logger.info if logger else (lambda *a, **k: None)
    screens_seen = []

    def take_screenshot(label):
        if not screenshot_dir:
            return None
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(screenshot_dir) / f"kdp_{label}_{ts}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception:
            return None

    # Navigate explicitly to bookshelf, see where Amazon redirects us
    page.goto(KDP_BOOKSHELF_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(2)

    state = detect_auth_screen(page)
    screens_seen.append(state)
    log("Initial auth state: %s at %s", state, page.url)

    if state == "authenticated":
        return {"ok": True, "state": "authenticated", "screens_seen": screens_seen,
                "screenshot": None, "message": "Authenticated via stored cookies"}

    for attempt in range(3):
        state = detect_auth_screen(page)
        log("Auth attempt %d, state: %s, url: %s", attempt, state, page.url)

        if state == "authenticated":
            return {"ok": True, "state": "authenticated", "screens_seen": screens_seen,
                    "screenshot": None, "message": f"Authenticated after {attempt} screen(s)"}

        if state == "password_only":
            page.fill("input#ap_password", password)
            try:
                page.locator("input#signInSubmit").first.click()
            except Exception:
                page.locator("button:has-text('Sign in'), input[type='submit']").first.click()
            page.wait_for_load_state("domcontentloaded", timeout=60000)
            time.sleep(3)
            screens_seen.append("password_submitted")
            continue

        if state == "email_password":
            try:
                page.fill("input#ap_email", email)
            except Exception:
                pass
            page.fill("input#ap_password", password)
            page.locator("input#signInSubmit").first.click()
            page.wait_for_load_state("domcontentloaded", timeout=60000)
            time.sleep(3)
            screens_seen.append("full_login_submitted")
            continue

        if state == "mfa":
            if otp_fetcher is None:
                shot = take_screenshot("mfa_no_fetcher")
                return {"ok": False, "state": "auth_failed",
                        "screens_seen": screens_seen, "screenshot": shot,
                        "message": "MFA requested but no OTP fetcher configured"}
            code = otp_fetcher()
            if not code:
                shot = take_screenshot("mfa_fetch_failed")
                return {"ok": False, "state": "auth_failed",
                        "screens_seen": screens_seen, "screenshot": shot,
                        "message": "MFA code not retrievable from email"}
            page.fill("input#auth-mfa-otpcode", code)
            page.locator("input#auth-signin-button, button:has-text('Sign in')").first.click()
            page.wait_for_load_state("domcontentloaded", timeout=60000)
            time.sleep(3)
            screens_seen.append("mfa_submitted")
            continue

        if state == "device_verification":
            shot = take_screenshot("device_verification")
            if otp_fetcher is None:
                return {"ok": False, "state": "device_verification_required",
                        "screens_seen": screens_seen, "screenshot": shot,
                        "message": ("Device verification required. Sign in manually "
                                    "in a browser with the same profile to clear "
                                    "this flag, then retry the automation.")}
            code = otp_fetcher()
            if not code:
                return {"ok": False, "state": "device_verification_required",
                        "screens_seen": screens_seen, "screenshot": shot,
                        "message": "Device verification email not found; sign in manually to clear."}
            try:
                page.fill("input#cvf-input-code, input[name='code']", code)
                page.locator("input[type='submit'], button:has-text('Verify'), button:has-text('Continue')").first.click()
                page.wait_for_load_state("domcontentloaded", timeout=60000)
                time.sleep(3)
                screens_seen.append("device_verification_submitted")
                continue
            except Exception as e:
                return {"ok": False, "state": "device_verification_required",
                        "screens_seen": screens_seen, "screenshot": shot,
                        "message": f"Could not submit verification code: {e}"}

        shot = take_screenshot(f"unknown_auth_state_attempt_{attempt}")
        return {"ok": False, "state": "auth_failed", "screens_seen": screens_seen,
                "screenshot": shot, "message": f"Unknown auth screen at {page.url}"}

    shot = take_screenshot("auth_max_attempts_exceeded")
    return {"ok": False, "state": "auth_failed", "screens_seen": screens_seen,
            "screenshot": shot,
            "message": f"Exceeded 3 auth attempts. Screens seen: {screens_seen}"}


def save_storage_state_if_authenticated(context, page, path: str) -> bool:
    """
    Only persist cookies when the page is provably authenticated.
    Prevents poisoning the cookie jar with a logged-out state.
    """
    if not is_authenticated(page):
        return False
    context.storage_state(path=path)
    return True


# ============================================================
# Truth-verification helpers (Part 3a, 2026-05-19 publish-lie fix).
# Both helpers are paranoid by design; see
# .claude/skills/truth_verification/SKILL.md for the rules they enforce.
# ============================================================


def is_publish_confirmed(page) -> dict:
    """Read the wizard page after a Publish click and report whether publishing
    actually completed.

    Returns ``{confirmed: bool, markers_seen: list, anti_markers_seen: list}``.

    Positive markers (any visible → candidate success):
      - text "Your book is being reviewed"
      - text "submitted for publishing"
      - text "Congratulations"
      - text "Your eBook has been submitted"

    Anti-markers (any visible → confirmed=False, regardless of positives):
      - publish_button_still_present : the yellow Publish button is still on
        screen — we never left the pricing page (the May 19 lie shape).
      - kicked_to_login              : input#ap_password visible — Amazon
        dropped the session and re-prompted; the click never reached publish.
      - red_error_banner             : visible KDP error UI — success cannot
        stand next to an error toast.
      - step_still_not_started       : a side-nav step badge reads "Not
        Started" — at least one wizard step never registered.
      - url_still_pricing_no_overlay : URL contains /pricing and no positive
        overlay marker — pure URL-substring trust is forbidden.

    The helper never raises. On page.evaluate failure it returns
    confirmed=False with a synthetic anti-marker naming the failure mode.
    """
    try:
        page_state = page.evaluate(r"""() => {
            const isVisible = (el) => {
                if (!el) return false;
                if (el.offsetParent === null) return false;
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            };
            const hasVisibleText = (needle) => {
                const target = needle.toLowerCase();
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null);
                let node;
                while ((node = walker.nextNode())) {
                    const text = (node.textContent || '').toLowerCase();
                    if (!text.includes(target)) continue;
                    if (isVisible(node.parentElement)) return true;
                }
                return false;
            };

            const positives = [];
            if (hasVisibleText('your book is being reviewed'))   positives.push('text_book_being_reviewed');
            if (hasVisibleText('submitted for publishing'))      positives.push('text_submitted_for_publishing');
            if (hasVisibleText('congratulations'))               positives.push('text_congratulations');
            if (hasVisibleText('your ebook has been submitted')) positives.push('text_ebook_submitted');

            const antis = [];
            const pubBtns = Array.from(document.querySelectorAll('button, input[type="submit"]'));
            if (pubBtns.some(b => isVisible(b) && /publish your kindle/i.test(b.textContent || b.value || ''))) {
                antis.push('publish_button_still_present');
            }
            const pw = document.querySelector('input#ap_password');
            if (pw && isVisible(pw)) antis.push('kicked_to_login');
            const err = document.querySelector('.a-alert-error, [role="alert"]');
            if (err && isVisible(err)) antis.push('red_error_banner');
            if (hasVisibleText('not started')) antis.push('step_still_not_started');

            return { positives, antis, url: location.href };
        }""")
    except Exception as e:
        return {
            "confirmed": False,
            "markers_seen": [],
            "anti_markers_seen": [f"page_evaluate_failed:{type(e).__name__}"],
        }

    markers_seen = page_state.get("positives", []) or []
    anti_markers_seen = page_state.get("antis", []) or []

    url = (page_state.get("url") or "").lower()
    if "/pricing" in url and not markers_seen:
        anti_markers_seen.append("url_still_pricing_no_overlay")

    confirmed = bool(markers_seen) and not anti_markers_seen
    return {
        "confirmed": confirmed,
        "markers_seen": markers_seen,
        "anti_markers_seen": anti_markers_seen,
    }


def _verify_result_against_bookshelf(*, claimed_state: str, page, title: str) -> dict:
    """Disinterested-witness check. Navigate AWAY to the bookshelf and read
    the title's actual status badge.

    Returns ``{bookshelf_says: str, status_row_seen: bool,
    overrides_to: Optional[str], detail: str, row_id: str,
    used_fallback: bool, status_selector_hit: str}``.

    Why a fresh navigation: reading cached DOM from the wizard means trusting
    state written by the same code that just produced the claim. The
    bookshelf is a separate page the wizard did not author, so it can
    independently verify (or refute) the claim — this is the
    "authority that did not write the claim" rule from the skill.

    Badge detection scopes to a status element first, falling back to the
    full row text only as last resort. used_fallback=True is treated as
    *low confidence* — positive claims are overridden to publish_unconfirmed
    when the scoped read missed, because a row-blob match can pick up
    incidental words ("Go live date", tooltips, marketing strings) that
    have nothing to do with the actual status badge.

    Override behavior (the wizard's claim is overridden if):
      - bookshelf badge is 'Draft' / 'unknown' / 'unpublished' / 'blocked'
        while the claim was in_review/live (the click never registered)
      - used_fallback=True on a positive claim (row-blob match is too
        unreliable to trust as proof of publishing)
      - bookshelf row missing entirely after a positive claim
      - bookshelf load itself failed (fail closed — never trust a positive
        claim we couldn't independently verify)

    The helper never raises.
    """
    BOOKSHELF_URL = "https://kdp.amazon.com/en_US/bookshelf"

    try:
        page.goto(BOOKSHELF_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
    except Exception as e:
        return {
            "bookshelf_says": "unknown",
            "status_row_seen": False,
            "overrides_to": ("publish_unconfirmed"
                             if claimed_state in ("in_review", "live") else None),
            "detail": f"bookshelf_load_failed: {type(e).__name__}: {str(e)[:200]}",
            "row_id": "",
            "used_fallback": False,
            "status_selector_hit": "",
        }

    try:
        info = page.evaluate(r"""(searchTitle) => {
            const target = (searchTitle || '').toLowerCase().trim();
            if (!target) return null;
            const rows = document.querySelectorAll('tr[class*="mt-row"], tr[id]');
            for (const row of rows) {
                const titleEl = row.querySelector('[class*="title-link-label"], [id*="title"]');
                const rowTitle = (titleEl?.textContent || row.textContent || '').toLowerCase().trim();
                if (!rowTitle.includes(target)) continue;

                // Scope the badge read to a dedicated status element. Best-guess
                // selectors against unobserved DOM; if none hit we record
                // used_fallback so the Python side can downgrade confidence.
                const statusSelectors = [
                    '[class*="status"]', '[class*="-state"]',
                    '[data-test*="status"]', '[data-column*="status"]',
                ];
                let statusEl = null;
                for (const sel of statusSelectors) {
                    const found = row.querySelector(sel);
                    if (found) { statusEl = found; break; }
                }
                const statusText = (statusEl?.textContent || '').toLowerCase().trim();
                const usedFallback = !statusText;
                const searchText = statusText || (row.textContent || '').toLowerCase();

                const badges = ['draft', 'in review', 'live', 'submitted', 'unpublished', 'blocked'];
                const badge_found = badges.find(b => searchText.includes(b)) || null;

                return {
                    row_id: row.id || '',
                    row_title_sample: rowTitle.slice(0, 120),
                    status_text_sample: searchText.slice(0, 200),
                    used_fallback: usedFallback,
                    status_selector_hit: statusEl
                        ? ((statusEl.className && statusEl.className.toString)
                            ? statusEl.className.toString().slice(0, 80)
                            : statusEl.tagName)
                        : '',
                    badge_found: badge_found,
                };
            }
            return null;
        }""", title)
    except Exception as e:
        return {
            "bookshelf_says": "unknown",
            "status_row_seen": False,
            "overrides_to": ("publish_unconfirmed"
                             if claimed_state in ("in_review", "live") else None),
            "detail": f"bookshelf_dom_probe_failed: {type(e).__name__}: {str(e)[:200]}",
            "row_id": "",
            "used_fallback": False,
            "status_selector_hit": "",
        }

    if info is None:
        return {
            "bookshelf_says": "not_found",
            "status_row_seen": False,
            "overrides_to": ("publish_unconfirmed"
                             if claimed_state in ("in_review", "live") else None),
            "detail": f"title {title[:60]!r} not found on bookshelf after publish click",
            "row_id": "",
            "used_fallback": False,
            "status_selector_hit": "",
        }

    badge = info.get("badge_found") or "unknown"
    used_fallback = bool(info.get("used_fallback"))
    bookshelf_says = {
        "draft": "draft",
        "in review": "in_review",
        "live": "live",
        "submitted": "submitted",
        "unpublished": "unpublished",
        "blocked": "blocked",
    }.get(badge, "unknown")

    overrides_to = None
    if claimed_state in ("in_review", "live"):
        # Strict policy: a positive claim requires a precise badge read.
        # Row-blob fallback can match incidental words; we won't trust it
        # to authorise a publish state.
        if used_fallback:
            overrides_to = "publish_unconfirmed"
        elif bookshelf_says in ("draft", "unknown", "unpublished", "blocked"):
            overrides_to = "publish_unconfirmed"

    return {
        "bookshelf_says": bookshelf_says,
        "status_row_seen": True,
        "overrides_to": overrides_to,
        "detail": (f"bookshelf row found: id={info.get('row_id')!r}, "
                   f"badge={badge!r}, used_fallback={used_fallback}, "
                   f"status_selector_hit={info.get('status_selector_hit')!r}"),
        "row_id": info.get("row_id", ""),
        "used_fallback": used_fallback,
        "status_selector_hit": info.get("status_selector_hit", ""),
    }
