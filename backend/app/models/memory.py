import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


MEMORY_TYPES = ("fact", "event", "preference", "note")
EMBEDDING_DIMENSIONS = 1536


class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    # FK to public.profiles(id) is declared at the Alembic / DDL level only.
    # Keeping it off the ORM model lets `Base.metadata.create_all` work in test
    # environments that don't ship the Supabase profiles table.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    memory_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="note",
        server_default="note",
    )
    embedding: Mapped[list[float]] = mapped_column(
        Vector(EMBEDDING_DIMENSIONS),
        nullable=False,
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_used_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            f"memory_type IN {MEMORY_TYPES}",
            name="ck_memories_memory_type",
        ),
        Index(
            "ix_memories_user_id_created_at",
            "user_id",
            text("created_at DESC"),
        ),
        Index("ix_memories_memory_type", "memory_type"),
    )

    def __repr__(self) -> str:
        return f"<Memory id={self.id} type={self.memory_type} user={self.user_id}>"
