"""Durable store + state machine for KAI's proposals (Wave 2) AND §21 ideas (Phase 3b).

Self-creating table; uses App B's Postgres. A proposal is created as 'proposed', then the OWNER moves
it to 'approved' or 'rejected' (the human gate). Dedup: a fresh generation never duplicates a still-open
proposal for the same priority (source_key). Fails SOFT (returns [] / False / None) if the DB is down.
Approving records the decision only — execution is a separate, later wave.

§21 IDEAS share this ONE table (no second store/queue), discriminated by the ``kind`` column
('proposal' | 'idea'). Every PROPOSAL read/lifecycle op is kind-scoped so ideas NEVER leak into an owner
decision (list_proposals / resolve_absent / sync_open dedup / owner-queue upsert all see kind='proposal'
only), and idea reads see kind='idea' only. Idea dedup is by EVIDENCE SIGNATURE, tracked as the SET of
every signature ever written for a source_key — so a rejected idea reappears only on genuinely-unseen
evidence, and reverting to a previously-rejected signature does NOT reappear (see idea_disposition).
"""
from __future__ import annotations
import hashlib
import json
from typing import Optional

from sqlalchemy import text
from app.database import SessionLocal

_DDL = """CREATE TABLE IF NOT EXISTS holding_proposals (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_key TEXT NOT NULL DEFAULT '',
    severity TEXT, entity TEXT, title TEXT,
    action JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'proposed',
    decided_at TIMESTAMPTZ, decided_by TEXT, reject_reason TEXT,
    evidence JSONB, executed_at TIMESTAMPTZ,
    kind TEXT NOT NULL DEFAULT 'proposal', evidence_sig TEXT
)"""
# For tables created before a column existed (idempotent, applied on every _ensure):
_ALTERS = ("ALTER TABLE holding_proposals ADD COLUMN IF NOT EXISTS evidence JSONB",
           "ALTER TABLE holding_proposals ADD COLUMN IF NOT EXISTS executed_at TIMESTAMPTZ",
           # §21: discriminator (existing rows backfill to 'proposal') + idea evidence signature.
           "ALTER TABLE holding_proposals ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'proposal'",
           "ALTER TABLE holding_proposals ADD COLUMN IF NOT EXISTS evidence_sig TEXT")

_VALID = {"approved", "rejected"}


def _ensure(db) -> None:
    db.execute(text(_DDL))
    for a in _ALTERS:
        db.execute(text(a))


def sync_open(proposals: list) -> int:
    """Insert generated proposals that have no still-open ('proposed') row for the same source_key.
    Returns the number newly inserted. Never raises."""
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            inserted = 0
            for p in (proposals or []):
                sk = p.get("source_key", "")
                # dedup: skip if there is a still-open proposal for this priority, OR one that was
                # decided in the last 24h (so a rejected/approved item doesn't re-propose every tick).
                # kind-scoped: an idea sharing a source_key never blocks a proposal insert.
                exists = db.execute(text("""
                    SELECT 1 FROM holding_proposals
                     WHERE source_key = :sk AND COALESCE(kind,'proposal') = 'proposal'
                       AND (status = 'proposed' OR (decided_at IS NOT NULL AND decided_at > now() - interval '24 hours'))
                     LIMIT 1"""), {"sk": sk}).fetchone()
                if exists:
                    continue
                action = {k: p.get(k) for k in
                          ("action_class", "proposed_action", "plan", "risk", "reversible", "worker",
                           "impact", "effort", "options", "cost")}
                db.execute(text("""
                    INSERT INTO holding_proposals (source_key, severity, entity, title, action, status)
                    VALUES (:sk, :sev, :ent, :ttl, CAST(:act AS JSONB), 'proposed')
                """), {"sk": sk, "sev": p.get("severity"), "ent": p.get("entity"),
                       "ttl": p.get("title"), "act": json.dumps(action)})
                inserted += 1
            db.commit()
            return inserted
        finally:
            db.close()
    except Exception:
        return 0


# ── §F2 writer-only owner-queue upsert ───────────────────────────────────────────────────────────
# The pure disposition decision (absent→insert / open→update / terminal→skip) lives DB-free in
# owner_queue.owner_upsert_disposition so it is testable without a database; upsert_owner_open below is
# the thin DB mechanics around it. It performs NO status transition and NO resolve/close.

