"""Continuous Research — KAI scans arXiv / Hacker News / GitHub Trending
on a daily cron and surfaces items relevant to the operator's interests.

What this is:
  - 3 sources (HN top + arXiv cs.AI + GH trending) polled daily
  - Keyword scoring against KAI_RESEARCH_INTERESTS (CSV in .env)
  - One digest per cycle, stored as JSONL at data/research/digests.jsonl
  - Optional Telegram alert when any item scores ≥ HIGH (0.5)
  - Background scheduler thread, opt-in via KAI_RESEARCH_ENABLED=1

What this is NOT (deferred):
  - LLM-based relevance scoring (cost on every digest cycle)
  - Per-source weight tuning
  - Weekly / monthly rollups
  - User-facing UI (operator-only for now)

Public API:
    from app.services.research import (
        run_research_cycle,
        latest_digests,
        list_digests,
    )
"""
from app.services.research.digest import (
    Digest,
    Item,
    latest_digests,
    list_digests,
    run_research_cycle,
)

__all__ = [
    "Digest",
    "Item",
    "latest_digests",
    "list_digests",
    "run_research_cycle",
]
