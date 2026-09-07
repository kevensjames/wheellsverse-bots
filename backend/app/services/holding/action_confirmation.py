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
REPLAYED = "CONFIRMATION_ALREADY_CONSUMED"
NO_NONCE = "CONFIRMATION_MISSING_NONCE"
NONCE_STORE_DOWN = "CONFIRMATION_NONCE_STORE_UNAVAILABLE"


def _new_nonce() -> str:
    import secrets
    return secrets.token_hex(16)


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
        # jti: the nonce. Consumed exactly once, atomically and durably, so a confirmation cannot be
        # replayed even inside its validity window and even across worker processes or a restart.
        "jti": _new_nonce(),
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
            "expires_at": payload["exp"], "action_digest": payload["dig"], "jti": payload["jti"]}


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
    jti = str(payload.get("jti") or "")
    if not jti:
        return {"ok": False, "reason": NO_NONCE}
    return {"ok": True, "reason": OK, "jti": jti,
            "confirmed_for": {"proposal_id": str(proposal_id), "environment": environment,
                              "expires_at": payload.get("exp")}}


# ── DURABLE, ATOMIC NONCE CONSUMPTION ─────────────────────────────────────────────────────────────
# Signature validity alone makes a confirmation REPLAYABLE inside its window: the same token verifies
# every time it is presented. Downstream, the proposal's status transition is atomic and would refuse
# a second execution — but that is a different guarantee, and it disappears the moment a proposal is
# re-approved while an old confirmation is still valid.
#
# So the nonce is consumed exactly once, in Postgres, with INSERT ... ON CONFLICT DO NOTHING RETURNING.
# The database decides the winner, which makes it:
#   ATOMIC across worker processes — two concurrent gunicorn workers race on a primary key, and
#                                    exactly one INSERT returns a row;
#   DURABLE across restart         — the row is committed, not held in process memory;
#   SELF-EXPIRING                  — rows carry the confirmation's own expiry and can be pruned.
# It FAILS CLOSED: if the store is unreachable, the confirmation is refused rather than allowed.
# The table is created by alembic revision 0007_add_holding_action_nonces, NOT here. Creating schema
# implicitly at call time means the shape of a production table depends on which code path ran first
# and is never reviewed. Consumption assumes the table exists; if it does not, the INSERT raises and
# the caller fails CLOSED, which is the correct behaviour for an unmigrated environment.
NONCE_RETENTION_DAYS = 30


def consume_nonce(jti: str, *, proposal_id, principal_id: str, environment: str,
                  expires_at: int, action_digest_value: str = "") -> dict:
    """Consume the nonce exactly once. Returns {consumed, reason}. Never raises."""
    if not jti:
        return {"consumed": False, "reason": NO_NONCE}
    try:
        from sqlalchemy import text
        from app.database import SessionLocal
    except Exception:
        return {"consumed": False, "reason": NONCE_STORE_DOWN}
    try:
        db = SessionLocal()
        try:
            row = db.execute(text("""
                INSERT INTO holding_action_nonces
                       (jti, proposal_id, principal_id, environment, action_digest, expires_at)
                VALUES (:jti, :pid, :sub, :env, :dig, to_timestamp(:exp))
                ON CONFLICT (jti) DO NOTHING
                RETURNING jti
            """), {"jti": jti, "pid": str(proposal_id), "sub": str(principal_id),
                   "env": str(environment), "dig": str(action_digest_value or ""),
                   "exp": int(expires_at)}).fetchone()
            db.commit()
            if row:
                return {"consumed": True, "reason": OK}
            return {"consumed": False, "reason": REPLAYED}
        finally:
            db.close()
    except Exception:
        # Fail CLOSED. An unreachable or unmigrated nonce store must refuse the action, never allow it.
        return {"consumed": False, "reason": NONCE_STORE_DOWN}


def prune_expired_nonces(*, older_than_days: int = NONCE_RETENTION_DAYS) -> int:
    """Bounded retention. A consumed nonce only needs to outlive the token it burned; keeping them
    forever grows a table nobody reads. Rows are deleted well AFTER expiry so the audit window is
    generous, and deleting an expired row cannot enable a replay — the token expired long before."""
    try:
        from sqlalchemy import text
        from app.database import SessionLocal
        db = SessionLocal()
        try:
            n = db.execute(text(
                "DELETE FROM holding_action_nonces "
                "WHERE expires_at < now() - (:d || ' days')::interval"
            ), {"d": int(max(1, older_than_days))}).rowcount
            db.commit()
            return int(n or 0)
        finally:
            db.close()
    except Exception:
        return 0


