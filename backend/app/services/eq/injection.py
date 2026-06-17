"""Injection — per-message emotional context for KAI's system prompt.

analyze(text) is the single entry point used by nai_brain: it detects the mood
of the CURRENT operator message and returns (mood, confidence, preamble). The
preamble is a short 'read the room' directive layered near the end of the system
prompt (most salient, immediate context). Gated by KAI_SCOPE_EQ and fail-open
(scope off / neutral / any error → ("neutral", 0.0, "")).

The brain persists the (mood, confidence) sample for the mood-history dashboard;
this module only classifies + composes the directive.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def analyze(text: str) -> tuple[str, float, str]:
    """Return (mood, confidence, preamble). Empty preamble for neutral/off."""
    try:
        from app.services.governance import is_scope_enabled
        if not is_scope_enabled("eq"):
            return "neutral", 0.0, ""
        from app.services.eq.adaptation import directive_for
        from app.services.eq.detection import detect_mood
        mood, confidence = detect_mood(text)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("eq.injection: skipped (%s)", e)
        return "neutral", 0.0, ""
    directive = directive_for(mood)
    if not directive:
        return mood, confidence, ""
    preamble = (
        "EMOTIONAL CONTEXT (read the room and adapt your tone — never mention this "
        "analysis or that you detected a mood):\n" + directive
    )
    return mood, confidence, preamble
