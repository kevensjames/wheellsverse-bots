"""
Toodle Capture Agent — leads in, tagged + routed into Kit (v4) nurture.

Endpoints (mounted with no NarAI prefix so they sit at the root of the app):

  POST /toodle/capture
    body: {"email_address": "...", "source": "...", "product_interest": "kdp|whop|..."}
    flow: upsert subscriber in Kit → resolve+apply tag (source) → resolve+apply
          tag (product_interest) → resolve sequence by product_interest name →
          add subscriber to sequence → persist row to kit_captures.

  POST /toodle/kit/webhook
    Kit will POST event payloads here once a webhook is registered. The body is
    persisted to `kit_webhook_events` for audit; subscriber.activated events
    flip the matching kit_captures row from `pending` → `activated`.

  GET  /toodle/status   (auth)
    Resolved tag/sequence maps + capture counts. Useful first-boot sanity check.

Honours KIT_DRY_RUN=true: every write call to Kit is logged + returned
synthesised; the DB row is still written with status="dry_run" so the local
plumbing can be verified end-to-end without touching Kit.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, Integer, String, Text, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from core.kit import KitClient, get_kit
from narai.api.auth import require_auth
from narai.core.db import Base, SessionLocal

ROOT_ENV = os.path.join(os.path.dirname(__file__), "..", "..", "..", ".env")
load_dotenv(ROOT_ENV)

log = logging.getLogger("toodle")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Product-interest → sequence-name mapping. Names are matched
# case-insensitively against Kit sequence names. If a value is set in env it
# overrides the default. Add new products by appending to this dict — the
# resolver will look up the live ID at startup or on first use.
DEFAULT_SEQUENCE_NAMES: Dict[str, str] = {
    "kdp": os.getenv("KIT_SEQUENCE_KDP_NAME", "KDP Launch"),
    "whop": os.getenv("KIT_SEQUENCE_WHOP_NAME", "Whop Signals"),
    "default": os.getenv("KIT_SEQUENCE_WELCOME_NAME", "Welcome"),
}

rt = APIRouter(tags=["toodle"])


# ── DB model ──────────────────────────────────────────────────────────────────

class KitCapture(Base):
    __tablename__ = "kit_captures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    source: Mapped[str] = mapped_column(String(64), default="")
    product_interest: Mapped[str] = mapped_column(String(64), default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    subscriber_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sequence_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")  # pending | subscribed | activated | dry_run | error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class KitWebhookEvent(Base):
    __tablename__ = "kit_webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_name: Mapped[str] = mapped_column(String(128), index=True, default="")
    subscriber_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ── Resolver: name → ID maps for tags & sequences ─────────────────────────────

class KitResolver:
    """Caches name → id maps for tags and sequences; auto-refreshes on miss."""

    def __init__(self, client: KitClient):
        self.client = client
        self._tags: Dict[str, int] = {}
        self._sequences: Dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._loaded = False

    async def _refresh(self) -> None:
        async with self._lock:
            tags = await asyncio.to_thread(self.client.list_tags)
            self._tags = {str(t.get("name", "")).strip().lower(): int(t["id"])
                          for t in tags if t.get("id") and t.get("name")}
            sequences = await asyncio.to_thread(self.client.list_sequences)
            self._sequences = {str(s.get("name", "")).strip().lower(): int(s["id"])
                               for s in sequences if s.get("id") and s.get("name")}
            self._loaded = True
            log.info("[toodle] resolver refreshed: %d tags, %d sequences",
                     len(self._tags), len(self._sequences))

    async def ensure_loaded(self) -> None:
        if not self._loaded:
            await self._refresh()

    async def tag_id(self, name: str, *, create_if_missing: bool = True) -> Optional[int]:
        if not name:
            return None
        key = name.strip().lower()
        await self.ensure_loaded()
        if key in self._tags:
            return self._tags[key]
        if not create_if_missing:
            return None
        created = await asyncio.to_thread(self.client.create_tag, name)
        # Dry-run path: synthesise an ID so the row can still be written.
        if created.get("_dry_run"):
            synthetic = -abs(hash(key)) % 10_000_000
            self._tags[key] = synthetic
            return synthetic
        tag_obj = created.get("tag") or created
        tag_id = tag_obj.get("id")
        if tag_id:
            self._tags[key] = int(tag_id)
            return int(tag_id)
        log.warning("[toodle] tag create returned no id for %s: %s", name, created)
        return None

    async def sequence_id(self, product_interest: str) -> Optional[int]:
        await self.ensure_loaded()
        target = DEFAULT_SEQUENCE_NAMES.get(product_interest.lower(),
                                            DEFAULT_SEQUENCE_NAMES["default"])
        return self._sequences.get(target.strip().lower())

    def snapshot(self) -> Dict[str, Any]:
        return {
            "loaded": self._loaded,
            "tag_count": len(self._tags),
            "sequence_count": len(self._sequences),
            "tags": dict(sorted(self._tags.items())),
            "sequences": dict(sorted(self._sequences.items())),
            "product_to_sequence_name": DEFAULT_SEQUENCE_NAMES,
        }


_resolver: Optional[KitResolver] = None


def get_resolver() -> KitResolver:
    global _resolver
    if _resolver is None:
        _resolver = KitResolver(get_kit())
    return _resolver


# ── Request / response models ─────────────────────────────────────────────────

class CaptureRequest(BaseModel):
    email_address: str = Field(..., description="Subscriber email (validated)")
    source: str = Field("", description="Where they came from, e.g. 'meta_ad', 'blog'")
    product_interest: str = Field("default", description="kdp | whop | default")
    first_name: str = Field("", description="Optional first name")
    extra_tags: List[str] = Field(default_factory=list, description="Additional tag names")


class CaptureResponse(BaseModel):
    status: str
    subscriber_id: Optional[int] = None
    sequence_id: Optional[int] = None
    tags: List[str] = []
    capture_id: Optional[int] = None
    dry_run: bool = False
    notes: List[str] = []


# ── Capture endpoint ──────────────────────────────────────────────────────────

@rt.post("/toodle/capture", response_model=CaptureResponse)
async def toodle_capture(req: CaptureRequest) -> CaptureResponse:
    if not EMAIL_RE.match(req.email_address):
        raise HTTPException(status_code=422, detail="invalid email_address")

    client = get_kit()
    if not client.is_configured():
        raise HTTPException(status_code=503, detail="KIT_API_KEY not configured")

    resolver = get_resolver()
    notes: List[str] = []
    applied_tags: List[str] = []
    dry_run = client.dry_run

    # 1) Upsert subscriber
    sub_result = await asyncio.to_thread(
        client.upsert_subscriber, req.email_address, req.first_name
    )
    subscriber_id: Optional[int] = None
    if sub_result.get("_dry_run"):
        subscriber_id = -abs(hash(req.email_address.lower())) % 10_000_000
        notes.append("dry_run subscriber id synthesised")
    else:
        sub_obj = sub_result.get("subscriber") or {}
        sub_id_raw = sub_obj.get("id") or sub_result.get("id")
        try:
            subscriber_id = int(sub_id_raw) if sub_id_raw is not None else None
        except (TypeError, ValueError):
            subscriber_id = None
        if subscriber_id is None:
            notes.append(f"upsert returned no subscriber id: {sub_result}")

    # 2) Apply tags  (source + product_interest + extras)
    tag_names = [t for t in [req.source, req.product_interest, *req.extra_tags] if t]
    for tag_name in tag_names:
        tag_id = await resolver.tag_id(tag_name)
        if tag_id and subscriber_id:
            await asyncio.to_thread(client.tag_subscriber, tag_id, subscriber_id)
            applied_tags.append(tag_name)

    # 3) Add to sequence by product_interest name
    sequence_id = await resolver.sequence_id(req.product_interest or "default")
    if sequence_id and subscriber_id:
        await asyncio.to_thread(
            client.add_subscriber_to_sequence, sequence_id, subscriber_id
        )
    elif sequence_id is None:
        notes.append(f"no sequence found for product_interest={req.product_interest!r}")

    # 4) Persist
    row_status = "dry_run" if dry_run else ("subscribed" if subscriber_id else "error")
    error_msg = None if subscriber_id else json.dumps(sub_result)[:1000]
    async with SessionLocal() as session:  # type: AsyncSession
        row = KitCapture(
            email=req.email_address,
            source=req.source or "",
            product_interest=req.product_interest or "default",
            tags=applied_tags,
            subscriber_id=subscriber_id,
            sequence_id=sequence_id,
            status=row_status,
            error=error_msg,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        capture_id = row.id

    log.info(
        "[toodle] capture email=%s source=%s product=%s sub_id=%s seq_id=%s tags=%s status=%s",
        req.email_address, req.source, req.product_interest, subscriber_id,
        sequence_id, applied_tags, row_status,
    )

    return CaptureResponse(
        status=row_status,
        subscriber_id=subscriber_id,
        sequence_id=sequence_id,
        tags=applied_tags,
        capture_id=capture_id,
        dry_run=dry_run,
        notes=notes,
    )


# ── Webhook receiver ──────────────────────────────────────────────────────────

@rt.post("/toodle/kit/webhook")
async def toodle_kit_webhook(request: Request) -> dict:
    raw = await request.body()
    try:
        payload = json.loads(raw.decode() or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON")

    event_name = (payload.get("event_name")
                  or payload.get("event")
                  or payload.get("name")
                  or "")
    sub = payload.get("subscriber") or {}
    sub_id = sub.get("id") or payload.get("subscriber_id")
    email = sub.get("email_address") or payload.get("email_address")

    async with SessionLocal() as session:
        session.add(KitWebhookEvent(
            event_name=str(event_name)[:128],
            subscriber_id=int(sub_id) if isinstance(sub_id, int) or (isinstance(sub_id, str) and sub_id.isdigit()) else None,
            email=email,
            payload=payload,
        ))

        # If we know the subscriber, flip matching captures to activated.
        if event_name and "activated" in str(event_name).lower() and sub_id:
            try:
                sub_id_int = int(sub_id)
                stmt = select(KitCapture).where(KitCapture.subscriber_id == sub_id_int)
                rows = (await session.execute(stmt)).scalars().all()
                for r in rows:
                    r.status = "activated"
            except (TypeError, ValueError):
                pass

        await session.commit()

    log.info("[toodle] webhook event=%s sub_id=%s email=%s", event_name, sub_id, email)
    return {"ok": True, "event": event_name}


# ── Status / introspection ────────────────────────────────────────────────────

@rt.get("/toodle/status")
async def toodle_status(_=Depends(require_auth)) -> dict:
    resolver = get_resolver()
    await resolver.ensure_loaded()
    async with SessionLocal() as session:
        total = (await session.execute(select(func.count(KitCapture.id)))).scalar_one()
        by_status_rows = (await session.execute(
            select(KitCapture.status, func.count(KitCapture.id)).group_by(KitCapture.status)
        )).all()
        by_status = {r[0]: int(r[1]) for r in by_status_rows}
        webhook_count = (await session.execute(select(func.count(KitWebhookEvent.id)))).scalar_one()

    return {
        "kit_configured": get_kit().is_configured(),
        "kit_dry_run": get_kit().dry_run,
        "captures_total": int(total),
        "captures_by_status": by_status,
        "webhook_events_total": int(webhook_count),
        "resolver": resolver.snapshot(),
    }
