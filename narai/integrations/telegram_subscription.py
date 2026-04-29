"""Telegram private-group subscription bridge.

Flow:
  1. POST /api/v2/narai/telegram/subscription/checkout
       → mints a pairing_token, creates a Stripe checkout session whose
         metadata.tg_pairing_token == the token. Returns {checkout_url, deep_link}.
  2. User pays. Stripe POSTs checkout.session.completed →
     handle_checkout_completed() promotes the row to status='pending_pair'.
  3. Stripe success page deep-links to t.me/<bot>?start=<pairing_token>.
  4. Telegram /start <token> → telegram bot calls begin_pairing()+finalize_pairing().
     finalize_pairing() persists the user_id, channel, and the single-use invite
     link the bot just minted via Bot API.
  5. customer.subscription.deleted → revoke_for_subscription() flips the row
     to 'revoked' and the caller kicks the user off the channel.

Stripe sends `customer.subscription.deleted` only after the cancelled period
ends, so the "grace until period_end" behaviour is implicit — we just kick on
deletion. Failed-payment cancellations also surface here.
"""
from __future__ import annotations

import logging
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

logger = logging.getLogger("narai.telegram.subscription")

PAIRING_TOKEN_TTL_SEC = 60 * 60 * 24
INVITE_LINK_TTL_SEC = 60 * 60

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "telegram_subscriptions.db"
_lock = threading.Lock()


def _db_path() -> Path:
    return Path(os.getenv("TG_SUB_DB_PATH", str(_DEFAULT_DB)))


def _bot_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "")


def _private_channel_id() -> str:
    return os.getenv("TELEGRAM_PRIVATE_CHANNEL_ID", "")


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    p = _db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(p))
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


