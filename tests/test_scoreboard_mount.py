from tests import board_fakes as bf


def _client(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key-123")
    # core/api.py reads _API_KEY ONCE at import, so setenv alone is a no-op whenever an earlier
    # test already imported the module — which is why these passed alone and failed in a full run.
    monkeypatch.setattr("core.api._API_KEY", "test-key-123", raising=False)
    from fastapi.testclient import TestClient
    from core.api import app
    return TestClient(app, raise_server_exceptions=False)


def test_scoreboard_page_served(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/admin/scoreboard")
    assert r.status_code == 200
    assert "Portfolio Scoreboard" in r.text
    # the board's page: its data from /api/board/* with the owner session cookie, never a key
    assert "/api/board/scoreboard" in r.text and "X-API-Key" not in r.text


def test_board_scoreboard_api_needs_the_owner(monkeypatch):
    """/api/board/scoreboard takes production's owner check: the owner key or an
    owner session cookie; nobody else (an operator's session included)."""
    bf.clear_connectors(monkeypatch)
    bf.install_board(monkeypatch)                     # the ledger's reads go to the fake, never the network
    c = _client(monkeypatch)
    assert c.get("/api/board/scoreboard").status_code == 401
    assert c.get("/api/board/scoreboard", headers=bf.owner_headers("operator")).status_code == 401
    for headers in ({"X-API-Key": "test-key-123"}, bf.owner_headers()):
        r = c.get("/api/board/scoreboard", headers=headers)
        assert r.status_code == 200
        j = r.json()
        assert "metrics" in j and "surfaces" in j


def test_scoreboard_api_real_and_authed(monkeypatch):
    bf.clear_connectors(monkeypatch)
    bf.install_board(monkeypatch)
    c = _client(monkeypatch)
    r = c.get("/api/narai/scoreboard", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200
    j = r.json()
    assert "metrics" in j and "surfaces" in j
    assert j["surfaces"]["ds24"] is False          # honestly not connected
    # See test_scoreboard.py: unconnected means value=None, never a fake 0.
    assert j["metrics"]["deployments"]["value"] is None
    assert j["metrics"]["deployments"]["connected"] is False
    assert j["metrics"]["revenue_month"]["value"] is None       # no Stripe key here: not measured, never $0
    assert j["metrics"]["places_scanned"]["label"] == "places scanned (outreach)"
    # global middleware enforces auth on /api/*
    assert c.get("/api/narai/scoreboard").status_code in (401, 403)


def test_killswitch_endpoint_deactivated(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/api/narai/killswitch", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200
    assert r.json()["status"] == "deactivated"                 # deactivated per operator
    assert c.get("/api/narai/killswitch").status_code in (401, 403)


def test_opportunities_endpoint_mounted(monkeypatch):
    monkeypatch.setattr("core.opportunities.scan",
                        lambda limit=8: {"opportunities": [], "feeds": {}, "connected_feeds": 0, "scanned": 0})
    c = _client(monkeypatch)
    r = c.get("/api/narai/opportunities", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200 and "opportunities" in r.json()
    assert c.get("/api/narai/opportunities").status_code in (401, 403)
