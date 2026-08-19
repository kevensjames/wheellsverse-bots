"""LOCAL staging surrogate — runs the merge gate checks against the REAL FastAPI
apps (core.api:app and app.main:app), booted in-process with a stub env and all
merge flags ON. No external credentials, DB, Redis, or network.

This is NOT a substitute for real staging certification (real DB-backed routes,
real LLM streaming, HTTPS Secure cookies, Cloudflare topology are staging-only),
but it certifies the identity spine + bridge security against the actual app
objects rather than isolated modules. Skips cleanly if an app can't import.
"""
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

# Flags ON + stub secrets, set BEFORE importing either app (both read env at import).
os.environ.update(
    DATABASE_URL="postgresql://stub/stub",
    API_KEY="ownerkey", ADMIN_TOKEN="optok", JWT_SECRET_KEY="jwt",
    SESSION_SIGNING_SECRET="surrogate-shared-secret",
    OPERATOR_SESSION_ENABLED="true",
    APP_ENV="test",  # -> secure_cookies False so TestClient round-trips
    KAI_BRIDGE_ENABLED="true", KAI_UPSTREAM_URL="http://kai-upstream.local",
    KAI_COMMAND_BAR_GOVERNED="true",
)

from fastapi.testclient import TestClient  # noqa: E402
from core.operator_session import mint_session, SCOPE_KAI_ULTRA  # noqa: E402

OWNER_KEY = "ownerkey"
ADMIN_TOKEN = "optok"
SECRET = "surrogate-shared-secret"

try:
    from core.api import app as app_a
    A = TestClient(app_a)
except Exception as e:  # pragma: no cover
    A = None
    _A_ERR = repr(e)

try:
    from app.main import app as app_b
    B = TestClient(app_b)
except Exception as e:  # pragma: no cover
    B = None
    _B_ERR = repr(e)

needs_a = pytest.mark.skipif(A is None, reason="App A (core.api) did not import locally")
needs_b = pytest.mark.skipif(B is None, reason="App B (app.main) did not import locally")


@pytest.fixture(autouse=True)
def _anonymous_start():
    """TestClient keeps a persistent cookie jar; reset both to anonymous so each
    test controls its own credentials."""
    if A is not None:
        A.cookies.clear()
    if B is not None:
        B.cookies.clear()
    yield


# ── S3: session certification (real App A) ───────────────────────────────────
@needs_a
def test_s3_owner_login_and_ultra():
    r = A.post("/admin/session/login", json={"secret": OWNER_KEY})
    assert r.status_code == 200 and r.json()["role"] == "owner"
    assert SCOPE_KAI_ULTRA in r.json()["scopes"]
    assert "wv_session" in r.cookies


@needs_a
def test_s3_operator_least_privilege():
    r = A.post("/admin/session/login", json={"secret": ADMIN_TOKEN})
    assert r.status_code == 200 and r.json()["role"] == "operator"
    assert SCOPE_KAI_ULTRA not in r.json()["scopes"]


@needs_a
def test_s3_anonymous_has_no_privilege():
    r = A.get("/admin/session/whoami")
    assert r.json()["authenticated"] is False and r.json()["scopes"] == []


# ── S4: cross-app cookie proof (App A cookie validates in App B) ──────────────
@needs_a
@needs_b
def test_s4_cross_app_cookie():
    login = A.post("/admin/session/login", json={"secret": OWNER_KEY})
    token = login.cookies.get("wv_session")
    assert token
    who = B.get("/admin/session/whoami", cookies={"wv_session": token})
    assert who.json()["authenticated"] and who.json()["role"] == "owner"
    assert SCOPE_KAI_ULTRA in who.json()["scopes"]  # same principal + scopes in App B


# ── S5: session attack tests (fail closed in both apps) ──────────────────────
@needs_a
@needs_b
@pytest.mark.parametrize("bad", ["tampered", "expired", "wrongsecret", "malformed"])
def test_s5_attacks_fail_closed(bad):
    if bad == "tampered":
        t = mint_session("owner", secret=SECRET, ttl_seconds=3600)
        body, sig = t.split(".", 1)
        cookie = body + "." + (sig[:-1] + ("A" if sig[-1] != "A" else "B"))
    elif bad == "expired":
        cookie = mint_session("owner", secret=SECRET, ttl_seconds=10, now=1000)
    elif bad == "wrongsecret":
        cookie = mint_session("owner", secret="not-the-secret", ttl_seconds=3600)
    else:
        cookie = "garbage.notatoken"
    for client in (A, B):
        r = client.get("/admin/session/whoami", cookies={"wv_session": cookie})
        assert r.json()["authenticated"] is False, f"{bad} leaked identity"


