"""Rule-based intent classifier. v1.

Single regex pass over the user's last message. Replace with a learned
classifier once we have a labeled production sample.
"""
from __future__ import annotations

import re

from app.services.router.types import Intent


_CODE_SIGNALS = (
    r"\bcode\b", r"\bfunction\b", r"\bdebug\b", r"\berror\b", r"\bexception\b",
    r"\bimplement\b", r"\brefactor\b", r"\btraceback\b", r"\bstack trace\b",
    r"```", r"\bpython\b", r"\bjavascript\b", r"\btypescript\b", r"\bsql\b",
    r"\bregex\b", r"\balgorithm\b", r"\bcomplexity\b", r"\bO\([1n]", r"\bAPI\b",
    r"\bclass\b", r"\bmethod\b", r"\bvariable\b", r"\bimport\b",
)

_REALTIME_SIGNALS = (
    r"\btoday\b", r"\bcurrent\b", r"\blatest\b", r"\bright now\b",
    r"\bthis (week|month|year)\b", r"\bnews\b", r"\bprice of\b",
    r"\bstock\b", r"\bweather\b", r"\bwhat's happening\b",
    r"\bwho is\b.*\b(president|ceo|leader)\b", r"\bjust released\b",
    r"\brecent(ly)?\b", r"\b202[6-9]\b", r"\b203\d\b",
)


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def classify_intent(message: str) -> Intent:
    """Single-pass classifier. Order matters — code is checked first (more specific)."""
    if _matches_any(message, _CODE_SIGNALS):
        return Intent.CODE
    if _matches_any(message, _REALTIME_SIGNALS):
        return Intent.REALTIME
    return Intent.GENERAL
