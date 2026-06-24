def _client(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key-123")
    from fastapi.testclient import TestClient
    from core.api import app
    return TestClient(app, raise_server_exceptions=False)


def test_scoreboard_page_served(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/admin/scoreboard")
    assert r.status_code == 200
    assert "Portfolio Scoreboard" in r.text


def test_scoreboard_api_real_and_authed(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/api/narai/scoreboard", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200
    j = r.json()
    assert "metrics" in j and "surfaces" in j
    assert j["surfaces"]["ds24"] is False          # honestly not connected
    assert j["metrics"]["deployments"]["value"] == 0
    # global middleware enforces auth on /api/*
    assert c.get("/api/narai/scoreboard").status_code in (401, 403)


def test_killswitch_endpoint(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/api/narai/killswitch", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200
    j = r.json()
    assert "businesses" in j and j["auto_paused"] == []        # recommend-only
    assert c.get("/api/narai/killswitch").status_code in (401, 403)


def test_opportunities_endpoint_mounted(monkeypatch):
    monkeypatch.setattr("core.opportunities.scan",
                        lambda limit=8: {"opportunities": [], "feeds": {}, "connected_feeds": 0, "scanned": 0})
    c = _client(monkeypatch)
    r = c.get("/api/narai/opportunities", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200 and "opportunities" in r.json()
    assert c.get("/api/narai/opportunities").status_code in (401, 403)
