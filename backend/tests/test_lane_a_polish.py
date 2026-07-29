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


# ── HIGH fix: a valid cookie holder can't mint new buckets by rotating bearer ─
def test_cookie_key_immune_to_bearer_rotation():
    """The limiter key must track the authenticated principal (cookie-first, like
    the endpoints) — rotating an unvalidated Authorization header must NOT change
    the bucket, or the per-user cap is trivially bypassed on the streaming path."""
    base = user_or_ip_key(_req(cookies={"nai_access": "cookieval"}))
    b1 = user_or_ip_key(_req(cookies={"nai_access": "cookieval"}, auth="Bearer rot-1"))
    b2 = user_or_ip_key(_req(cookies={"nai_access": "cookieval"}, auth="Bearer rot-2"))
    assert base == b1 == b2  # cookie wins; bearer rotation has no effect


def test_pure_bearer_client_still_keyed_by_bearer():
    # no cookie/query token -> bearer IS the credential, so it keys the bucket
    assert user_or_ip_key(_req(auth="Bearer only-cred")).startswith("u:")


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


def test_logout_revokes_via_refresh_when_access_cookie_absent(client, monkeypatch):
    """The routine >60-min case: access cookie expired, refresh cookie still
    present. Logout must exchange the refresh token and revoke — not no-op."""
    calls = {}
    def _fake_refresh(r):
        calls["refreshed"] = r
        return {"access_token": "exchanged-tok"}
    monkeypatch.setattr("app.services.supabase_auth.refresh_session", _fake_refresh)
    monkeypatch.setattr("app.services.supabase_auth.sign_out",
                        lambda tok: calls.__setitem__("signed_out", tok))
    r = client.post("/auth/logout", cookies={"nai_refresh": "refresh-tok-xyz"})
    assert r.status_code == 204
    assert calls["refreshed"] == "refresh-tok-xyz"       # refresh token exchanged (and thereby rotated/invalidated)
    assert calls["signed_out"] == "exchanged-tok"        # session actually revoked


# ── Stripe money-mode latch accepts restricted (rk_) keys ────────────────────
def _prod(**kw):
    return Settings(DATABASE_URL="postgresql://x", ADMIN_TOKEN=_STRONG, APP_ENV="production", **kw)


def test_stripe_restricted_live_key_boots_in_prod():
    # rk_live_ is a valid Stripe secret (least-privilege) — must not crash boot.
    assert _prod(STRIPE_SECRET_KEY="rk_live_abc123restricted").STRIPE_SECRET_KEY.startswith("rk_live_")


def test_stripe_restricted_test_key_refused_in_prod():
    with pytest.raises(ValueError, match="TEST Stripe key"):
        _prod(STRIPE_SECRET_KEY="rk_test_abc123restricted")


def test_stripe_restricted_live_key_refused_in_nonprod():
    with pytest.raises(ValueError, match="LIVE Stripe key"):
        Settings(DATABASE_URL="postgresql://x", ADMIN_TOKEN=_STRONG,
                 APP_ENV="development", STRIPE_SECRET_KEY="rk_live_abc123restricted")


# ── 429 carries Retry-After (directive requirement) ──────────────────────────
@pytest.fixture
def _rate_limiter_on():
    from app.core.rate_limit import limiter
    limiter.reset(); limiter.enabled = True
    try:
        yield
    finally:
        limiter.enabled = False; limiter.reset()


def test_signup_429_carries_retry_after(client, faker_fixture, _rate_limiter_on):
    for _ in range(5):
        client.post("/auth/signup", json={"email": faker_fixture.unique.email().lower(),
                                           "password": "testpass123", "full_name": "T U"})
    r = client.post("/auth/signup", json={"email": faker_fixture.unique.email().lower(),
                                          "password": "testpass123", "full_name": "T U"})
    assert r.status_code == 429
    assert "retry-after" in {k.lower() for k in r.headers}  # client can back off


