"""Week 2 acceptance — Supabase email/password login + create_token(user_id).

Covers:
  1. create_token(user_id) produces a JWT with the correct sub claim
  2. require_auth decodes a token minted by create_token and returns the sub
  3. sign_in_with_supabase returns the user UUID when Supabase says ok
  4. sign_in_with_supabase returns None when Supabase rejects the password
  5. sign_in_with_supabase returns None on Supabase transport error
  6. Round-trip: sign_in -> create_token -> require_auth retrieves the same uuid
"""
from __future__ import annotations

import jwt
import pytest
from types import SimpleNamespace

from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from narai.api import auth as auth_module


# ── create_token / require_auth ─────────────────────────────────────────────


def test_create_token_emits_jwt_with_correct_sub():
    token = auth_module.create_token("user-uuid-aaa")
    payload = jwt.decode(token, auth_module._SECRET, algorithms=[auth_module._ALGORITHM])
    assert payload["sub"] == "user-uuid-aaa"
    assert "exp" in payload


def test_require_auth_returns_sub_from_valid_token():
    token = auth_module.create_token("user-uuid-bbb")
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    assert auth_module.require_auth(creds=creds) == "user-uuid-bbb"


def test_require_auth_raises_401_on_invalid_token():
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="not-a-jwt")
    with pytest.raises(HTTPException) as exc:
        auth_module.require_auth(creds=creds)
    assert exc.value.status_code == 401


def test_create_token_round_trip_different_users_get_different_subs():
    t1 = auth_module.create_token("alice-uuid")
    t2 = auth_module.create_token("bob-uuid")
    c1 = HTTPAuthorizationCredentials(scheme="Bearer", credentials=t1)
    c2 = HTTPAuthorizationCredentials(scheme="Bearer", credentials=t2)
    assert auth_module.require_auth(creds=c1) == "alice-uuid"
    assert auth_module.require_auth(creds=c2) == "bob-uuid"


# ── sign_in_with_supabase ───────────────────────────────────────────────────


class _FakeSupabaseSuccess:
    """Stub mirroring supabase-py's sign_in_with_password success shape."""
    class _Auth:
        def sign_in_with_password(self, body):
            return SimpleNamespace(user=SimpleNamespace(id="fake-uuid-123"))
    auth = _Auth()


class _FakeSupabaseRejected:
    """Stub for Supabase rejecting the password — user attribute is None."""
    class _Auth:
        def sign_in_with_password(self, body):
            return SimpleNamespace(user=None)
    auth = _Auth()


class _FakeSupabaseTransportError:
    """Stub that raises mid-request (e.g. network error)."""
    class _Auth:
        def sign_in_with_password(self, body):
            raise RuntimeError("supabase 503")
    auth = _Auth()


def test_sign_in_returns_uuid_on_success(monkeypatch):
    from core import narai_user
    monkeypatch.setattr(narai_user, "get_supabase", lambda: _FakeSupabaseSuccess())
    result = auth_module.sign_in_with_supabase("alice@x.com", "good-password")
    assert result == "fake-uuid-123"


def test_sign_in_returns_none_when_password_wrong(monkeypatch):
    from core import narai_user
    monkeypatch.setattr(narai_user, "get_supabase", lambda: _FakeSupabaseRejected())
    result = auth_module.sign_in_with_supabase("alice@x.com", "bad-password")
    assert result is None


def test_sign_in_returns_none_on_transport_error(monkeypatch):
    """Errors must never propagate — login route relies on None to send 401."""
    from core import narai_user
    monkeypatch.setattr(narai_user, "get_supabase", lambda: _FakeSupabaseTransportError())
    result = auth_module.sign_in_with_supabase("alice@x.com", "anything")
    assert result is None


# ── End-to-end round-trip ───────────────────────────────────────────────────


def test_sign_in_then_token_then_require_auth_returns_same_uuid(monkeypatch):
    """Walk the full login flow: Supabase says ok → mint JWT → decode → sub."""
    from core import narai_user
    monkeypatch.setattr(narai_user, "get_supabase", lambda: _FakeSupabaseSuccess())

    uuid_from_signin = auth_module.sign_in_with_supabase("alice@x.com", "good")
    token = auth_module.create_token(uuid_from_signin)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    uuid_from_auth = auth_module.require_auth(creds=creds)

    assert uuid_from_signin == uuid_from_auth == "fake-uuid-123"
