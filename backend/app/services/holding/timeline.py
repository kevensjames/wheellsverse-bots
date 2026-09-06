"""§61 HoldingTimeline — a certified backend event store for OBSERVABLE holding events ONLY.

What it IS: a durable, append-only, newest-first record of things that OBSERVABLY happened across the
holding — a deploy, a mission transition, an incident, an approval, a worker execution, a customer
milestone, a finance event, a security event, a KAI recommendation. The dashboard's §61 timeline reads
from here.

What it is NOT (the certified boundary):
  • It NEVER stores hidden chain-of-thought. append() REJECTS any event carrying a reasoning-trace /
    scratchpad / internal-monologue field (recursively) — only observable, published facts are stored.
  • It NEVER fabricates events. Events come from the EXISTING real sources via an injectable adapter
    (audit_log / mission transitions / proposals / holding_deployment / security events). No source
    data → 0 events.
  • Every event is provenance-tagged (REAL | DERIVED | UNAVAILABLE) and typed.

HOW IT IS WIRED (the §61 read path). ``view()`` is THE panel payload and the only thing the router calls:
it ``ingest()``s from the real sources and then returns the bounded stored view. Ingestion runs on the
READ path deliberately — §79 forbids a new collector/daemon/scheduler, and append is idempotent, so the
read seam is the wiring. Two consequences the operator is entitled to see, both carried in the payload:
  • ``store``   — CONNECTED / UNAVAILABLE for the durable store itself.
  • ``sources`` — one row per real source with CONNECTED / UNAVAILABLE + how many events it contributed.
An UNREADABLE source (its module is not in this build, or the read failed) must therefore never render as
"nothing happened": the panel states which sources are readable, so an empty timeline is a fact about the
sources, not an inference. Nothing is ever synthesised to fill the gap.

Durable store: the self-creating-table, fail-soft pattern of proposals_store / cycle_store / mission on
App B's Postgres. append() is idempotent (ON CONFLICT (event_id) DO NOTHING) so re-ingesting the same
real source never duplicates. Pure validation + the source adapters are DB-free and testable as a plain
``python3`` script (mirrors test_registry.py); the DB store is fail-soft.

CONSOLIDATION (§0): this is not a second event bus. It READS the already-collected governance/mission/
deployment/security state and normalizes it to one observable event shape — it introduces no new
collector, daemon, or scheduler (§79).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from sqlalchemy import bindparam, text
from app.database import SessionLocal

# ── the observable event vocabulary (§61) ────────────────────────────────────────────────────────────
EVENT_TYPES = frozenset({
    "deployment", "mission", "incident", "approval", "worker_execution",
    "customer_milestone", "finance_event", "security_event", "kai_recommendation",
})
_PROVENANCE = frozenset({"REAL", "DERIVED", "UNAVAILABLE"})
_REQUIRED = ("event_id", "ts", "type", "company", "summary", "source", "provenance")

# Keys that would carry HIDDEN chain-of-thought — an event containing ANY of these (at any depth) is
# REFUSED. This is the certified §61 boundary: the timeline stores only observable, published facts, never
# KAI's private reasoning. ('rationale'/'summary' are OBSERVABLE published text and are allowed.)
_COT_KEYS = frozenset({
    "chain_of_thought", "cot", "reasoning_trace", "reasoning_steps", "internal_monologue",
    "scratchpad", "hidden_reasoning", "private_reasoning", "thoughts", "deliberation", "raw_thought",
    "thinking", "inner_monologue",
    "reasoning", "thought",     # §87 bare forms — the ONE vocabulary explain / what_i_did / attention strip on
})
# The matcher is by TOKEN, not exact key: a key is hidden reasoning when ANY of its tokens (split on
# non-alphanumerics and camelCase, casefolded) is in this set — so reasoning_v2 / llm_thoughts / cot_trace /
# 'reasoning trace' / llmThoughts are caught, not only the spellings listed above (each of which it covers).
_COT_TOKENS = frozenset({"reasoning", "thought", "thoughts", "cot", "scratchpad", "monologue", "deliberation", "thinking"})
# The ONE key that legitimately names reasoning: the §17/§87 boolean attestation (attention_model / explain /
# what_i_did emit it). It is admissible ONLY with the value False — any other value is treated as hidden reasoning.
ATTESTATION_KEY = "hidden_reasoning_exposed"


def is_cot_key(key) -> bool:
    """§61/§87: THE hidden-reasoning key rule (explain / what_i_did / validate_event all use this one)."""
    k = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key)).casefold()
    return any(t in _COT_TOKENS for t in re.split(r"[^0-9a-z]+", k))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _contains_cot(obj) -> bool:
    """True if a hidden-chain-of-thought key appears ANYWHERE in the event (recursively through dicts and
    lists). Fail-closed: an ambiguous structure is walked fully, never skipped. The only pass-through is the
    attestation key carrying exactly False."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == ATTESTATION_KEY and v is False:
                continue
            if is_cot_key(k):
                return True
            if _contains_cot(v):
                return True
        return False
    if isinstance(obj, (list, tuple)):
        return any(_contains_cot(x) for x in obj)
    return False


