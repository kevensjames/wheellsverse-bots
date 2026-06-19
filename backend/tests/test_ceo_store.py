import pytest
from app.services.ceo import store as st


@pytest.fixture(autouse=True)
def _isolated_ceo_db(tmp_path, monkeypatch):
    db = tmp_path / "ceo.db"
    monkeypatch.setattr(st, "CEO_DB_PATH", db)
    yield db


def test_company_is_singleton():
    assert st.get_company() is None
    a = st.upsert_company("Grow WheellsVerse net revenue", target_value=100000.0)
    assert a["id"] == 1
    assert a["metric"] == "net_revenue"
    b = st.upsert_company("Grow WheellsVerse net revenue to $1M")
    assert b["id"] == 1
    assert st.get_company()["goal"].endswith("$1M")


def test_decisions_and_ledger_roundtrip():
    did = st.record_decision("new_initiative", "Launch KDP bundle", linked_plan_id=7)
    assert did > 0
    rows = st.list_decisions()
    assert rows[0]["kind"] == "new_initiative"
    assert rows[0]["linked_plan_id"] == 7
    st.add_ledger(12.50, "ads", linked_decision_id=did)
    st.add_ledger(7.25, "ads")
    assert st.period_spend("1970-01-01T00:00:00+00:00") == pytest.approx(19.75)


def test_snapshot_roundtrip():
    rid = st.record_snapshot({"revenue": 0, "spend_period": 0, "alerts": 2})
    assert rid > 0
    assert st.latest_snapshot()["alerts"] == 2


def test_org_upsert():
    st.upsert_org_member("engineer", "writes code", reports_to="CEO")
    st.upsert_org_member("engineer", "writes + reviews code", reports_to="CEO")
    org = st.list_org()
    assert len(org) == 1
    assert org[0]["capabilities"] == "writes + reviews code"
