"""Regression guard: /admin/* pages must NOT bake the API key into served HTML.
They are reachable unauthenticated, so an injected key would leak to anyone."""


def _client(monkeypatch):
    # Must match the suite-wide key — the api_key middleware freezes _API_KEY at first
    # import, so using a different value here would 401 the other tests in the run.
    monkeypatch.setenv("API_KEY", "test-key-123")
    from fastapi.testclient import TestClient
    from core.api import app
    return TestClient(app, raise_server_exceptions=False)


def test_admin_toodle_pages_do_not_leak_the_api_key(monkeypatch):
    c = _client(monkeypatch)
    for path in ("/admin/leadgen", "/admin/portfolio-hq", "/admin/scoreboard"):
        r = c.get(path)
        assert r.status_code == 200, path
        assert "test-key-123" not in r.text, f"API key LEAKED in {path}"
        assert "%%API_KEY%%" in r.text, f"{path} should keep the placeholder (page prompts)"
