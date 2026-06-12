"""Failure-log storage — JSONL append-only with simple keyword similarity.

Why JSONL instead of pgvector:
  - Zero migration risk on prod Supabase (matches the KG MVP approach)
  - One file, easy to grep / rotate / back up
  - Keyword overlap (Jaccard on lowercased tokens) is good enough until
    we have enough failure volume to justify embedding cost per chat turn
  - Upgrade path: when the file grows past ~100K lines, batch-embed
    historical failures into a pgvector table and switch the similarity
    search there. Same record shape, no caller changes.

Each failure record:
  id           uuid hex
  ts           ISO-8601 UTC
  user_id      who was in chat when this happened (str or null)
  prompt       the user message that triggered the failure (truncated)
  category     tool_error / llm_error / manual / other
  tool_name    when category=tool_error
  adapter      when category=llm_error
  detail       what went wrong (short)
  context      free-form dict (preserved if write fails — silent failures
               are worse than verbose ones in an audit context)
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 5 parents: storage.py → failure_memory → services → app → backend → REPO
_REPO_ROOT = Path(__file__).resolve().parents[4]

FAILURE_LOG_PATH = Path(
    os.environ.get(
        "KAI_FAILURE_LOG_PATH",
        str(_REPO_ROOT / "data" / "failures.jsonl"),
    )
)
FAILURE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# Don't let a single failure record bloat the log file — 800 chars/field
# fits comfortably under POSIX PIPE_BUF (4096) for atomic appends.
_MAX_FIELD_LEN = 800

# Tokens shorter than 3 chars or in this stopword set are dropped before
# Jaccard similarity. Reduces noise from "the", "a", "is", etc.
_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "at", "by",
    "for", "with", "from", "as", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall", "can", "this", "that",
    "these", "those", "i", "you", "he", "she", "it", "we", "they", "me",
    "him", "her", "us", "them", "my", "your", "his", "its", "our", "their",
    "what", "when", "where", "why", "how", "who", "which",
})


@dataclass(slots=True)
class Failure:
    id: str
    ts: str
    user_id: str | None
    prompt: str
    category: str
    tool_name: str | None
    adapter: str | None
    detail: str
    context: dict[str, Any] = field(default_factory=dict)
    # _score is set during find_recent_similar to the Jaccard overlap with
    # the query. 0.0 means "not from a similarity search" or "perfect miss".
    # It's an instance field (not a property) so it works under slots=True.
    _score: float = 0.0

    @property
    def similarity_score(self) -> float:
        return self._score


# ─── write side ─────────────────────────────────────────────────────


def record_failure(
    *,
    prompt: str,
    detail: str,
    category: str = "tool_error",
    tool_name: str | None = None,
    adapter: str | None = None,
    user_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> Failure:
    """Append a failure record. Returns the record so the caller can pass
    its id back to a response if useful.

    Never raises — a write failure here is logged at WARNING but never
    breaks the action that's being audited (we'd rather lose one failure
    record than break a user's chat).
    """
    rec = Failure(
        id=uuid.uuid4().hex,
        ts=datetime.now(timezone.utc).isoformat(),
        user_id=user_id,
        prompt=_truncate(prompt or ""),
        category=(category or "other").strip().lower(),
        tool_name=tool_name,
        adapter=adapter,
        detail=_truncate(detail or ""),
        context=_truncate_dict(context or {}),
    )
    try:
        with FAILURE_LOG_PATH.open("a") as fp:
            fp.write(json.dumps(asdict(rec), default=str) + "\n")
    except Exception as e:
        logger.warning(
            "failure_memory: write failed for category=%s tool=%s — %s",
            category, tool_name, e,
        )
    return rec


# ─── read side ──────────────────────────────────────────────────────


def list_recent(
    *,
    limit: int = 50,
    category: str | None = None,
    tool_name: str | None = None,
    since: datetime | None = None,
) -> list[Failure]:
    """Newest-first slice. Filters in Python because the file fits in
    memory; revisit when it doesn't."""
    if not FAILURE_LOG_PATH.exists():
        return []
    limit = max(1, min(int(limit), 500))
    out: list[Failure] = []
    try:
        with FAILURE_LOG_PATH.open() as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec_dict = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if category and rec_dict.get("category") != category:
                    continue
                if tool_name and rec_dict.get("tool_name") != tool_name:
                    continue
                if since:
                    ts = _parse_ts(rec_dict.get("ts"))
                    if ts is None or ts < since:
                        continue
                out.append(_dict_to_failure(rec_dict))
    except Exception as e:
        logger.warning("failure_memory: read failed: %s", e)
        return []
    out.reverse()  # newest first
    return out[:limit]


def find_recent_similar(
    query: str,
    *,
    k: int = 3,
    min_score: float = 0.10,
    window_days: int = 30,
) -> list[Failure]:
    """Top-K failures whose prompt has the highest Jaccard overlap with
    the query. Score ≤ min_score is filtered out so we don't surface
    noise as "past failure".

    window_days limits how far back we look (older failures are less
    likely to be relevant and would otherwise dominate as the log grows)."""
    if not query or not query.strip():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, int(window_days)))
    query_tokens = _tokens(query)
    if not query_tokens:
        return []

    scored: list[Failure] = []
    for f in list_recent(limit=500, since=cutoff):
        f_tokens = _tokens(f.prompt + " " + f.detail)
        score = _jaccard(query_tokens, f_tokens)
        if score < min_score:
            continue
        f._score = score
        scored.append(f)

    scored.sort(key=lambda f: f._score, reverse=True)
    return scored[: max(1, int(k))]


# ─── helpers ────────────────────────────────────────────────────────


def _truncate(s: str) -> str:
    if not isinstance(s, str):
        s = str(s)
    if len(s) > _MAX_FIELD_LEN:
        return s[:_MAX_FIELD_LEN] + f"… ({len(s)} chars)"
    return s


def _truncate_dict(d: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in d.items():
        if isinstance(v, str):
            out[k] = _truncate(v)
        elif isinstance(v, (int, float, bool, type(None))):
            out[k] = v
        else:
            out[k] = _truncate(repr(v))
    return out


def _tokens(text: str) -> set[str]:
    """Lowercase word tokens, stopwords + sub-3-char tokens removed."""
    return {
        w for w in re.findall(r"[a-z][a-z0-9]+", (text or "").lower())
        if len(w) >= 3 and w not in _STOPWORDS
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    if union == 0:
        return 0.0
    return inter / union


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def _dict_to_failure(d: dict[str, Any]) -> Failure:
    return Failure(
        id=d.get("id", ""),
        ts=d.get("ts", ""),
        user_id=d.get("user_id"),
        prompt=d.get("prompt", ""),
        category=d.get("category", "other"),
        tool_name=d.get("tool_name"),
        adapter=d.get("adapter"),
        detail=d.get("detail", ""),
        context=d.get("context", {}) or {},
    )
