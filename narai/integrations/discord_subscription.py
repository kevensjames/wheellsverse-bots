"""Discord paid-role sync via Stripe — mirror of telegram_subscription.

Flow:
  1. User runs /subscribe in Discord → bot mints a pairing_token, creates a
     Stripe checkout session whose metadata.discord_pairing_token == the token
     and metadata.discord_user_id == their Discord id, posts the URL.
  2. User pays. Stripe POSTs checkout.session.completed →
     handle_checkout_completed() promotes the row to status='active' and
     calls the role_grant callback (assigns DISCORD_PAID_ROLE_ID to the user).
  3. customer.subscription.deleted → revoke_for_subscription() removes the
     role and marks the row 'revoked'.

State lives in SQLite next to telegram_subscriptions.db.
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

logger = logging.getLogger("narai.discord.subscription")

PAIRING_TOKEN_TTL_SEC = 60 * 60 * 24

_DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "discord_subscriptions.db"
_lock = threading.Lock()


def _db_path() -> Path:
    return Path(os.getenv("DISCORD_SUB_DB_PATH", str(_DEFAULT_DB)))


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
                discord_user_id        TEXT NOT NULL,
                discord_guild_id       TEXT,
                stripe_session_id      TEXT,
                stripe_subscription_id TEXT,
                stripe_customer_id     TEXT,
                customer_email         TEXT,
                role_id                TEXT,
                status                 TEXT NOT NULL,
                period_end             INTEGER,
                created_at             INTEGER NOT NULL,
                granted_at             INTEGER,
                revoked_at             INTEGER
            )
            """
        )
        c.execute("CREATE INDEX IF NOT EXISTS idx_disc_sub ON subs(stripe_subscription_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_disc_user ON subs(discord_user_id)")
        c.commit()


_init()


# ── Token lifecycle ──────────────────────────────────────────────────────────


def new_pairing_token(discord_user_id: str, discord_guild_id: str | None = None) -> str:
    """Mint a fresh pairing token tied to a Discord user."""
    token = secrets.token_urlsafe(24)
    now = int(time.time())
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO subs (pairing_token, discord_user_id, discord_guild_id, "
            "                  status, created_at) VALUES (?, ?, ?, ?, ?)",
            (token, str(discord_user_id), discord_guild_id, "pending_payment", now),
        )
        c.commit()
    return token


def attach_session(token: str, stripe_session_id: str) -> None:
    with _lock, _conn() as c:
        c.execute(
            "UPDATE subs SET stripe_session_id=? WHERE pairing_token=?",
            (stripe_session_id, token),
        )
        c.commit()


# ── Stripe webhook handlers ──────────────────────────────────────────────────


def handle_checkout_completed(session: dict) -> Optional[dict]:
    """Promote the row to active. Returns the row dict so caller can grant role.

    Returns None if the session has no discord_pairing_token (different product).
    """
    metadata = session.get("metadata") or {}
    token = metadata.get("discord_pairing_token")
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
            "SELECT * FROM subs WHERE pairing_token=?", (token,)
        ).fetchone()
        if not row:
            logger.warning(
                "discord checkout completed for unknown token: %s...", token[:8]
            )
            return None
        c.execute(
            """
            UPDATE subs SET stripe_subscription_id=?, stripe_customer_id=?,
                            customer_email=?, status='active', granted_at=?
            WHERE pairing_token=?
            """,
            (sub_id, cust_id, email, int(time.time()), token),
        )
        c.commit()
        out = c.execute(
            "SELECT * FROM subs WHERE pairing_token=?", (token,)
        ).fetchone()
    logger.info("discord checkout completed: token=%s... sub=%s", token[:8], sub_id)
    return dict(out) if out else None


def handle_subscription_updated(subscription: dict) -> None:
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
    """Mark active row revoked. Returns the row so caller can remove the Discord role."""
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


# ── Reads ────────────────────────────────────────────────────────────────────


def lookup_active_by_discord_user(discord_user_id: str) -> Optional[dict]:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM subs WHERE discord_user_id=? AND status='active' "
            "ORDER BY granted_at DESC LIMIT 1",
            (str(discord_user_id),),
        ).fetchone()
        return dict(row) if row else None


def list_active_subscribers() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT pairing_token, discord_user_id, discord_guild_id, "
            "       customer_email, period_end FROM subs WHERE status='active'"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Discord side-effect (HTTP API) ───────────────────────────────────────────


async def grant_role(guild_id: str, discord_user_id: str, role_id: str) -> bool:
    """PUT a guild role onto a member via Discord HTTP API."""
    return await _role_op("PUT", guild_id, discord_user_id, role_id)


async def revoke_role(guild_id: str, discord_user_id: str, role_id: str) -> bool:
    """DELETE a guild role from a member."""
    return await _role_op("DELETE", guild_id, discord_user_id, role_id)


async def _role_op(method: str, guild_id: str, user_id: str, role_id: str) -> bool:
    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token:
        logger.warning("role op: DISCORD_BOT_TOKEN unset")
        return False
    try:
        import httpx
    except ImportError:
        logger.warning("role op: httpx not installed")
        return False

    url = f"https://discord.com/api/v10/guilds/{guild_id}/members/{user_id}/roles/{role_id}"
    headers = {"Authorization": f"Bot {token}"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.request(method, url, headers=headers)
        # 204 No Content = success on PUT/DELETE for role ops
        ok = r.status_code in (200, 204)
        if not ok:
            logger.warning(
                "role %s failed: status=%s body=%s user=%s role=%s guild=%s",
                method, r.status_code, r.text[:200], user_id, role_id, guild_id,
            )
        return ok
    except Exception as e:
        logger.exception(f"role {method} raised: {e}")
        return False
