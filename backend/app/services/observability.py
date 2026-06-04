"""Operator-side observability: fire-and-forget Telegram alerts.

Hooked into the user-lifecycle events that the operator cares about during
the first weeks of paid traffic:

  - signup      → "🎉 New signup"        (auth.py after Supabase create_user)
  - paid        → "💰 New paid sub"       (billing.py _handle_checkout_completed)
  - canceled    → "❌ Sub canceled"        (billing.py _handle_sub_deleted)
  - payment-fail→ "⚠️ Payment failed"      (billing.py _handle_payment_failed)

Design notes
------------
- Fail-OPEN. If Telegram is unreachable, we log a warning and proceed.
  An alert outage must never block a paid-signup webhook from completing.
- Uses urllib (stdlib) — zero extra dependency, no async event loop conflict
  with FastAPI's sync request handlers.
- Runs in a daemon thread so the request doesn't block on Telegram's API
  (200-800ms round trip otherwise).
- Settings.TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID empty → silent no-op,
  so this module is safe to import in tests / local dev without TG set up.
"""
from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.request

from app.config import settings

logger = logging.getLogger(__name__)


def _send_sync(text: str) -> None:
    """Blocking send. Called from a background thread by notify()."""
    tok = settings.TELEGRAM_BOT_TOKEN
    chat = settings.TELEGRAM_CHAT_ID
    if not tok or not chat:
        return
    body = json.dumps({
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{tok}/sendMessage",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            if r.status >= 300:
                logger.warning("telegram alert non-2xx: %s", r.status)
    except urllib.error.HTTPError as e:
        logger.warning("telegram alert HTTP %s: %s", e.code, e.read()[:200])
    except Exception as e:  # network failure, DNS, etc. — never crash caller
        logger.warning("telegram alert failed: %s", e)


def notify(text: str) -> None:
    """Fire a Telegram alert in the background. Returns immediately."""
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    threading.Thread(target=_send_sync, args=(text,), daemon=True).start()


# ── Event-shaped helpers (keep call sites uncluttered) ─────────────────────


def alert_signup(email: str) -> None:
    notify(f"🎉 <b>New KAI signup</b>\n{_html_escape(email)}")


def alert_paid(email: str, tier: str, stripe_sub_id: str) -> None:
    notify(
        f"💰 <b>New paid sub</b>\n"
        f"tier: <b>{_html_escape(tier)}</b>\n"
        f"user: {_html_escape(email)}\n"
        f"stripe: <code>{_html_escape(stripe_sub_id)}</code>"
    )


def alert_canceled(email: str, stripe_sub_id: str) -> None:
    notify(
        f"❌ <b>Sub canceled</b>\n"
        f"user: {_html_escape(email)}\n"
        f"stripe: <code>{_html_escape(stripe_sub_id)}</code>"
    )


def alert_payment_failed(email: str, stripe_sub_id: str) -> None:
    notify(
        f"⚠️ <b>Payment failed</b>\n"
        f"user: {_html_escape(email)}\n"
        f"stripe: <code>{_html_escape(stripe_sub_id)}</code>"
    )


def _html_escape(s: str) -> str:
    """Telegram HTML parse_mode needs &<> escaped to avoid breaking the
    message on email addresses with special chars."""
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
