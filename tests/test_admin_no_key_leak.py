"""Regression guard: /admin/* pages must NOT bake the API key into served HTML.
They are reachable unauthenticated, so an injected key would leak to anyone."""


def _client(monkeypatch):
    monkeypatch.setenv("API_KEY", "super-secret-key-xyz123")
    from fastapi.testclient import TestClient
    from core.api import app
    return TestClient(app, raise_server_exceptions=False)


def test_admin_toodle_pages_do_not_leak_the_api_key(monkeypatch):
    c = _client(monkeypatch)
    for path in ("/admin/leadgen", "/admin/portfolio-hq", "/admin/scoreboard"):
        r = c.get(path)
        assert r.status_code == 200, path
        assert "super-secret-key-xyz123" not in r.text, f"API key LEAKED in {path}"
        assert "%%API_KEY%%" in r.text, f"{path} should keep the placeholder (page prompts)"
