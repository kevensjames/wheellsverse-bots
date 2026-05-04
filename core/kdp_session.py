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
