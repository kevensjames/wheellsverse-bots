"""SQLAlchemy mapper for public.profiles (Path X).

Profiles is the user-data table in the canonical Supabase pattern: rows are
mirrored from auth.users via the on_auth_user_created trigger. The backend
treats this as the authoritative user table (Stage 6's fictional public.users
is gone). FK targets across the app point here.

Schema mirrors the production table at https://supabase.com/dashboard →
SQL Editor → public.profiles. Keep them in sync if either changes.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Integer,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        CheckConstraint(
            "tier IN ('free','pro','max','ultra')",
            name="profiles_tier_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        # Prod has profiles.id FK auth.users(id) — but auth schema is
        # Supabase-managed and not modelled here. Omit the FK at the
        # SQLAlchemy level (Alembic on prod has it).
    )
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    tier: Mapped[str] = mapped_column(Text, nullable=False, server_default="free")
    messages_used_today: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_reset_date: Mapped[date] = mapped_column(
        Date, nullable=False, server_default=func.current_date()
    )
    stripe_customer_id: Mapped[str | None] = mapped_column(Text, nullable=True)
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
        return f"<Profile id={self.id} email={self.email!r} tier={self.tier}>"
