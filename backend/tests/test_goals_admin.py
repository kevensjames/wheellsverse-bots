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


def _patch_llm(monkeypatch, content, *, cost=0.001):
    """Patch admin_goals' router build + operator resolution so the bridge runs
    against a fake router with canned planner content — no real adapter/DB."""
    import uuid
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.routers import admin_goals
    fake_router = MagicMock()
    fake_router.complete.return_value = SimpleNamespace(content=content, total_cost_usd=cost)
    monkeypatch.setattr(admin_goals, "build_default_router", lambda session: fake_router)
    monkeypatch.setattr(admin_goals, "_resolve_operator_profile",
                        lambda session: SimpleNamespace(id=uuid.uuid4(), tier="ultra"))
    return fake_router


@pytest.fixture(autouse=True)
def _isolated_planning_db(tmp_path, monkeypatch):
    from app.services.planning import storage as pl
    monkeypatch.setattr(pl, "PLANNING_DB_PATH", tmp_path / "planning.db")
    yield


def test_approve_proposal_scope_off_403(client, monkeypatch, _isolated_audit):
    monkeypatch.delenv("KAI_SCOPE_GOALS_APPROVE_PROPOSAL", raising=False)
    g = store.create_goal("x"); store.update_goal(g.id, next_action="do thing")
    r = client.post(f"/admin/goals/{g.id}/approve-proposal", headers=ADMIN_HEADERS,
                    json={"approved": True})
    assert r.status_code == 403


def test_approve_proposal_wildcard_not_enough_403(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_GOALS", "1")  # wildcard only — GOV-005 must reject
    monkeypatch.delenv("KAI_SCOPE_GOALS_APPROVE_PROPOSAL", raising=False)
    g = store.create_goal("x"); store.update_goal(g.id, next_action="do thing")
    r = client.post(f"/admin/goals/{g.id}/approve-proposal", headers=ADMIN_HEADERS,
                    json={"approved": True})
    assert r.status_code == 403


def test_approve_proposal_requires_approval_409(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_GOALS_APPROVE_PROPOSAL", "1")
    g = store.create_goal("x"); store.update_goal(g.id, next_action="do thing")
    r = client.post(f"/admin/goals/{g.id}/approve-proposal", headers=ADMIN_HEADERS,
                    json={"approved": False})
    assert r.status_code == 409


def test_approve_proposal_creates_and_autoapproves_plan(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_GOALS_APPROVE_PROPOSAL", "1")
    _patch_llm(monkeypatch, '{"steps":[{"action":"one"},{"action":"two"}]}')
    g = store.create_goal("Ship v1"); store.update_goal(g.id, next_action="write the README")
    r = client.post(f"/admin/goals/{g.id}/approve-proposal", headers=ADMIN_HEADERS,
                    json={"approved": True})
    assert r.status_code == 200
    body = r.json()
    assert body["plan"]["status"] == "approved"
    assert len(body["plan"]["steps"]) == 2
    assert body["plan"]["meta"]["goal_id"] == g.id
    assert store.get_goal(g.id).linked_plan_id == str(body["plan"]["id"])


def test_approve_proposal_empty_steps_stays_draft(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_GOALS_APPROVE_PROPOSAL", "1")
    _patch_llm(monkeypatch, "no parseable steps here")
    g = store.create_goal("Ship v1"); store.update_goal(g.id, next_action="do thing")
    r = client.post(f"/admin/goals/{g.id}/approve-proposal", headers=ADMIN_HEADERS,
                    json={"approved": True})
    assert r.status_code == 200
    body = r.json()
    assert body["plan"]["status"] == "draft"
    assert body["note"]


def test_approve_proposal_no_proposal_400(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_GOALS_APPROVE_PROPOSAL", "1")
    _patch_llm(monkeypatch, '{"steps":[{"action":"one"}]}')
    g = store.create_goal("x")  # no next_action set
    r = client.post(f"/admin/goals/{g.id}/approve-proposal", headers=ADMIN_HEADERS,
                    json={"approved": True})
    assert r.status_code == 400


def test_run_endpoint_triggers_cycle(client, monkeypatch, _isolated_audit):
    monkeypatch.setenv("KAI_SCOPE_GOALS", "1")  # goals.run is non-destructive → wildcard ok
    monkeypatch.setattr("app.services.goals.scheduler.run_cycle",
                        lambda **kw: {"advanced": 0, "results": [], "notified": False})
    r = client.post("/admin/goals/run", headers=ADMIN_HEADERS,
                    json={"notify": False, "approved": True})
    assert r.status_code == 200
    assert r.json()["advanced"] == 0


def test_approve_proposal_non_active_goal_400(client, monkeypatch, _isolated_audit):
    # Only an *active* goal may be bridged; a blocked goal with a proposal must 400.
    monkeypatch.setenv("KAI_SCOPE_GOALS_APPROVE_PROPOSAL", "1")
    _patch_llm(monkeypatch, '{"steps":[{"action":"one"}]}')
    g = store.create_goal("x")
    store.update_goal(g.id, next_action="do thing", status="blocked")
    r = client.post(f"/admin/goals/{g.id}/approve-proposal", headers=ADMIN_HEADERS,
                    json={"approved": True})
    assert r.status_code == 400