# safe descriptive/evidence fields carried in the action JSON (never authority or decision state)
_OWNER_ACTION_FIELDS = ("action_class", "proposed_action", "plan", "risk", "reversible", "worker",
                        "impact", "effort", "kai_completed", "surface", "deadline", "last_observed_at",
                        "evidence")


def upsert_owner_open(items: list) -> dict:
    """Writer-ONLY owner-queue upsert (§F2). Per source_key, using the newest row's status:
      - no row       → INSERT status='proposed'
      - 'proposed'   → UPDATE safe descriptive/evidence fields ONLY (status/decided_* untouched)
      - terminal     → leave untouched (never reopen a decision the owner already made)
    Performs NO status transition and NO resolve/close. Returns {ok, inserted, updated, skipped_terminal};
    ok=False on DB failure (the caller records OWNER_QUEUE_PERSIST_FAILED). Never raises."""
    from app.services.holding.owner_queue import owner_upsert_disposition
    out = {"ok": True, "inserted": 0, "updated": 0, "skipped_terminal": 0}
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            for p in (items or []):
                sk = p.get("source_key", "")
                row = db.execute(text("SELECT status FROM holding_proposals WHERE source_key = :sk "
                                      "AND COALESCE(kind,'proposal') = 'proposal' "
                                      "ORDER BY id DESC LIMIT 1"), {"sk": sk}).fetchone()
                disp = owner_upsert_disposition(row[0] if row else None)
                action = {k: p.get(k) for k in _OWNER_ACTION_FIELDS}
                ev = json.dumps(p.get("evidence") or [])
                if disp == "insert":
                    db.execute(text(
                        "INSERT INTO holding_proposals (source_key, severity, entity, title, action, status, evidence)"
                        " VALUES (:sk,:sev,:ent,:ttl, CAST(:act AS JSONB), 'proposed', CAST(:ev AS JSONB))"),
                        {"sk": sk, "sev": p.get("severity"), "ent": p.get("entity"), "ttl": p.get("title"),
                         "act": json.dumps(action), "ev": ev})
                    out["inserted"] += 1
                elif disp == "update":
                    # update ONLY the newest still-open row; status/decided_at/decided_by never touched
                    db.execute(text(
                        "UPDATE holding_proposals SET severity=:sev, title=:ttl, action=CAST(:act AS JSONB),"
                        " evidence=CAST(:ev AS JSONB)"
                        " WHERE id = (SELECT id FROM holding_proposals WHERE source_key=:sk AND status='proposed'"
                        "             AND COALESCE(kind,'proposal')='proposal'"
                        "             ORDER BY id DESC LIMIT 1)"),
                        {"sev": p.get("severity"), "ttl": p.get("title"), "act": json.dumps(action),
                         "ev": ev, "sk": sk})
                    out["updated"] += 1
                else:
                    out["skipped_terminal"] += 1
            db.commit()
            return out
        finally:
            db.close()
    except Exception:
        return {"ok": False, "inserted": 0, "updated": 0, "skipped_terminal": 0}


def list_proposals(status: Optional[str] = None, limit: int = 50) -> list:
    """Rows newest-first, optionally filtered by status. Never raises."""
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            # kind-scoped to 'proposal' (COALESCE covers legacy NULL rows) so §21 ideas NEVER surface to
            # a proposal consumer (owner_queue / briefing / build_daily_plan / digital_twin / self_model).
            q = ("SELECT id, created_at, source_key, severity, entity, title, action, status, decided_at, "
                 "reject_reason FROM holding_proposals WHERE COALESCE(kind,'proposal') = 'proposal'")
            params = {"lim": limit}
            if status:
                q += " AND status = :st"; params["st"] = status
            q += " ORDER BY created_at DESC, id DESC LIMIT :lim"
            rows = db.execute(text(q), params).fetchall()
            out = []
            for r in rows:
                act = r[6] if isinstance(r[6], dict) else json.loads(r[6] or "{}")
                out.append({"id": r[0], "created_at": str(r[1]), "source_key": r[2], "severity": r[3],
                            "entity": r[4], "title": r[5], "action": act, "status": r[7],
                            "decided_at": str(r[8]) if r[8] else None, "reject_reason": r[9]})
            return out
        finally:
            db.close()
    except Exception:
        return []


