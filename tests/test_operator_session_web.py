"""Integration tests for the FastAPI session adapter (Phase P2 wiring).

Uses a minimal TestClient app — no production monolith boot required. Covers the
login/logout/whoami surface, cookie attributes, fail-closed on tamper/expiry,
role→scope correctness, and that two apps sharing one secret validate the same
cookie (the cross-app guarantee).
"""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.operator_session_web import resolve_api_key


def _fake_req(header=None, query=None):
    return SimpleNamespace(
        headers={"x-api-key": header} if header else {},
        query_params={"api_key": query} if query else {},
    )


# ── C1 regression: ?api_key= accepted only while sessions are OFF ─────────────
def test_query_api_key_allowed_only_when_sessions_off():
    off = SessionConfig(enabled=False, owner_key="k", admin_token=None, session_secret="s")
    on = SessionConfig(enabled=True, owner_key="k", admin_token=None, session_secret="s")
    # header always works, both states
    assert resolve_api_key(_fake_req(header="K"), off) == "K"
    assert resolve_api_key(_fake_req(header="K"), on) == "K"
    # query param: accepted when OFF, IGNORED (rejected) when ON
    assert resolve_api_key(_fake_req(query="K"), off) == "K"
    assert resolve_api_key(_fake_req(query="K"), on) is None
    # header wins over query
    assert resolve_api_key(_fake_req(header="H", query="Q"), off) == "H"

from core import operator_session as osess
from core.operator_session_web import SessionConfig, install_operator_session, COOKIE_NAME, HINT_COOKIE


def _cookie_line(resp, name):
    """The specific Set-Cookie header line for `name` (login sets two cookies)."""
    for line in resp.headers.get_list("set-cookie"):
        if line.lower().startswith(name.lower() + "="):
            return line.lower()
    return ""

OWNER_KEY = "owner-key"
ADMIN_TOKEN = "admin-token"
SECRET = "shared-signing-secret"


def _app(enabled=True, secure=False, secret=SECRET):
    app = FastAPI()
    cfg = SessionConfig(enabled=enabled, owner_key=OWNER_KEY, admin_token=ADMIN_TOKEN,
                        session_secret=secret, secure_cookies=secure, ttl_seconds=3600)
    install_operator_session(app, cfg)
    return TestClient(app), cfg


# ── flag OFF: zero surface ───────────────────────────────────────────────────
def test_flag_off_no_routes():
    client, _ = _app(enabled=False)
    assert client.get("/admin/session/whoami").status_code == 404
    assert client.post("/admin/session/login", json={"secret": OWNER_KEY}).status_code == 404


# ── login ────────────────────────────────────────────────────────────────────
def test_owner_login_sets_cookie_and_ultra_scope():
    client, _ = _app()
    r = client.post("/admin/session/login", json={"secret": OWNER_KEY})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "owner"
    assert osess.SCOPE_KAI_ULTRA in body["scopes"]
    assert COOKIE_NAME in r.cookies


