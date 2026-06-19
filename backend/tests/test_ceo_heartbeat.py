import json, uuid
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from app.services.ceo import heartbeat, store as st
from app.services.planning import storage as pl


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CEO_DB_PATH", tmp_path / "ceo.db")
    monkeypatch.setattr(pl, "PLANNING_DB_PATH", tmp_path / "planning.db")
    monkeypatch.setenv("KAI_SCOPE_CEO", "1")
    monkeypatch.setenv("KAI_CEO_BUDGET_CEILING", "100")
    monkeypatch.delenv("KAI_CEO_KILLED", raising=False)
    yield


def _router(payload):
    r = MagicMock()
    r.complete.return_value = SimpleNamespace(content=json.dumps(payload))
    return r


def test_cycle_skips_without_company():
    out = heartbeat.run_cycle(router=_router({}), user_id=uuid.uuid4(), dry_run=True)
    assert out["ran"] is False
    assert "company" in out["reason"]


def test_cycle_runs_dry_then_live():
    st.upsert_company("Grow net revenue")
    payload = {"initiatives": [{"title": "Launch KDP bundle", "rationale": "low CAC",
                                "expected_impact": "+$2k"}], "reprioritize": [], "escalations": []}
    dry = heartbeat.run_cycle(router=_router(payload), user_id=uuid.uuid4(), dry_run=True)
    assert dry["ran"] is True and dry["result"]["created"] == []
    live = heartbeat.run_cycle(router=_router(payload), user_id=uuid.uuid4(), dry_run=False)
    assert len(live["result"]["created"]) == 1


def test_cycle_blocked_by_kill(monkeypatch):
    st.upsert_company("Grow net revenue")
    monkeypatch.setenv("KAI_CEO_KILLED", "1")
    out = heartbeat.run_cycle(router=_router({}), user_id=uuid.uuid4(), dry_run=False)
    assert out["ran"] is False and "kill" in out["reason"].lower()


def test_cycle_blocked_by_scope(monkeypatch):
    st.upsert_company("Grow net revenue")
    monkeypatch.delenv("KAI_SCOPE_CEO", raising=False)
    out = heartbeat.run_cycle(router=_router({}), user_id=uuid.uuid4(), dry_run=False)
    assert out["ran"] is False and "scope" in out["reason"].lower()