def decide(proposal_id: int, status: str, *, reason: Optional[str] = None, by: str = "owner") -> Optional[dict]:
    """Move a 'proposed' proposal to 'approved'/'rejected' (idempotent-safe: only acts on open rows).
    Returns the updated row, or None if not found / not open / DB down. Never raises."""
    if status not in _VALID:
        return None
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            res = db.execute(text("""
                UPDATE holding_proposals
                   SET status = :st, decided_at = now(), decided_by = :by,
                       reject_reason = :rsn
                 WHERE id = :id AND status = 'proposed'
             RETURNING id, source_key, title, status
            """), {"st": status, "by": by, "rsn": (reason if status == "rejected" else None), "id": proposal_id}).fetchone()
            db.commit()
            if not res:
                return None
            return {"id": res[0], "source_key": res[1], "title": res[2], "status": res[3]}
        finally:
            db.close()
    except Exception:
        return None


def resolve_absent(active_source_keys: list, *, by: str = "kai-auto") -> int:
    """Auto-resolve (§3): mark every still-open ('proposed') proposal whose source_key is NOT in the
    current active set as 'superseded' — the underlying blocker disappeared, so it must not linger in
    Today. Only touches KAI-derived open rows (never an owner's approved/rejected decision). Returns
    the count resolved. Never raises. An empty active set resolves ALL open rows (nothing is active)."""
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            keys = [k for k in (active_source_keys or []) if k]
            # kind-scoped: auto-resolve NEVER touches an §21 idea (only KAI-derived open PROPOSALS).
            if keys:
                res = db.execute(text("""
                    UPDATE holding_proposals SET status='superseded', decided_at=now(), decided_by=:by
                     WHERE status='proposed' AND COALESCE(kind,'proposal')='proposal' AND source_key <> ALL(:keys)
                 RETURNING id"""), {"by": by, "keys": keys}).fetchall()
            else:
                res = db.execute(text("""
                    UPDATE holding_proposals SET status='superseded', decided_at=now(), decided_by=:by
                     WHERE status='proposed' AND COALESCE(kind,'proposal')='proposal' RETURNING id"""),
                    {"by": by}).fetchall()
            db.commit()
            return len(res)
        finally:
            db.close()
    except Exception:
        return 0


def get(proposal_id: int) -> Optional[dict]:
    """One proposal by id (with its action + status). None if not found / DB down. Never raises."""
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            r = db.execute(text(
                "SELECT id, source_key, severity, entity, title, action, status FROM holding_proposals WHERE id = :id"),
                {"id": proposal_id}).fetchone()
            if not r:
                return None
            act = r[5] if isinstance(r[5], dict) else json.loads(r[5] or "{}")
            return {"id": r[0], "source_key": r[1], "severity": r[2], "entity": r[3],
                    "title": r[4], "action": act, "status": r[6]}
        finally:
            db.close()
    except Exception:
        return None


def record_execution(proposal_id: int, evidence: dict) -> bool:
    """Move an 'approved' proposal to 'executed' and store its evidence. Only acts on approved rows
    (execution is bound to a prior approval). True on success. Never raises."""
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            res = db.execute(text("""
                UPDATE holding_proposals
                   SET status = 'executed', executed_at = now(), evidence = CAST(:ev AS JSONB)
                 WHERE id = :id AND status = 'approved'
             RETURNING id
            """), {"ev": json.dumps(evidence), "id": proposal_id}).fetchone()
            db.commit()
            return bool(res)
        finally:
            db.close()
    except Exception:
        return False


# ── §21 Idea mode — shares this ONE table (kind='idea'), never a second store ───────────────────────
# Ideas' descriptive fields carried in the action JSON (never authority or decision state).
_IDEA_ACTION_FIELDS = ("category", "why_now", "expected_benefit", "confidence", "effort", "risk",
                       "dependencies", "owner_impact", "recommended_next_step")


