"""Tests for the ChromaDB-backed memory layer (module-level vector API).

These exercise the real Chroma pipeline (embed → upsert → query → score).
The ``real_chroma`` marker opts out of the conftest's chroma-mocking
fixture and routes us through an isolated, on-disk per-test Chroma
instance instead.
"""
import pytest

# All tests in this file need real ChromaDB.
pytestmark = pytest.mark.real_chroma


def test_remember_and_recall():
    from infra.brain.memory import count, recall, remember

    remember("test_key", "NarAI is a personal AI assistant for J.K. Blaze", tags=["narai"])
    assert count() == 1

    results = recall("personal AI assistant")
    assert len(results) == 1
    assert results[0]["key"] == "test_key"
    assert results[0]["score"] > 0


def test_forget():
    from infra.brain.memory import count, forget, remember

    remember("to_delete", "temporary memory entry")
    assert count() == 1
    result = forget("to_delete")
    assert result is True
    assert count() == 0


def test_recall_context_format():
    from infra.brain.memory import recall_context, remember

    remember("mk1", "BTCUSD is trending bullish on the 4h chart", tags=["trading"])
    ctx = recall_context("bitcoin trading")
    assert "[MEMORY CONTEXT]" in ctx
    assert "mk1" in ctx


def test_multiple_memories_ranked():
    from infra.brain.memory import recall, remember

    remember("m1", "Python is great for data science and ML pipelines")
    remember("m2", "FastAPI is an async web framework for Python")
    remember("m3", "Bitcoin halving occurs every four years")

    results = recall("async Python web development", n=3)
    # FastAPI result should score higher than Bitcoin for this query
    keys = [r["key"] for r in results]
    assert "m2" in keys
