"""Lane A polish: rate-limit keying, DEBUG default, provider timeout, logout revoke.

The 429-firing mechanism itself is the shared slowapi limiter, already proven by
tests/test_auth_rate_limit.py. These tests cover the NEW logic: correct per-user /
per-IP keying (isolation + trusted-proxy), the safe DEBUG default, the bounded
provider timeout, and that logout actually revokes the Supabase session.
"""
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.core.client_ip import client_ip, user_or_ip_key
from app.services.router.adapters._timeout import provider_timeout


def _req(peer="127.0.0.1", headers=None, cookies=None, query=None, auth=None):
    h = dict(headers or {})
    if auth:
        h["authorization"] = auth
    return SimpleNamespace(
        client=SimpleNamespace(host=peer),
        headers=h, query_params=dict(query or {}), cookies=dict(cookies or {}),
    )


# ── client IP: trust forwarded headers ONLY from a trusted local peer ────────
def test_client_ip_trusts_cf_header_from_loopback_peer():
    assert client_ip(_req(peer="127.0.0.1", headers={"cf-connecting-ip": "9.9.9.9"})) == "9.9.9.9"


def test_client_ip_ignores_spoofed_header_from_untrusted_peer():
    # a routable public peer must NOT be able to spoof its client IP via XFF.
    # (Use 8.8.8.8 — the 203.0.113/24 doc range is is_private=True on py3.11+.)
    r = _req(peer="8.8.8.8", headers={"x-forwarded-for": "1.2.3.4"})
    assert client_ip(r) == "8.8.8.8"


def test_client_ip_ipv6_loopback_is_trusted():
    assert client_ip(_req(peer="::1", headers={"cf-connecting-ip": "9.9.9.9"})) == "9.9.9.9"


def test_client_ip_none_request_is_unknown():
    assert client_ip(None) == "unknown"


# ── per-user keying: tenants are isolated, no plaintext token in the key ─────
def test_user_key_isolates_two_users():
    k1 = user_or_ip_key(_req(auth="Bearer token-user-1"))
    k2 = user_or_ip_key(_req(auth="Bearer token-user-2"))
    assert k1 != k2 and k1.startswith("u:") and "token-user-1" not in k1  # hashed


def test_same_token_same_key():
    assert user_or_ip_key(_req(auth="Bearer t")) == user_or_ip_key(_req(auth="Bearer t"))


def test_stream_token_and_cookie_are_keyed():
    assert user_or_ip_key(_req(query={"token": "qtok"})).startswith("u:")
    assert user_or_ip_key(_req(cookies={"nai_access": "ctok"})).startswith("u:")


def test_anonymous_falls_back_to_ip():
    k = user_or_ip_key(_req(peer="127.0.0.1", headers={"cf-connecting-ip": "9.9.9.9"}))
    assert k == "ip:9.9.9.9"


# ── DEBUG safe default ───────────────────────────────────────────────────────
_STRONG = "a-strong-admin-token-of-at-least-32-chars-xxx"


def test_debug_defaults_off():
    assert Settings(DATABASE_URL="postgresql://x", ADMIN_TOKEN=_STRONG).DEBUG is False


def test_debug_true_in_prod_refused():
    with pytest.raises(ValueError, match="DEBUG"):
        Settings(DATABASE_URL="postgresql://x", ADMIN_TOKEN=_STRONG,
                 APP_ENV="production", DEBUG=True)


# ── provider timeout ─────────────────────────────────────────────────────────
def test_provider_timeout_default_and_override(monkeypatch):
    monkeypatch.delenv("NAI_PROVIDER_TIMEOUT_S", raising=False)
    assert provider_timeout() == 30.0
    monkeypatch.setenv("NAI_PROVIDER_TIMEOUT_S", "12.5")
    assert provider_timeout() == 12.5
    monkeypatch.setenv("NAI_PROVIDER_TIMEOUT_S", "garbage")
    assert provider_timeout() == 30.0  # bad value → safe default


# ── logout revokes the Supabase session ──────────────────────────────────────
def test_logout_revokes_session(client, monkeypatch):
    called = {}
    monkeypatch.setattr("app.services.supabase_auth.sign_out",
                        lambda tok: called.setdefault("tok", tok))
    r = client.post("/auth/logout", cookies={"nai_access": "access-tok-123"})
    assert r.status_code == 204
    assert called["tok"] == "access-tok-123"  # refresh/session revoked, not just cookies cleared


def test_logout_idempotent_without_token(client, monkeypatch):
    monkeypatch.setattr("app.services.supabase_auth.sign_out", lambda tok: None)
    assert client.post("/auth/logout").status_code == 204  # no token → still succeeds
