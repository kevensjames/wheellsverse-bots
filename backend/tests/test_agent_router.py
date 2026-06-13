"""Phase 4 — agent_router.classify_domain (super-router) + suggest_agent tool.
Validates against the real preset catalog; mocks only the LLM router."""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import agent_router


def _router(content, *, cost=0.0005):
    r = MagicMock()
    r.complete.return_value = SimpleNamespace(content=content, total_cost_usd=cost)
    return r


def test_routes_to_known_preset():
    r = _router('{"preset_id":"medical_research","confidence":"high","reason":"clinical question"}')
    out = agent_router.classify_domain(router=r, user_id=uuid.uuid4(),
                                       question="stage II hypertension protocol?")
    assert out["preset_id"] == "medical_research" and out["confidence"] == "high"


def test_hallucinated_preset_becomes_none():
    r = _router('{"preset_id":"astrology","confidence":"high","reason":"x"}')
    out = agent_router.classify_domain(router=r, user_id=uuid.uuid4(), question="q")
    assert out["preset_id"] is None and out["confidence"] == "low"


def test_null_preset_is_general():
    r = _router('{"preset_id":null,"confidence":"low","reason":"general chat"}')
    out = agent_router.classify_domain(router=r, user_id=uuid.uuid4(), question="hey")
    assert out["preset_id"] is None


def test_empty_question_short_circuits():
    out = agent_router.classify_domain(router=MagicMock(), user_id=uuid.uuid4(), question="   ")
    assert out["preset_id"] is None and out["cost_usd"] == 0.0


def test_router_crash_failsoft():
    r = MagicMock(); r.complete.side_effect = RuntimeError("down")
    out = agent_router.classify_domain(router=r, user_id=uuid.uuid4(), question="q")
    assert out["preset_id"] is None and out["confidence"] == "low"


# ─── suggest_agent tool ──────────────────────────────────────────────

from app.services.tools.base import ToolContext, ToolError  # noqa: E402
from app.services.tools.suggest_agent import SuggestAgentTool  # noqa: E402


def test_tool_returns_recommendation(monkeypatch):
    from app.services import agent_router as ar
    monkeypatch.setattr(ar, "classify_domain",
                        lambda **k: {"preset_id": "legal_research", "confidence": "high", "reason": "law"})
    monkeypatch.setattr("app.services.router.build_default_router", lambda s: MagicMock())
    out = SuggestAgentTool().execute(
        ToolContext(user_id=uuid.uuid4(), session=MagicMock()), question="is this clause enforceable?")
    assert out["preset_id"] == "legal_research" and out["confidence"] == "high"


def test_tool_blank_raises():
    with pytest.raises(ToolError):
        SuggestAgentTool().execute(ToolContext(user_id=uuid.uuid4(), session=MagicMock()), question="")
