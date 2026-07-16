def _client(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key-123")
    from fastapi.testclient import TestClient
    from core.api import app
    # Pin the module global: _API_KEY is frozen at first import, and deny-by-default now
    # fails CLOSED (503) when it is unset — so pin it rather than rely on import order.
    monkeypatch.setattr("core.api._API_KEY", "test-key-123")
    return TestClient(app, raise_server_exceptions=False)


def test_leadgen_page_served(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/admin/leadgen")
    assert r.status_code == 200
    assert "Lead-Gen Campaigns" in r.text


def test_leadgen_campaigns_endpoint(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/api/narai/leadgen/campaigns", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200
    j = r.json()
    assert len(j["campaigns"]) == 6 and "credentials" in j
    assert c.get("/api/narai/leadgen/campaigns").status_code in (401, 403)
