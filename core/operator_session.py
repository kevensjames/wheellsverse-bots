"""Unified operator identity for the KAI⇄Admin merge (Phase P2).

Reconciles the two pre-existing shared-secret auth schemes into ONE principal:

  - App A owner key   — core/api.py `verify_api_key` (X-API-Key, hmac-compared
                        against API_KEY). Today: binary all-or-nothing, and it
                        also accepts the leaky `?api_key=` query param.
  - App B operator    — backend/app/dependencies/admin.py `require_admin_token`
                        (X-Admin-Token vs ADMIN_TOKEN, plain `!=`, not even
                        constant-time).

Neither has roles or scopes. This module adds a `Principal` (role + least-
privilege scopes) plus a stateless HMAC-signed session cookie, so an operator
authenticates ONCE and every surface — the admin pages, the KAI orb/drawer, the
full Nexus — reads the *same* identity and the *same* authority.

Pure module: no FastAPI / DB / Redis import, so the security logic is unit-
testable without booting the 15k-line monolith (the app can't run locally).
The thin FastAPI adapter lives in the integration plan, not here.

SECURITY INVARIANTS (each pinned by a test in tests/test_operator_session.py):
  1. Every secret/signature comparison is constant-time (hmac.compare_digest).
  2. The session cookie is HMAC-signed and TTL'd; any tamper or expiry yields
     NO principal (fail-closed), never a downgraded-but-valid one.
  3. Least privilege: the `operator` role does NOT hold FINANCIAL, DESTRUCTIVE,
     or KAI-ULTRA scope. Only `owner` does.
  4. `SCOPE_KAI_ULTRA` gates the /admin/kai-chat synthetic "ultra" profile that
     today bypasses all tier gates — so wiring the orb to it can no longer be a
     privilege-escalation path (merge brief §12).
  5. Precedence owner > operator > session; an unknown/empty credential set
     resolves to None (anonymous), never to a default role.
"""
from __future__ import annotations

import base64
import hmac
import json
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Optional


# ── Scope taxonomy — mirrors the merge brief §13 impact classes ──────────────
SCOPE_READ = "read"                 # READ_ONLY — safe to auto-run for any principal
SCOPE_WRITE = "write"               # REVERSIBLE_WRITE — ordinary mutations
SCOPE_HIGH_IMPACT = "high_impact"   # HIGH_IMPACT — deploys etc.; approval-gated in governance
SCOPE_FINANCIAL = "financial"       # FINANCIAL — refunds/payouts; explicit confirmation
SCOPE_DESTRUCTIVE = "destructive"   # DESTRUCTIVE — deletes; strong confirmation + audit
SCOPE_KAI_CHAT = "kai.chat"         # talk to the governed KAI brain
SCOPE_KAI_ULTRA = "kai.ultra"       # the /admin/kai-chat 'ultra' no-tier-gate profile — OWNER ONLY

ALL_SCOPES = frozenset({
    SCOPE_READ, SCOPE_WRITE, SCOPE_HIGH_IMPACT, SCOPE_FINANCIAL,
    SCOPE_DESTRUCTIVE, SCOPE_KAI_CHAT, SCOPE_KAI_ULTRA,
})

# ── Roles → scopes. Least privilege: operator is deliberately NOT financial/
#    destructive/ultra. Those require the owner key (or an explicit approval
#    flow layered on top — governance.py, out of scope for this module). ──────
ROLE_OWNER = "owner"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"

ROLE_SCOPES: dict[str, frozenset[str]] = {
    ROLE_OWNER: ALL_SCOPES,
    ROLE_OPERATOR: frozenset({SCOPE_READ, SCOPE_WRITE, SCOPE_KAI_CHAT}),
    ROLE_VIEWER: frozenset({SCOPE_READ}),
}


@dataclass(frozen=True)
class Principal:
    """Who is acting, and what they may do. Immutable so a resolved identity
    can't be mutated mid-request into a higher authority."""
    role: str
    scopes: frozenset
    source: str  # "owner_key" | "admin_token" | "session" — for audit

    def has(self, scope: str) -> bool:
        return scope in self.scopes


def principal_for_role(role: str, source: str) -> Optional[Principal]:
    scopes = ROLE_SCOPES.get(role)
    if scopes is None:
        return None
    return Principal(role=role, scopes=scopes, source=source)


# ── Secret-based resolution (the two legacy schemes, now returning a role) ────
def _ct_eq(a: Optional[str], b: Optional[str]) -> bool:
    """Constant-time string equality that is safe on None / length mismatch."""
    if not a or not b:
        return False
    return hmac.compare_digest(a, b)


