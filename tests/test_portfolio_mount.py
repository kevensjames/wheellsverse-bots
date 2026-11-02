import os

from tests import board_fakes as bf


def _client(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    return bf.client(monkeypatch)   # API_KEY "test-key-123", also on the imported module


def test_portfolio_html_served(monkeypatch, tmp_path):
    fake = bf.install(monkeypatch)
    c = _client(monkeypatch, tmp_path)
    assert c.get("/admin/portfolio", follow_redirects=False).status_code == 302   # owner session required
    r = c.get("/admin/portfolio", headers=bf.cookie(fake.add_session()))
    assert r.status_code == 200
    assert "W-MOS" in r.text or "Portfolio" in r.text


def test_portfolio_router_mounted(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    r = c.get("/api/narai/portfolio/overview", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200
    assert len(r.json()["businesses"]) == 10
