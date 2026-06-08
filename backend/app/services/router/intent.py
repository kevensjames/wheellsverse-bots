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

# Conservative SIMPLE signals — only match when the user is clearly asking
# for something an 8B Llama can handle: definitions, summaries, translations,
# spelling, simple yes/no. We deliberately keep this list small; false
# positives route a complex query to the cheapest (weakest) model and
# degrade UX. Pair with the length cap below — long messages stay GENERAL.
_SIMPLE_SIGNALS = (
    r"^\s*(what is|what's|whats)\b",
    r"^\s*(define|definition of)\b",
    r"^\s*(summari[sz]e|summary of|tl;?dr)\b",
    r"^\s*translate\b",
    r"^\s*spell\b",
    r"^\s*list\s+(\d+|some|a few|the)\b",
    r"^\s*(yes or no|true or false):",
    r"^\s*synonyms? (for|of)\b",
)

# Max chars for a SIMPLE-eligible message. Longer than this almost always
# means context or multi-step reasoning the cheap model will fumble.
_SIMPLE_MAX_CHARS = 200


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def classify_intent(message: str) -> Intent:
    """Single-pass classifier. Order matters:

    1. CODE — most specific signals, checked first
    2. REALTIME — needs fresh web data
    3. SIMPLE — short, low-reasoning prompts (cheapest adapter)
    4. GENERAL — default fallback

    SIMPLE comes AFTER code/realtime so anything that looks like code or
    needs fresh data isn't downgraded to the cheap model.
    """
    if _matches_any(message, _CODE_SIGNALS):
        return Intent.CODE
    if _matches_any(message, _REALTIME_SIGNALS):
        return Intent.REALTIME
    if len(message) <= _SIMPLE_MAX_CHARS and _matches_any(message, _SIMPLE_SIGNALS):
        return Intent.SIMPLE
    return Intent.GENERAL
