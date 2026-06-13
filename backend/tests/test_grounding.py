"""Phase 2 — grounding.verify_statement: RAG-grounded fact-check with a verdict
+ blended confidence, fail-soft. Plus the verify_claim tool wrapper.
Mocks rag.retrieve + the LLM router (no DB, no network)."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.services.rag as rag
from app.services import grounding


def _router(content, *, cost=0.001):
    r = MagicMock()
    r.complete.return_value = SimpleNamespace(content=content, total_cost_usd=cost)
    return r


def _chunks(distance=0.1):
    return [{"chunk_id": "c", "doc_id": "d", "position": 1,
             "content": "Target BP <130/80 for stage II hypertension.",
             "filename": "jnc8.pdf", "distance": distance}]


def _verify(monkeypatch, *, chunks, router):
    monkeypatch.setattr(rag, "retrieve", lambda *a, **k: chunks)
    return grounding.verify_statement(
        db=MagicMock(), router=router, user_id=uuid.uuid4(),
        statement="Stage II hypertension targets BP under 130/80.",
    )


def test_no_sources_refuses(monkeypatch):
    out = _verify(monkeypatch, chunks=[], router=MagicMock())
    assert out["verdict"] == "no_sources"
    assert out["supported"] is False and out["confidence"] == "low"


def test_supported_with_strong_retrieval_is_high(monkeypatch):
    r = _router('{"verdict":"supported","confidence":"high","supporting_sources":[1],"reason":"source 1 states it"}')
    out = _verify(monkeypatch, chunks=_chunks(distance=0.1), router=r)
    assert out["verdict"] == "supported" and out["supported"] is True
    assert out["confidence"] == "high"
    assert out["support"][0]["source"] == "jnc8.pdf" and out["support"][0]["position"] == 1


def test_weak_retrieval_downgrades_confidence(monkeypatch):
    # LLM says supported/high, but retrieval similarity is low (distance 0.85) →
    # blended confidence must NOT be high.
    r = _router('{"verdict":"supported","confidence":"high","supporting_sources":[1],"reason":"x"}')
    out = _verify(monkeypatch, chunks=_chunks(distance=0.85), router=r)
    assert out["verdict"] == "supported"
    assert out["confidence"] == "low"   # top similarity < 0.30 → not trusted


def test_contradicted(monkeypatch):
    r = _router('{"verdict":"contradicted","confidence":"high","supporting_sources":[1],"reason":"source says opposite"}')
    out = _verify(monkeypatch, chunks=_chunks(distance=0.1), router=r)
    assert out["verdict"] == "contradicted" and out["supported"] is False


def test_router_crash_failsoft(monkeypatch):
    r = MagicMock(); r.complete.side_effect = RuntimeError("down")
    out = _verify(monkeypatch, chunks=_chunks(), router=r)
    assert out["verdict"] == "unknown" and out["supported"] is False and out["confidence"] == "low"


def test_empty_statement_raises():
    with pytest.raises(ValueError):
        grounding.verify_statement(db=MagicMock(), router=MagicMock(), user_id=uuid.uuid4(), statement="  ")


# ─── verify_claim tool ───────────────────────────────────────────────

from app.services.tools.base import ToolContext, ToolError  # noqa: E402
from app.services.tools.verify_claim import VerifyClaimTool  # noqa: E402


def test_tool_maps_verdict(monkeypatch):
    from app.services import grounding as g
    monkeypatch.setattr(g, "verify_statement", lambda **k: {
        "verdict": "partial", "supported": False, "confidence": "medium",
        "support": [{"source": "f.pdf", "position": 2, "excerpt": "…"}],
        "reason": "only partly", "sources_checked": 3, "cost_usd": 0.001,
    })
    import app.services.tools.verify_claim as vc
    monkeypatch.setattr("app.services.router.build_default_router", lambda s: MagicMock())
    out = VerifyClaimTool().execute(ToolContext(user_id=uuid.uuid4(), session=MagicMock()), claim="x")
    assert out["verdict"] == "partial" and out["confidence"] == "medium"
    assert out["support"][0]["source"] == "f.pdf"


def test_tool_blank_claim_raises():
    with pytest.raises(ToolError):
        VerifyClaimTool().execute(ToolContext(user_id=uuid.uuid4(), session=MagicMock()), claim="")