def validate_event(event: dict) -> tuple[bool, str]:
    """PURE §61 admission check. An event is admissible ONLY if it is a typed, provenance-tagged, fully-
    formed OBSERVABLE fact with NO hidden chain-of-thought. Returns (ok, reason). DB-free."""
    if not isinstance(event, dict) or not event:
        return False, "EMPTY_EVENT"
    for f in _REQUIRED:
        if not event.get(f):
            return False, f"MISSING_{f.upper()}"
    if event["type"] not in EVENT_TYPES:
        return False, f"UNKNOWN_TYPE:{event['type']}"
    if event["provenance"] not in _PROVENANCE:
        return False, f"BAD_PROVENANCE:{event['provenance']}"
    if _contains_cot(event):
        return False, "REJECTED_CHAIN_OF_THOUGHT"      # certified boundary — never store hidden reasoning
    return True, "OK"


# ── durable store (self-creating table, fail-soft — proposals_store / mission pattern) ─────────────────
_DDL = """CREATE TABLE IF NOT EXISTS holding_timeline (
    event_id TEXT PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    type TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT 'holding',
    summary TEXT NOT NULL,
    source TEXT NOT NULL,
    provenance TEXT NOT NULL DEFAULT 'REAL',
    refs JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)"""
_IDX = "CREATE INDEX IF NOT EXISTS holding_timeline_ts ON holding_timeline (ts DESC)"


def _ensure(db) -> None:
    db.execute(text(_DDL))
    try:
        db.execute(text(_IDX))
    except Exception:
        pass


_INSERT = ("INSERT INTO holding_timeline (event_id, ts, type, company, summary, source, provenance, refs) "
           "VALUES (:id, :ts, :ty, :co, :su, :sr, :pr, CAST(:rf AS JSONB)) "
           "ON CONFLICT (event_id) DO NOTHING")


def _row(event: dict) -> dict:
    return {"id": event["event_id"], "ts": event["ts"], "ty": event["type"],
            "co": event.get("company") or "holding", "su": event["summary"],
            "sr": event["source"], "pr": event["provenance"],
            "rf": json.dumps(event.get("refs") or [])}


def append(event: dict) -> dict:
    """Validate then durably append ONE observable event. Idempotent (ON CONFLICT (event_id) DO NOTHING),
    so re-ingesting the same real source never duplicates. Returns {ok, inserted, reason}. A rejected
    event (missing fields / unknown type / bad provenance / hidden chain-of-thought) is NOT stored.
    Fails SOFT (ok=False, PERSIST_FAILED) if the DB is down. Never raises."""
    ok, reason = validate_event(event)
    if not ok:
        return {"ok": False, "inserted": False, "reason": reason}
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            r = db.execute(text(_INSERT + " RETURNING event_id"), _row(event)).fetchone()
            db.commit()
            return {"ok": True, "inserted": bool(r), "reason": "OK"}
        finally:
            db.close()
    except Exception:
        return {"ok": False, "inserted": False, "reason": "PERSIST_FAILED"}


def append_many(events: list) -> dict:
    """Validate then durably append MANY observable events in ONE statement. Same admission rule as
    append() — a rejected event (missing fields / unknown type / bad provenance / hidden chain-of-thought)
    is NOT stored and is counted in ``rejected``. Idempotent: already-stored event_ids are skipped, so
    re-ingesting the same real sources on every read never duplicates and never re-writes history.
    Returns {ok, inserted, rejected}. Fails SOFT (ok=False) if the DB is down. Never raises.

    This exists because ingest() runs on the read path: one session + one statement, not one session,
    one CREATE-TABLE-IF-NOT-EXISTS and one round trip per candidate event."""
    rows, rejected = [], 0
    for ev in (events or []):
        ok, _reason = validate_event(ev)
        if ok:
            rows.append(_row(ev))
        else:
            rejected += 1
    if not rows:
        return {"ok": True, "inserted": 0, "rejected": rejected}
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            ids = [r["id"] for r in rows]
            seen = {x[0] for x in db.execute(
                text("SELECT event_id FROM holding_timeline WHERE event_id IN :ids").bindparams(
                    bindparam("ids", expanding=True)), {"ids": ids}).fetchall()}
            new = [r for r in rows if r["id"] not in seen]
            if new:
                db.execute(text(_INSERT), new)      # executemany; ON CONFLICT covers a concurrent writer
            db.commit()
            return {"ok": True, "inserted": len(new), "rejected": rejected}
        finally:
            db.close()
    except Exception:
        return {"ok": False, "inserted": 0, "rejected": rejected}


