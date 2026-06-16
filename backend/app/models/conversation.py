"""SQLAlchemy models for the NAI chat tables (conversations + messages).

Columns mirror the *actual* Supabase schema after Stage 4's additive ALTER.
Existing production rows (29 conversations, 98 messages) follow this shape.

Important deviations from the Stage 4 prompt template:
- ``title`` is NOT NULL on the live table (default 'New Chat'); the ORM
  matches by setting ``default='New Chat'`` for fresh rows.
- ``model_used`` (not ``model``) is the existing model-name column.
- ``message_count`` is a counter the Brain layer maintains as it inserts.
- ``messages.user_id`` is denormalized — the Brain populates it from the
  parent conversation's user_id on every insert.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.database import Base


VALID_ROLES = ("user", "assistant", "system", "tool")


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        Text, nullable=False, default="New Chat", server_default="New Chat"
    )
    model_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    message_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.created_at.asc()",
    )

    __table_args__ = (
        Index("ix_conversations_user_updated", "user_id", "updated_at"),
    )

    def __repr__(self) -> str:
        return f"<Conversation id={self.id} user={self.user_id} title={self.title!r}>"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_calls: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    adapter: Mapped[str | None] = mapped_column(String(50), nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )

    __table_args__ = (
        CheckConstraint(
            f"role IN {VALID_ROLES}", name="ck_messages_role"
        ),
        Index("ix_messages_conv_created", "conversation_id", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Message id={self.id} role={self.role} "
            f"conv={self.conversation_id} adapter={self.adapter}>"
        )
