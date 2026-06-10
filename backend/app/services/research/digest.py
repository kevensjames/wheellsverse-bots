"""Research digest orchestrator — runs the daily cycle.

One cycle:
  1. Fetch from all 3 sources (parallel via threads)
  2. Score every item against operator interests
  3. Compose a digest (top-K per source by score)
  4. Persist to data/research/digests.jsonl (one digest per line)
  5. Telegram alert if any item scored ≥ HIGH

Storage: JSONL like the audit + failure logs. Each line is one full
digest including the top items. Reader-side helpers (latest_digests,
list_digests) load + filter in memory — file size will stay small at
1 cycle/day for a long time.

Routes through @audited(scope="research.run_cycle") so every digest
generation lands in the governance audit log too.
"""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.research.scorer import (
    HIGH_THRESHOLD,
    load_interests,
    score_items,
    severity,
)
from app.services.research.sources import (
    Item,
    fetch_arxiv,
    fetch_gh_trending,
    fetch_hn,
)

logger = logging.getLogger(__name__)

# 5 parents up: digest.py → research → services → app → backend → REPO
_REPO_ROOT = Path(__file__).resolve().parents[4]

DIGESTS_PATH = Path(
    os.environ.get(
        "KAI_RESEARCH_DIGESTS_PATH",
        str(_REPO_ROOT / "data" / "research" / "digests.jsonl"),
    )
)
DIGESTS_PATH.parent.mkdir(parents=True, exist_ok=True)


# Top items per source kept in the digest. Smaller than the fetch top_n
# because we don't need to surface the long tail — the scoring already
# bubbled the relevant stuff to the top.
PER_SOURCE_KEEP = 5


@dataclass(slots=True)
class Digest:
    id: str
    generated_at: str
    interests: list[str]
    severity_counts: dict[str, int]
    top_by_source: dict[str, list[dict[str, Any]]]
    high_count: int
    total_items_fetched: int


# Item type re-exported for downstream typing
__all_dataclasses__ = (Digest, Item)


# ─── one cycle ───────────────────────────────────────────────────────


def run_research_cycle() -> Digest:
    """Run one full cycle: fetch → score → persist → maybe-alert.

    Source failures don't stop the cycle — the digest just reflects
    whatever came back. If ALL three fail (unlikely), the digest is
    still recorded with empty source buckets so the operator sees
    "research ran but every source 0'd".
    """
    interests = load_interests()
    started = datetime.now(timezone.utc)

    # Parallel fetch — three independent network calls
    with ThreadPoolExecutor(max_workers=3) as ex:
        hn_f = ex.submit(_safe, fetch_hn)
        arxiv_f = ex.submit(_safe, fetch_arxiv)
        gh_f = ex.submit(_safe, fetch_gh_trending)
        hn_items = hn_f.result()
        arxiv_items = arxiv_f.result()
        gh_items = gh_f.result()

    all_items = hn_items + arxiv_items + gh_items
    score_items(all_items, interests)

    # Bucket by source, keep top-K per source
    buckets: dict[str, list[Item]] = {"hn": [], "arxiv": [], "gh_trending": []}
    for it in all_items:
        if it.source in buckets:
            buckets[it.source].append(it)
    top_by_source: dict[str, list[dict[str, Any]]] = {}
    for src, items in buckets.items():
        items.sort(key=lambda x: x.score, reverse=True)
        top_by_source[src] = [_item_to_dict(x) for x in items[:PER_SOURCE_KEEP]]

    sev_counts = {"high": 0, "medium": 0, "low": 0, "none": 0}
    for it in all_items:
        sev_counts[severity(it.score)] += 1

    high_count = sev_counts["high"]
    digest_id = started.strftime("%Y%m%dT%H%M%SZ")
    digest = Digest(
        id=digest_id,
        generated_at=started.isoformat(),
        interests=interests,
        severity_counts=sev_counts,
        top_by_source=top_by_source,
        high_count=high_count,
        total_items_fetched=len(all_items),
    )

    _append(digest)
    logger.info(
        "research: cycle %s done — fetched=%d high=%d",
        digest_id, len(all_items), high_count,
    )

    # Telegram alert on HIGH items (uses Supreme's helper — same
    # TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env vars)
    if high_count > 0:
        try:
            from app.services.supreme.scanner import telegram_send
            telegram_send(_format_for_telegram(digest))
        except Exception as e:
            logger.warning("research: telegram alert swallowed: %s", e)

    return digest


# ─── read side ───────────────────────────────────────────────────────


def list_digests(limit: int = 30) -> list[dict[str, Any]]:
    """Return digest summaries (no top items), newest-first. Cheap header
    rows for the admin panel."""
    if not DIGESTS_PATH.exists():
        return []
    limit = max(1, min(int(limit), 365))
    out: list[dict[str, Any]] = []
    try:
        with DIGESTS_PATH.open() as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                out.append({
                    "id": d.get("id"),
                    "generated_at": d.get("generated_at"),
                    "severity_counts": d.get("severity_counts"),
                    "high_count": d.get("high_count"),
                    "total_items_fetched": d.get("total_items_fetched"),
                })
    except Exception as e:
        logger.warning("research: read digests failed: %s", e)
        return []
    out.reverse()
    return out[:limit]


def latest_digests(n: int = 1) -> list[dict[str, Any]]:
    """Full digest objects, newest-first."""
    if not DIGESTS_PATH.exists():
        return []
    out: list[dict[str, Any]] = []
    try:
        with DIGESTS_PATH.open() as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.warning("research: read digests failed: %s", e)
        return []
    out.reverse()
    return out[: max(1, n)]


# ─── helpers ────────────────────────────────────────────────────────


def _safe(fn):
    """Wrap a fetcher so it returns [] on any exception instead of
    blowing up the cycle."""
    try:
        return fn()
    except Exception as e:
        logger.warning("research: %s raised: %s", fn.__name__, e)
        return []


def _item_to_dict(it: Item) -> dict[str, Any]:
    return {
        "source": it.source,
        "title": it.title,
        "url": it.url,
        "summary": it.summary,
        "score": round(it.score, 3),
        "severity": severity(it.score),
        "metadata": it.metadata,
    }


def _append(d: Digest) -> None:
    """Append-only. Swallow write errors (same audit-log pattern)."""
    try:
        with DIGESTS_PATH.open("a") as fp:
            fp.write(json.dumps(asdict(d), default=str) + "\n")
    except Exception as e:
        logger.warning("research: digest append failed: %s", e)


def _format_for_telegram(d: Digest) -> str:
    """Compose the alert. Caps lines so an unusually fat digest doesn't
    blow the Telegram 4096-char limit."""
    lines = [
        f"*KAI Research — {d.high_count} high-relevance item(s)*",
        f"fetched {d.total_items_fetched} across HN+arXiv+GH",
        "",
    ]
    for src in ("hn", "arxiv", "gh_trending"):
        items = d.top_by_source.get(src) or []
        high = [i for i in items if i.get("severity") == "high"]
        if not high:
            continue
        lines.append(f"_{src}_")
        for i in high[:3]:
            lines.append(f"  • {i.get('title', '')[:120]}")
            url = i.get("url", "")
            if url:
                lines.append(f"    {url}")
        lines.append("")
    return "\n".join(lines)[:4000]