def query(*, type: str | None = None, company: str | None = None, limit: int = 100) -> list:
    """Bounded, newest-first timeline view, optionally filtered by type and/or company. limit is clamped
    to [1, 500]. Returns event dicts. Fails SOFT (returns []) if the DB is down. Never raises."""
    return _query(type=type, company=company, limit=limit)[0]


def _query(*, type: str | None = None, company: str | None = None, limit: int = 100) -> tuple[list, bool]:
    """query() + whether the STORE was actually readable. The panel needs the difference: an empty list
    from a healthy store means 'no events recorded', an empty list from an unreachable store means
    'unknown' — and the two must never render the same way."""
    lim = max(1, min(int(limit or 100), 500))
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            q = ("SELECT event_id, ts, type, company, summary, source, provenance, refs "
                 "FROM holding_timeline WHERE 1=1")
            params: dict = {"lim": lim}
            if type:
                q += " AND type = :ty"; params["ty"] = type
            if company:
                q += " AND company = :co"; params["co"] = company
            # TOTAL order: ts, then insertion time, then the PRIMARY KEY. The last term is what makes
            # it deterministic — append_many writes a whole batch in one transaction, so created_at
            # (DEFAULT now() = transaction time) ties across it, and event_id is the only unique
            # column left. Without it two reads of an unchanged store could order events differently.
            q += " ORDER BY ts DESC, created_at DESC, event_id DESC LIMIT :lim"
            rows = db.execute(text(q), params).fetchall()
            out = []
            for r in rows:
                refs = r[7] if isinstance(r[7], (list, dict)) else json.loads(r[7] or "[]")
                out.append({"event_id": r[0], "ts": str(r[1]), "type": r[2], "company": r[3],
                            "summary": r[4], "source": r[5], "provenance": r[6], "refs": refs})
            return out, True
        finally:
            db.close()
    except Exception:
        return [], False


# ── source adapters — map the EXISTING real sources to observable events (PURE, no fabrication) ─────────
def _company_from_scope(scope: str) -> str:
    """A holding entity id if the audit scope names one, else UNKNOWN (mirrors evidence_bus — never guess
    a company)."""
    prefix = (scope or "").split(".")[0]
    if not prefix:
        return "holding"
    try:
        from app.services.holding import registry
        return prefix if registry.get(prefix) is not None else "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def events_from_audit(records: list) -> list:
    """Governance audit records → OBSERVABLE approval events (only APPROVED actions — an owner decision is
    the timeline-worthy governance fact; non-approval actions surface via the security lens). Pure."""
    out = []
    for r in (records or []):
        if not isinstance(r, dict) or r.get("approved") is not True:
            continue
        rid = r.get("id")
        if not rid:
            continue
        action = r.get("action") or "action"
        scope = r.get("scope") or ""
        result = "success" if r.get("success") else "failure"
        out.append({
            "event_id": f"approval:{rid}", "ts": r.get("ts") or _now(), "type": "approval",
            "company": _company_from_scope(scope),
            "summary": f"owner-approved {action} ({scope or 'holding'}) → {result}",
            "source": "governance.audit_log", "provenance": "REAL" if r.get("ts") else "DERIVED",
            "refs": [{"audit_id": rid, "destructive": bool(r.get("destructive")), "result": result}]})
    return out


def events_from_missions(headers: list) -> list:
    """Mission headers → OBSERVABLE mission-transition events. The observable transition is derived from
    the header's durable state alone (cancelled / completed_at / created) — NO linked-record reasoning,
    NO CoT. event_id carries the state so a later transition is a NEW event (not a mutated one). Pure."""
    out = []
    for h in (headers or []):
        m = h if isinstance(h, dict) else (h.as_dict() if hasattr(h, "as_dict") else dict(h))
        mid = m.get("mission_id")
        if not mid:
            continue
        if m.get("cancelled"):
            state, ts = "CANCELLED", (m.get("updated_at") or m.get("created_at"))
        elif m.get("completed_at"):
            state, ts = "COMPLETE", m.get("completed_at")
        else:
            state, ts = "CREATED", m.get("created_at")
        out.append({
            "event_id": f"mission:{mid}:{state}", "ts": ts or _now(), "type": "mission",
            "company": m.get("company") or "holding",
            "summary": f"mission {state}: {m.get('objective') or mid}",
            "source": "holding.mission", "provenance": "REAL" if ts else "DERIVED",  # synthesized ts is DERIVED
            "refs": [{"mission_id": mid, "state": state, "root_signature": m.get("root_signature")}]})
    return out


