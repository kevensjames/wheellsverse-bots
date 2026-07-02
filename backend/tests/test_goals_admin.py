"""KAI v1 build #4b — goals admin endpoints (reads + CRUD)."""
import pytest

from app.config import settings
from app.services import _sqlite_util
from app.services.goals import store

ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


@pytest.fixture(autouse=True)
def _isolated_goals_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "GOALS_DB_PATH", tmp_path / "goals.db")
    _sqlite_util.reset_for_tests()
    yield
    _sqlite_util.reset_for_tests()


@pytest.fixture
def _isolated_audit(monkeypatch):
    import tempfile
    from app.services.governance import audit_log as _al
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        monkeypatch.setattr(_al, "AUDIT_LOG_PATH", _al.Path(tf.name))
        yield


def test_stats_requires_token(client):
    assert client.get("/admin/goals/stats").status_code == 403


def test_stats_and_list_empty(client):
    r = client.get("/admin/goals/stats", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert client.get("/admin/goals/list", headers=ADMIN_HEADERS).json()["count"] == 0


def test_get_missing_404(client):
    assert client.get("/admin/goals/nope", headers=ADMIN_HEADERS).status_code == 404


def test_scheduler_status_endpoint(client):
    r = client.get("/admin/goals/scheduler", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    assert "enabled" in r.json()


def test_create_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_GOALS", raising=False)
    monkeypatch.delenv("KAI_SCOPE_GOALS_CREATE", raising=False)
    r = client.post("/admin/goals/create", headers=ADMIN_HEADERS,
                    json={"title": "x", "approved": True})
    assert r.status_code == 403


def test_create_wildcard_not_enough_for_destructive_403(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_GOALS", "1")  # wildcard only — GOV-005 must reject
    monkeypatch.delenv("KAI_SCOPE_GOALS_CREATE", raising=False)
    r = client.post("/admin/goals/create", headers=ADMIN_HEADERS,
                    json={"title": "x", "approved": True})
    assert r.status_code == 403


def test_create_requires_approval_409(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_GOALS_CREATE", "1")
    r = client.post("/admin/goals/create", headers=ADMIN_HEADERS,
                    json={"title": "x", "approved": False})
    assert r.status_code == 409


def test_create_approved_creates_goal(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_GOALS_CREATE", "1")
    r = client.post("/admin/goals/create", headers=ADMIN_HEADERS,
                    json={"title": "Register LLC", "done_when": "EIN issued", "approved": True})
    assert r.status_code == 200
    assert r.json()["goal"]["title"] == "Register LLC"
    assert client.get("/admin/goals/stats", headers=ADMIN_HEADERS).json()["active"] == 1


def test_update_status_flow(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_GOALS_CREATE", "1")
    monkeypatch.setenv("KAI_SCOPE_GOALS_EDIT", "1")
    gid = client.post("/admin/goals/create", headers=ADMIN_HEADERS,
                      json={"title": "x", "approved": True}).json()["goal"]["id"]
    r = client.post(f"/admin/goals/{gid}/update", headers=ADMIN_HEADERS,
                    json={"status": "done", "approved": True})
    assert r.status_code == 200 and r.json()["goal"]["status"] == "done"


def test_update_bad_status_400(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_GOALS_CREATE", "1")
    monkeypatch.setenv("KAI_SCOPE_GOALS_EDIT", "1")
    gid = client.post("/admin/goals/create", headers=ADMIN_HEADERS,
                      json={"title": "x", "approved": True}).json()["goal"]["id"]
    r = client.post(f"/admin/goals/{gid}/update", headers=ADMIN_HEADERS,
                    json={"status": "nonsense", "approved": True})
    assert r.status_code == 400
