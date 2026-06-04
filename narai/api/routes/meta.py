"""
narai/api/routes/meta.py
─────────────────────────────────────────────────────────────────────────────
Meta-platform endpoints — minimum surface required for Facebook App Review.

Meta requires every app requesting `ads_management` / `business_management` /
similar elevated permissions to expose a **Data Deletion Callback** that
accepts signed_request POSTs and starts data deletion for the identified
user. This file implements that callback plus a public status-check endpoint
that Meta links the user to.

Routes (mounted at no prefix so they're publicly addressable):

  POST /meta/data-deletion
      Body: form-encoded `signed_request=<base64url>.<base64url>`
      Verifies the signed_request HMAC-SHA256 with META_APP_SECRET, extracts
      `user_id`, schedules deletion, returns JSON with `url` + `confirmation_code`.

  GET /meta/data-deletion/status?code=<confirmation_code>
      Public page Meta links the user to. Reports whether deletion is
      complete or still in progress.

Env vars:
  META_APP_SECRET — required for signed_request HMAC verification.
                    If unset, the endpoint logs a warning and accepts requests
                    without verification (useful during App Review pre-submit
                    testing; do NOT leave unset in production).
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Form, HTTPException, Request
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from narai.core.db import Base, SessionLocal

log = logging.getLogger("meta_routes")

rt = APIRouter(tags=["meta"])


# ── DB model ──────────────────────────────────────────────────────────────────

class MetaDeletionRequest(Base):
    """One row per data-deletion request received from Meta."""
    __tablename__ = "meta_deletion_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fb_user_id: Mapped[str] = mapped_column(String(64), index=True)
    confirmation_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="received", index=True)
    # received | in_progress | completed | failed
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ── signed_request decoder ────────────────────────────────────────────────────

def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def parse_signed_request(signed_request: str, app_secret: Optional[str]) -> dict:
    """
    Verify + decode a Facebook signed_request.

    If app_secret is None, skip verification and log a warning.
    Raises ValueError on malformed input or signature mismatch.
    """
    try:
        encoded_sig, payload_b64 = signed_request.split(".", 1)
    except ValueError:
        raise ValueError("malformed signed_request — expected <sig>.<payload>")

    payload_bytes = _b64url_decode(payload_b64)
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"payload not JSON: {e}")

    if payload.get("algorithm", "").upper() != "HMAC-SHA256":
        raise ValueError(f"unsupported algorithm: {payload.get('algorithm')!r}")

    if app_secret is None:
        log.warning("[meta] signed_request verification SKIPPED — "
                    "META_APP_SECRET not set. Set it before going live.")
        return payload

    sig = _b64url_decode(encoded_sig)
    expected = hmac.new(
        app_secret.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(sig, expected):
        raise ValueError("signed_request signature mismatch — APP_SECRET wrong "
                         "or request tampered with")
    return payload


# ── Endpoints ─────────────────────────────────────────────────────────────────

@rt.post("/meta/data-deletion")
async def meta_data_deletion(request: Request, signed_request: str = Form(...)) -> dict:
    """
    Meta Data Deletion Callback (RFC: developers.facebook.com/docs/development/
    create-an-app/app-dashboard/data-deletion-callback).
    """
    app_secret = os.getenv("META_APP_SECRET") or None
    try:
        payload = parse_signed_request(signed_request, app_secret)
    except ValueError as e:
        log.error("[meta] data-deletion: invalid signed_request: %s", e)
        raise HTTPException(status_code=400, detail=str(e))

    fb_user_id = str(payload.get("user_id") or "")
    if not fb_user_id:
        raise HTTPException(status_code=400, detail="signed_request missing user_id")

    confirmation_code = secrets.token_urlsafe(24)

    async with SessionLocal() as session:  # type: AsyncSession
        session.add(MetaDeletionRequest(
            fb_user_id=fb_user_id,
            confirmation_code=confirmation_code,
            status="received",
        ))
        await session.commit()

    log.info("[meta] data-deletion received for fb_user_id=%s code=%s",
             fb_user_id, confirmation_code)

    # The URL Meta will link the user to. Hosted on the Cloudflare Pages
    # frontend — that's where the status page lives. We use this server's
    # public URL via APP_BASE_URL for the status endpoint that returns JSON.
    base = (os.getenv("APP_BASE_URL")
            or "https://wheellsverse-bots.pages.dev").rstrip("/")
    return {
        "url": f"{base}/meta/data-deletion/status?code={confirmation_code}",
        "confirmation_code": confirmation_code,
    }


@rt.get("/meta/data-deletion/status")
async def meta_data_deletion_status(code: str) -> dict:
    """Public lookup endpoint Meta links the user to."""
    from sqlalchemy import select
    if not code:
        raise HTTPException(status_code=400, detail="missing code")
    async with SessionLocal() as session:
        row = (await session.execute(
            select(MetaDeletionRequest).where(
                MetaDeletionRequest.confirmation_code == code
            )
        )).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown confirmation code")
        return {
            "confirmation_code": code,
            "status": row.status,
            "received_at": row.received_at.isoformat() if row.received_at else None,
            "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        }


@rt.get("/meta/data-deletion/health")
async def meta_data_deletion_health() -> dict:
    """Pre-flight sanity check Meta's review team can hit."""
    return {
        "ok": True,
        "app_secret_configured": bool(os.getenv("META_APP_SECRET")),
        "now_utc": datetime.now(timezone.utc).isoformat(),
    }
