"""Tests for NarAI Steps 6 + 7 — pattern storage, proactive context, and mining."""
import tempfile
import time
import pytest

from narai.core.memory import MemoryStore
from narai.core.patterns import (
    _extract_stat_patterns,
    get_proactive_context,
)


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmp:
        yield MemoryStore(data_dir=tmp)


# ── MemoryStore pattern methods ───────────────────────────────────────────────

def test_get_patterns_empty(store):
    result = store.get_patterns("user1")
    assert result == []


def test_upsert_and_get_patterns(store):
    store.upsert_pattern("user1", "interaction", "Pattern A", observations_count=5)
    store.upsert_pattern("user1", "temporal", "Pattern B", observations_count=12)

    patterns = store.get_patterns("user1", limit=3)
    assert len(patterns) == 2
    # Sorted by observations_count DESC
    assert patterns[0].description == "Pattern B"
    assert patterns[0].observations_count == 12
    assert patterns[1].description == "Pattern A"


def test_upsert_is_idempotent(store):
    store.upsert_pattern("user1", "interaction", "Repeating pattern", observations_count=3)
    store.upsert_pattern("user1", "interaction", "Repeating pattern", observations_count=7)

    patterns = store.get_patterns("user1")
    assert len(patterns) == 1
    assert patterns[0].observations_count == 7


def test_get_recent_episodes_raw_sorted(store):
    store.log_episode("user1", "[mode=operator overwhelm=none] User: first\nNarAI: ok")
    time.sleep(0.01)
    store.log_episode("user1", "[mode=companion overwhelm=mild] User: second\nNarAI: ok")
    time.sleep(0.01)
    store.log_episode("user1", "[mode=operator overwhelm=high] User: third\nNarAI: ok")

    episodes = store.get_recent_episodes_raw("user1", limit=10)
    assert len(episodes) == 3
    # Newest first
    assert "third" in episodes[0]["content"]
    assert "first" in episodes[2]["content"]


def test_get_recent_episodes_raw_empty(store):
    result = store.get_recent_episodes_raw("nobody")
    assert result == []


# ── Step 6: proactive context ─────────────────────────────────────────────────

def test_get_proactive_context_empty(store):
    ctx = get_proactive_context("user1", store)
    assert ctx == ""


def test_get_proactive_context_with_patterns(store):
    store.upsert_pattern("user1", "interaction", "User prefers short replies", 8)
    store.upsert_pattern("user1", "temporal", "High stress on Mondays", 3)

    ctx = get_proactive_context("user1", store)
    assert "Behavioral patterns detected" in ctx
    assert "User prefers short replies" in ctx
    assert "High stress on Mondays" in ctx


# ── Step 7: statistical pattern extraction ────────────────────────────────────

def _make_episodes(n_high=0, n_mild=0, n_none=0, n_companion=0, n_operator=0) -> list[dict]:
    episodes = []
    for _ in range(n_high):
        episodes.append({"content": "[mode=operator overwhelm=high] User: x\nNarAI: y", "timestamp": ""})
    for _ in range(n_mild):
        episodes.append({"content": "[mode=operator overwhelm=mild] User: x\nNarAI: y", "timestamp": ""})
    for _ in range(n_none):
        episodes.append({"content": "[mode=operator overwhelm=none] User: x\nNarAI: y", "timestamp": ""})
    for _ in range(n_companion):
        episodes.append({"content": "[mode=companion overwhelm=none] User: x\nNarAI: y", "timestamp": ""})
    for _ in range(n_operator):
        episodes.append({"content": "[mode=operator overwhelm=none] User: x\nNarAI: y", "timestamp": ""})
    return episodes


def test_stat_overwhelm_pattern_above_threshold():
    # 4 high out of 10 = 40% → pattern fires (threshold 30%)
    episodes = _make_episodes(n_high=4, n_none=6)
    patterns = _extract_stat_patterns(episodes)
    descriptions = [p["description"] for p in patterns]
    assert any("overwhelm" in d.lower() or "40%" in d for d in descriptions)


def test_stat_no_pattern_below_overwhelm_threshold():
    # 2 high out of 10 = 20% → below 30% threshold, no pattern
    episodes = _make_episodes(n_high=2, n_none=8)
    patterns = _extract_stat_patterns(episodes)
    overwhelm_patterns = [p for p in patterns if "overwhelm" in p["description"].lower()]
    assert len(overwhelm_patterns) == 0


def test_stat_companion_pattern_above_threshold():
    # 7 companion out of 10 = 70% → pattern fires (threshold 60%)
    episodes = _make_episodes(n_companion=7, n_operator=3)
    patterns = _extract_stat_patterns(episodes)
    descriptions = [p["description"] for p in patterns]
    assert any("companion" in d.lower() or "70%" in d for d in descriptions)
