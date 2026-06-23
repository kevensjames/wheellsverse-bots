# tests/test_portfolio_admin_api.py
import os
from fastapi import FastAPI
from fastapi.testclient import TestClient
from core.portfolio import state


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("API_KEY", "test-key-123")
    monkeypatch.delenv("WMOS_ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("WMOS_KILL", raising=False)
    from narai.api.routes.portfolio_admin import router
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


HEAD = {"X-API-Key": "test-key-123"}


def test_overview_requires_auth(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/api/narai/portfolio/overview").status_code == 401          # no key
    r = c.get("/api/narai/portfolio/overview", headers=HEAD)
    assert r.status_code == 200
    assert len(r.json()["businesses"]) == 10


def test_orchestrator_arm_disarm_kill(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/api/narai/portfolio/orchestrator", headers=HEAD).json() == {"enabled": False, "kill": False}
    armed = c.post("/api/narai/portfolio/orchestrator", headers=HEAD, json={"action": "arm"}).json()
    assert armed["enabled"] is True
    killed = c.post("/api/narai/portfolio/orchestrator", headers=HEAD, json={"action": "kill"}).json()
    assert killed["kill"] is True
    bad = c.post("/api/narai/portfolio/orchestrator", headers=HEAD, json={"action": "nope"})
    assert bad.status_code == 400


def test_approvals_list_and_resolve(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    from core.portfolio.actions import Action, ActionClass
    aid = state.queue_approval(Action("deploy", "infra", ActionClass.AMBER, [], "n8n", {}))
    pending = c.get("/api/narai/portfolio/approvals", headers=HEAD, params={"status": "pending"}).json()
    assert len(pending["approvals"]) == 1
    r = c.post(f"/api/narai/portfolio/approvals/{aid}/resolve", headers=HEAD, json={"status": "approved"})
    assert r.json() == {"ok": True}
    assert c.get("/api/narai/portfolio/approvals", headers=HEAD, params={"status": "pending"}).json()["approvals"] == []


def test_audit_endpoint(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    state.audit({"verb": "x", "status": "executed"})
    r = c.get("/api/narai/portfolio/audit", headers=HEAD, params={"limit": 10})
    assert r.status_code == 200
    assert r.json()["audit"][0]["verb"] == "x"


def test_overview_503_when_api_key_unset(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("API_KEY", raising=False)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from narai.api.routes.portfolio_admin import router
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app, raise_server_exceptions=False)
    r = c.get("/api/narai/portfolio/overview", headers={"X-API-Key": "anything"})
    assert r.status_code == 503


def test_orchestrator_disarm_and_unkill(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.post("/api/narai/portfolio/orchestrator", headers=HEAD, json={"action": "arm"})
    c.post("/api/narai/portfolio/orchestrator", headers=HEAD, json={"action": "kill"})
    disarmed = c.post("/api/narai/portfolio/orchestrator", headers=HEAD, json={"action": "disarm"}).json()
    assert disarmed["enabled"] is False
    unkilled = c.post("/api/narai/portfolio/orchestrator", headers=HEAD, json={"action": "unkill"}).json()
    assert unkilled["kill"] is False


def test_resolve_rejects_bad_status(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    from core.portfolio.actions import Action, ActionClass
    aid = state.queue_approval(Action("x", "a", ActionClass.AMBER, [], "n8n", {}))
    r = c.post(f"/api/narai/portfolio/approvals/{aid}/resolve", headers=HEAD, json={"status": "cancelled"})
    assert r.status_code == 400
