"""Path X auth tests.

The shape of the API is unchanged from Stage 6 (signup returns TokenResponse,
login 401s on bad creds, refresh rotates), but the backend now talks to
Supabase Auth — mocked in conftest's fake_supabase_auth shim.
"""
from __future__ import annotations

import time

import jwt
import pytest
from sqlalchemy import text


SIGNUP = "/auth/signup"
LOGIN = "/auth/login"
REFRESH = "/auth/refresh"
LOGOUT = "/auth/logout"
ME = "/auth/me"


def _payload(faker):
    return {
        "email": faker.unique.email().lower(),
        "password": "testpass123",
        "full_name": faker.name(),
    }


# --- signup ---

def test_signup_success(client, db_session, faker_fixture):
    body = _payload(faker_fixture)
    r = client.post(SIGNUP, json=body)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["access_token"] and data["refresh_token"]
    assert data["token_type"] == "bearer"
    # Path X: signup writes auth.users (trigger -> profiles). The fake creates
    # the profiles row directly. Verify it landed.
    prof = db_session.execute(
        text("SELECT email, name FROM profiles WHERE email = :e"),
        {"e": body["email"]},
    ).mappings().first()
    assert prof is not None
    assert prof["email"] == body["email"]
    assert prof["name"] == body["full_name"]


def test_signup_duplicate_email(client, faker_fixture):
    body = _payload(faker_fixture)
    assert client.post(SIGNUP, json=body).status_code == 201
    r = client.post(SIGNUP, json=body)
    assert r.status_code == 409


def test_signup_weak_password(client, faker_fixture):
    body = _payload(faker_fixture)
    body["password"] = "short"
    r = client.post(SIGNUP, json=body)
    assert r.status_code == 422


def test_signup_invalid_email(client):
    r = client.post(SIGNUP, json={"email": "notanemail", "password": "testpass123"})
    assert r.status_code == 422


# --- login ---

def test_login_success(client, faker_fixture):
    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)
    r = client.post(LOGIN, json={"email": body["email"], "password": body["password"]})
    assert r.status_code == 200
    assert r.json()["access_token"]


def test_login_wrong_password(client, faker_fixture):
    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)
    r = client.post(LOGIN, json={"email": body["email"], "password": "wrongpass1"})
    assert r.status_code == 401
    # Same generic message for unknown email + bad password (no enumeration).
    assert "invalid" in r.json()["detail"].lower()


def test_login_nonexistent_email(client):
    r = client.post(LOGIN, json={"email": "nobody@example.com", "password": "testpass123"})
    assert r.status_code == 401
    assert "invalid" in r.json()["detail"].lower()


# --- /me ---

def test_me_authenticated(client, faker_fixture):
    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)
    # TestClient keeps cookies; /me works on the cookie.
    r = client.get(ME)
    assert r.status_code == 200
    me = r.json()
    assert me["email"] == body["email"]
    # Path X UserResponse: id, email, full_name, tier, created_at.
    assert "tier" in me
    assert me["tier"] == "free"


def test_me_no_token(client):
    client.cookies.clear()
    r = client.get(ME)
    assert r.status_code == 401


def test_me_invalid_token(client):
    client.cookies.clear()
    r = client.get(ME, headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401


def test_me_expired_token(client, faker_fixture):
    """Mint an HS256 token with exp in the past — patched decode_supabase_jwt
    rejects it."""
    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)
    now = int(time.time())
    expired = jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000000",
            "email": body["email"],
            "role": "authenticated",
            "aud": "authenticated",
            "iat": now - 7200,
            "exp": now - 60,
        },
        "test-secret-not-prod",
        algorithm="HS256",
    )
    client.cookies.clear()
    r = client.get(ME, headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code == 401


# --- refresh ---

def test_refresh_success(client, faker_fixture):
    body = _payload(faker_fixture)
    tokens = client.post(SIGNUP, json=body).json()
    r = client.post(REFRESH, json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    new_tokens = r.json()
    assert new_tokens["access_token"]
    assert new_tokens["refresh_token"]
    # New access token authenticates /me.
    client.cookies.clear()
    me = client.get(ME, headers={"Authorization": f"Bearer {new_tokens['access_token']}"})
    assert me.status_code == 200


def test_refresh_with_access_token_is_rejected(client, faker_fixture):
    """Path X: the fake's refresh_session checks refresh_to_user map; an
    access token isn't there, so 401."""
    body = _payload(faker_fixture)
    tokens = client.post(SIGNUP, json=body).json()
    r = client.post(REFRESH, json={"refresh_token": tokens["access_token"]})
    assert r.status_code == 401


def test_refresh_invalid(client):
    r = client.post(REFRESH, json={"refresh_token": "garbage"})
    assert r.status_code == 401


def test_refresh_missing_token(client):
    client.cookies.clear()
    r = client.post(REFRESH)
    assert r.status_code == 401


# --- logout ---

def test_logout_clears_cookies(client, faker_fixture):
    body = _payload(faker_fixture)
    client.post(SIGNUP, json=body)
    r = client.post(LOGOUT)
    assert r.status_code == 204
    # After logout, /me with no fresh login is 401.
    r2 = client.get(ME)
    assert r2.status_code == 401
