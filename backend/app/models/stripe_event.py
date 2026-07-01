"""Idempotency ledger for Stripe webhook events (audit CORR-F2).

The webhook claims each `event.id` before handling it; a duplicate delivery
(Stripe retries the same event for up to ~3 days) hits the primary key and is
short-circuited so side effects don't re-fire. This covers ALL event types —
the previous `UNIQUE(stripe_subscription_id)` only protected the subscription
upsert handlers, leaving checkout/invoice handlers replay-able.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ProcessedStripeEvent(Base):
    __tablename__ = "processed_stripe_events"

    event_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    event_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
