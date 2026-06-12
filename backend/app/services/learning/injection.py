"""Injection — where the learning loop CLOSES.

active_lessons_preamble() returns a system-prompt section listing the operator-
APPROVED (active) lessons, which nai_brain.system_prompt layers into every KAI
reply. Gated by KAI_SCOPE_LEARNING and fully fail-open: if the scope is off,
there are no active lessons, or anything errors, it returns "" — a learning
problem must NEVER break a chat reply.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 10


def active_lessons_preamble(limit: int = DEFAULT_LIMIT) -> str:
    """The approved-lessons block for the system prompt, or "" when the feature
    is off / there's nothing active / on any error."""
    try:
        from app.services.governance import is_scope_enabled
        if not is_scope_enabled("learning"):
            return ""
        from app.services.learning import storage
        lessons = storage.list_lessons(status="active", limit=limit)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("learning.injection: skipped (%s)", e)
        return ""
    if not lessons:
        return ""
    lines = ["Lessons learned from past feedback — apply these to your reply:"]
    for lesson in lessons:
        lines.append(f"- {lesson.text}")
    return "\n".join(lines)