def verify_and_consume(token, *, principal_id, role, proposal_id, action, environment, secret,
                       now=None) -> dict:
    """The ONE call a route should make: verify, then atomically consume. Fails closed."""
    v = verify(token, principal_id=principal_id, role=role, proposal_id=proposal_id, action=action,
               environment=environment, secret=secret, now=now)
    if not v.get("ok"):
        return v
    c = consume_nonce(v["jti"], proposal_id=proposal_id, principal_id=principal_id,
                      environment=environment,
                      expires_at=int((v.get("confirmed_for") or {}).get("expires_at") or 0),
                      action_digest_value=action_digest(action))
    if not c["consumed"]:
        return {"ok": False, "reason": c["reason"]}
    return {**v, "nonce_consumed": True}


# ── self-test ─────────────────────────────────────────────────────────────────────────────────────
_res: list = []


def ck(name, ok):
    _res.append((name, bool(ok)))


def _code_only(src: str) -> str:
    """Strip comments and docstrings so a check inspects CODE, not the prose describing it."""
    import io
    import tokenize
    out = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                continue
            if tok.type == tokenize.STRING and tok.line.lstrip()[:3] in ('"""', "'''"):
                continue
            out.append(tok.string)
    except Exception:
        return src
    return " ".join(out)


def _sql_constants_of(*funcs) -> list:
    """Every SQL-looking string constant these functions can actually execute.

    Reads compiled code objects, so it sees what runs — not comments, docstrings, or the text of
    the assertions doing the checking.
    """
    _VERBS = ("SEL" + "ECT", "INS" + "ERT", "UPD" + "ATE", "DEL" + "ETE",
              "CRE" + "ATE", "ALT" + "ER", "DR" + "OP")
    found, seen = [], set()

    def walk(code):
        if id(code) in seen:
            return
        seen.add(id(code))
        for c in code.co_consts:
            if isinstance(c, str):
                head = c.strip().upper()
                if any(head.startswith(v) for v in _VERBS):
                    found.append(c)
            elif hasattr(c, "co_consts"):
                walk(c)

    for f in funcs:
        walk(f.__code__)
    return found


def _downgrade_body(msrc: str) -> str:
    i = msrc.find("def downgrade(")
    return msrc[i:] if i >= 0 else ""


def _create_table_columns(msrc: str) -> list:
    """The column names actually declared in the migration's CREATE TABLE."""
    import re as _re
    m = _re.search(r"CREATE TABLE IF NOT EXISTS holding_action_nonces\s*\((.*?)\n\s*\)", msrc, _re.S)
    if not m:
        return []
    cols = []
    for line in m.group(1).splitlines():
        line = line.strip().rstrip(",")
        if line:
            cols.append(line.split()[0])
    return cols


def _db_up() -> bool:
    try:
        from sqlalchemy import text
        from app.database import SessionLocal
        db = SessionLocal(); db.execute(text("select 1")); db.close(); return True
    except Exception:
        return False


def _drop_session_cache() -> None:
    """Approximate a worker restart: discard pooled connections so the next read is a fresh one."""
    try:
        from app.database import engine
        engine.dispose()
    except Exception:
        pass


