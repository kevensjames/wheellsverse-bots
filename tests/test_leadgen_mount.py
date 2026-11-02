from tests import board_fakes as bf


def _client(monkeypatch):
    return bf.client(monkeypatch)   # API_KEY "test-key-123", also on the imported module


def test_leadgen_page_served(monkeypatch):
    fake = bf.install(monkeypatch)
    c = _client(monkeypatch)
    assert c.get("/admin/leadgen", follow_redirects=False).status_code == 302   # owner session required
    r = c.get("/admin/leadgen", headers=bf.cookie(fake.add_session()))
    assert r.status_code == 200
    assert "Lead-Gen Campaigns" in r.text


def test_leadgen_campaigns_endpoint(monkeypatch):
    c = _client(monkeypatch)
    r = c.get("/api/narai/leadgen/campaigns", headers={"X-API-Key": "test-key-123"})
    assert r.status_code == 200
    j = r.json()
    assert len(j["campaigns"]) == 6 and "credentials" in j
    assert c.get("/api/narai/leadgen/campaigns").status_code in (401, 403)
