"""Subscription model — matches the actual prod schema.

The Stage 5 design had a normalized `plans` table + `subscriptions.plan_id`
FK. Prod never adopted that schema. The real prod table stores tier
denormalized (CHECK in 'pro','max','ultra') and the Stripe price ID
directly on the row. Stripe is the source of truth for what was bought;
the local DB is just a cache for fast "is this user paid?" lookups.

The fictional `Plan` model that lived here is gone. Tier metadata (display
name, default predictions-per-day, plan-code → price-id mapping) is in
`app/services/billing/tiers.py` as a code-level registry — single source
of truth, no DB drift possible.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Subscription(Base):
    """Mirrors public.subscriptions exactly. See \\d output committed in
    evidence/phase_b_§2_schema_drift_*.log for the prod schema this matches."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        Index("idx_subs_user", "user_id"),
        Index("idx_subs_status", "status"),
        CheckConstraint(
            "tier IN ('pro','max','ultra')",
            name="subscriptions_tier_check",
        ),
        CheckConstraint(
            "status IN ('active','canceled','past_due','trialing')",
            name="subscriptions_status_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        # Python-side default works in both prod (uuid_generate_v4 extension)
        # and tests (pgcrypto's gen_random_uuid) without coupling to either.
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    tier: Mapped[str] = mapped_column(Text, nullable=False)
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        Text, unique=True, nullable=True
    )
    stripe_price_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="active"
    )
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<Subscription user={self.user_id} tier={self.tier} status={self.status}>"
