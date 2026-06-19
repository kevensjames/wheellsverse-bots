import pytest
from app.services.ceo import executor, store as st
from app.services.planning import storage as pl


@pytest.fixture(autouse=True)
def _dbs(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CEO_DB_PATH", tmp_path / "ceo.db")
    monkeypatch.setattr(pl, "PLANNING_DB_PATH", tmp_path / "planning.db")
    monkeypatch.setenv("KAI_CEO_BUDGET_CEILING", "100")
    monkeypatch.setenv("KAI_CEO_CATASTROPHIC_USD", "50")
    yield


def test_inpolicy_creates_plan_when_live():
    ds = {"initiatives": [{"title": "Launch KDP bundle", "rationale": "low CAC",
                           "expected_impact": "+$2k"}], "reprioritize": [], "escalations": []}
    out = executor.apply(ds, dry_run=False)
    assert len(out["created"]) == 1
    plan = pl.get_plan(out["created"][0])
    assert plan.status == "draft"
    assert "Launch KDP bundle" in plan.title


def test_dry_run_creates_nothing_but_records():
    ds = {"initiatives": [{"title": "X", "rationale": "y", "expected_impact": "z"}],
          "reprioritize": [], "escalations": []}
    out = executor.apply(ds, dry_run=True)
    assert out["created"] == []
    assert out["decisions"] >= 1
    assert pl.list_plans() == []


def test_escalations_recorded_not_executed():
    ds = {"initiatives": [], "reprioritize": [], "escalations": ["rotate prod secret"]}
    out = executor.apply(ds, dry_run=False)
    assert out["created"] == []
    kinds = [d["kind"] for d in st.list_decisions()]
    assert "escalation" in kinds


def test_catastrophic_initiative_escalates_not_executed():
    ds = {"initiatives": [{"title": "Deploy to prod", "kind": "prod_deploy", "rationale": "ship"}],
          "reprioritize": [], "escalations": []}
    out = executor.apply(ds, dry_run=False)
    assert out["created"] == []
    assert out["queued"][0]["verdict"] == "catastrophic"
