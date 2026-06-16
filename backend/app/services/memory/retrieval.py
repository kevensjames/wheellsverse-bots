"""Semantic retrieval with recency boost.

Score = 0.7 * cosine_similarity + 0.3 * recency, where recency is exp-decay
with a 30-day half-life on last_used_at.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.memory import MEMORY_TYPES
from app.services.memory.embeddings import embed_one

DEFAULT_K = 8
SIMILARITY_WEIGHT = 0.7
RECENCY_WEIGHT = 0.3
RECENCY_HALFLIFE_SECONDS = 30 * 24 * 3600


@dataclass(slots=True)
class RetrievedMemory:
    id: uuid.UUID
    content: str
    memory_type: str
    similarity: float
    recency: float
    score: float
    created_at: datetime
    last_used_at: datetime


_SEARCH_SQL = text(
    """
    SELECT
        id,
        content,
        memory_type,
        created_at,
        last_used_at,
        1 - (embedding <=> CAST(:query_embedding AS vector)) AS similarity,
        EXP(-EXTRACT(EPOCH FROM (NOW() - last_used_at)) / :halflife) AS recency
    FROM memories
    WHERE user_id = :user_id
      AND (:type_filter IS NULL OR memory_type = :type_filter)
    ORDER BY (
        :sim_w * (1 - (embedding <=> CAST(:query_embedding AS vector)))
        + :rec_w * EXP(-EXTRACT(EPOCH FROM (NOW() - last_used_at)) / :halflife)
    ) DESC
    LIMIT :k
    """
)


def search_memories(
    session: Session,
    *,
    user_id: uuid.UUID,
    query: str,
    k: int = DEFAULT_K,
    memory_type: str | None = None,
    bump_last_used: bool = True,
) -> list[RetrievedMemory]:
    if memory_type is not None and memory_type not in MEMORY_TYPES:
        raise ValueError(f"invalid memory_type={memory_type!r}")

    query_embedding = embed_one(query)

    rows = session.execute(
        _SEARCH_SQL,
        {
            "user_id": str(user_id),
            "query_embedding": str(query_embedding),
            "k": k,
            "type_filter": memory_type,
            "sim_w": SIMILARITY_WEIGHT,
            "rec_w": RECENCY_WEIGHT,
            "halflife": RECENCY_HALFLIFE_SECONDS,
        },
    ).all()

    results = [
        RetrievedMemory(
            id=r.id,
            content=r.content,
            memory_type=r.memory_type,
            similarity=float(r.similarity),
            recency=float(r.recency),
            score=SIMILARITY_WEIGHT * float(r.similarity)
            + RECENCY_WEIGHT * float(r.recency),
            created_at=r.created_at,
            last_used_at=r.last_used_at,
        )
        for r in rows
    ]

    if bump_last_used and results:
        session.execute(
            text("UPDATE memories SET last_used_at = NOW() WHERE id = ANY(:ids)"),
            {"ids": [r.id for r in results]},
        )

    return results


def format_for_prompt(memories: Sequence[RetrievedMemory]) -> str:
    if not memories:
        return ""
    lines = ["Relevant memories about the user:"]
    lines.extend(f"- [{m.memory_type}] {m.content}" for m in memories)
    return "\n".join(lines)
