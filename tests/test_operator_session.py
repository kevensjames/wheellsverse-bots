"""Pure unit tests for the unified operator identity (Phase P2).

Runs with plain `pytest` — no DB, Redis, or FastAPI app boot required, because
core/operator_session.py is deliberately framework-free. Each test pins one of
the security invariants documented at the top of that module.
"""
import time

import pytest

from core.operator_session import (
    ROLE_OWNER, ROLE_OPERATOR, ROLE_VIEWER,
    SCOPE_READ, SCOPE_WRITE, SCOPE_FINANCIAL, SCOPE_DESTRUCTIVE,
    SCOPE_KAI_CHAT, SCOPE_KAI_ULTRA,
    Principal, mint_session, verify_session, resolve_secret,
    resolve_principal, require_scope, principal_for_role,
)

SECRET = "session-signing-secret"
OWNER_KEY = "owner-api-key-value"
ADMIN_TOKEN = "operator-admin-token-value"


# ── Invariant 3 & 4: least privilege; owner-only ultra ───────────────────────
def test_operator_role_is_least_privilege():
    op = principal_for_role(ROLE_OPERATOR, "test")
    assert op.has(SCOPE_READ) and op.has(SCOPE_WRITE) and op.has(SCOPE_KAI_CHAT)
    # The dangerous scopes must NOT be on operator.
    for s in (SCOPE_FINANCIAL, SCOPE_DESTRUCTIVE, SCOPE_KAI_ULTRA):
        assert not op.has(s), f"operator must not hold {s}"


def test_only_owner_holds_kai_ultra():
    assert principal_for_role(ROLE_OWNER, "t").has(SCOPE_KAI_ULTRA)
    assert not principal_for_role(ROLE_OPERATOR, "t").has(SCOPE_KAI_ULTRA)
    assert not principal_for_role(ROLE_VIEWER, "t").has(SCOPE_KAI_ULTRA)


def test_viewer_is_read_only():
    v = principal_for_role(ROLE_VIEWER, "t")
    assert v.has(SCOPE_READ)
    assert not v.has(SCOPE_WRITE)


# ── Invariant 5 & precedence: secret resolution ──────────────────────────────
def test_owner_key_resolves_to_owner():
    p = resolve_secret(x_api_key=OWNER_KEY, x_admin_token=None,
                       owner_key=OWNER_KEY, admin_token=ADMIN_TOKEN)
    assert p.role == ROLE_OWNER and p.source == "owner_key"


def test_admin_token_resolves_to_operator():
    p = resolve_secret(x_api_key=None, x_admin_token=ADMIN_TOKEN,
                       owner_key=OWNER_KEY, admin_token=ADMIN_TOKEN)
    assert p.role == ROLE_OPERATOR and p.source == "admin_token"


def test_owner_key_beats_admin_token():
    # Both presented → owner wins (higher authority).
    p = resolve_secret(x_api_key=OWNER_KEY, x_admin_token=ADMIN_TOKEN,
                       owner_key=OWNER_KEY, admin_token=ADMIN_TOKEN)
    assert p.role == ROLE_OWNER


def test_bad_secrets_resolve_to_none():
    assert resolve_secret(x_api_key="nope", x_admin_token="nope",
                          owner_key=OWNER_KEY, admin_token=ADMIN_TOKEN) is None
    # Empty/None credentials never yield a default principal.
    assert resolve_secret(x_api_key=None, x_admin_token=None,
                          owner_key=OWNER_KEY, admin_token=ADMIN_TOKEN) is None


def test_unset_server_secret_never_authenticates():
    # If the server has no owner_key configured, an attacker-sent empty key
    # must not match (guards against the `_ct_eq("", "")` foot-gun).
    assert resolve_secret(x_api_key="", x_admin_token=None,
                          owner_key="", admin_token=ADMIN_TOKEN) is None
    assert resolve_secret(x_api_key=None, x_admin_token="",
                          owner_key=OWNER_KEY, admin_token="") is None


# ── Invariant 2: signed, TTL'd session; fail-closed ──────────────────────────
def test_session_round_trip():
    tok = mint_session(ROLE_OPERATOR, secret=SECRET, ttl_seconds=60, now=1000)
    p = verify_session(tok, secret=SECRET, now=1030)
    assert p.role == ROLE_OPERATOR and p.source == "session"


