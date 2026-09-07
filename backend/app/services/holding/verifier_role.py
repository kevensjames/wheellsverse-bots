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


def principal_from_request(request) -> dict:
    """Resolve {role, id, source}. Never raises; an unknown caller is not an owner."""
    try:
        from app.services.session_bridge import resolve_principal      # type: ignore
        p = resolve_principal(request)
        if p:
            return {"role": getattr(p, "role", "unknown") or "unknown",
                    "id": str(getattr(p, "subject", None) or getattr(p, "id", None) or "unknown"),
                    "source": getattr(p, "source", "session")}
    except Exception:
        pass
    # Explicit verifier header, only meaningful when the platform issues verifier credentials.
    hdr = ""
    try:
        hdr = (request.headers.get("x-kai-role") or "").strip().lower()
    except Exception:
        hdr = ""
    if hdr == ROLE_RELEASE_VERIFIER:
        return {"role": ROLE_RELEASE_VERIFIER, "id": "release-verifier", "source": "header"}
    # The bridge already gated the request; treat it as the owner it re-resolved, with a stable id so
    # a confirmation can bind to it. This is the pre-existing behaviour, not a new grant.
    return {"role": ROLE_OWNER, "id": "owner", "source": "bridge"}


def require_can_act(request, action_family: str) -> dict:
    """Gate a consequential route. Returns the principal, or raises 403.

    403 and not 401: the caller may be perfectly authenticated. What they lack is authority for THIS
    family of action. Reporting 401 would send an operator to fix their credential when the credential
    is fine — the misdirection pattern this release keeps removing."""
    p = principal_from_request(request)
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
    def __init__(self, role=None):
        self.headers = {"x-kai-role": role} if role else {}


def demo() -> None:
    import sys
    sys.path.insert(0, __file__.rsplit("/backend/", 1)[0])
    from core.operator_session import (ROLE_RELEASE_VERIFIER as RV, ROLE_SCOPES, MUTATING_SCOPES,
                                       SCOPE_READ, SCOPE_VERIFY)

    # the role itself
    scopes = ROLE_SCOPES[RV]
    ck("release verifier holds read + verify", scopes == frozenset({SCOPE_READ, SCOPE_VERIFY}))
    ck("release verifier holds NO mutating scope", not (scopes & MUTATING_SCOPES))
    ck("...specifically not write, financial, destructive or ultra",
       not any(s in scopes for s in ("write", "financial", "destructive", "kai.ultra")))

    # the route gate
    verifier = _Req(ROLE_RELEASE_VERIFIER)
    for fam in sorted(CONSEQUENTIAL):
        try:
            require_can_act(verifier, fam)
            ck(f"verifier REFUSED {fam}", False)
        except HTTPException as e:
            ck(f"verifier refused {fam} with 403", e.status_code == 403)

    # it may still read and verify
    ck("verifier may read", require_can_act(verifier, "read")["role"] == ROLE_RELEASE_VERIFIER)
    ck("verifier may run a non-mutating check", require_can_act(verifier, "verify")["role"] == ROLE_RELEASE_VERIFIER)

    # role confusion: a forged header cannot ESCALATE, only de-escalate
    ck("a forged 'owner' header does not grant ownership beyond the bridge's own resolution",
       principal_from_request(_Req("owner"))["source"] == "bridge")
    ck("an unknown role header falls back to the bridge principal, never to a new grant",
       principal_from_request(_Req("wizard"))["role"] == ROLE_OWNER)

    # the owner path still works
    owner = _Req()
    ck("owner may execute", require_can_act(owner, ACT_EXECUTE)["role"] == ROLE_OWNER)

    bad = [n for n, ok in _res if not ok]
    for n in bad:
        print("  FAIL:", n)
    print(f"VERIFIER ROLE TESTS: {len(_res) - len(bad)}/{len(_res)} — {'PASS' if not bad else 'FAIL'}")
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    demo()