def test_operator_login_no_ultra():
    client, _ = _app()
    r = client.post("/admin/session/login", json={"secret": ADMIN_TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "operator"
    assert osess.SCOPE_KAI_ULTRA not in body["scopes"]
    assert osess.SCOPE_DESTRUCTIVE not in body["scopes"]


def test_invalid_secret_401_no_cookie():
    client, _ = _app()
    r = client.post("/admin/session/login", json={"secret": "wrong"})
    assert r.status_code == 401
    assert COOKIE_NAME not in r.cookies
    # never leaks which scheme failed / the secret
    assert "wrong" not in r.text and "owner" not in r.text.lower()


def test_login_503_when_unconfigured():
    client, _ = _app(secret="")  # no signing secret
    r = client.post("/admin/session/login", json={"secret": OWNER_KEY})
    assert r.status_code == 503


# ── whoami ───────────────────────────────────────────────────────────────────
def test_whoami_anonymous():
    client, _ = _app()
    r = client.get("/admin/session/whoami")
    assert r.status_code == 200 and r.json()["authenticated"] is False
    assert r.json()["role"] == "anonymous" and r.json()["scopes"] == []


def test_login_then_whoami_roundtrip():
    client, _ = _app()
    client.post("/admin/session/login", json={"secret": OWNER_KEY})
    r = client.get("/admin/session/whoami")
    assert r.json()["authenticated"] and r.json()["role"] == "owner"
    assert r.json()["source"] == "session"


def test_whoami_via_legacy_header_still_works():
    client, _ = _app()
    r = client.get("/admin/session/whoami", headers={"x-api-key": OWNER_KEY})
    assert r.json()["role"] == "owner" and r.json()["source"] == "owner_key"
    r2 = client.get("/admin/session/whoami", headers={"x-admin-token": ADMIN_TOKEN})
    assert r2.json()["role"] == "operator" and r2.json()["source"] == "admin_token"


# ── fail-closed: tamper / expiry / wrong secret ──────────────────────────────
def test_tampered_cookie_is_anonymous():
    client, _ = _app()
    good = osess.mint_session("owner", secret=SECRET, ttl_seconds=3600)
    body, sig = good.split(".", 1)
    forged = body + "." + (sig[:-1] + ("A" if sig[-1] != "A" else "B"))
    r = client.get("/admin/session/whoami", cookies={COOKIE_NAME: forged})
    assert r.json()["authenticated"] is False  # NOT downgraded-but-valid


def test_expired_cookie_is_anonymous():
    client, _ = _app()
    expired = osess.mint_session("owner", secret=SECRET, ttl_seconds=10, now=1000)
    r = client.get("/admin/session/whoami", cookies={COOKIE_NAME: expired})
    assert r.json()["authenticated"] is False


def test_cookie_from_other_secret_rejected():
    client, _ = _app(secret=SECRET)
    foreign = osess.mint_session("owner", secret="different-secret", ttl_seconds=3600)
    r = client.get("/admin/session/whoami", cookies={COOKIE_NAME: foreign})
    assert r.json()["authenticated"] is False


# ── logout ───────────────────────────────────────────────────────────────────
def test_logout_clears_cookie():
    client, _ = _app()
    client.post("/admin/session/login", json={"secret": OWNER_KEY})
    r = client.post("/admin/session/logout")
    assert r.status_code == 200 and r.json()["ok"] is True
    # Set-Cookie clears it (max-age=0 / empty)
    sc = r.headers.get("set-cookie", "")
    assert COOKIE_NAME in sc


# ── cookie attributes ────────────────────────────────────────────────────────
def test_cookie_attributes_secure_and_httponly():
    client, _ = _app(secure=True)
    r = client.post("/admin/session/login", json={"secret": OWNER_KEY})
    sc = _cookie_line(r, COOKIE_NAME)
    assert "httponly" in sc
    assert "samesite=lax" in sc
    assert "secure" in sc
    assert "path=/" in sc


def test_cookie_not_secure_in_dev():
    client, _ = _app(secure=False)
    r = client.post("/admin/session/login", json={"secret": OWNER_KEY})
    sc = _cookie_line(r, COOKIE_NAME)
    assert "httponly" in sc and "secure" not in sc


def test_session_hint_cookie_is_js_readable_and_no_secret():
    client, _ = _app(secure=True)
    r = client.post("/admin/session/login", json={"secret": OWNER_KEY})
    hint = _cookie_line(r, HINT_COOKIE)
    assert hint and "httponly" not in hint         # JS-readable
    token = r.cookies.get(COOKIE_NAME)
    assert token and token not in hint             # hint carries no session token


# ── cross-app: two apps, one secret, same cookie validates in both ───────────
def test_two_apps_share_one_session():
    app_a, _ = _app(secret=SECRET)
    app_b, _ = _app(secret=SECRET)
    login = app_a.post("/admin/session/login", json={"secret": OWNER_KEY})
    token = login.cookies.get(COOKIE_NAME)
    assert token
    # App B (independent app, same secret) accepts the App A cookie.
    r = app_b.get("/admin/session/whoami", cookies={COOKIE_NAME: token})
    assert r.json()["authenticated"] and r.json()["role"] == "owner"