def evidence_signature(evidence) -> str:
    """Stable signature of an idea's evidence[]. Changes when the evidence MATERIALLY changes, so a
    genuinely-new evidence state (e.g. a metric moved) is 'unseen' and can resurface; identical evidence
    yields the identical signature and is suppressed. Deterministic, order-insensitive."""
    try:
        norm = sorted(json.dumps(e, sort_keys=True, default=str) for e in (evidence or []))
        if not norm:
            return ""      # no real evidence → blank sig, not a stable hash of nothing (§21 dedup)
        return hashlib.sha1("\n".join(norm).encode()).hexdigest()[:16]
    except Exception:
        return ""


def idea_disposition(evidence_sig: str, seen_sigs) -> str:
    """PURE §21 dedup decision → 'present' | 'suppress'. ``seen_sigs`` is the SET of EVERY evidence
    signature already written for this idea's source_key (open OR decided — not just the newest row).

    An idea is presented ONLY on a genuinely-UNSEEN evidence signature. A blank signature, or one already
    in the set, is suppressed — so a rejected idea does not re-nag, and reverting to a previously-rejected
    signature (evidence flip-flop A→B→A) does NOT reappear because A is still in the seen set."""
    if not evidence_sig:
        return "suppress"                                 # no evidence signature → never surface (no generic idea)
    return "suppress" if evidence_sig in set(seen_sigs or ()) else "present"


def sync_ideas(ideas: list) -> int:
    """Insert §21 ideas (kind='idea') that carry a genuinely-UNSEEN evidence signature for their
    source_key. ``ideas`` are opportunity-shaped dicts (source_key or signature, evidence[], + descriptive
    fields). Per source_key the SET of all previously-written signatures is gathered (idea_disposition
    decides on the SET, not the newest row). Returns the count newly inserted. Never raises."""
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            inserted = 0
            for p in (ideas or []):
                sk = p.get("source_key") or p.get("signature") or ""
                sig = p.get("evidence_sig") or evidence_signature(p.get("evidence"))
                seen = {r[0] for r in db.execute(text(
                    "SELECT DISTINCT evidence_sig FROM holding_proposals "
                    "WHERE source_key = :sk AND kind = 'idea' AND evidence_sig IS NOT NULL"),
                    {"sk": sk}).fetchall()}
                if idea_disposition(sig, seen) != "present":
                    continue
                action = {k: p.get(k) for k in _IDEA_ACTION_FIELDS}
                db.execute(text(
                    "INSERT INTO holding_proposals (source_key, severity, entity, title, action, status, "
                    "evidence, kind, evidence_sig) VALUES (:sk, :sev, :ent, :ttl, CAST(:act AS JSONB), "
                    "'proposed', CAST(:ev AS JSONB), 'idea', :sig)"),
                    {"sk": sk, "sev": p.get("confidence"), "ent": p.get("company"), "ttl": p.get("title"),
                     "act": json.dumps(action), "ev": json.dumps(p.get("evidence") or []), "sig": sig})
                inserted += 1
            db.commit()
            return inserted
        finally:
            db.close()
    except Exception:
        return 0


def list_ideas(status: Optional[str] = None, limit: int = 50) -> list:
    """§21 idea rows (kind='idea') newest-first, optionally filtered by status. NEVER returns a proposal.
    Never raises."""
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            q = ("SELECT id, created_at, source_key, severity, entity, title, action, status, decided_at, "
                 "reject_reason, evidence, evidence_sig FROM holding_proposals WHERE kind = 'idea'")
            params = {"lim": limit}
            if status:
                q += " AND status = :st"; params["st"] = status
            q += " ORDER BY created_at DESC, id DESC LIMIT :lim"
            rows = db.execute(text(q), params).fetchall()
            out = []
            for r in rows:
                act = r[6] if isinstance(r[6], dict) else json.loads(r[6] or "{}")
                ev = r[10] if isinstance(r[10], (list, dict)) else json.loads(r[10] or "[]")
                out.append({"id": r[0], "created_at": str(r[1]), "source_key": r[2], "confidence": r[3],
                            "company": r[4], "title": r[5], "action": act, "status": r[7],
                            "decided_at": str(r[8]) if r[8] else None, "reject_reason": r[9],
                            "evidence": ev, "evidence_sig": r[11]})
            return out
        finally:
            db.close()
    except Exception:
        return []
