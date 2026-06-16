"""API key model — backs the /v1/chat/completions OpenAI-compatible endpoint.

A paid KAI user can issue any number of API keys from /account/api-keys.
Each key:
  - is issued ONCE in plaintext (kai_<32 url-safe chars>); only its bcrypt
    hash is stored. If lost, revoke and issue a new one.
  - is owned by a single user_id (Supabase auth.users id)
  - is tier-gated at request time — we check the OWNER's current
    profile.tier; if they downgrade to free, all their keys 401.
  - tracks last_used_at so the user can see which keys are active.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class ApiKey(Base):
    __tablename__ = "kai_api_keys"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SHA-256 hex of the plaintext key. Comparison is constant-time-safe
    # (SHA is deterministic so we can index it). Not bcrypt because keys
    # are high-entropy random — a 256-bit SHA hash gives ample security
    # and lets us look up O(log n) instead of scanning all keys.
    key_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Short human-readable prefix (`kai_xxx`) so the user can identify
    # which key is which in the UI without seeing the secret again.
    prefix: Mapped[str] = mapped_column(Text, nullable=False)
    # User-supplied label like "my laptop" or "github actions".
    label: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_kai_api_keys_user_id", "user_id"),
        Index("ix_kai_api_keys_key_hash", "key_hash", unique=True),
    )

    def __repr__(self) -> str:
        return f"<ApiKey id={self.id} prefix={self.prefix!r} user={self.user_id}>"
