import os


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("API_KEY", "test-key-123")
    # core/api.py reads _API_KEY ONCE at import, so setenv alone is a no-op whenever an earlier
    # test already imported the module — which is why these passed alone and failed in a full run.
    monkeypatch.setattr("core.api._API_KEY", "test-key-123", raising=False)
    from fastapi.testclient import TestClient
    from core.api import app
    return TestClient(app, raise_server_exceptions=False)


def test_portfolio_html_served(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/admin/portfolio")
    assert r.status_code == 200
    assert "W-MOS" in r.text or "Portfolio" in r.text


def test_portfolio_router_mounted(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/api/narai/portfolio/overview", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200
    assert len(r.json()["businesses"]) == 10