def test_session_expires():
    tok = mint_session(ROLE_OWNER, secret=SECRET, ttl_seconds=60, now=1000)
    assert verify_session(tok, secret=SECRET, now=1000 + 61) is None


def test_session_rejects_tampered_signature():
    tok = mint_session(ROLE_OPERATOR, secret=SECRET, ttl_seconds=60, now=1000)
    body, sig = tok.split(".", 1)
    assert verify_session(tok, secret="different-secret", now=1030) is None
    # Flip the last char of the signature.
    bad = body + "." + sig[:-1] + ("A" if sig[-1] != "A" else "B")
    assert verify_session(bad, secret=SECRET, now=1030) is None


def test_session_rejects_role_escalation_via_payload_swap():
    # An attacker who swaps the payload for role=owner but keeps the old
    # operator signature must be rejected (sig covers the body).
    op_tok = mint_session(ROLE_OPERATOR, secret=SECRET, ttl_seconds=60, now=1000)
    _, op_sig = op_tok.split(".", 1)
    ow_tok = mint_session(ROLE_OWNER, secret=SECRET, ttl_seconds=60, now=1000)
    ow_body, _ = ow_tok.split(".", 1)
    forged = ow_body + "." + op_sig
    assert verify_session(forged, secret=SECRET, now=1030) is None


def test_session_garbage_inputs_fail_closed():
    for junk in (None, "", "no-dot", "a.b.c.d", "...", "notbase64!.x"):
        assert verify_session(junk, secret=SECRET, now=1000) is None


def test_mint_unknown_role_raises():
    with pytest.raises(ValueError):
        mint_session("superuser", secret=SECRET)
    with pytest.raises(ValueError):
        mint_session(ROLE_OWNER, secret="")  # no secret


# ── resolve_principal precedence + require_scope gate ────────────────────────
def test_resolve_principal_prefers_secret_over_session():
    op_sess = mint_session(ROLE_OPERATOR, secret=SECRET, ttl_seconds=60, now=1000)
    p = resolve_principal(
        x_api_key=OWNER_KEY, session_cookie=op_sess,
        owner_key=OWNER_KEY, admin_token=ADMIN_TOKEN,
        session_secret=SECRET, now=1030,
    )
    assert p.role == ROLE_OWNER  # owner key beats a valid operator session


def test_resolve_principal_falls_back_to_session():
    sess = mint_session(ROLE_OPERATOR, secret=SECRET, ttl_seconds=60, now=1000)
    p = resolve_principal(
        x_api_key="wrong", session_cookie=sess,
        owner_key=OWNER_KEY, admin_token=ADMIN_TOKEN,
        session_secret=SECRET, now=1030,
    )
    assert p.role == ROLE_OPERATOR and p.source == "session"


def test_resolve_principal_anonymous():
    assert resolve_principal(owner_key=OWNER_KEY, admin_token=ADMIN_TOKEN,
                             session_secret=SECRET) is None


def test_require_scope_fail_closed_on_anonymous():
    assert require_scope(None, SCOPE_READ) is False
    op = principal_for_role(ROLE_OPERATOR, "t")
    assert require_scope(op, SCOPE_WRITE) is True
    assert require_scope(op, SCOPE_DESTRUCTIVE) is False


# ── Invariant 1: constant-time comparison is actually used ───────────────────
def test_uses_constant_time_compare(monkeypatch):
    import core.operator_session as mod
    calls = {"n": 0}
    real = mod.hmac.compare_digest

    def counting(a, b):
        calls["n"] += 1
        return real(a, b)

    monkeypatch.setattr(mod.hmac, "compare_digest", counting)
    resolve_secret(x_api_key=OWNER_KEY, x_admin_token=None,
                   owner_key=OWNER_KEY, admin_token=ADMIN_TOKEN)
    verify_session(mint_session(ROLE_OWNER, secret=SECRET, now=1000),
                   secret=SECRET, now=1000)
    assert calls["n"] >= 2  # secret compare + signature compare both constant-time


def test_frozen_principal_is_immutable():
    p = principal_for_role(ROLE_OPERATOR, "t")
    with pytest.raises(Exception):
        p.role = ROLE_OWNER  # frozen dataclass
