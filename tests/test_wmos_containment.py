"""Containment regression tests for the W-MOS critical audit findings.

Branch: fix/wmos-critical-containment. Each test pins one audit finding so it can
never silently regress:

  C1  the platform API_KEY must NEVER be injected into an /admin/* HTML body
  H2  /api/narai/leadgen/run/{slug} is a locked mutation (auth required)
  M6  the API-key middleware must fail CLOSED (503) when API_KEY is unconfigured
"""
import pytest

SECRET = "super-secret-test-key-DO-NOT-LEAK"

# Every /admin/* page that previously baked the operator key into its HTML via the
# '%%API_KEY%%' placeholder.
ADMIN_PAGES = [
    "/admin/portfolio",
    "/admin/portfolio/n8n",
    "/admin/scoreboard",
    "/admin/leadgen",
    "/admin/siteboost",
]

# The legacy dashboard served on /admin and /admin/legacy injected the key via a
# different pattern (const API_KEY = '...'); it resolves the key client-side from
# localStorage instead, so it has no %%API_KEY%% placeholder to assert.
DASHBOARD_PAGES = [
    "/admin",
    "/admin/legacy",
]


def _client(monkeypatch, tmp_path, api_key=SECRET):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    import core.api as capi
    # _API_KEY is captured at import time; force it at call time so the test is
    # independent of import order across the session.
    monkeypatch.setattr(capi, "_API_KEY", api_key)
    from fastapi.testclient import TestClient
    return TestClient(capi.app, raise_server_exceptions=False)


@pytest.mark.parametrize("page", ADMIN_PAGES)
def test_admin_page_never_leaks_api_key(monkeypatch, tmp_path, page):
    """C1: an anonymous GET of an admin page must not contain the real key, and
    must leave the placeholder for the client-side prompt()/sessionStorage flow."""
    c = _client(monkeypatch, tmp_path)
    r = c.get(page)
    assert r.status_code == 200
    assert SECRET not in r.text, f"{page} leaked the operator API_KEY into its body"
    assert "%%API_KEY%%" in r.text, f"{page} dropped the placeholder the client fallback needs"


@pytest.mark.parametrize("page", DASHBOARD_PAGES)
def test_legacy_dashboard_never_leaks_api_key(monkeypatch, tmp_path, page):
    """C1 (legacy dashboard): /admin and /admin/legacy are unauthenticated and must
    NOT bake the platform key into the page body; the dashboard resolves it
    client-side (localStorage.wv_api_key / prompt)."""
    c = _client(monkeypatch, tmp_path)
    r = c.get(page)
    assert r.status_code == 200
    assert SECRET not in r.text, f"{page} leaked the operator API_KEY into its body"


def test_leadgen_run_is_a_locked_mutation():
    """H2: POST /api/narai/leadgen/run/{slug} fires real Google Places / Hunter /
    Instantly calls — it must be a locked mutation that always requires the key,
    even if the legacy allowlist ever marks it public."""
    from core import api_auth
    assert api_auth.is_locked_mutation("/api/narai/leadgen/run/n8n", "POST") is True
    assert api_auth.requires_api_key("/api/narai/leadgen/run/n8n", "POST", True) is True
    # Reads stay unlocked — the campaigns list is a safe GET.
    assert api_auth.is_locked_mutation("/api/narai/leadgen/campaigns", "GET") is False


def test_auth_fails_closed_when_api_key_unset(monkeypatch, tmp_path):
    """M6: with the server API_KEY unconfigured, a protected mutation must be
    DENIED (503) rather than silently served — matching the portfolio routers'
    fail-closed behavior. A missing key is 'deny', never 'allow-all'."""
    c = _client(monkeypatch, tmp_path, api_key="")
    r = c.post("/api/narai/leadgen/run/n8n")
    assert r.status_code == 503, f"protected mutation served with no key configured (got {r.status_code})"


def test_protected_read_also_fails_closed_when_api_key_unset(monkeypatch, tmp_path):
    """M6 (widened): protected READS — not only mutations — are denied (503) when the
    server API_KEY is unconfigured. /api/narai/scoreboard is a non-public /api/ read."""
    c = _client(monkeypatch, tmp_path, api_key="")
    assert c.get("/api/narai/scoreboard").status_code == 503


def test_public_route_stays_open_when_api_key_unset(monkeypatch, tmp_path):
    """M6 regression guard: failing closed must NOT block a genuinely public route."""
    c = _client(monkeypatch, tmp_path, api_key="")
    assert c.get("/api/health").status_code == 200
