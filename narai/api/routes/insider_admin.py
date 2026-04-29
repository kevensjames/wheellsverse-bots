"""Insider admin + lead-capture routes.

  POST /api/v2/narai/insider/lead         — public, capture email + send sample
  GET  /api/v2/narai/insider/leads        — admin, list captured emails
  GET  /api/v2/narai/insider/subscribers  — admin, list active subscribers
  POST /api/v2/narai/insider/revoke       — admin, force-kick by subscription_id
  POST /api/v2/narai/insider/reissue      — admin, generate fresh invite for a paired subscriber

Admin auth: X-Admin-Token header must equal NARAI_ADMIN_TOKEN env. If the env
isn't set, admin endpoints all return 503 (intentional — no anonymous access).
"""
from __future__ import annotations

import logging
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, EmailStr

logger = logging.getLogger("narai.insider_admin")

rt = APIRouter(prefix="/insider", tags=["insider-admin"])

LEADS_DB = Path(
    os.getenv(
        "INSIDER_LEADS_DB_PATH",
        str(Path(__file__).resolve().parents[3] / "data" / "insider_leads.db"),
    )
)
_lock = threading.Lock()


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    LEADS_DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(LEADS_DB))
    c.row_factory = sqlite3.Row
    try:
        yield c
    finally:
        c.close()


