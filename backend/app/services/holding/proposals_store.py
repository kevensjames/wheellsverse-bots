"""Durable store + state machine for KAI's proposals (Wave 2).

Self-creating table; uses App B's Postgres. A proposal is created as 'proposed', then the OWNER moves
it to 'approved' or 'rejected' (the human gate). Dedup: a fresh generation never duplicates a still-open
proposal for the same priority (source_key). Fails SOFT (returns [] / False / None) if the DB is down.
Approving records the decision only — execution is a separate, later wave.
"""
from __future__ import annotations
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
    evidence JSONB, executed_at TIMESTAMPTZ
)"""
# For tables created before Wave 3 (no evidence/executed_at columns):
_ALTERS = ("ALTER TABLE holding_proposals ADD COLUMN IF NOT EXISTS evidence JSONB",
           "ALTER TABLE holding_proposals ADD COLUMN IF NOT EXISTS executed_at TIMESTAMPTZ")

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
                exists = db.execute(text("""
                    SELECT 1 FROM holding_proposals
                     WHERE source_key = :sk
                       AND (status = 'proposed' OR (decided_at IS NOT NULL AND decided_at > now() - interval '24 hours'))
                     LIMIT 1"""), {"sk": sk}).fetchone()
                if exists:
                    continue
                action = {k: p.get(k) for k in ("action_class", "proposed_action", "plan", "risk", "reversible")}
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


def list_proposals(status: Optional[str] = None, limit: int = 50) -> list:
    """Rows newest-first, optionally filtered by status. Never raises."""
    try:
        db = SessionLocal()
        try:
            _ensure(db)
            q = "SELECT id, created_at, source_key, severity, entity, title, action, status, decided_at, reject_reason FROM holding_proposals"
            params = {"lim": limit}
            if status:
                q += " WHERE status = :st"; params["st"] = status
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