def _clean_nonces() -> None:
    try:
        from sqlalchemy import text
        from app.database import SessionLocal
        db = SessionLocal()
        db.execute(text("DELETE FROM holding_action_nonces WHERE principal_id = 'owner-1'"))
        db.commit(); db.close()
    except Exception:
        pass


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

    # ── DURABLE, ATOMIC NONCE CONSUMPTION (guarded Postgres) ─────────────────────────────────────
    ck("every minted confirmation carries a unique nonce",
       mint(**base, now=1000)["jti"] != mint(**base, now=1000)["jti"])
    ck("verify returns the nonce for the caller to consume", "jti" in verify(m["token"], **base, now=1010))
    if _db_up():
        f1 = mint(**base, now=1000)
        r1 = verify_and_consume(f1["token"], **base, now=1010)
        ck("[db] first use: verified AND nonce consumed", r1["ok"] and r1.get("nonce_consumed"))
        r2 = verify_and_consume(f1["token"], **base, now=1011)
        ck("[db] REPLAY of the same confirmation is refused as ALREADY_CONSUMED",
           r2["ok"] is False and r2["reason"] == REPLAYED)
        ck("[db] ...and it is refused for the RIGHT reason, not as forged or expired",
           r2["reason"] not in (BAD_SIGNATURE, EXPIRED, MALFORMED))

        # ATOMIC ACROSS PROCESSES: the DB primary key decides the winner, not application logic.
        f2 = mint(**base, now=1000)
        import concurrent.futures as _cf
        with _cf.ThreadPoolExecutor(max_workers=8) as ex:
            outs = list(ex.map(lambda _: verify_and_consume(f2["token"], **base, now=1010), range(8)))
        wins = sum(1 for o in outs if o.get("ok"))
        ck("[db] 8 concurrent consumers of ONE confirmation -> exactly 1 wins", wins == 1)
        ck("[db] ...and the other 7 are all ALREADY_CONSUMED",
           sum(1 for o in outs if o.get("reason") == REPLAYED) == 7)

        # DURABLE ACROSS RESTART: the row is committed, not process memory. A fresh engine/session
        # (what a restarted worker gets) still sees it consumed.
        f3 = mint(**base, now=1000)
        ck("[db] consume once", verify_and_consume(f3["token"], **base, now=1010)["ok"])
        _drop_session_cache()
        ck("[db] after dropping every cached session (restart-equivalent) the replay STILL fails",
           verify_and_consume(f3["token"], **base, now=1010)["reason"] == REPLAYED)
        _clean_nonces()
    else:
        ck("[db] nonce suite SKIPPED — no database reachable (pure checks above still ran)", True)

    # ── SCHEMA AUDIT: the nonce table is a reviewed migration, not implicit runtime DDL ──────────
    import pathlib as _pl
    _mig = _pl.Path(__file__).resolve().parents[3] / "alembic" / "versions" / "0007_add_holding_action_nonces.py"
    _msrc = _mig.read_text() if _mig.exists() else ""
    _asrc = _pl.Path(__file__).read_text()
    ck("a project-native migration introduces the table", _mig.exists())
    ck("it chains from the CURRENT production head 0006",
       'down_revision: Union[str, None] = "0006_add_kai_api_keys"' in _msrc)
    # Grepping this file for DDL keywords cannot work: the audit's own migration parser and these
    # very assertions contain those keywords, so the module always matches itself. Assert the real
    # property instead — the SQL the runtime functions actually execute. Needles are built from
    # fragments so they never appear verbatim in the source being inspected.
    _DDL = tuple(a + " " + b for a, b in
                 (("CRE" + "ATE", "TAB" + "LE"), ("ALT" + "ER", "TAB" + "LE"),
                  ("CRE" + "ATE", "IND" + "EX"), ("DR" + "OP", "TAB" + "LE")))
    _runtime_sql = _sql_constants_of(mint, verify, consume_nonce, prune_expired_nonces,
                                     verify_and_consume)
    ck("APPLICATION CODE executes no schema statement — the runtime SQL is pure DML",
       bool(_runtime_sql) and not any(k in s.upper() for s in _runtime_sql for k in _DDL))
    ck("...and the DB-touching runtime SQL is exactly the nonce INSERT and the retention DELETE",
       {s.strip().split()[0].upper() for s in _runtime_sql} <= {"INSERT", "DELETE", "SELECT"})
    ck("jti carries an enforced conflict key", "jti           TEXT PRIMARY KEY" in _msrc
       and "ON CONFLICT (jti) DO NOTHING" in _asrc)
    for col in ("proposal_id", "principal_id", "environment", "action_digest",
                "expires_at", "consumed_at"):
        ck(f"the binding/audit column {col} is represented", col in _msrc)
    # Inspect the COLUMN LIST, not the file: the migration's own docstring names the things it
    # does not store, and an earlier version of this check matched that prose.
    _cols = _create_table_columns(_msrc)
    ck("NO token, signature, confirmation body or secret is stored",
       bool(_cols) and not any(k in " ".join(_cols).lower()
                               for k in ("token", "signature", "secret", "credential", "body")))
    ck("...and the stored columns are exactly the binding + audit facts",
       set(_cols) == {"jti", "proposal_id", "principal_id", "environment", "action_digest",
                      "expires_at", "consumed_at"})
    ck("repeated migration execution is safe (IF NOT EXISTS throughout)",
       _msrc.count("IF NOT EXISTS") >= 3)
    ck("downgrade does NOT drop the table — audit evidence survives a code rollback",
       "DROP TABLE" not in _code_only(_downgrade_body(_msrc)))
    ck("...and says why in the migration itself", "audit evidence" in _msrc)
    ck("expired rows have BOUNDED retention", "def prune_expired_nonces" in _asrc
       and "NONCE_RETENTION_DAYS" in _asrc)
    ck("retention deletes only rows already past expiry, so pruning cannot enable a replay",
       "expires_at < now() -" in _asrc)

    bad = [n for n, ok in _res if not ok]
    for n in bad:
        print("  FAIL:", n)
    print(f"ACTION CONFIRMATION TESTS: {len(_res) - len(bad)}/{len(_res)} — {'PASS' if not bad else 'FAIL'}")
    if bad:
        raise SystemExit(1)


if __name__ == "__main__":
    demo()
