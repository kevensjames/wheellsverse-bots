def _client(monkeypatch, tmp_path):
    # Same key as test_portfolio_mount.py: core.api's global api_key_middleware freezes
    # _API_KEY at first import, so all core.api-importing tests must agree on the value.
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path)); monkeypatch.setenv("API_KEY", "test-key-123")
    from fastapi.testclient import TestClient
    from core.api import app
    return TestClient(app, raise_server_exceptions=False)


def test_cockpit_html_served(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    assert c.get("/admin/portfolio/n8n").status_code == 200


def test_hq_still_served(monkeypatch, tmp_path):  # the {slug} route didn't shadow HQ
    c = _client(monkeypatch, tmp_path)
    assert c.get("/admin/portfolio").status_code == 200


def test_cockpit_api_mounted(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.post("/api/narai/portfolio/biz/n8n/seed", headers={"X-API-Key": "test-key-123"})
    r = c.get("/api/narai/portfolio/biz/n8n/overview", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200
