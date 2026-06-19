import pytest
from app.services.ceo import kpis, store as st


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CEO_DB_PATH", tmp_path / "ceo.db")
    yield


def test_build_snapshot_failsoft(monkeypatch):
    monkeypatch.setattr(kpis, "_plan_counts", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(kpis, "_revenue", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(kpis, "_security_score", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(kpis, "_alerts", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    snap = kpis.build_snapshot()
    assert snap["plans_active"] == 0
    assert snap["revenue"] == 0
    assert snap["security_score"] is None
    assert "ts" in snap
    assert st.latest_snapshot() is not None


def test_build_snapshot_uses_sources(monkeypatch):
    monkeypatch.setattr(kpis, "_plan_counts", lambda: (3, 9))
    monkeypatch.setattr(kpis, "_revenue", lambda: 1234.5)
    monkeypatch.setattr(kpis, "_security_score", lambda: 72)
    monkeypatch.setattr(kpis, "_alerts", lambda: 2)
    snap = kpis.build_snapshot()
    assert snap["plans_active"] == 3
    assert snap["plans_total"] == 9
    assert snap["revenue"] == 1234.5
    assert snap["security_score"] == 72
    assert snap["alerts"] == 2
