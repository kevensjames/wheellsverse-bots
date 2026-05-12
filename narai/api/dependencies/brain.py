"""Per-request BrainClient dependency with per-user TTL cache.

Each authenticated request resolves to a BrainClient instance keyed by the
JWT `sub` claim. Instances are cached for 10 minutes so streaming and
back-to-back turns reuse the same expensive construction (memory store
connections, RAG client, skill registry, tier classifier). The threading
lock guards concurrent dependency resolution under FastAPI's async loop.

Test isolation: tests can clear the cache via `_cache.clear()`.
"""
from __future__ import annotations

from threading import Lock

from cachetools import TTLCache
from fastapi import Depends

from infra.brain.interface import BrainClient
from narai.api.auth import require_auth


_cache: TTLCache = TTLCache(maxsize=128, ttl=600)
_lock = Lock()


def get_brain(user_id: str = Depends(require_auth)) -> BrainClient:
    """Return a BrainClient scoped to the authenticated user."""
    with _lock:
        client = _cache.get(user_id)
        if client is None:
            client = BrainClient(user_id=user_id, mode="narai")
            _cache[user_id] = client
        return client
