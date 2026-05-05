"""Tests for ChromaDB memory layer using a temp directory."""
import os
import pytest


@pytest.fixture(autouse=True)
def temp_chroma(tmp_path, monkeypatch):
    monkeypatch.setenv("NARAI_CHROMA_PATH", str(tmp_path / "chroma"))
    # Reset module-level singletons so each test gets a fresh collection
    import narai.core.memory as m
    m._client = None
    m._collection = None
    yield
    m._client = None
    m._collection = None


def test_remember_and_recall():
    from narai.core.memory import count, recall, remember

    remember("test_key", "NarAI is a personal AI assistant for J.K. Blaze", tags=["narai"])
    assert count() == 1

    results = recall("personal AI assistant")
    assert len(results) == 1
    assert results[0]["key"] == "test_key"
    assert results[0]["score"] > 0


def test_forget():
    from narai.core.memory import count, forget, remember

    remember("to_delete", "temporary memory entry")
    assert count() == 1
    result = forget("to_delete")
    assert result is True
    assert count() == 0


def test_recall_context_format():
    from narai.core.memory import recall_context, remember

    remember("mk1", "BTCUSD is trending bullish on the 4h chart", tags=["trading"])
    ctx = recall_context("bitcoin trading")
    assert "[MEMORY CONTEXT]" in ctx
    assert "mk1" in ctx


def test_multiple_memories_ranked():
    from narai.core.memory import recall, remember

    remember("m1", "Python is great for data science and ML pipelines")
    remember("m2", "FastAPI is an async web framework for Python")
    remember("m3", "Bitcoin halving occurs every four years")

    results = recall("async Python web development", n=3)
    # FastAPI result should score higher than Bitcoin for this query
    keys = [r["key"] for r in results]
    assert "m2" in keys