# ── S6: C1 query-secret rejected when sessions ON (real App A middleware) ─────
@needs_a
def test_s6_query_api_key_rejected_when_sessions_on():
    # A gated /api/ path (unknown route → middleware runs first). No creds:
    assert A.get("/api/_c1probe").status_code == 401
    # ?api_key= with the CORRECT key must now be REJECTED (401) — C1 closed.
    assert A.get("/api/_c1probe?api_key=ownerkey").status_code == 401
    # Header path still authenticates (passes middleware → 404 route-missing, not 401).
    assert A.get("/api/_c1probe", headers={"X-API-Key": OWNER_KEY}).status_code != 401
    # Session cookie authenticates /api/ too.
    A.post("/admin/session/login", json={"secret": OWNER_KEY})
    assert A.get("/api/_c1probe").status_code != 401  # cookie from the jar


# ── S8: bridge security certification (real App A bridge, pre-upstream) ───────
@needs_a
def test_s8_bridge_health():
    assert A.get("/admin/kai-bridge/health").json()["enabled"] is True


@needs_a
def test_s8_bridge_anonymous_denied():
    A.cookies.clear()
    assert A.post("/admin/kai/kai-chat").status_code == 401


@needs_a
def test_s8_bridge_operator_denied_ultra():
    A.cookies.clear()
    A.post("/admin/session/login", json={"secret": ADMIN_TOKEN})  # operator
    assert A.post("/admin/kai/kai-chat/ultra").status_code == 403


@needs_a
def test_s8_bridge_allowlist_and_traversal():
    A.cookies.clear()
    A.post("/admin/session/login", json={"secret": OWNER_KEY})  # owner
    assert A.get("/admin/kai/secret-internal").status_code == 404   # not allowlisted
    assert A.get("/admin/kai/kg/../../etc/passwd").status_code == 404  # traversal


@needs_a
def test_s8_bridge_owner_allowed_reaches_forward():
    A.cookies.clear()
    A.post("/admin/session/login", json={"secret": OWNER_KEY})  # owner
    # Allowed + authorized → passes auth/allowlist, attempts forward to the
    # (unreachable fake) upstream → 502. Proves the gate opened for owner.
    assert A.get("/admin/kai/kg").status_code in (502, 504)


# ── P11/P12: presence assets served + integrated into the shell ──────────────
@needs_a
def test_kai_presence_js_served():
    r = A.get("/admin/kai-presence.js")
    assert r.status_code == 200
    assert "kaip-orb" in r.text and "/admin/kai/kai-chat/stream" in r.text
    assert r.headers.get("content-type", "").startswith(("text/javascript", "application/javascript"))


@needs_a
def test_kai_presence_css_served():
    r = A.get("/admin/kai-presence.css")
    assert r.status_code == 200 and ".kaip-drawer" in r.text


@needs_a
def test_hub_shell_uses_presence_not_legacy_drawer():
    r = A.get("/admin/hub")
    assert r.status_code == 200
    assert "/admin/kai-presence.js" in r.text        # governed presence wired
    assert "kai-fab" not in r.text                    # legacy NarAI drawer removed
    assert "api/v2/narai/chat" not in r.text


@needs_a
@pytest.mark.parametrize("route", [
    "/admin/hub", "/admin/shopify", "/admin/portfolio", "/admin/portfolio/acme",
    "/admin/siteboost", "/admin/scoreboard", "/admin/leadgen", "/admin/theme-picker",
])
def test_presence_injected_on_all_admin_pages(route):
    r = A.get(route)
    assert r.status_code == 200
    assert "/admin/kai-presence.js" in r.text, f"{route} missing governed presence"


@needs_a
@pytest.mark.parametrize("route", ["/terms", "/privacy"])
def test_presence_not_injected_on_public_pages(route):
    assert "/admin/kai-presence.js" not in A.get(route).text


# ── P13: Nexus immersive page served (shared provider, distinct from bridge) ──
@needs_a
def test_nexus_page_served_in_nexus_mode():
    r = A.get("/admin/nexus")
    assert r.status_code == 200
    assert 'data-kai-mode="nexus"' in r.text     # provider renders immersive
    assert "/admin/kai-presence.js" in r.text     # same shared provider
    # /admin/nexus must NOT be the bridge (that's /admin/kai/*)
    assert A.get("/admin/kai-bridge/health").status_code == 200


# ── Nexus cinematic assets (allowlisted) + ceo.html governed streaming ────────
@needs_a
def test_nexus_assets_allowlisted():
    assert A.get("/admin/nexus-assets/kai.jpg").status_code == 200
    assert A.get("/admin/nexus-assets/kai-idle.mp4").headers["content-type"] == "video/mp4"
    assert A.get("/admin/nexus-assets/../secret").status_code in (404, 400)  # no traversal
    assert A.get("/admin/nexus-assets/evil.exe").status_code == 404          # allowlist


@needs_a
def test_ceo_command_bar_uses_governed_stream():
    r = A.get("/admin")   # serves dashboard/ceo.html
    assert r.status_code == 200
    assert "/admin/kai/kai-chat/stream" in r.text     # repointed to the streaming brain
