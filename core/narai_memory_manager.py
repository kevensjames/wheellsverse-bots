#!/usr/bin/env python3
"""
core/narai_memory_manager.py
─────────────────────────────────────────────────────────────────────────────
NarAI Memory Manager — Tiered Persistent Memory System

MEMORY TIERS (total ≈ 170GB logical capacity):
  Tier 1 — Core Memory     (~50GB)  data/narai_memory/core/
    NarAI's internal working memory. Everything she has learned,
    all market intel, content patterns, what works per platform.
    Entries: up to 500,000 records. Auto-rotates oldest.

  Tier 2 — Market Memory   (~30GB)  data/narai_memory/market/
    Market intelligence snapshots per platform and date.
    Entries: up to 100,000 records. Replaces stale data.

  Tier 3 — Creation Memory (~30GB)  data/narai_memory/creation/
    Every piece of content NarAI has ever created + QC scores.
    NarAI uses this to never repeat herself and always improve.
    Entries: up to 100,000 records.

  Tier 4 — Personal Memory (~20GB)  data/narai_memory/personal/
    NarAI's curated insights, lessons learned, her "identity."
    Things she would NEVER forget. Her preferences. Her style.
    Entries: capped at 5,000 — only the most important survive.

  Tier 5 — Autopilot Log   (~20GB)  data/narai_memory/autopilot/
    Complete log of every autopilot session, what was published,
    what worked, what got the most engagement.
    Entries: up to 50,000 records.

FEATURES:
  - save(tier, key, content, tags, metadata)  → store a memory
  - search(query, tiers, limit)               → semantic search
  - get_context(platform, task, limit)        → NarAI pre-creation brief
  - forget(tier, key)                         → remove a memory
  - stats()                                   → memory usage overview
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

MEMORY_ROOT = ROOT / "data" / "narai_memory"

log = logging.getLogger("narai_memory_manager")


# ── Tier configuration ──────────────────────────────────────────────────────

TIERS = {
    "core": {"dir": MEMORY_ROOT / "core", "max_entries": 500_000, "gb": 50},
    "market": {"dir": MEMORY_ROOT / "market", "max_entries": 100_000, "gb": 30},
    "creation": {"dir": MEMORY_ROOT / "creation", "max_entries": 100_000, "gb": 30},
    "personal": {"dir": MEMORY_ROOT / "personal", "max_entries": 5_000, "gb": 20},
    "autopilot": {"dir": MEMORY_ROOT / "autopilot", "max_entries": 50_000, "gb": 20},
}

# Create all tier directories
for _tier in TIERS.values():
    _tier["dir"].mkdir(parents=True, exist_ok=True)

# Legacy compatibility — main narai_memory.json maps to core tier
_LEGACY_FILE = ROOT / "data" / "narai_memory.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tier_file(tier: str) -> Path:
    return TIERS[tier]["dir"] / "memory.json"


def _load_tier(tier: str) -> list:
    f = _tier_file(tier)
    try:
        if f.exists():
            return json.loads(f.read_text())
    except Exception:
        pass
    return []


def _save_tier(tier: str, entries: list):
    f = _tier_file(tier)
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(entries, indent=2, default=str))
    except Exception as e:
        log.error(f"Memory save error [{tier}]: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# CORE API
# ══════════════════════════════════════════════════════════════════════════════

def save(
    tier: str,
    key: str,
    content: str,
    tags: List[str] = None,
    metadata: Dict = None,
    importance: int = 5,  # 1-10, only matters for personal tier pruning
) -> dict:
    """
    Save a memory entry to the specified tier.
    If key already exists, it is updated (newer replaces older).
    """
    if tier not in TIERS:
        tier = "core"

    entry = {
        "key": key,
        "content": content,
        "tags": tags or [],
        "metadata": metadata or {},
        "importance": importance,
        "saved_at": _now(),
        "tier": tier,
    }

    entries = _load_tier(tier)

    # Remove existing entry with same key
    entries = [e for e in entries if e.get("key") != key]

    # Personal tier: enforce importance — push high-importance to front
    if tier == "personal":
        if importance >= 7:
            entries.insert(0, entry)
        else:
            entries.append(entry)
    else:
        entries.insert(0, entry)

    # Rotate to max size
    max_e = TIERS[tier]["max_entries"]
    if len(entries) > max_e:
        if tier == "personal":
            # Keep highest-importance entries
            entries.sort(key=lambda x: x.get("importance", 5), reverse=True)
        entries = entries[:max_e]

    _save_tier(tier, entries)

    # Keep legacy file in sync with core tier (for backwards compat)
    if tier == "core":
        _sync_legacy(entries[:5000])

    return entry


def _sync_legacy(entries: list):
    """Keep data/narai_memory.json in sync with core tier (backwards compat)."""
    try:
        _LEGACY_FILE.write_text(json.dumps(entries, indent=2, default=str))
    except Exception:
        pass


def save_market_intel(platform: str, data: dict):
    """Specialized save for market intelligence data."""
    save(
        tier="market",
        key=f"market_{platform}_{_now()[:10]}",
        content=json.dumps(data, indent=2)[:10000],
        tags=["market_intel", platform],
        metadata={"platform": platform, "date": _now()[:10]},
        importance=7,
    )
    # Also save key insight to personal tier
    insight = data.get("key_insight", "")
    if insight:
        save(
            tier="personal",
            key=f"insight_{platform}",
            content=f"[{platform.upper()} KEY INSIGHT] {insight}",
            tags=["key_insight", platform],
            importance=8,
        )


def save_creation(content_type: str, platform: str, title: str,
                  content: str, qc_score: int, published: bool):
    """Save every piece of content NarAI creates to creation memory."""
    save(
        tier="creation",
        key=f"creation_{platform}_{int(time.time())}",
        content=f"[{content_type.upper()} for {platform.upper()}]\nTitle: {title}\nQC Score: {qc_score}/100\nPublished: {published}\n\n{content[:5000]}",
        tags=["creation", content_type, platform],
        metadata={"content_type": content_type, "platform": platform,
                  "title": title, "qc_score": qc_score, "published": published},
        importance=6 if published else 4,
    )


def save_lesson(lesson: str, context: str = "", importance: int = 8):
    """Save a lesson NarAI has learned — goes to personal tier."""
    key = f"lesson_{int(time.time())}"
    save(
        tier="personal",
        key=key,
        content=f"LESSON LEARNED:\n{lesson}\n\nContext: {context}",
        tags=["lesson", "narai_growth"],
        importance=importance,
    )


def save_autopilot_session(session_id: str, stats: dict, content_count: int):
    """Save autopilot session summary."""
    save(
        tier="autopilot",
        key=f"session_{session_id}",
        content=json.dumps({
            "session_id": session_id, "stats": stats,
            "content_count": content_count, "completed_at": _now(),
        }, indent=2),
        tags=["autopilot_session", "performance"],
        importance=6,
    )


def search(
    query: str,
    tiers: List[str] = None,
    limit: int = 20,
    tags_filter: List[str] = None,
) -> List[dict]:
    """
    Simple keyword search across memory tiers.
    Returns most relevant entries (keyword matching + recency).
    """
    if tiers is None:
        tiers = list(TIERS.keys())

    query_lower = query.lower()
    query_words = set(query_lower.split())
    results = []

    for tier in tiers:
        entries = _load_tier(tier)
        for entry in entries:
            # Tag filter
            if tags_filter:
                if not any(t in entry.get("tags", []) for t in tags_filter):
                    continue
            # Score by keyword matches
            text = (entry.get("content", "") + " " + " ".join(entry.get("tags", []))).lower()
            score = sum(1 for w in query_words if w in text)
            score += entry.get("importance", 5) * 0.1  # importance boost
            if score > 0:
                results.append({**entry, "_score": score})

    results.sort(key=lambda x: (x["_score"], x.get("saved_at", "")), reverse=True)
    return results[:limit]


def get_context(platform: str, task: str, limit: int = 15) -> str:
    """
    Build NarAI's pre-creation context brief for a platform + task.
    Returns a formatted string NarAI reads before creating anything.
    """
    parts = []

    # Personal insights always included
    personal = _load_tier("personal")[:10]
    if personal:
        parts.append("=== NarAI's Core Knowledge ===")
        for e in personal[:5]:
            parts.append(f"• {e.get('content', '')[:200]}")

    # Platform market intel
    market_entries = search(platform, tiers=["market"], limit=3)
    if market_entries:
        parts.append(f"\n=== {platform.upper()} Market Intelligence ===")
        for e in market_entries[:2]:
            parts.append(e.get("content", "")[:800])

    # Recent successful creations for this platform
    creations = search(platform, tiers=["creation"], tags_filter=["creation", platform], limit=5)
    published_creations = [c for c in creations if c.get("metadata", {}).get("published")]
    if published_creations:
        parts.append(f"\n=== Previous Successful {platform.title()} Content ===")
        for c in published_creations[:3]:
            meta = c.get("metadata", {})
            parts.append(f"• [{meta.get('content_type', '')}] '{meta.get('title', '')}' — QC: {meta.get('qc_score', 0)}/100")

    # Task-specific search
    task_memories = search(task, tiers=["core", "personal"], limit=5)
    if task_memories:
        parts.append(f"\n=== Relevant Memory for: {task} ===")
        for m in task_memories[:3]:
            parts.append(f"• {m.get('content', '')[:200]}")

    return "\n".join(parts) if parts else f"No specific memory for {platform}/{task}."


def forget(tier: str, key: str) -> bool:
    """Remove a specific memory entry."""
    if tier not in TIERS:
        return False
    entries = _load_tier(tier)
    original_len = len(entries)
    entries = [e for e in entries if e.get("key") != key]
    if len(entries) < original_len:
        _save_tier(tier, entries)
        return True
    return False


def stats() -> dict:
    """Return memory usage statistics."""
    result = {}
    total_entries = 0
    for tier_name, cfg in TIERS.items():
        entries = _load_tier(tier_name)
        count = len(entries)
        total_entries += count
        f = _tier_file(tier_name)
        size_mb = round(f.stat().st_size / 1024 / 1024, 2) if f.exists() else 0
        result[tier_name] = {
            "entries": count,
            "max": cfg["max_entries"],
            "usage_pct": round(count / cfg["max_entries"] * 100, 1),
            "size_mb": size_mb,
            "capacity_gb": cfg["gb"],
        }
    result["total_entries"] = total_entries
    result["memory_root"] = str(MEMORY_ROOT)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# SYSTEM STATE ADAPTER — used by NarAICore
# ══════════════════════════════════════════════════════════════════════════════

_STATE_FILE = Path("data/system_state.json")


def load_state() -> dict:
    """
    Load lightweight system state for NarAICore goal decisions.
    Returns: {revenue, audience, assets, last_goal, consecutive_failures, total_cycles}
    """
    try:
        if _STATE_FILE.exists():
            import json
            return json.loads(_STATE_FILE.read_text())
    except Exception:
        pass
    return {
        "revenue": 0.0,
        "audience": 0,
        "assets": 0,
        "last_goal": None,
        "consecutive_failures": 0,
        "total_cycles": 0,
    }


def update_state(state: dict, goal: str, results: list, metrics: dict) -> None:
    """
    Persist system state + record cycle in autopilot memory tier.
    Called by NarAICore after each cycle.
    """
    import json, time
    from datetime import datetime, timezone

    # Update state fields
    if metrics.get("failure", 0) > metrics.get("success", 0):
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
    else:
        state["consecutive_failures"] = 0
    state["last_goal"]    = goal
    state["total_cycles"] = state.get("total_cycles", 0) + 1
    state["last_updated"] = datetime.now(timezone.utc).isoformat()

    # Persist state file
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        import logging
        logging.getLogger("narai_memory_manager").warning(f"State save failed: {e}")

    # Record in autopilot tier
    session_id = f"core_cycle_{int(time.time())}"
    save(
        tier="autopilot",
        key=session_id,
        content=json.dumps({"goal": goal, "metrics": metrics}),
        tags=["core_cycle", goal],
        importance=5,
    )

    # Record each successful task result in creation tier
    for r in results:
        if r.get("status") == "success":
            save_creation(
                content_type=r.get("task", "task"),
                platform="narai_core",
                title=r.get("task", ""),
                content=r.get("output", ""),
                qc_score=100,
                published=True,
            )


def consolidate():
    """
    Consolidate memories: remove duplicates, prune low-importance personal
    entries, merge related market intel.
    """
    consolidated = 0
    for tier_name in TIERS:
        entries = _load_tier(tier_name)
        # Remove exact duplicate content
        seen_content = set()
        unique = []
        for e in entries:
            c = e.get("content", "")[:100]  # Use first 100 chars as fingerprint
            if c not in seen_content:
                seen_content.add(c)
                unique.append(e)
        removed = len(entries) - len(unique)
        if removed > 0:
            _save_tier(tier_name, unique)
            consolidated += removed
    return {"duplicates_removed": consolidated}
