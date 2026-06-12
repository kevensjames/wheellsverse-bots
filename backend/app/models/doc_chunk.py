"""Chunk-level rows for RAG v2.

One kai_documents row → many kai_doc_chunks rows. Each chunk carries its
own 1536-dim embedding (OpenAI text-embedding-3-small) so we can do
top-k cosine retrieval at query time instead of injecting the whole
document.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KaiDocChunk(Base):
    __tablename__ = "kai_doc_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    doc_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("kai_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Stored as Text in the ORM (pgvector's type adapter isn't installed in
    # this venv). The DB column is `vector(1536)`. Reads/writes happen via
    # raw SQL in app/services/documents.py — the model exists for ORM
    # relationships + cascade behavior, not for chunk-fetch code paths.
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_kai_doc_chunks_doc_id", "doc_id"),
        Index("ix_kai_doc_chunks_user_id", "user_id"),
    )
