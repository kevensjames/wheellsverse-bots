"""document_search tool — formats RAG hits into cited passages, fails soft."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from app.services.tools.base import ToolContext, ToolError
from app.services.tools.document_search import DocumentSearchTool


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def test_returns_cited_passages(monkeypatch):
    import app.services.rag as rag
    monkeypatch.setattr(rag, "retrieve", lambda *a, **k: [
        {"chunk_id": "x", "doc_id": "d", "position": 3,
         "content": "Stage II hypertension: start two agents.",
         "filename": "guidelines.pdf", "distance": 0.12},
    ])
    out = DocumentSearchTool().execute(_ctx(), query="hypertension protocol")
    assert out["count"] == 1
    p = out["passages"][0]
    assert p["source"] == "guidelines.pdf" and p["position"] == 3
    assert p["relevance"] == round(1.0 - 0.12, 3)   # cosine distance → similarity
    assert "source:" in out["note"]


def test_empty_knowledge_base(monkeypatch):
    import app.services.rag as rag
    monkeypatch.setattr(rag, "retrieve", lambda *a, **k: [])
    out = DocumentSearchTool().execute(_ctx(), query="anything")
    assert out["count"] == 0 and out["passages"] == []
    assert "No indexed documents" in out["note"]


def test_blank_query_raises():
    with pytest.raises(ToolError):
        DocumentSearchTool().execute(_ctx(), query="   ")


def test_k_is_clamped(monkeypatch):
    import app.services.rag as rag
    seen = {}
    def _capture(db, *, user_id, query, k):
        seen["k"] = k
        return []
    monkeypatch.setattr(rag, "retrieve", _capture)
    DocumentSearchTool().execute(_ctx(), query="x", k=999)
    assert seen["k"] == 12   # clamped to max


def test_retrieve_failure_is_tool_error(monkeypatch):
    import app.services.rag as rag
    monkeypatch.setattr(rag, "retrieve", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    with pytest.raises(ToolError):
        DocumentSearchTool().execute(_ctx(), query="x")
