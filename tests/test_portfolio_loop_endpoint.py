def _client(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key-123")
    from fastapi.testclient import TestClient
    from core.api import app
    return TestClient(app, raise_server_exceptions=False)


def test_portfolio_loop_endpoint(monkeypatch):
    c = _client(monkeypatch)
    h = {"X-API-Key": "test-key-123"}
    j = c.get("/api/narai/portfolio/loop/n8n", headers=h).json()
    assert j["total"] == 9 and j["auto"] == 6 and j["gated"] == 3
    assert {s["verb"] for s in j["steps"] if s["gated"]} == {
        "run_outreach_campaign", "publish_landing_page", "deploy_demo_instance"}
    # whitelist + auth
    assert c.get("/api/narai/portfolio/loop/bogus", headers=h).status_code == 404
    assert c.get("/api/narai/portfolio/loop/n8n").status_code in (401, 403)
