"""Item scorer — Jaccard overlap between item text and operator interests.

Configuration: KAI_RESEARCH_INTERESTS env var, CSV-style:
    KAI_RESEARCH_INTERESTS=ai-agents,llm,wheellsverse,stripe,supabase,...

Each interest is normalized to lowercased tokens. Items get a score in
[0, 1] based on token overlap between (title + summary + topics) and the
interests set. Items above HIGH_THRESHOLD (0.5) trigger Telegram alerts.

Why keyword scoring instead of LLM:
  - One digest cycle hits 80-100 items. LLM scoring each = ~$0.05/day
    on the cheap CF tier or ~$0.50/day on GPT-4o. Acceptable but real.
  - Keyword overlap is deterministic, free, and good enough to filter
    the obvious noise.
  - Future: optional LLM rescoring pass on the top-K only (cheap and
    higher precision than per-item LLM).
"""
from __future__ import annotations

import logging
import os
import re

from app.services.research.sources import Item

logger = logging.getLogger(__name__)

HIGH_THRESHOLD = 0.5
MEDIUM_THRESHOLD = 0.25

_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at",
    "by", "for", "with", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall", "can",
    "this", "that", "these", "those", "we", "i", "you", "they", "it",
    "what", "when", "where", "why", "how", "who", "which",
})


def load_interests() -> list[str]:
    """Pull KAI_RESEARCH_INTERESTS from env, normalize to lowercased
    multi-token phrases. Empty list = no scoring (everything gets 0).
    """
    raw = (os.environ.get("KAI_RESEARCH_INTERESTS") or "").strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",")]
    return [p.lower() for p in parts if p]


def score_item(item: Item, interests: list[str]) -> float:
    """Return a score in [0, 1] for how well this item matches operator
    interests.

    Algorithm:
      1. Build the item's token bag from title + summary + topics.
      2. For each interest phrase, see if its tokens are a SUBSET of the
         item's bag.
      3. Score = matches / len(interests), clamped to [0, 1].

    Multi-token interest phrases ("ai agents", "knowledge graph") are
    treated as a single hit if ALL their tokens appear in the item bag.
    This gives more signal than scoring each token independently — a
    paper about "graph databases" shouldn't trigger on the "graph" half
    of "knowledge graph".
    """
    if not interests:
        return 0.0

    item_tokens = _tokenize(
        " ".join([
            item.title or "",
            item.summary or "",
            " ".join((item.metadata or {}).get("topics") or []),
        ])
    )
    if not item_tokens:
        return 0.0

    hits = 0
    for phrase in interests:
        ph_tokens = _tokenize(phrase)
        if not ph_tokens:
            continue
        if ph_tokens.issubset(item_tokens):
            hits += 1

    return min(1.0, hits / max(1, len(interests)))


def score_items(items: list[Item], interests: list[str] | None = None) -> list[Item]:
    """Mutating: writes .score onto each item AND returns the same list,
    sorted by score descending."""
    interests = interests if interests is not None else load_interests()
    for it in items:
        it.score = score_item(it, interests)
    items.sort(key=lambda x: x.score, reverse=True)
    return items


def severity(score: float) -> str:
    """Categorize for the digest header + alert routing."""
    if score >= HIGH_THRESHOLD:
        return "high"
    if score >= MEDIUM_THRESHOLD:
        return "medium"
    if score > 0:
        return "low"
    return "none"


# ─── helpers ────────────────────────────────────────────────────────


def _tokenize(text: str) -> set[str]:
    """Lowercase alnum tokens, stopwords + sub-3-char removed."""
    return {
        w for w in re.findall(r"[a-z][a-z0-9]+", (text or "").lower())
        if len(w) >= 3 and w not in _STOPWORDS
    }
