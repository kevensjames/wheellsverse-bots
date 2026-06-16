"""User-uploaded reference documents (RAG v1).

v1 stores full text; chat handlers prepend the whole document to the user
message at compose time. Works great for the 5-10 page docs that are 80%
of the use case (resumes, contracts, RFPs, short PDFs).

Future v2 will add chunk-level embeddings (pgvector) + retrieval for long
docs — same table, just add `chunks` and `embedding` columns.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class KaiDocument(Base):
    __tablename__ = "kai_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    text_len: Mapped[int] = mapped_column(Integer, nullable=False)
    full_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_kai_documents_user_id", "user_id"),
        Index("ix_kai_documents_created_at", "created_at"),
    )
