"""Memory store: create, get, delete. Retrieval lives in retrieval.py."""
from __future__ import annotations

import uuid
from typing import Sequence

from sqlalchemy.orm import Session

from app.models.memory import MEMORY_TYPES, Memory
from app.services.memory.embeddings import embed_many, embed_one


class MemoryStoreError(ValueError):
    pass


def add_memory(
    session: Session,
    *,
    user_id: uuid.UUID,
    content: str,
    memory_type: str = "note",
    metadata: dict | None = None,
) -> Memory:
    if memory_type not in MEMORY_TYPES:
        raise MemoryStoreError(f"invalid memory_type={memory_type!r}")
    if not content.strip():
        raise MemoryStoreError("content cannot be empty")

    memory = Memory(
        user_id=user_id,
        content=content,
        memory_type=memory_type,
        embedding=embed_one(content),
        metadata_=metadata or {},
    )
    session.add(memory)
    session.flush()
    return memory


def add_memories_bulk(
    session: Session,
    *,
    user_id: uuid.UUID,
    items: Sequence[tuple[str, str]],
    metadata: dict | None = None,
) -> list[Memory]:
    if not items:
        return []
    for _, mt in items:
        if mt not in MEMORY_TYPES:
            raise MemoryStoreError(f"invalid memory_type={mt!r}")

    embeddings = embed_many([c for c, _ in items])
    memories = [
        Memory(
            user_id=user_id,
            content=c,
            memory_type=mt,
            embedding=e,
            metadata_=metadata or {},
        )
        for (c, mt), e in zip(items, embeddings)
    ]
    session.add_all(memories)
    session.flush()
    return memories


def get_memory(session: Session, memory_id: uuid.UUID) -> Memory | None:
    return session.get(Memory, memory_id)


def delete_memory(session: Session, memory_id: uuid.UUID) -> bool:
    memory = session.get(Memory, memory_id)
    if memory is None:
        return False
    session.delete(memory)
    return True


def count_memories(session: Session, user_id: uuid.UUID) -> int:
    return session.query(Memory).filter(Memory.user_id == user_id).count()
