#!/usr/bin/env python3
"""
core/dedup.py
─────────────────────────────────────────────────────────────────────────────
Execution-level deduplication for WheellsVerse bots.

Stops double-triggered runs from burning API credits. The screenshots showed
"The Wrong Confession" generated twice in the same minute, NEXORA landing.html
built twice, Coinbase Daily posted twice — all wasted tokens. This module
prevents that.

Distinct from `BaseBot.topic_is_duplicate` (which suppresses same-topic runs
over a 7-day window). This module suppresses same-execution runs (same bot +
action + args) within a short TTL.

Backend: Redis (atomic SET NX EX) with filesystem fallback. The filesystem
fallback is important — if Redis is transiently unreachable, bots should
still have SOME dedup, just weaker.

Env:
    REDIS_URL         — optional; falls back to filesystem if unset or down
    DEDUP_CACHE_DIR   — filesystem fallback dir (default /tmp/wv_dedup)

Public API:
    is_duplicate(agent, payload, ttl_seconds) -> bool
    dedup_guard(agent, ttl_seconds=3600, ...) — decorator

Both are idempotent: first caller gets False (proceed), subsequent callers
within TTL get True (skip).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Optional

# ─── Redis init (graceful) ───────────────────────────────────────────────────
_redis_client = None
try:
    import redis  # type: ignore

    _REDIS_URL = os.getenv("REDIS_URL")
    if _REDIS_URL:
        # short timeouts — we don't want dedup itself to block bot execution
        _redis_client = redis.from_url(
            _REDIS_URL,
            socket_timeout=2,
            socket_connect_timeout=2,
            decode_responses=True,
        )
        # ping once at import so we fail fast to fs fallback if misconfigured
        try:
            _redis_client.ping()
        except Exception:
            _redis_client = None
except Exception:
    _redis_client = None

_FALLBACK_DIR = Path(os.getenv("DEDUP_CACHE_DIR", "/tmp/wv_dedup"))
_FALLBACK_DIR.mkdir(parents=True, exist_ok=True)


# ─── Helpers ─────────────────────────────────────────────────────────────────
def _hash_content(content: Any) -> str:
    """Stable short hash of any serializable payload."""
    if not isinstance(content, (str, bytes)):
        content = json.dumps(content, sort_keys=True, default=str)
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()[:16]


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _redis_mark(key: str, ttl: int) -> bool:
    """Atomic set-if-not-exists. Returns True if this caller inserted (new)."""
    # SET NX EX — Redis guarantees atomicity across concurrent callers
    inserted = _redis_client.set(key, "1", nx=True, ex=ttl)
    return bool(inserted)


def _file_mark(key: str, ttl: int) -> bool:
    """Filesystem fallback. Returns True if newly marked (i.e., not a dup)."""
    safe = key.replace(":", "_").replace("/", "_")
    path = _FALLBACK_DIR / f"{safe}.marker"
    now = time.time()
    if path.exists():
        age = now - path.stat().st_mtime
        if age < ttl:
            return False
    path.touch()
    return True


# ─── Public API ──────────────────────────────────────────────────────────────
def is_duplicate(agent: str, payload: Any, ttl_seconds: int = 3600) -> bool:
    """
    Atomically mark (agent, payload) as seen for ttl_seconds. Return True if
    already seen within TTL, False if this is the first sighting (proceed).

    Callers should short-circuit when True is returned.
    """
    key = f"wv:dedup:{agent}:{_today_utc()}:{_hash_content(payload)}"

    if _redis_client:
        try:
            inserted = _redis_mark(key, ttl_seconds)
            # `inserted` True means we claimed the slot → not a duplicate
            return not inserted
        except Exception:
            pass  # fall through to filesystem
    inserted = _file_mark(key, ttl_seconds)
    return not inserted


def dedup_guard(
    agent: str,
    ttl_seconds: int = 3600,
    fingerprint_arg: Optional[str] = None,
    on_skip: Optional[Callable[[str], None]] = None,
):
    """
    Decorator that short-circuits duplicate executions.

    Args:
        agent: agent name for namespacing (e.g. "104_finance_agent").
        ttl_seconds: how long to suppress duplicates (default 1h).
        fingerprint_arg: if set, hashes only kwargs[fingerprint_arg] instead
            of all args+kwargs. Useful when call signatures include an
            unstable argument (e.g. timestamp) that would defeat dedup.
        on_skip: optional callback when a duplicate is suppressed.
    """

    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if fingerprint_arg:
                payload = kwargs.get(fingerprint_arg)
            else:
                payload = {"fn": func.__name__, "args": args, "kwargs": kwargs}
            if is_duplicate(agent, payload, ttl_seconds):
                msg = (
                    f"[dedup] {agent}:{func.__name__} suppressed "
                    f"(duplicate within {ttl_seconds}s)"
                )
                if on_skip:
                    on_skip(msg)
                else:
                    print(msg)
                return None
            return func(*args, **kwargs)

        return wrapper

    return decorator


def backend() -> str:
    """Report which backend is active — useful for health checks."""
    return "redis" if _redis_client else "filesystem"
