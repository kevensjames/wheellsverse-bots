import os
from fastapi import FastAPI
from fastapi.testclient import TestClient

HEAD = {"X-API-Key": "k"}


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("API_KEY", "k")
    from narai.api.routes.portfolio_cockpit_admin import router
    app = FastAPI(); app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_seed_then_overview(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.post("/api/narai/portfolio/biz/n8n/seed", headers=HEAD).json()["ok"] is True
    ov = c.get("/api/narai/portfolio/biz/n8n/overview", headers=HEAD).json()
    assert ov["business"] == "n8n"
    assert ov["steps"][0]["verb"] == "research_niche"
    assert c.get("/api/narai/portfolio/biz/n8n/overview").status_code == 401  # auth


def test_tick_drafts_then_artifact_listed(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    import core.base_bot as bb
    monkeypatch.setattr(bb.BaseBot, "claude", lambda self, prompt, **kw: "DRAFTED")
    c.post("/api/narai/portfolio/biz/n8n/seed", headers=HEAD)
    r = c.post("/api/narai/portfolio/biz/n8n/tick", headers=HEAD).json()
    assert r["status"] == "executed"          # first GREEN step ran (drafted)
    arts = c.get("/api/narai/portfolio/biz/n8n/artifacts", headers=HEAD).json()["artifacts"]
    assert any(a["kind"] == "research" for a in arts)
