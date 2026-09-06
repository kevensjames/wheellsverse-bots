"""Durable store for the manual single-cycle trigger — authoritative PRIOR snapshot, single-flight
lease, and idempotency, on App B's Postgres. Self-creating tables; fails SOFT. Same method surface as
manual_cycle.InMemoryCycleStore so the route uses this and the tests use the in-memory one.
"""
from __future__ import annotations
import json
import secrets

from sqlalchemy import text
from app.database import SessionLocal

_DDL_STATE = """CREATE TABLE IF NOT EXISTS holding_cycle_state (
    holding_id TEXT PRIMARY KEY,
    prior_snapshot JSONB, last_cycle_id TEXT, seq BIGINT NOT NULL DEFAULT 0,
    running_until TIMESTAMPTZ, running_token TEXT, updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"""
# older tables (created before the lease-token fix) get the column added idempotently
_ALTER_TOKEN = "ALTER TABLE holding_cycle_state ADD COLUMN IF NOT EXISTS running_token TEXT"
_DDL_RUNS = """CREATE TABLE IF NOT EXISTS holding_cycle_runs (
    idempotency_key TEXT PRIMARY KEY, record JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())"""


class DbCycleStore:
    def _ensure(self, db):
        db.execute(text(_DDL_STATE)); db.execute(text(_DDL_RUNS)); db.execute(text(_ALTER_TOKEN))

    def next_cycle_id(self, holding_id, now):
        try:
            db = SessionLocal()
            try:
                self._ensure(db)
                db.execute(text("INSERT INTO holding_cycle_state (holding_id, seq) VALUES (:h, 0) "
                                "ON CONFLICT (holding_id) DO NOTHING"), {"h": holding_id})
                r = db.execute(text("UPDATE holding_cycle_state SET seq = seq + 1, updated_at = now() "
                                    "WHERE holding_id = :h RETURNING seq"), {"h": holding_id}).fetchone()
                db.commit()
                return f"cy-{holding_id}-{r[0] if r else 0}"
            finally:
                db.close()
        except Exception:
            return f"cy-{holding_id}-x"

    def get_run(self, key):
        try:
            db = SessionLocal()
            try:
                self._ensure(db)
                r = db.execute(text("SELECT record FROM holding_cycle_runs WHERE idempotency_key = :k"),
                               {"k": key}).fetchone()
                return (r[0] if isinstance(r[0], dict) else json.loads(r[0])) if r else None
            finally:
                db.close()
        except Exception:
            return None

    def save_run(self, key, rec):
        try:
            db = SessionLocal()
            try:
                self._ensure(db)
                db.execute(text("INSERT INTO holding_cycle_runs (idempotency_key, record) "
                                "VALUES (:k, CAST(:r AS JSONB)) ON CONFLICT (idempotency_key) DO NOTHING"),
                           {"k": key, "r": json.dumps(rec)})
                db.commit()
            finally:
                db.close()
        except Exception:
            pass

    def list_runs(self, limit: int = 200):
        """§34 eval feed: newest-first stored CycleRecord dicts. [] if empty/DB down (never raises)."""
        try:
            db = SessionLocal()
            try:
                self._ensure(db)
                rows = db.execute(text("SELECT record FROM holding_cycle_runs ORDER BY created_at DESC "
                                       "LIMIT :l"), {"l": max(1, int(limit))}).fetchall()
                return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]
            finally:
                db.close()
        except Exception:
            return []

    def try_lock(self, holding_id, lease_s, now):
        """Single-flight: acquire only if no live lease (running_until null or in the past). Atomic.
        Returns a LEASE TOKEN (str) on success, else None — so only the holder can release it."""
        token = secrets.token_hex(8)
        try:
            db = SessionLocal()
            try:
                self._ensure(db)
                db.execute(text("INSERT INTO holding_cycle_state (holding_id) VALUES (:h) "
                                "ON CONFLICT (holding_id) DO NOTHING"), {"h": holding_id})
                r = db.execute(text(
                    "UPDATE holding_cycle_state SET running_until = now() + (:lease || ' seconds')::interval, "
                    "running_token = :tok "
                    "WHERE holding_id = :h AND (running_until IS NULL OR running_until < now()) "
                    "RETURNING holding_id"), {"h": holding_id, "lease": str(int(lease_s)), "tok": token}).fetchone()
                db.commit()
                return token if r else None
            finally:
                db.close()
        except Exception:
            return None   # DB down → fail closed (do not run a cycle we cannot lock)

    def release_lock(self, holding_id, token=None):
        """Release ONLY our own lease (recheck fix): a late releaser whose lease already expired and was
        re-acquired by a successor must NOT null the successor's live lease. Token-scoped."""
        try:
            db = SessionLocal()
            try:
                self._ensure(db)
                db.execute(text("UPDATE holding_cycle_state SET running_until = NULL, running_token = NULL "
                                "WHERE holding_id = :h AND running_token = :tok"),
                           {"h": holding_id, "tok": token})
                db.commit()
            finally:
                db.close()
        except Exception:
            pass

    def load_prior(self, holding_id):
        try:
            db = SessionLocal()
            try:
                self._ensure(db)
                r = db.execute(text("SELECT prior_snapshot FROM holding_cycle_state WHERE holding_id = :h"),
                               {"h": holding_id}).fetchone()
                if not r or r[0] is None:
                    return None
                return r[0] if isinstance(r[0], dict) else json.loads(r[0])
            finally:
                db.close()
        except Exception:
            return None

    def save_snapshot(self, holding_id, snapshot, cycle_id):
        try:
            db = SessionLocal()
            try:
                self._ensure(db)
                db.execute(text("UPDATE holding_cycle_state SET prior_snapshot = CAST(:s AS JSONB), "
                                "last_cycle_id = :c, updated_at = now() WHERE holding_id = :h"),
                           {"s": json.dumps(snapshot), "c": cycle_id, "h": holding_id})
                db.commit()
            finally:
                db.close()
        except Exception:
            pass
