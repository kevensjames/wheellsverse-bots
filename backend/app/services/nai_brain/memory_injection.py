"""Pulls top-K memories and formats them as a system-prompt prefix.

Lives outside the router so the brain layer (Stage 4) decides *when* to
inject. K defaults to 3 — chat context is already large, don't burn the
budget on memories that aren't load-bearing.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.services.memory.retrieval import format_for_prompt, search_memories

DEFAULT_INJECT_K = 3


def build_memory_preamble(
    session: Session,
    user_id: uuid.UUID,
    query: str,
    k: int = DEFAULT_INJECT_K,
) -> str:
    """Returns a string suitable for prepending to a system prompt.
    Empty string if no relevant memories.
    """
    memories = search_memories(
        session, user_id=user_id, query=query, k=k, bump_last_used=True
    )
    return format_for_prompt(memories)