def events_from_deployment(sha: str, *, features: list | None = None, env: str = "UNKNOWN") -> list:
    """The deployed-SHA truth → ONE OBSERVABLE deployment event. An UNKNOWN sha yields NO event (honest —
    no real deployment evidence, never a fabricated deploy). ts is first-observed time; the stable event_id
    (keyed by sha) keeps that first observation. Pure."""
    if not sha or sha == "UNKNOWN":
        return []
    # "present" means present in this BUILD. Counting only rows whose deployed flag was true made
    # this number a function of deployment state, and therefore of request order, inside a durable
    # first-write-wins record. Presence is a property of the registry alone.
    n = len(features or [])
    return [{
        "event_id": f"deployment:{sha}", "ts": _now(), "type": "deployment", "company": "holding",
        "summary": f"deployed SHA {sha} observed ({n} features present) in {env}",
        "source": "holding.holding_deployment", "provenance": "DERIVED",   # sha REAL; ts is observation time
        "refs": [{"sha": sha, "features_present": n, "environment": env}]}]


def events_from_proposals(rows: list) -> list:
    """Owner-facing proposals → OBSERVABLE events, both timestamped by the row's OWN real columns:
    ``created_at`` → the kai_recommendation KAI published, ``decided_at`` → the owner's approval decision.
    An undecided proposal yields NO decision event (nothing is presumed); a row without its timestamp
    yields nothing for that half. The reject_reason text is deliberately not carried — the decision is the
    observable fact. Pure."""
    out = []
    for p in (rows or []):
        d = p if isinstance(p, dict) else (p.as_dict() if hasattr(p, "as_dict") else dict(p))
        pid = d.get("id")
        if pid in (None, ""):
            continue
        title = d.get("title") or f"proposal {pid}"
        co = d.get("entity") or "holding"
        if d.get("created_at"):
            out.append({
                "event_id": f"proposal:{pid}:PROPOSED", "ts": d["created_at"], "type": "kai_recommendation",
                "company": co, "summary": f"KAI proposed: {title}",
                "source": "holding.proposals_store", "provenance": "REAL",
                "refs": [{"proposal_id": pid, "severity": d.get("severity"), "status": d.get("status")}]})
        status = str(d.get("status") or "").lower()
        if d.get("decided_at") and status in ("approved", "rejected"):
            out.append({
                "event_id": f"proposal:{pid}:{status.upper()}", "ts": d["decided_at"], "type": "approval",
                "company": co, "summary": f"owner {status} proposal: {title}",
                "source": "holding.proposals_store", "provenance": "REAL",
                "refs": [{"proposal_id": pid, "decision": status}]})
    return out


def events_from_security(sec_events: list) -> list:
    """Normalized SecurityEvents (evidence_bus.events) → OBSERVABLE security-event timeline entries. Pure."""
    out = []
    for e in (sec_events or []):
        d = e if isinstance(e, dict) else (e.as_dict() if hasattr(e, "as_dict") else dict(e))
        eid = d.get("event_id")
        if not eid:
            continue
        out.append({
            "event_id": f"security:{eid}", "ts": d.get("timestamp") or _now(), "type": "security_event",
            "company": d.get("company") or "UNKNOWN",
            "summary": f"{d.get('severity', 'INFO')} {d.get('category', 'event')}: "
                       f"{d.get('action', 'action')} on {d.get('resource', 'UNKNOWN')} → {d.get('result', 'UNKNOWN')}",
            "source": "security.evidence_bus", "provenance": "REAL" if d.get("timestamp") else "DERIVED",
            "refs": [{"security_event_id": eid, "actor": d.get("actor")}]})
    return out


