from tests import board_fakes as bf


def _client(monkeypatch):
    return bf.client(monkeypatch)   # API_KEY "test-key-123", also on the imported module


def test_scoreboard_page_served(monkeypatch):
    fake = bf.install(monkeypatch)
    c = _client(monkeypatch)
    r = c.get("/admin/scoreboard", follow_redirects=False)
    assert r.status_code == 302                       # owner session required
    assert r.headers["location"] == "/board/login?next=%2Fadmin%2Fscoreboard"
    r = c.get("/admin/scoreboard", headers=bf.cookie(fake.add_session()))
    assert r.status_code == 200
    assert "Portfolio Scoreboard" in r.text
    assert "/api/board/scoreboard" in r.text and "X-API-Key" not in r.text


def test_board_scoreboard_api_needs_the_owner_session(monkeypatch):
    bf.clear_connectors(monkeypatch)
    fake = bf.install(monkeypatch)
    bf.install_board(monkeypatch)                     # the ledger's reads go to the fake, never the network
    c = _client(monkeypatch)
    assert c.get("/api/board/scoreboard").status_code == 401
    r = c.get("/api/board/scoreboard", headers=bf.cookie(fake.add_session()))
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
    assert j["metrics"]["deployments"]["value"] == 0
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