def test_stream_rate_limit_survives_bearer_rotation_e2e(client, monkeypatch, _rate_limiter_on):
    """RELEASE GATE for the HIGH finding. With the LIVE limiter enabled, a
    cookie-authenticated caller who rotates the Authorization bearer on every
    request must still be throttled at the 30/minute cap — proving the bucket
    tracks the cookie principal, not the attacker-chosen header.

    This is the exact bypass the APP_ENV=test / limiter-disabled suite could not
    see (original probe: 60/60 opened, 0×429). Keep it end-to-end so the whole
    class of key-vs-auth precedence bypass cannot quietly return."""
    import uuid as _uuid
    from app.main import app
    from app.dependencies.stream_auth import get_user_for_stream

    class _Principal:
        id = _uuid.uuid4()

    class _StubBrain:  # no providers/DB — the limiter fires before this runs on #31
        def stream(self, **kw):
            yield {"type": "done", "assistant_message_id": "x"}

    app.dependency_overrides[get_user_for_stream] = lambda: _Principal()
    monkeypatch.setattr("app.routers.nai._build_brain", lambda session: _StubBrain())
    try:
        codes = [
            client.get("/kai/chat/stream", params={"message": "hi"},
                       headers={"Authorization": f"Bearer rot-{n}"},
                       cookies={"nai_access": "stable-session-cookie"}).status_code
            for n in range(40)
        ]
    finally:
        app.dependency_overrides.pop(get_user_for_stream, None)

    assert all(c == 200 for c in codes[:30]), f"first 30 should pass: {codes[:30]}"
    assert codes[30] == 429, f"31st (rotated bearer) must be throttled, got {codes[30]}"
    assert codes.count(200) == 30  # rotating the bearer did NOT mint fresh buckets


# ── hosted adapters do not blindly retry a non-idempotent completion ─────────
def test_hosted_adapters_disable_blind_retry():
    from app.services.router.adapters.openai_adapter import OpenAIAdapter
    from app.services.router.adapters.anthropic_adapter import AnthropicAdapter
    from app.services.router.adapters.perplexity_adapter import PerplexityAdapter
    assert OpenAIAdapter(api_key="sk-test-x")._client.max_retries == 0
    assert AnthropicAdapter(api_key="sk-test-x")._client.max_retries == 0
    assert PerplexityAdapter(api_key="sk-test-x")._client.max_retries == 0


# ── brain.stream redacts unexpected errors, preserves the spend-cap signal ───
def _brain(db_session, router):
    from app.services.nai_brain import Brain
    from app.services.tools.registry import ToolRegistry
    return Brain(session=db_session, router=router, registry=ToolRegistry())


def _stream_errors(brain, user_id):
    events = list(brain.stream(user_id=user_id, conversation_id=None, user_message="hi"))
    return [e for e in events if e.get("type") == "error"]


def test_stream_redacts_raw_provider_error(db_session, free_user):
    class _Boom:
        def stream(self, **kw):
            raise RuntimeError("PROVIDER-500 secret-internal-detail-xyz")
            yield  # noqa — makes this a generator so the raise fires on iteration
    errs = _stream_errors(_brain(db_session, _Boom()), free_user.id)
    assert errs and errs[0]["error"] == "The assistant hit an error. Please try again."
    assert "secret-internal-detail" not in errs[0]["error"]  # raw detail not leaked to client


def test_stream_preserves_spend_cap_signal(db_session, free_user):
    from app.services.router.router import SpendCapExceeded
    class _Capped:
        def stream(self, **kw):
            raise SpendCapExceeded("daily")
            yield
    errs = _stream_errors(_brain(db_session, _Capped()), free_user.id)
    # the actionable spend-cap message is surfaced verbatim, NOT redacted to the generic one
    assert errs and "daily usage limit" in errs[0]["error"]
    assert errs[0]["error"] != "The assistant hit an error. Please try again."
