"""Pulls top-K memories + recent matching failures and formats them as a
system-prompt prefix.

Lives outside the router so the brain layer (Stage 4) decides *when* to
inject. K defaults to 3 — chat context is already large, don't burn the
budget on memories that aren't load-bearing.

Failure memories surface as a SEPARATE block ("⚠️ Past failures with
similar prompts") so the model treats them distinctly from positive
recall. The model is instructed (via BASE_SYSTEM_PROMPT) to flag the
warning to the user when about to repeat an action that's failed before.
"""
from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from app.services.memory.retrieval import format_for_prompt, search_memories

logger = logging.getLogger(__name__)

DEFAULT_INJECT_K = 3
DEFAULT_FAILURE_K = 2  # Smaller — failures are louder per-line, K=2 is enough


def build_memory_preamble(
    session: Session,
    user_id: uuid.UUID,
    query: str,
    k: int = DEFAULT_INJECT_K,
    failure_k: int = DEFAULT_FAILURE_K,
) -> str:
    """Returns a string suitable for prepending to a system prompt.
    Empty string if neither memories nor matching failures are found.

    Two blocks, concatenated (failure block sits FIRST so model attention
    treats prior failures as primary context):
      1. ⚠️ Past failures block — from failure_memory.find_recent_similar
      2. Memory recall block — from pgvector / search_memories
    """
    parts: list[str] = []

    # Failures: cheap keyword similarity, no embedding cost per turn.
    # Wrapped in try so a broken failure log can't take down chat.
    try:
        from app.services.failure_memory import find_recent_similar
        failures = find_recent_similar(query, k=failure_k)
        if failures:
            lines = [
                "⚠️ Past failures with similar prompts — if you're about "
                "to repeat one of these actions, warn the user first:",
            ]
            for f in failures:
                tool_bit = f" via {f.tool_name}" if f.tool_name else ""
                lines.append(
                    f"- ({f.ts[:10]}) '{f.prompt[:120]}'{tool_bit} → {f.detail[:200]}"
                )
            parts.append("\n".join(lines))
    except Exception as e:
        logger.warning("memory_injection: failure lookup swallowed: %s", e)

    memories = search_memories(
        session, user_id=user_id, query=query, k=k, bump_last_used=True
    )
    mem_text = format_for_prompt(memories)
    if mem_text:
        parts.append(mem_text)

    return "\n\n".join(parts)
