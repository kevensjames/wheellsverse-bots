from tests import board_fakes as bf


def _client(monkeypatch, tmp_path):
    # Same key as test_portfolio_mount.py: core.api's global api_key_middleware freezes
    # _API_KEY at first import, so bf.client also sets the module value.
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    return bf.client(monkeypatch)


def test_cockpit_html_served(monkeypatch, tmp_path):
    fake = bf.install(monkeypatch)
    c = _client(monkeypatch, tmp_path)
    assert c.get("/admin/portfolio/n8n", follow_redirects=False).status_code == 302   # owner session required
    assert c.get("/admin/portfolio/n8n", headers=bf.cookie(fake.add_session())).status_code == 200


def test_hq_still_served(monkeypatch, tmp_path):  # the {slug} route didn't shadow HQ
    fake = bf.install(monkeypatch)
    c = _client(monkeypatch, tmp_path)
    r = c.get("/admin/portfolio", headers=bf.cookie(fake.add_session()))
    assert r.status_code == 200 and 'data-tab="approvals"' in r.text   # the HQ page, not a cockpit


def test_cockpit_api_mounted(monkeypatch, tmp_path):
    c = _client(monkeypatch, tmp_path)
    c.post("/api/narai/portfolio/biz/n8n/seed", headers={"X-API-Key": "test-key-123"})
    r = c.get("/api/narai/portfolio/biz/n8n/overview", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200
