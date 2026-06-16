"""Failure memory — append-only log of KAI's failed actions so the next
attempt at a similar task can warn the user instead of repeating the
mistake.

What gets recorded:
  - Tool calls that returned errors during the chat loop
  - LLM provider failures that the router caught
  - Manual entries (the operator can explicitly teach KAI "this is what
    breaks when you do X")

How it's used:
  - At chat time, build_memory_preamble pulls top-K failures matching
    the current prompt (simple Jaccard similarity on tokens) and
    prepends them to the system prompt as a "⚠️ past failures" block
  - KAI gets a `failure_lookup` tool to explicitly check for similar
    failures before attempting a risky action

Storage: JSONL at data/failures.jsonl. Same pattern as the governance
audit log — append-only, grep-friendly, no DB schema changes. Future:
migrate to pgvector when there's enough volume that embedding lookup
beats keyword overlap.
"""
from app.services.failure_memory.storage import (
    FAILURE_LOG_PATH,
    Failure,
    find_recent_similar,
    list_recent,
    record_failure,
)

__all__ = [
    "FAILURE_LOG_PATH",
    "Failure",
    "find_recent_similar",
    "list_recent",
    "record_failure",
]
