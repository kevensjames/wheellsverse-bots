"""Injection — KAI's own persona at the TOP of the system prompt.

persona_preamble() returns the active persona as a 'who you are' block that
nai_brain.system_prompt layers FIRST (model attention treats it as primary
identity). Gated by KAI_SCOPE_PERSONA and fail-open (scope off / no traits /
any error → "", never breaks a reply).

This is what turns KAI from a neutral assistant into a warm, consistent
companion — distinct from the twin (who the OPERATOR is) and lessons (behavioral
fixes from feedback).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 200


def persona_preamble(limit: int = DEFAULT_LIMIT) -> str:
    try:
        from app.services.governance import is_scope_enabled
        if not is_scope_enabled("persona"):
            return ""
        from app.services.persona import composer, storage
        active = storage.list_entries(status="active", limit=limit)
        body = composer.compose_persona(active)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("persona.injection: skipped (%s)", e)
        return ""
    if not body:
        return ""
    return (
        "WHO YOU ARE — embody this character in every reply (it defines your "
        "voice, humor, and values; speak as this person, never break it):\n" + body
    )
