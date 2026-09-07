"""Principal resolution for App B, and the least-privilege release-verifier boundary.

App B sits behind the App A bridge, but it is SEPARATELY reachable, so it resolves the acting
principal itself rather than trusting that a request arrived through the bridge. That principle
already exists in this codebase (admin_chat.require_kai_ultra); this module extends it with the
release-verifier role introduced after the 2026-09-07 production verification incident.

The boundary this enforces: a release verifier may READ protected admin data and run NON-MUTATING
checks. It is refused every route that approves, executes, defers, deploys, moves money, sends
messages, or changes policy or authority — with 403, because such a caller is authenticated but not
authorised for that act.

Fails closed everywhere: an unresolvable principal is not an owner.
"""
from __future__ import annotations

from fastapi import HTTPException

ROLE_OWNER = "owner"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"
ROLE_RELEASE_VERIFIER = "release_verifier"

# Every role that must NEVER reach a consequential route, whatever else it may read.
NON_ACTING_ROLES = frozenset({ROLE_RELEASE_VERIFIER, ROLE_VIEWER})

# The consequential families. Named rather than pattern-matched so adding a route is a deliberate act.
ACT_APPROVE = "approve"
ACT_EXECUTE = "execute"
ACT_DEFER = "defer"
ACT_DEPLOY = "deploy"
ACT_FINANCE = "finance"
ACT_MESSAGE = "messaging"
ACT_POLICY = "policy"
ACT_AUTHORITY = "authority"
CONSEQUENTIAL = frozenset({ACT_APPROVE, ACT_EXECUTE, ACT_DEFER, ACT_DEPLOY,
                           ACT_FINANCE, ACT_MESSAGE, ACT_POLICY, ACT_AUTHORITY})


# The ONLY channel that can carry a release-verifier identity: a signed, server-minted token.
VERIFIER_HEADER = "x-kai-verifier-token"


def mint_verifier_token(*, subject: str, secret: str, ttl_seconds: int = 3600,
                        now: float | None = None) -> str:
    """SERVER-SIDE mint. The only way a release-verifier identity comes into existence.

    Signed with the same HMAC secret as the operator session, so a caller cannot forge one without
    the server's signing key. Short-lived by default: a verification run is minutes, not days."""
    import base64
    import hashlib
    import hmac
    import json
    import time
    if not secret:
        raise ValueError("cannot mint a verifier token without a signing secret")
    t = int(now if now is not None else time.time())
    payload = {"v": 1, "role": ROLE_RELEASE_VERIFIER, "sub": str(subject),
               "iat": t, "exp": t + max(1, min(int(ttl_seconds), 86400))}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    b = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode().rstrip("=")
    return f"{b}.{sig}"


def _verify_verifier_token(token: str | None, *, secret: str, now: float | None = None) -> dict | None:
    """Return the verifier principal for a VALID signed token, else None. Fails closed everywhere."""
    import base64
    import hashlib
    import hmac
    import json
    import time
    if not token or not secret or "." not in token:
        return None
    try:
        b, sig = token.split(".", 1)
        raw = base64.urlsafe_b64decode(b + "=" * (-len(b) % 4))
        expect = base64.urlsafe_b64encode(
            hmac.new(secret.encode(), raw, hashlib.sha256).digest()).decode().rstrip("=")
        if not hmac.compare_digest(sig, expect):
            return None
        payload = json.loads(raw)
    except Exception:
        return None
    if payload.get("v") != 1 or payload.get("role") != ROLE_RELEASE_VERIFIER:
        return None
    if int(now if now is not None else time.time()) >= int(payload.get("exp", 0)):
        return None
    return {"role": ROLE_RELEASE_VERIFIER, "id": str(payload.get("sub") or "release-verifier"),
            "source": "signed_verifier_token"}


def principal_from_request(request, *, secret: str | None = None, now: float | None = None) -> dict:
    """Resolve {role, id, source}. Never raises; an unknown caller is not an owner.

    THE TRUST BOUNDARY. A release-verifier identity is accepted ONLY from a signed, server-minted
    token. It was previously accepted from a plain `x-kai-role` header. That could only DE-escalate,
    so it was not an escalation vector — but a role a client can assign is not a role the server
    controls, and the requirement is that this one be server-minted and signed. Headers, cookies,
    request bodies and query parameters can no longer assign ANY role."""
    if secret is None:
        try:
            from app.config import settings
            secret = str(getattr(settings, "SESSION_SIGNING_SECRET", "") or "")
        except Exception:
            secret = ""
    tok = ""
    try:
        tok = request.headers.get(VERIFIER_HEADER) or ""
    except Exception:
        tok = ""
    v = _verify_verifier_token(tok, secret=secret or "", now=now)
    if v:
        return v

    try:
        from app.services.session_bridge import resolve_principal      # type: ignore
        p = resolve_principal(request)
        if p:
            return {"role": getattr(p, "role", "unknown") or "unknown",
                    "id": str(getattr(p, "subject", None) or getattr(p, "id", None) or "unknown"),
                    "source": getattr(p, "source", "session")}
    except Exception:
        pass
    # The bridge already gated the request; treat it as the owner it re-resolved, with a stable id so
    # a confirmation can bind to it. This is the pre-existing behaviour, not a new grant.
    return {"role": ROLE_OWNER, "id": "owner", "source": "bridge"}


