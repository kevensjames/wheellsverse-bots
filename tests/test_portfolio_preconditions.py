from core.portfolio import preconditions, state, budget
from core.portfolio.actions import Action, ActionClass
from core.portfolio.loops import LoopStep


def _step(verb, preconds):
    return LoopStep(verb, "agent", ActionClass.AUTO_CAPPED, preconds)


def test_unknown_precondition_is_false(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    out = preconditions.evaluate("n8n", _step("v", ["totally_made_up"]), today="2026-06-23", month="2026-06")
    assert out == {"totally_made_up": False}


def test_approval_history_precondition(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    step = _step("run_outreach_campaign", ["campaign_approved_once"])
    assert preconditions.evaluate("n8n", step, today="2026-06-23", month="2026-06")["campaign_approved_once"] is False
    aid = state.queue_approval(Action("run_outreach_campaign", "cold_outreach", ActionClass.AUTO_CAPPED, [], "n8n", {}))
    state.resolve_approval(aid, "approved")
    assert preconditions.evaluate("n8n", step, today="2026-06-23", month="2026-06")["campaign_approved_once"] is True


def test_daily_cap_and_flags_and_budget(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    step = _step("run_outreach_campaign", ["under_daily_cap", "warmup_complete", "under_cost_ceiling"])
    out = preconditions.evaluate("n8n", step, today="2026-06-23", month="2026-06")
    assert out["under_daily_cap"] is True        # 0 sends < cap
    assert out["warmup_complete"] is False        # flag unset
    assert out["under_cost_ceiling"] is True      # nothing spent
    state.set_flag("n8n", "warmup_complete", True)
    state.record_send("n8n", "2026-06-23", preconditions.DAILY_CAP)   # hit the cap
    budget.record_spend("n8n", 999.0, "x", "2026-06")                 # blow the ceiling
    out2 = preconditions.evaluate("n8n", step, today="2026-06-23", month="2026-06")
    assert out2["under_daily_cap"] is False
    assert out2["warmup_complete"] is True
    assert out2["under_cost_ceiling"] is False


def test_make_ctx_for_binds_business(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    ctxf = preconditions.make_ctx_for("n8n")
    out = ctxf(_step("v", ["warmup_complete"]))
    assert out == {"warmup_complete": False}