def _init() -> None:
    with _lock, _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS subs (
                pairing_token          TEXT PRIMARY KEY,
                stripe_session_id      TEXT,
                stripe_subscription_id TEXT,
                stripe_customer_id     TEXT,
                customer_email         TEXT,
                telegram_user_id       INTEGER,
                channel_id             TEXT,
                status                 TEXT NOT NULL,
                period_end             INTEGER,
                created_at             INTEGER NOT NULL,
                paired_at              INTEGER,
                revoked_at             INTEGER,
                last_invite_link       TEXT
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_sub ON subs(stripe_subscription_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_session ON subs(stripe_session_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_tg_user ON subs(telegram_user_id)")
        c.commit()


_init()


# ── Token lifecycle ──────────────────────────────────────────────────────────


def new_pairing_token() -> str:
    """Mint a fresh pairing token and persist it as pending_payment."""
    token = secrets.token_urlsafe(24)
    now = int(time.time())
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO subs (pairing_token, status, created_at) VALUES (?, ?, ?)",
            (token, "pending_payment", now),
        )
        c.commit()
    return token


def attach_session(token: str, stripe_session_id: str) -> None:
    """Record the Stripe session id once we have it from Stripe's response."""
    with _lock, _conn() as c:
        c.execute(
            "UPDATE subs SET stripe_session_id=? WHERE pairing_token=?",
            (stripe_session_id, token),
        )
        c.commit()


# ── Stripe webhook handlers ──────────────────────────────────────────────────


def handle_checkout_completed(session: dict) -> Optional[str]:
    """Promote a row to pending_pair after Stripe confirms payment.

    Returns the pairing token on success, or None if the session has no
    tg_pairing_token (i.e. it's a different product) or is unknown to us.
    """
    metadata = session.get("metadata") or {}
    token = metadata.get("tg_pairing_token")
    if not token:
        return None

    sub_id = session.get("subscription") or ""
    cust_id = session.get("customer") or ""
    email = (
        (session.get("customer_details") or {}).get("email")
        or session.get("customer_email")
        or ""
    )

    with _lock, _conn() as c:
        row = c.execute(
            "SELECT status FROM subs WHERE pairing_token=?", (token,)
        ).fetchone()
        if not row:
            logger.warning(
                "checkout completed for unknown pairing token: %s...", token[:8]
            )
            return None
        c.execute(
            """
            UPDATE subs SET stripe_subscription_id=?, stripe_customer_id=?,
                            customer_email=?, status='pending_pair'
            WHERE pairing_token=?
            """,
            (sub_id, cust_id, email, token),
        )
        c.commit()
    logger.info("checkout completed: token=%s... sub=%s", token[:8], sub_id)
    return token


def handle_subscription_updated(subscription: dict) -> None:
    """Track period_end so cancellations land at the right moment."""
    sub_id = subscription.get("id")
    period_end = subscription.get("current_period_end")
    if not sub_id:
        return
    with _lock, _conn() as c:
        c.execute(
            "UPDATE subs SET period_end=? WHERE stripe_subscription_id=?",
            (period_end, sub_id),
        )
        c.commit()


def revoke_for_subscription(stripe_subscription_id: str) -> Optional[dict]:
    """Mark the active row for this subscription as revoked. Returns the row
    (so the caller can kick the user from the channel), or None if no active
    row was found.
    """
    if not stripe_subscription_id:
        return None
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT * FROM subs WHERE stripe_subscription_id=? AND status='active'",
            (stripe_subscription_id,),
        ).fetchone()
        if not row:
            return None
        c.execute(
            "UPDATE subs SET status='revoked', revoked_at=? WHERE pairing_token=?",
            (int(time.time()), row["pairing_token"]),
        )
        c.commit()
        return dict(row)


# ── Telegram /start <token> pairing ──────────────────────────────────────────


def begin_pairing(token: str) -> dict:
    """Validate that a token is ready to be paired. Returns
    {ok, channel_id, error}. Side-effect free — call before minting the
    invite link.
    """
    if not _private_channel_id():
        return {"ok": False, "channel_id": None, "error": "channel_not_configured"}
    now = int(time.time())
    with _conn() as c:
        row = c.execute(
            "SELECT status, created_at FROM subs WHERE pairing_token=?",
            (token,),
        ).fetchone()
    if not row:
        return {"ok": False, "channel_id": None, "error": "unknown_token"}
    if row["status"] != "pending_pair":
        return {"ok": False, "channel_id": None, "error": f"wrong_status:{row['status']}"}
    if now - row["created_at"] > PAIRING_TOKEN_TTL_SEC:
        return {"ok": False, "channel_id": None, "error": "token_expired"}
    return {"ok": True, "channel_id": _private_channel_id(), "error": None}


def finalize_pairing(
    token: str,
    telegram_user_id: int,
    channel_id: str,
    invite_link: str,
) -> None:
    """Mark a pairing as active. Caller has already minted the invite link."""
    now = int(time.time())
    with _lock, _conn() as c:
        c.execute(
            """
            UPDATE subs SET telegram_user_id=?, channel_id=?, last_invite_link=?,
                            status='active', paired_at=?
            WHERE pairing_token=?
            """,
            (telegram_user_id, channel_id, invite_link, now, token),
        )
        c.commit()


# ── Read helpers ─────────────────────────────────────────────────────────────


def lookup_active_by_telegram_user(telegram_user_id: int) -> Optional[dict]:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM subs WHERE telegram_user_id=? AND status='active' "
            "ORDER BY paired_at DESC LIMIT 1",
            (telegram_user_id,),
        ).fetchone()
        return dict(row) if row else None


def list_active_subscribers() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT pairing_token, telegram_user_id, channel_id, customer_email, "
            "       period_end FROM subs WHERE status='active'"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Telegram side-effects ────────────────────────────────────────────────────


async def kick_telegram_user(channel_id: str, telegram_user_id: int) -> bool:
    """Remove the user from the private channel.

    `banChatMember` followed by `unbanChatMember` is the canonical pattern:
    ban kicks them, unban allows them to rejoin if they resubscribe later.
    """
    token = _bot_token()
    if not token:
        logger.warning("kick: TELEGRAM_BOT_TOKEN not set")
        return False
    try:
        import httpx
    except ImportError:
        logger.warning("kick: httpx not installed")
        return False

    base = f"https://api.telegram.org/bot{token}"
    async with httpx.AsyncClient(timeout=10) as client:
        r1 = await client.post(
            f"{base}/banChatMember",
            json={"chat_id": channel_id, "user_id": telegram_user_id},
        )
        r2 = await client.post(
            f"{base}/unbanChatMember",
            json={
                "chat_id": channel_id,
                "user_id": telegram_user_id,
                "only_if_banned": True,
            },
        )
    ok = r1.status_code == 200 and r2.status_code == 200
    if not ok:
        logger.warning(
            "kick failed: ban=%s unban=%s for user=%s chan=%s",
            r1.status_code, r2.status_code, telegram_user_id, channel_id,
        )
    return ok