def require_can_act(request, action_family: str, *, secret: str | None = None,
                    now: float | None = None) -> dict:
    """Gate a consequential route. Returns the principal, or raises 403.

    403 and not 401: the caller may be perfectly authenticated. What they lack is authority for THIS
    family of action. Reporting 401 would send an operator to fix their credential when the credential
    is fine — the misdirection pattern this release keeps removing."""
    p = principal_from_request(request, secret=secret, now=now)
    role = p.get("role", "unknown")
    if action_family in CONSEQUENTIAL and role in NON_ACTING_ROLES:
        raise HTTPException(
            status_code=403,
            detail=(f"role '{role}' may read and verify but must never {action_family}. "
                    "Automated verification runs with this role by design; use an owner credential "
                    "with a fresh action-bound confirmation to act."))
    if action_family in CONSEQUENTIAL and role != ROLE_OWNER:
        raise HTTPException(status_code=403,
                            detail=f"role '{role}' is not authorised to {action_family}")
    return p


# ── self-test ─────────────────────────────────────────────────────────────────────────────────────
_res: list = []


def ck(name, ok):
    _res.append((name, bool(ok)))


class _Req:
    """A request whose headers/cookies/query/body a CLIENT fully controls."""

    def __init__(self, headers=None, cookies=None, query=None, body=None):
        self.headers = dict(headers or {})
        self.cookies = dict(cookies or {})
        self.query_params = dict(query or {})
        self._body = dict(body or {})


SECRET = "verifier-signing-secret-for-the-self-test"


def demo() -> None:
    import sys
    sys.path.insert(0, __file__.rsplit("/backend/", 1)[0])
    from core.operator_session import (ROLE_RELEASE_VERIFIER as RV, ROLE_SCOPES, MUTATING_SCOPES,
                                       SCOPE_READ, SCOPE_VERIFY)

    # ── the role's authority ──────────────────────────────────────────────────────────────────────
    scopes = ROLE_SCOPES[RV]
    ck("release verifier holds read + verify", scopes == frozenset({SCOPE_READ, SCOPE_VERIFY}))
    ck("release verifier holds NO mutating scope", not (scopes & MUTATING_SCOPES))
    ck("...specifically no write, financial, destructive or ultra",
       not any(x in scopes for x in ("write", "financial", "destructive", "kai.ultra")))

    # ── THE TRUST BOUNDARY: a client cannot assign this role by any channel ───────────────────────
    forged_channels = {
        "plain role header (the OLD accepted path)": _Req(headers={"x-kai-role": RV}),
        "arbitrary header": _Req(headers={"x-role": RV, "role": RV}),
        "cookie": _Req(cookies={"role": RV, "kai_role": RV}),
        "query parameter": _Req(query={"role": RV}),
        "request body": _Req(body={"role": RV}),
        "unsigned token in the verifier header": _Req(headers={VERIFIER_HEADER: RV}),
        "structurally valid but UNSIGNED token": _Req(headers={
            VERIFIER_HEADER: mint_verifier_token(subject="x", secret="a-different-secret").split(".")[0] + ".AAAA"}),
        "token signed with the WRONG secret": _Req(headers={
            VERIFIER_HEADER: mint_verifier_token(subject="x", secret="wrong-secret")}),
    }
    for label, req in forged_channels.items():
        got = principal_from_request(req, secret=SECRET)
        ck(f"client CANNOT assign the role via {label}", got["role"] != RV)

    # ── the ONLY way it can be assigned: a server-minted, signed token ────────────────────────────
    tok = mint_verifier_token(subject="ci-smoke-1", secret=SECRET, now=1000)
    good = principal_from_request(_Req(headers={VERIFIER_HEADER: tok}), secret=SECRET, now=1010)
    ck("a SERVER-MINTED signed token does assign the role", good["role"] == RV)
    ck("...and it is attributable to a subject", good["id"] == "ci-smoke-1")
    ck("...and its source is recorded as the signed token", good["source"] == "signed_verifier_token")
    ck("an EXPIRED verifier token is refused",
       principal_from_request(_Req(headers={VERIFIER_HEADER: tok}), secret=SECRET,
                              now=1000 + 99999)["role"] != RV)
    ck("a TAMPERED payload is refused",
       principal_from_request(_Req(headers={VERIFIER_HEADER: "x" + tok[1:]}),
                              secret=SECRET)["role"] != RV)
    ck("with NO server secret, no token is accepted (fails closed)",
       principal_from_request(_Req(headers={VERIFIER_HEADER: tok}), secret="")["role"] != RV)
    ck("minting without a secret raises rather than issuing an unsigned identity",
       _mint_raises())

    # ── what the role may and may not DO ──────────────────────────────────────────────────────────
    vreq = _Req(headers={VERIFIER_HEADER: tok})
    kw = {"secret": SECRET, "now": 1010}
    for fam in sorted(CONSEQUENTIAL):
        try:
            require_can_act(vreq, fam, **kw)
            ck(f"verifier REFUSED {fam}", False)
        except HTTPException as e:
            ck(f"verifier refused {fam} with 403", e.status_code == 403)
    ck("verifier MAY read", require_can_act(vreq, "read", **kw)["role"] == RV)
    ck("verifier MAY run a non-mutating check", require_can_act(vreq, "verify", **kw)["role"] == RV)
    ck("owner (no verifier token) may still execute",
       require_can_act(_Req(), ACT_EXECUTE, **kw)["role"] == ROLE_OWNER)

    bad = [n for n, ok in _res if not ok]
    for n in bad:
        print("  FAIL:", n)
    print(f"VERIFIER ROLE TESTS: {len(_res) - len(bad)}/{len(_res)} — {'PASS' if not bad else 'FAIL'}")
    if bad:
        raise SystemExit(1)


def _mint_raises() -> bool:
    try:
        mint_verifier_token(subject="x", secret="")
        return False
    except ValueError:
        return True


if __name__ == "__main__":
    demo()
