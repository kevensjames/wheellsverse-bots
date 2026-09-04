"""§61 HoldingTimeline — a certified backend event store for OBSERVABLE holding events ONLY.

What it IS: a durable, append-only, newest-first record of things that OBSERVABLY happened across the
holding — a deploy, a mission transition, an incident, an approval, a worker execution, a customer
milestone, a finance event, a security event, a KAI recommendation. The dashboard's §61 timeline reads
from here.

What it is NOT (the certified boundary):
  • It NEVER stores hidden chain-of-thought. append() REJECTS any event carrying a reasoning-trace /
    scratchpad / internal-monologue field (recursively) — only observable, published facts are stored.
  • It NEVER fabricates events. Events come from the EXISTING real sources via an injectable adapter
    (audit_log / mission transitions / holding_deployment / security events). No source data → 0 events.
  • Every event is provenance-tagged (REAL | DERIVED | UNAVAILABLE) and typed.

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
from datetime import datetime, timezone

from sqlalchemy import text
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
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _contains_cot(obj) -> bool:
    """True if a hidden-chain-of-thought key appears ANYWHERE in the event (recursively through dicts and
    lists). Fail-closed: an ambiguous structure is walked fully, never skipped."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).strip().lower() in _COT_KEYS:
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
            r = db.execute(text(
                "INSERT INTO holding_timeline (event_id, ts, type, company, summary, source, provenance, refs) "
                "VALUES (:id, :ts, :ty, :co, :su, :sr, :pr, CAST(:rf AS JSONB)) "
                "ON CONFLICT (event_id) DO NOTHING RETURNING event_id"),
                {"id": event["event_id"], "ts": event["ts"], "ty": event["type"],
                 "co": event.get("company") or "holding", "su": event["summary"],
                 "sr": event["source"], "pr": event["provenance"],
                 "rf": json.dumps(event.get("refs") or [])}).fetchone()
            db.commit()
            return {"ok": True, "inserted": bool(r), "reason": "OK"}
        finally:
            db.close()
    except Exception:
        return {"ok": False, "inserted": False, "reason": "PERSIST_FAILED"}


def query(*, type: str | None = None, company: str | None = None, limit: int = 100) -> list:
    """Bounded, newest-first timeline view, optionally filtered by type and/or company. limit is clamped
    to [1, 500]. Returns event dicts. Fails SOFT (returns []) if the DB is down. Never raises."""
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
            q += " ORDER BY ts DESC, created_at DESC LIMIT :lim"
            rows = db.execute(text(q), params).fetchall()
            out = []
            for r in rows:
                refs = r[7] if isinstance(r[7], (list, dict)) else json.loads(r[7] or "[]")
                out.append({"event_id": r[0], "ts": str(r[1]), "type": r[2], "company": r[3],
                            "summary": r[4], "source": r[5], "provenance": r[6], "refs": refs})
            return out
        finally:
            db.close()
    except Exception:
        return []


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


def events_from_deployment(sha: str, *, features: list | None = None, env: str = "production") -> list:
    """The deployed-SHA truth → ONE OBSERVABLE deployment event. An UNKNOWN sha yields NO event (honest —
    no real deployment evidence, never a fabricated deploy). ts is first-observed time; the stable event_id
    (keyed by sha) keeps that first observation. Pure."""
    if not sha or sha == "UNKNOWN":
        return []
    n = len([f for f in (features or []) if (f.get("deployed") if isinstance(f, dict) else True)])
    return [{
        "event_id": f"deployment:{sha}", "ts": _now(), "type": "deployment", "company": "holding",
        "summary": f"deployed SHA {sha} observed ({n} features present) in {env}",
        "source": "holding.holding_deployment", "provenance": "DERIVED",   # sha REAL; ts is observation time
        "refs": [{"sha": sha, "features_present": n, "environment": env}]}]


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


def ingest(*, audit=None, missions=None, deployment=None, security=None, limit: int = 200) -> dict:
    """Ingest observable events from the four EXISTING real sources and append them (idempotent). Each
    source is INJECTABLE — pass a list to use a fixture; leave None to read the REAL source (fail-soft).
    NOTHING is fabricated: a source with no data contributes 0 events. Returns per-source + total counts.

    ``deployment`` (when None) is read as the current deployed SHA + feature registry; pass a dict
    {"sha", "features", "env"} or a list of pre-built deployment events to inject."""
    events: list = []

    recs = audit if audit is not None else _read_audit(limit)
    events += events_from_audit(recs)

    hdrs = missions if missions is not None else _read_missions(limit)
    events += events_from_missions(hdrs)

    events += _resolve_deployment(deployment)

    secs = security if security is not None else _read_security(limit)
    events += events_from_security(secs)

    inserted = 0
    rejected = 0
    for ev in events:
        r = append(ev)
        if r.get("inserted"):
            inserted += 1
        elif not r.get("ok"):
            rejected += 1
    return {"candidates": len(events), "inserted": inserted, "rejected": rejected,
            "by_source": {"audit": len(events_from_audit(recs)), "missions": len(events_from_missions(hdrs))}}


# ── real-source readers (fail-soft; the injection seams above bypass these in tests) ───────────────────
def _read_audit(limit: int) -> list:
    try:
        from app.services.governance import list_actions
        return list_actions(limit=limit)
    except Exception:
        return []


def _read_missions(limit: int) -> list:
    try:
        from app.services.holding.mission import list_missions
        return list_missions(limit=limit)
    except Exception:
        return []


def _read_security(limit: int) -> list:
    try:
        from app.services.security.evidence_bus import events as sec_events
        return (sec_events(limit=limit) or {}).get("events", [])
    except Exception:
        return []


def _resolve_deployment(deployment) -> list:
    if isinstance(deployment, list):
        return deployment                                   # pre-built events injected
    if isinstance(deployment, dict):
        return events_from_deployment(deployment.get("sha", ""), features=deployment.get("features"),
                                      env=deployment.get("env", "production"))
    if deployment is not None:
        return []
    try:
        from app.services.holding.holding_deployment import deployed_sha, feature_registry
        from app.config import settings
        return events_from_deployment(deployed_sha(), features=feature_registry(settings))
    except Exception:
        return []


if __name__ == "__main__":
    from app.services.holding.test_timeline import run
    raise SystemExit(0 if run() else 1)
