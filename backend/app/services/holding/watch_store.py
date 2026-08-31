"""Durable state for the continuous watch loop — last-seen state + alert memory (for dedup/cooldown).

Self-contained (creates its own single-row table on first use; no migration). Uses App B's Postgres
via SessionLocal. Fails SOFT everywhere (returns {} / no-op) so the watch degrades to a first-run
baseline rather than erroring.
"""
from __future__ import annotations
import json
from typing import Optional

from sqlalchemy import text
from app.database import SessionLocal

_DDL = """CREATE TABLE IF NOT EXISTS holding_watch_state (
    id INT PRIMARY KEY DEFAULT 1,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    state JSONB NOT NULL DEFAULT '{}',
    alert_memory JSONB NOT NULL DEFAULT '{}',
    CONSTRAINT holding_watch_singleton CHECK (id = 1)
)"""


def load() -> dict:
    """Return {'state': {...}, 'alert_memory': {...}} — empty dicts if none/unavailable."""
    try:
        db = SessionLocal()
        try:
            db.execute(text(_DDL))
            row = db.execute(text("SELECT state, alert_memory FROM holding_watch_state WHERE id = 1")).fetchone()
            if not row:
                return {"state": {}, "alert_memory": {}}
            st = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}")
            am = row[1] if isinstance(row[1], dict) else json.loads(row[1] or "{}")
            return {"state": st, "alert_memory": am}
        finally:
            db.close()
    except Exception:
        return {"state": {}, "alert_memory": {}}


def save(state: dict, alert_memory: dict) -> bool:
    """Upsert the single row. True on success, False if DB unavailable."""
    try:
        db = SessionLocal()
        try:
            db.execute(text(_DDL))
            db.execute(text("""
                INSERT INTO holding_watch_state (id, updated_at, state, alert_memory)
                VALUES (1, now(), CAST(:s AS JSONB), CAST(:m AS JSONB))
                ON CONFLICT (id) DO UPDATE SET updated_at = now(), state = EXCLUDED.state, alert_memory = EXCLUDED.alert_memory
            """), {"s": json.dumps(state), "m": json.dumps(alert_memory)})
            db.commit()
            return True
        finally:
            db.close()
    except Exception:
        return False
