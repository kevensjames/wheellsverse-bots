"""Super-router — decision heuristic + plan proposal (mocked planner, no LLM)."""
from unittest.mock import patch

import pytest

from app.services import superrouter


# ─── should_plan heuristic (free, no LLM) ──────────────────────────────
@pytest.mark.parametrize("msg,expected", [
    ("what time is it?", False),                                  # short question
    ("summarize this email", False),                              # simple, one-shot
    ("Build the landing page and then set up the email sequence and finally launch the ad campaign", True),  # multi-step
    ("Research competitors, design the pricing, and implement the checkout", True),  # project verbs + list
    ("Do these: 1. scrape the site 2. enrich leads 3. send outreach", True),  # enumerated
    ("can you help me?", False),
])
def test_should_plan(msg, expected):
    ok, reason = superrouter.should_plan(msg)
    assert ok is expected, f"{msg!r} -> {ok} ({reason})"


def test_should_plan_empty():
    assert superrouter.should_plan("")[0] is False


def test_enabled_off_by_default(monkeypatch):
    monkeypatch.delenv("KAI_SUPERROUTER_ENABLED", raising=False)
    assert superrouter.enabled() is False
    monkeypatch.setenv("KAI_SUPERROUTER_ENABLED", "1")
    assert superrouter.enabled() is True


# ─── propose_plan (mocked planner.generate_plan) ───────────────────────
class _FakePlan:
    id = 42
    title = "Launch plan"
    status = "draft"

    class _S:
        def __init__(self, a): self.action = a
    steps = [_S("scrape"), _S("enrich"), _S("send")]


def test_propose_plan_returns_proposal():
    with patch("app.services.planning.planner.generate_plan",
               return_value=(_FakePlan(), 0.012)):
        out = superrouter.propose_plan("build and launch X and then Y",
                                       router=object(), user_id="u")
    assert out["plan_id"] == 42
    assert out["step_count"] == 3
    assert out["steps"] == ["scrape", "enrich", "send"]
    assert out["proposal_cost_usd"] == 0.012
    assert "approve" in out["note"].lower()


def test_propose_plan_fail_open():
    # generate_plan blowing up (e.g. brain down) must yield None, not raise
    with patch("app.services.planning.planner.generate_plan",
               side_effect=RuntimeError("brain down")):
        assert superrouter.propose_plan("x y z", router=object(), user_id="u") is None