def ingest(*, audit=None, missions=None, proposals=None, deployment=None, security=None,
           limit: int = 200) -> dict:
    """Ingest observable events from the EXISTING real sources and append them (idempotent). Each source
    is INJECTABLE — pass a list to use a fixture; leave None to read the REAL source (fail-soft).
    NOTHING is fabricated: a source with no data contributes 0 events, and a source that cannot be read
    contributes 0 events AND is reported UNAVAILABLE so its silence is never mistaken for 'nothing
    happened'.

    ``deployment`` (when None) is read as the current deployed SHA + feature registry; pass a dict
    {"sha", "features", "env"} or a list of pre-built deployment events to inject.

    Returns {candidates, inserted, rejected, sources:[{source, status, events}]}."""
    plan = (
        ("governance.audit_log", audit, _read_audit, events_from_audit),
        ("holding.mission", missions, _read_missions, events_from_missions),
        ("holding.proposals_store", proposals, _read_proposals, events_from_proposals),
        ("security.evidence_bus", security, _read_security, events_from_security),
    )
    events: list = []
    sources: list = []
    for name, injected, reader, adapt in plan:
        recs, ok = (injected, True) if injected is not None else reader(limit)
        evs = adapt(recs)
        events += evs
        sources.append({"source": name, "status": "CONNECTED" if ok else "UNAVAILABLE", "events": len(evs)})

    dep, dep_ok = _resolve_deployment(deployment)
    events += dep
    sources.append({"source": "holding.holding_deployment",
                    "status": "CONNECTED" if dep_ok else "UNAVAILABLE", "events": len(dep)})

    r = append_many(events)
    return {"candidates": len(events), "inserted": r["inserted"], "rejected": r["rejected"],
            "sources": sources}


def view(*, type: str | None = None, company: str | None = None, limit: int = 100) -> dict:
    """THE §61 panel payload — the one function the router calls.

    Ingests from the real sources (idempotent; on the read path because §79 forbids a new collector /
    daemon / scheduler) and returns the bounded stored view TOGETHER with the honest status of the store
    and of every source. The panel needs all three facts to tell the operator the truth:
      events + sources CONNECTED           → these things happened
      no events + a source CONNECTED       → no observable events recorded (a fact, not a gap)
      no events + nothing CONNECTED        → UNAVAILABLE; the silence proves nothing
    Never raises; never fabricates an event to fill an empty panel."""
    try:
        sources = ingest(limit=200).get("sources", [])
    except Exception:                                       # fail closed: unknown sources, not "all fine"
        sources = []
    rows, store_ok = _query(type=type, company=company, limit=limit)
    return {"events": rows, "store": "CONNECTED" if store_ok else "UNAVAILABLE", "sources": sources}


# ── real-source readers — each returns (records, readable). "readable" is the honest difference between
#    a source that is present and empty and one this build cannot read at all (module absent / read failed).
def _read_audit(limit: int) -> tuple[list, bool]:
    try:
        from app.services.governance import list_actions
        return list_actions(limit=limit), True
    except Exception:
        return [], False


def _db_ok() -> bool:
    """Is Postgres actually reachable? The DB-backed readers below fail SOFT to [] internally, so an empty
    result from them is ambiguous — this is the probe that resolves it. Only called when a source came back
    empty, i.e. only when the distinction matters."""
    try:
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            return True
        finally:
            db.close()
    except Exception:
        return False


def _read_missions(limit: int) -> tuple[list, bool]:
    try:
        from app.services.holding.mission import list_missions
        rows = list_missions(limit=limit)
        return rows, (True if rows else _db_ok())
    except Exception:
        return [], False


def _read_proposals(limit: int) -> tuple[list, bool]:
    try:
        from app.services.holding.proposals_store import list_proposals
        rows = list_proposals(limit=limit)
        return rows, (True if rows else _db_ok())
    except Exception:
        return [], False


def _read_security(limit: int) -> tuple[list, bool]:
    try:
        from app.services.security.evidence_bus import events as sec_events
        return (sec_events(limit=limit) or {}).get("events", []), True
    except Exception:
        return [], False                    # not shipped in every build → UNAVAILABLE, never silent-empty


def _resolve_deployment(deployment) -> tuple[list, bool]:
    if isinstance(deployment, list):
        return deployment, True                             # pre-built events injected
    if isinstance(deployment, dict):
        return events_from_deployment(deployment.get("sha", ""), features=deployment.get("features"),
                                      env=deployment.get("env", "production")), True
    if deployment is not None:
        return [], True
    try:
        from app.services.holding.holding_deployment import deployed_sha, feature_registry
        from app.config import settings
        # env MUST come from the running settings. Letting it fall back to the "production" default wrote
        # "in production" onto a staging timeline — the same defect class as the hardcoded
        # OperationalSelfModel(environment="production") fixed in 9200706, in a different surface.
        # Found on the hosted staging run, not by a test: no test asserted the env of a real ingest.
        env = str(getattr(settings, "APP_ENV", "") or "").strip() or "UNKNOWN"
        return events_from_deployment(deployed_sha(), features=feature_registry(settings), env=env), True
    except Exception:
        return [], False


if __name__ == "__main__":
    from app.services.holding.test_timeline import run
    raise SystemExit(0 if run() else 1)
