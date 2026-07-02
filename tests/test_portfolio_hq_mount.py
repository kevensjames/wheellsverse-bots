def _client(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key-123")
    from fastapi.testclient import TestClient
    from core.api import app
    return TestClient(app, raise_server_exceptions=False)


def test_portfolio_hq_page_served(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/admin/portfolio-hq")
    assert r.status_code == 200 and "Portfolio HQ" in r.text


def test_portfolio_businesses_endpoint(monkeypatch):
    c = _client(monkeypatch)
    h = {"X-API-Key": "test-key-123"}
    r = c.get("/api/narai/portfolio/businesses", headers=h)
    assert r.status_code == 200
    bs = r.json()["businesses"]
    assert len(bs) == 10 and all(b["offer"] and b["price"] for b in bs)
    assert all(b["has_kit"] for b in bs)   # all 10 GTM kits committed
    assert c.get("/api/narai/portfolio/businesses").status_code in (401, 403)


def test_portfolio_kit_whitelisted(monkeypatch):
    c = _client(monkeypatch)
    h = {"X-API-Key": "test-key-123"}
    assert c.get("/api/narai/portfolio/kit/n8n", headers=h).status_code == 200
    assert c.get("/api/narai/portfolio/kit/bogus", headers=h).status_code == 404
    assert c.get("/api/narai/portfolio/kit/..%2f..%2fpasswd", headers=h).status_code == 404


def test_portfolio_org_endpoint(monkeypatch):
    c = _client(monkeypatch)
    j = c.get("/api/narai/portfolio/org", headers={"X-API-Key": "test-key-123"}).json()
    assert j["ceo"] == "KAI"
    assert len(j["supervisors"]) == 10 and len(j["agents"]) >= 19
