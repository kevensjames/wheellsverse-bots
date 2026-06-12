"""Injection — the always-on operator self-model in KAI's system prompt.

twin_preamble() returns the active profile as an 'operator profile' block that
nai_brain.system_prompt layers into every reply, so KAI always knows who it
serves. Gated by KAI_SCOPE_TWIN and fail-open (scope off / no entries / any
error → "", never breaks a reply).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 200


def twin_preamble(limit: int = DEFAULT_LIMIT) -> str:
    try:
        from app.services.governance import is_scope_enabled
        if not is_scope_enabled("twin"):
            return ""
        from app.services.twin import composer, storage
        active = storage.list_entries(status="active", limit=limit)
        body = composer.compose_profile(active)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("twin.injection: skipped (%s)", e)
        return ""
    if not body:
        return ""
    return "Operator profile (your principal — tailor your replies to them):\n" + body
