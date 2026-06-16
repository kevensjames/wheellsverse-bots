"""Stage 6 cookie-auth tests.

Verifies the HttpOnly-cookie surface added on top of the existing Bearer flow:
- /auth/signup and /auth/login set both cookies
- cookie attributes (HttpOnly, SameSite=Lax, paths)
- /auth/me works with cookie only (no Authorization header)
- /auth/logout clears the cookies
- /auth/refresh accepts the cookie alone (no JSON body)
- /nai/chat/stream accepts the cookie (no ?token= query param)
- /nai/chat/stream legacy ?token= path still works but logs a deprecation warning
"""
from __future__ import annotations

import logging

from app.dependencies.cookie_auth import ACCESS_COOKIE, REFRESH_COOKIE


SIGNUP = "/auth/signup"
LOGIN = "/auth/login"
REFRESH = "/auth/refresh"
LOGOUT = "/auth/logout"
ME = "/auth/me"
STREAM = "/nai/chat/stream"


def _payload(faker):
    return {
        "email": faker.unique.email().lower(),
        "password": "testpass123",
        "full_name": faker.name(),
    }


def _cookie_attrs(response, name: str) -> dict | None:
    """Find the Set-Cookie header for `name` and return parsed attributes."""
    for header_value in response.headers.get_list("set-cookie") if hasattr(
        response.headers, "get_list"
    ) else [response.headers.get("set-cookie", "")]:
        # httpx multi-headers come through .headers.get_list; fall back to single.
        if not header_value:
            continue
        first, *attrs = [a.strip() for a in header_value.split(";")]
        k, _, v = first.partition("=")
        if k.strip() == name:
            out = {"value": v}
            for a in attrs:
                if "=" in a:
                    ak, _, av = a.partition("=")
                    out[ak.strip().lower()] = av.strip()
                else:
                    out[a.lower()] = True
            return out
    return None


# --- cookie issuance ---

def test_signup_sets_both_cookies(client, faker_fixture):
    body = _payload(faker_fixture)
    r = client.post(SIGNUP, json=body)
    assert r.status_code == 201
    # JSON body still carries tokens (API-client back-compat).
    assert r.json()["access_token"]
    # Cookies are set.
    assert ACCESS_COOKIE in r.cookies
    assert REFRESH_COOKIE in r.cookies


def test_login_sets_both_cookies(client, faker_fixture):
    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)
    # New client to clear any pre-existing cookies from signup.
    client.cookies.clear()
    r = client.post(LOGIN, json={"email": body["email"], "password": body["password"]})
    assert r.status_code == 200
    assert ACCESS_COOKIE in r.cookies
    assert REFRESH_COOKIE in r.cookies


def test_access_cookie_is_httponly_samesite_lax(client, faker_fixture):
    body = _payload(faker_fixture)
    r = client.post(SIGNUP, json=body)
    attrs = _cookie_attrs(r, ACCESS_COOKIE)
    assert attrs is not None
    assert attrs.get("httponly") is True
    assert attrs.get("samesite", "").lower() == "lax"
    assert attrs.get("path") == "/"


def test_refresh_cookie_is_path_scoped_to_auth(client, faker_fixture):
    body = _payload(faker_fixture)
    r = client.post(SIGNUP, json=body)
    attrs = _cookie_attrs(r, REFRESH_COOKIE)
    assert attrs is not None
    assert attrs.get("httponly") is True
    # Narrowing the refresh cookie path limits CSRF/leak blast radius.
    assert attrs.get("path") == "/auth"


# --- cookie auth on protected endpoints ---

def test_me_with_cookie_only(client, faker_fixture):
    """No Authorization header — cookie alone authenticates /auth/me."""
    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)
    # TestClient persists cookies on the client instance — that's how a browser
    # behaves, so this is the realistic flow.
    r = client.get(ME)
    assert r.status_code == 200, r.text
    assert r.json()["email"] == body["email"]


def test_me_with_bearer_header_still_works(client, faker_fixture):
    """API clients without cookies must keep working via Authorization header."""
    body = _payload(faker_fixture)
    tokens = client.post(SIGNUP, json=body).json()
    client.cookies.clear()
    r = client.get(ME, headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert r.status_code == 200
    assert r.json()["email"] == body["email"]


def test_me_no_auth_at_all_is_401(client):
    client.cookies.clear()
    r = client.get(ME)
    assert r.status_code == 401


# --- logout ---

def test_logout_clears_cookies(client, faker_fixture):
    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)
    assert ACCESS_COOKIE in client.cookies

    r = client.post(LOGOUT)
    assert r.status_code == 204
    # After logout, /auth/me with no fresh login is 401.
    # (The TestClient may have cleared cookies via the Set-Cookie max-age=0.)
    r2 = client.get(ME)
    assert r2.status_code == 401


# --- refresh via cookie ---

def test_refresh_using_cookie_only(client, faker_fixture):
    """The refresh cookie alone (no JSON body) must rotate tokens."""
    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)
    # Empty POST — server reads the cookie.
    r = client.post(REFRESH)
    assert r.status_code == 200, r.text
    assert r.json()["access_token"]


def test_refresh_with_invalid_cookie_is_401(client):
    client.cookies.set(REFRESH_COOKIE, "garbage", path="/auth")
    r = client.post(REFRESH)
    assert r.status_code == 401


# --- SSE cookie path ---

def test_stream_with_cookie_only(client, faker_fixture, monkeypatch):
    """/nai/chat/stream must accept cookies (no ?token= query needed)."""
    # Stub the Brain to avoid touching an LLM. We only care that auth resolves.
    from app.routers import nai as nai_router

    class _StubBrain:
        def stream(self, **_kwargs):
            yield {"type": "meta", "conversation_id": "00000000-0000-0000-0000-000000000000"}
            yield {"type": "done"}

    monkeypatch.setattr(nai_router, "_build_brain", lambda _s: _StubBrain())

    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)  # cookies are set on client
    r = client.get(STREAM, params={"message": "hi"})
    assert r.status_code == 200
    assert r.headers.get("content-type", "").startswith("text/event-stream")


def test_stream_legacy_query_token_still_works_with_warning(
    client, faker_fixture, monkeypatch, caplog
):
    """Backward compat: ?token= still authenticates but logs a deprecation warning."""
    from app.routers import nai as nai_router

    class _StubBrain:
        def stream(self, **_kwargs):
            yield {"type": "done"}

    monkeypatch.setattr(nai_router, "_build_brain", lambda _s: _StubBrain())

    body = _payload(faker_fixture)
    tokens = client.post(SIGNUP, json=body).json()
    client.cookies.clear()  # force fallback path

    with caplog.at_level(logging.WARNING, logger="app.dependencies.stream_auth"):
        r = client.get(STREAM, params={"message": "hi", "token": tokens["access_token"]})
    assert r.status_code == 200
    assert any("deprecated ?token=" in rec.message for rec in caplog.records)


def test_stream_no_auth_is_401(client, monkeypatch):
    client.cookies.clear()
    r = client.get(STREAM, params={"message": "hi"})
    assert r.status_code == 401
