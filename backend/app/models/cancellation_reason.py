"""Captured cancellation reasons — for retention analytics + winback.

Populated when a user cancels via Stripe Billing Portal and returns to
/kai-ui/chat.html?canceled=1, where a one-question modal asks why.

We deliberately keep this minimal: a reason_code (predefined dropdown) +
optional free_text. No PII beyond what's already on profile. Useful for:
  - 'why are people churning' — pivot the reason_code histogram weekly
  - winback decisions — text feedback for product roadmap
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CancellationReason(Base):
    __tablename__ = "cancellation_reasons"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Predefined code: 'too_expensive' | 'missing_feature' | 'not_using' |
    #                  'switched_to' | 'bug' | 'other'
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    free_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_cancellation_reasons_user_id", "user_id"),
        Index("ix_cancellation_reasons_created_at", "created_at"),
    )