def resolve_secret(
    *,
    x_api_key: Optional[str],
    x_admin_token: Optional[str],
    owner_key: Optional[str],
    admin_token: Optional[str],
) -> Optional[Principal]:
    """Map the two shared secrets to a Principal. Owner key wins over operator
    token (higher authority). Returns None if neither matches — never a default."""
    if owner_key and _ct_eq(x_api_key, owner_key):
        return principal_for_role(ROLE_OWNER, "owner_key")
    if admin_token and _ct_eq(x_admin_token, admin_token):
        return principal_for_role(ROLE_OPERATOR, "admin_token")
    return None


# ── Stateless signed session cookie ──────────────────────────────────────────
# Format: b64url(payload_json) + "." + b64url(hmac_sha256(payload_json)).
# Stateless (no server store) so it works across gunicorn workers without Redis,
# which the transformation plan flags as a real constraint for in-memory state.
_SESSION_VERSION = 1


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64u_dec(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def mint_session(role: str, *, secret: str, ttl_seconds: int = 43200,
                 now: Optional[float] = None) -> str:
    """Issue a signed session token for `role` (default TTL 12h). Raises on an
    unknown role so we never mint a token that resolves to no authority."""
    if role not in ROLE_SCOPES:
        raise ValueError(f"unknown role: {role!r}")
    if not secret:
        raise ValueError("session secret required")
    now = time.time() if now is None else now
    payload = {"v": _SESSION_VERSION, "role": role,
               "iat": int(now), "exp": int(now) + int(ttl_seconds)}
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), body, sha256).digest()
    return _b64u(body) + "." + _b64u(sig)


def verify_session(token: Optional[str], *, secret: str,
                   now: Optional[float] = None) -> Optional[Principal]:
    """Return the Principal for a valid, unexpired, untampered token, else None.
    Fail-closed on every error path (bad shape, bad sig, expired, unknown role)."""
    if not token or not secret or "." not in token:
        return None
    try:
        body_b64, sig_b64 = token.split(".", 1)
        body = _b64u_dec(body_b64)
        got_sig = _b64u_dec(sig_b64)
    except Exception:
        return None
    want_sig = hmac.new(secret.encode("utf-8"), body, sha256).digest()
    if not hmac.compare_digest(got_sig, want_sig):
        return None
    try:
        payload = json.loads(body)
    except Exception:
        return None
    if payload.get("v") != _SESSION_VERSION:
        return None
    now = time.time() if now is None else now
    if not isinstance(payload.get("exp"), int) or payload["exp"] < now:
        return None
    return principal_for_role(payload.get("role", ""), "session")


# ── The one resolver every surface calls ─────────────────────────────────────
def resolve_principal(
    *,
    x_api_key: Optional[str] = None,
    x_admin_token: Optional[str] = None,
    session_cookie: Optional[str] = None,
    owner_key: Optional[str] = None,
    admin_token: Optional[str] = None,
    session_secret: Optional[str] = None,
    now: Optional[float] = None,
) -> Optional[Principal]:
    """Single entry point: reconcile any credential into one Principal.
    Precedence: owner key > operator token > session cookie > anonymous(None)."""
    p = resolve_secret(
        x_api_key=x_api_key, x_admin_token=x_admin_token,
        owner_key=owner_key, admin_token=admin_token,
    )
    if p is not None:
        return p
    if session_secret:
        return verify_session(session_cookie, secret=session_secret, now=now)
    return None


def require_scope(principal: Optional[Principal], scope: str) -> bool:
    """Authorization check: True iff a principal exists AND holds `scope`.
    Anonymous (None) is always False — fail-closed."""
    return principal is not None and principal.has(scope)


if __name__ == "__main__":  # tiny smoke self-check (see tests for the real suite)
    tok = mint_session(ROLE_OPERATOR, secret="s3cret", ttl_seconds=60, now=1000)
    assert verify_session(tok, secret="s3cret", now=1030).role == ROLE_OPERATOR
    assert verify_session(tok, secret="s3cret", now=2000) is None  # expired
    assert verify_session(tok, secret="WRONG", now=1030) is None   # bad sig
    op = resolve_principal(x_admin_token="t", admin_token="t")
    assert op.role == ROLE_OPERATOR and not op.has(SCOPE_KAI_ULTRA)  # no escalation
    ow = resolve_principal(x_api_key="k", owner_key="k")
    assert ow.role == ROLE_OWNER and ow.has(SCOPE_KAI_ULTRA)
    print("operator_session smoke OK")