def _init() -> None:
    with _lock, _conn() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
                email      TEXT PRIMARY KEY,
                source     TEXT,
                created_at INTEGER NOT NULL,
                sample_sent_at INTEGER,
                converted_to_subscriber INTEGER DEFAULT 0
            )
            """
        )
        c.commit()


_init()


# ── Public: lead capture ─────────────────────────────────────────────────────


class LeadRequest(BaseModel):
    email: EmailStr
    source: Optional[str] = None


@rt.post("/lead")
def capture_lead(body: LeadRequest) -> dict:
    """Persist email + queue a sample signal email. Idempotent on email."""
    now = int(time.time())
    with _lock, _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO leads (email, source, created_at) VALUES (?, ?, ?)",
            (body.email, body.source or "unknown", now),
        )
        c.commit()
        already = c.execute(
            "SELECT sample_sent_at FROM leads WHERE email=?", (body.email,)
        ).fetchone()

    if already and already["sample_sent_at"]:
        return {"ok": True, "message": "already_sent"}

    sent = _send_sample_email(body.email)
    if sent:
        with _lock, _conn() as c:
            c.execute(
                "UPDATE leads SET sample_sent_at=? WHERE email=?",
                (int(time.time()), body.email),
            )
            c.commit()

    return {"ok": True, "sent": sent}


def _send_sample_email(email: str) -> bool:
    """Send the free sample signal via the existing email pipeline.

    Returns True on apparent success (no exception, SMTP didn't reject).
    Looks up SMTP creds via core.email_sender if available; otherwise no-ops
    so dev environments don't fail.
    """
    try:
        from core.email_sender import send_email  # type: ignore
    except ImportError:
        try:
            from core.drip import _send_email as send_email  # type: ignore
        except Exception:
            logger.info("no email sender available — sample queued only")
            return False

    subject = "Your free Insider sample — one AI-picked setup"
    body = (
        "Here's a sample of what Insider members get every weekday:\n\n"
        "------------------------------------------------------------\n"
        "AI-picked setup (sample, educational only):\n\n"
        "  🟢 NVDA — bullish (5-day, ~62% conf)\n"
        "  Trigger: SMA20 > SMA50 + MACD positive cross\n"
        "  Risk: stop below recent 5-day low\n"
        "------------------------------------------------------------\n\n"
        "This is one of ~5 setups our scanner produced today.\n"
        "Subscribers get the full list at 7am ET, plus a midday\n"
        "scan and a Sunday weekly review.\n\n"
        "Join the private channel — $19/mo, cancel anytime:\n"
        "https://app.wheellsverse.com/insider\n\n"
        "Educational content only. Not investment advice."
    )
    try:
        return bool(send_email(to=email, subject=subject, body=body))
    except Exception as e:
        logger.warning(f"sample email send raised: {e}")
        return False


# ── Admin auth helper ────────────────────────────────────────────────────────


def _require_admin(token: str | None) -> None:
    expected = os.environ.get("NARAI_ADMIN_TOKEN", "").strip()
    if not expected:
        raise HTTPException(503, "Admin disabled (NARAI_ADMIN_TOKEN not set)")
    if not token or not secrets.compare_digest(token, expected):
        raise HTTPException(401, "Invalid admin token")


# ── Admin: leads ─────────────────────────────────────────────────────────────


@rt.get("/leads")
def list_leads(x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin(x_admin_token)
    with _conn() as c:
        rows = c.execute(
            "SELECT email, source, created_at, sample_sent_at, converted_to_subscriber "
            "FROM leads ORDER BY created_at DESC LIMIT 500"
        ).fetchall()
    return {"count": len(rows), "leads": [dict(r) for r in rows]}


# ── Admin: subscribers ───────────────────────────────────────────────────────


@rt.get("/subscribers")
def list_subscribers(x_admin_token: str | None = Header(default=None)) -> dict:
    _require_admin(x_admin_token)
    from narai.integrations import telegram_subscription as ts
    active = ts.list_active_subscribers()
    return {"count": len(active), "subscribers": active}


class RevokeRequest(BaseModel):
    stripe_subscription_id: str


@rt.post("/revoke")
async def revoke_subscriber(
    body: RevokeRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """Force-revoke a subscription. Use when a refund happened outside Stripe
    or when manual intervention is needed."""
    _require_admin(x_admin_token)
    from narai.integrations import telegram_subscription as ts
    row = ts.revoke_for_subscription(body.stripe_subscription_id)
    if row is None:
        return {"ok": True, "revoked": False, "reason": "no_active_row"}

    kicked = False
    if row.get("telegram_user_id") and row.get("channel_id"):
        kicked = await ts.kick_telegram_user(
            row["channel_id"], row["telegram_user_id"]
        )
    return {
        "ok": True,
        "revoked": True,
        "kicked_from_channel": kicked,
        "telegram_user_id": row.get("telegram_user_id"),
    }


class ReissueRequest(BaseModel):
    telegram_user_id: int


@rt.post("/reissue")
async def reissue_invite(
    body: ReissueRequest,
    x_admin_token: str | None = Header(default=None),
) -> dict:
    """Generate a fresh single-use invite for an active subscriber who lost theirs."""
    _require_admin(x_admin_token)
    from narai.integrations import telegram_subscription as ts

    sub = ts.lookup_active_by_telegram_user(body.telegram_user_id)
    if not sub:
        raise HTTPException(404, "No active subscription for that telegram_user_id")

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel = sub.get("channel_id") or os.environ.get("TELEGRAM_PRIVATE_CHANNEL_ID", "")
    if not token or not channel:
        raise HTTPException(503, "Telegram not configured")

    try:
        import httpx
    except ImportError:
        raise HTTPException(503, "httpx not installed")

    expire = datetime.now(timezone.utc) + timedelta(seconds=ts.INVITE_LINK_TTL_SEC)
    payload = {
        "chat_id": channel,
        "member_limit": 1,
        "expire_date": int(expire.timestamp()),
        "name": f"reissue:{sub['pairing_token'][:8]}",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"https://api.telegram.org/bot{token}/createChatInviteLink", data=payload
        )
    data = r.json()
    if not data.get("ok"):
        raise HTTPException(502, f"Telegram error: {data.get('description', 'unknown')}")

    invite_link = data["result"]["invite_link"]
    # Update the stored invite link for audit / reuse-detection
    with _lock, _conn():
        pass  # this DB is for leads; subscription DB updated via subscription module
    from narai.integrations.telegram_subscription import _conn as sub_conn  # type: ignore
    with sub_conn() as c:
        c.execute(
            "UPDATE subs SET last_invite_link=? WHERE pairing_token=?",
            (invite_link, sub["pairing_token"]),
        )
        c.commit()

    return {"ok": True, "invite_link": invite_link, "expires_at": int(expire.timestamp())}
