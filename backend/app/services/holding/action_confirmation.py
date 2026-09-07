"""Action-bound owner confirmation for consequential holding actions.

WHY THIS EXISTS. On 2026-09-07 a release verifier executed an owner-approved proposal on production
with a generic owner session, while checking whether the control failed closed. It did not, and it was
right not to: the proposal genuinely was approved, and the session genuinely was the owner. Nothing
bound the two together.

Approval and execution are separated in time. Between them, an approval decays into a standing
permission that any later owner-authenticated request can spend. This module removes that: executing an
approved proposal requires a FRESH confirmation bound to five things at once —

    owner identity   the confirmation is minted for one principal and no other
    proposal id      it authorises exactly one proposal
    action digest    it authorises exactly the action that was approved; if the action changes, the
                     confirmation stops matching, so a swapped payload cannot ride an old confirmation
    environment      a staging confirmation cannot execute in production
    expiry           short-lived, so a captured confirmation is useless minutes later

A confirmation is a signed token, not server state, so it works across workers with no shared store —
the same constraint the session cookie is built around. It is single-use in the sense that matters:
execution itself remains one-time and idempotent, enforced by the proposal store's status transition.
This module adds a gate in front of that; it does not replace it.

WHAT THIS IS NOT. It is not an approval mechanism. The owner still approves a proposal through the
normal governed path. This only ensures that spending an approval is a deliberate, current, specific
act rather than an ambient capability of being logged in.

Pure stdlib. No I/O. Testable as a plain python3 module.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

# Deliberately short. A confirmation is meant to be minted, shown to the owner, and spent immediately.
DEFAULT_TTL_SECONDS = 120
MAX_TTL_SECONDS = 600

_VERSION = 1

# Failure reasons. Each is distinct so a caller can never collapse "expired" into "forged" and report
# the wrong cause to an operator — the misdirection defect this release keeps removing.
OK = "OK"
MISSING = "CONFIRMATION_MISSING"
MALFORMED = "CONFIRMATION_MALFORMED"
BAD_SIGNATURE = "CONFIRMATION_SIGNATURE_INVALID"
EXPIRED = "CONFIRMATION_EXPIRED"
WRONG_PRINCIPAL = "CONFIRMATION_PRINCIPAL_MISMATCH"
WRONG_PROPOSAL = "CONFIRMATION_PROPOSAL_MISMATCH"
WRONG_ACTION = "CONFIRMATION_ACTION_DIGEST_MISMATCH"
WRONG_ENVIRONMENT = "CONFIRMATION_ENVIRONMENT_MISMATCH"
NOT_OWNER = "CONFIRMATION_REQUIRES_OWNER"


def action_digest(action: dict | None) -> str:
    """A stable digest of the exact action being authorised.

    Canonical JSON with sorted keys, so key order cannot change the digest, and any change to the
    action's content DOES change it. That is the point: a confirmation authorises one action, not
    "whatever proposal 9 happens to say when the request arrives"."""
    canonical = json.dumps(action or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(txt: str) -> bytes:
    return base64.urlsafe_b64decode(txt + "=" * (-len(txt) % 4))


def _sign(payload: bytes, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), payload, hashlib.sha256).digest())


def mint(*, principal_id: str, role: str, proposal_id, action: dict | None, environment: str,
         secret: str, ttl_seconds: int = DEFAULT_TTL_SECONDS, now: float | None = None) -> dict:
    """Mint a confirmation. Only an OWNER may hold one — a release verifier must never be able to."""
    if role != "owner":
        return {"ok": False, "reason": NOT_OWNER, "token": None}
    if not secret:
        return {"ok": False, "reason": "CONFIRMATION_NO_SIGNING_SECRET", "token": None}
    ttl = max(1, min(int(ttl_seconds or DEFAULT_TTL_SECONDS), MAX_TTL_SECONDS))
    t = int(now if now is not None else time.time())
    payload = {
        "v": _VERSION,
        "sub": str(principal_id),
        "role": role,
        "pid": str(proposal_id),
        "dig": action_digest(action),
        "env": str(environment or "").strip().lower(),
        "iat": t,
        "exp": t + ttl,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {"ok": True, "reason": OK, "token": f"{_b64(raw)}.{_sign(raw, secret)}",
            "expires_at": payload["exp"], "action_digest": payload["dig"]}


def verify(token: str | None, *, principal_id: str, role: str, proposal_id, action: dict | None,
           environment: str, secret: str, now: float | None = None) -> dict:
    """Verify a confirmation against the request actually being made. Fails closed on every path.

    Order matters: the signature is checked BEFORE any field is trusted, so a forged token cannot
    steer the comparison. Each mismatch reports its own reason."""
    if not token:
        return {"ok": False, "reason": MISSING}
    if role != "owner":
        return {"ok": False, "reason": NOT_OWNER}
    if not secret:
        return {"ok": False, "reason": "CONFIRMATION_NO_SIGNING_SECRET"}
    try:
        b64_payload, sig = token.split(".", 1)
        raw = _unb64(b64_payload)
        payload = json.loads(raw)
    except Exception:
        return {"ok": False, "reason": MALFORMED}
    if not hmac.compare_digest(sig, _sign(raw, secret)):
        return {"ok": False, "reason": BAD_SIGNATURE}
    if payload.get("v") != _VERSION or payload.get("role") != "owner":
        return {"ok": False, "reason": MALFORMED}

    t = int(now if now is not None else time.time())
    if t >= int(payload.get("exp", 0)):
        return {"ok": False, "reason": EXPIRED}
    if not hmac.compare_digest(str(payload.get("sub", "")), str(principal_id)):
        return {"ok": False, "reason": WRONG_PRINCIPAL}
    if str(payload.get("pid")) != str(proposal_id):
        return {"ok": False, "reason": WRONG_PROPOSAL}
    if str(payload.get("env", "")) != str(environment or "").strip().lower():
        return {"ok": False, "reason": WRONG_ENVIRONMENT}
    if not hmac.compare_digest(str(payload.get("dig", "")), action_digest(action)):
        return {"ok": False, "reason": WRONG_ACTION}
    return {"ok": True, "reason": OK, "confirmed_for": {"proposal_id": str(proposal_id),
                                                        "environment": environment,
                                                        "expires_at": payload.get("exp")}}


# ── self-test ─────────────────────────────────────────────────────────────────────────────────────
_res: list = []


def ck(name, ok):
    _res.append((name, bool(ok)))


def demo() -> None:
    S = "signing-secret-for-the-self-test"
    ACT = {"action_class": "REPROBE", "target": "holding", "worker": None}
    base = dict(principal_id="owner-1", role="owner", proposal_id=9, action=ACT,
                environment="production", secret=S)

    m = mint(**base, now=1000)
    ck("an owner can mint a confirmation", m["ok"] and m["token"])
    ck("verifying the same request succeeds", verify(m["token"], **base, now=1010)["ok"])

    # THE INCIDENT: a generic owner session with no confirmation must be refused.
    ck("no confirmation -> refused (this is what would have stopped 2026-09-07)",
       verify(None, **base, now=1010)["reason"] == MISSING)

    # A release verifier must never mint or spend one, even holding a valid token.
    ck("a release verifier cannot MINT", mint(**{**base, "role": "release_verifier"}, now=1000)["reason"] == NOT_OWNER)
    ck("a release verifier cannot SPEND an owner's token",
       verify(m["token"], **{**base, "role": "release_verifier"}, now=1010)["reason"] == NOT_OWNER)

    # Stale approval: the confirmation, not the approval, is what expires.
    ck("expired confirmation -> refused", verify(m["token"], **base, now=1000 + DEFAULT_TTL_SECONDS + 1)["reason"] == EXPIRED)
    ck("...and it is refused as EXPIRED, not as forged (right cause, right fix)",
       verify(m["token"], **base, now=99999)["reason"] == EXPIRED)

    # Role confusion / forged identity.
    ck("another owner's confirmation is refused",
       verify(m["token"], **{**base, "principal_id": "owner-2"}, now=1010)["reason"] == WRONG_PRINCIPAL)
    ck("a forged signature is refused",
       verify(m["token"][:-4] + "AAAA", **base, now=1010)["reason"] == BAD_SIGNATURE)
    ck("a garbage token is refused as MALFORMED, never accepted",
       verify("not-a-token", **base, now=1010)["reason"] in (MALFORMED, BAD_SIGNATURE))
    ck("an unsigned payload cannot be substituted",
       verify(_b64(json.dumps({"v":1,"sub":"owner-1","role":"owner","pid":"9","dig":action_digest(ACT),
                               "env":"production","iat":1000,"exp":9999999}).encode()) + ".x",
              **base, now=1010)["reason"] == BAD_SIGNATURE)

    # Replay across proposals and environments.
    ck("replayed against a DIFFERENT proposal -> refused",
       verify(m["token"], **{**base, "proposal_id": 10}, now=1010)["reason"] == WRONG_PROPOSAL)
    ck("a STAGING confirmation cannot execute in production",
       verify(mint(**{**base, "environment": "staging"}, now=1000)["token"], **base, now=1010)["reason"] == WRONG_ENVIRONMENT)

    # Changed action digest: the approval was for THIS action.
    ck("a changed action invalidates the confirmation",
       verify(m["token"], **{**base, "action": {**ACT, "target": "sol"}}, now=1010)["reason"] == WRONG_ACTION)
    ck("key ORDER does not change the digest (canonical form)",
       action_digest({"a": 1, "b": 2}) == action_digest({"b": 2, "a": 1}))
    ck("but a changed VALUE does", action_digest({"a": 1}) != action_digest({"a": 2}))
    ck("an absent action still digests deterministically", action_digest(None) == action_digest({}))

    # TTL bounds.
    ck("ttl is clamped to a maximum",
       mint(**base, ttl_seconds=99999, now=1000)["expires_at"] == 1000 + MAX_TTL_SECONDS)
    ck("no signing secret -> fails closed, never open",
       mint(**{**base, "secret": ""}, now=1000)["ok"] is False
       and verify(m["token"], **{**base, "secret": ""}, now=1010)["ok"] is False)

    bad = [n for n, ok in _res if not ok]
    for n in bad:
        print("  FAIL:", n)
    print(f"ACTION CONFIRMATION TESTS: {len(_res) - len(bad)}/{len(_res)} — {'PASS' if not bad else 'FAIL'}")
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    demo()
