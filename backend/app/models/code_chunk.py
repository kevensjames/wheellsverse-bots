"""ORM model for kai_code_chunks (code intelligence).

Embedding is typed ``Text`` in the ORM (the pgvector SQLAlchemy adapter isn't
used here) — the real DB column is ``vector(1536)`` via migration 0007, and all
vector reads/writes go through raw SQL in
``app/services/code_intel/pgvector_provider.py``. This model exists for cascade /
relationship behavior, not for chunk-fetch code paths. Mirrors models/doc_chunk.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CodeChunkRow(Base):
    __tablename__ = "kai_code_chunks"
    __table_args__ = (
        UniqueConstraint("user_id", "repo_id", "path", "content_sha",
                         name="uq_kai_code_chunks_ident"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False, index=True)
    repo_id: Mapped[str] = mapped_column(String(200), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    lang: Mapped[str] = mapped_column(String(40), nullable=False)
    symbol: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha: Mapped[str] = mapped_column(String(64), nullable=False)
    # DB column is vector(1536); Text here so create_all works without the
    # pgvector adapter. Accessed only via raw SQL.
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False)
