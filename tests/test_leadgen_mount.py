def _client(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key-123")
    from fastapi.testclient import TestClient
    from core.api import app
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


def test_leadgen_download_whitelists_slug(monkeypatch):
    c = _client(monkeypatch)
    h = {"X-API-Key": "test-key-123"}
    # unknown / traversal-shaped slug must be rejected by the whitelist (no file path built)
    assert c.get("/api/narai/leadgen/download/bogus", headers=h).status_code == 404
    assert c.get("/api/narai/leadgen/download/..%2f..%2fetc%2fpasswd", headers=h).status_code == 404
    # auth still required
    assert c.get("/api/narai/leadgen/download/dental-boston").status_code in (401, 403)
