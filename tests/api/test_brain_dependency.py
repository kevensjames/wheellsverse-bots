"""Per-user BrainClient TTLCache behavior tests.

Covers the four guarantees:
  1. Same user_id → same BrainClient instance (cache hit)
  2. Different user_ids → different instances (isolation)
  3. After TTL expiry, instance is rebuilt
  4. Concurrent dependency resolution doesn't double-instantiate
"""
from __future__ import annotations

import threading
import time

import pytest

from narai.api.dependencies import brain as brain_dep


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts with an empty cache."""
    brain_dep._cache.clear()
    yield
    brain_dep._cache.clear()


def test_same_user_id_returns_cached_instance():
    a = brain_dep.get_brain(user_id="alice")
    b = brain_dep.get_brain(user_id="alice")
    assert a is b, "expected same BrainClient instance for the same user_id"


def test_different_user_ids_get_different_instances():
    alice = brain_dep.get_brain(user_id="alice")
    bob = brain_dep.get_brain(user_id="bob")
    assert alice is not bob
    assert alice.user_id == "alice"
    assert bob.user_id == "bob"


def test_ttl_expiry_rebuilds_instance(monkeypatch):
    """After the TTL window elapses, the next get_brain returns a fresh instance."""
    from cachetools import TTLCache

    # Swap in a tiny-TTL cache for the duration of this test
    small = TTLCache(maxsize=8, ttl=0.05)
    monkeypatch.setattr(brain_dep, "_cache", small)

    first = brain_dep.get_brain(user_id="charlie")
    time.sleep(0.1)  # exceed the TTL
    second = brain_dep.get_brain(user_id="charlie")
    assert first is not second, "expected a rebuilt BrainClient after TTL expiry"


def test_concurrent_resolution_does_not_double_instantiate():
    """Hammer get_brain() from many threads with the same user_id; only one
    BrainClient should ever be constructed inside the cache."""
    results: list = []

    def worker():
        results.append(brain_dep.get_brain(user_id="dana"))

    threads = [threading.Thread(target=worker) for _ in range(32)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every returned instance must be the same object
    assert all(r is results[0] for r in results), (
        "concurrent get_brain calls returned different BrainClient instances"
    )
    assert len(set(id(r) for r in results)) == 1
