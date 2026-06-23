import json
from core.portfolio import rollup, state, paths


def test_portfolio_overview_covers_all_ten(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    overview = rollup.portfolio_overview()
    assert len(overview) == 10
    n8n = next(b for b in overview if b["slug"] == "n8n")
    assert n8n["name"] == "n8n Automation Agency"
    assert n8n["phase"] == "planning"          # default state
    assert n8n["completed"] == 0
    assert n8n["pending"] == 0
    assert n8n["next_step"] is None            # no loop.json seeded yet
    assert n8n["total_steps"] == 0


def test_business_summary_reflects_state_and_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    # seed a loop + some completed/pending state
    d = tmp_path / "n8n"
    d.mkdir(parents=True, exist_ok=True)
    (d / "loop.json").write_text(json.dumps({"business": "n8n", "steps": [
        {"verb": "research_niche", "agent": "kai", "class": "green"},
        {"verb": "draft_outreach", "agent": "kai", "class": "green"},
        {"verb": "run_campaign", "agent": "kai", "class": "auto_capped"},
    ]}))
    state.mark_completed("n8n", "research_niche")
    state.mark_pending("n8n", "draft_outreach")
    s = rollup.business_summary("n8n", "n8n Automation Agency")
    assert s["completed"] == 1
    assert s["pending"] == 1
    assert s["total_steps"] == 3
    assert s["next_step"] == "run_campaign"    # first not completed/pending


def test_recent_audit_newest_first(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    state.audit({"verb": "a", "status": "executed"})
    state.audit({"verb": "b", "status": "queued"})
    recent = rollup.recent_audit(limit=10)
    assert [r["verb"] for r in recent] == ["b", "a"]   # newest first
    assert rollup.recent_audit(limit=1) == [recent[0]]
