"""Durable KPI snapshot history — enables REAL day-over-day movement in the briefing.

Self-contained: creates its own table on first use (the subsystem is dormant/flag-gated, so no
Alembic migration is added to the shared chain). Uses App B's existing Postgres via SessionLocal
— no parallel datastore. Every function fails SOFT (returns None / no-op) if the DB is unavailable,
so the briefing degrades to a disclaimed movement rather than erroring.

Only the SCHEDULED daily briefing persists a snapshot; the on-demand endpoint reads movement
vs. the last daily snapshot without recording, so history stays one-per-day and deltas are meaningful.
"""
from __future__ import annotations
import json
from typing import Optional

from sqlalchemy import text
from app.database import SessionLocal

_DDL = """CREATE TABLE IF NOT EXISTS holding_kpi_history (
    id BIGSERIAL PRIMARY KEY,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    kpis JSONB NOT NULL
)"""


def record_snapshot(kpis: dict) -> bool:
    """Append a KPI snapshot. Returns True on success, False if the DB was unavailable."""
    try:
        db = SessionLocal()
        try:
            db.execute(text(_DDL))
            db.execute(text("INSERT INTO holding_kpi_history (kpis) VALUES (CAST(:k AS JSONB))"),
                       {"k": json.dumps(kpis)})
            db.commit()
            return True
        finally:
            db.close()
    except Exception:
        return False


def previous_snapshot() -> Optional[dict]:
    """The most recent stored snapshot's kpis (the baseline to diff against). None if empty/unavailable."""
    try:
        db = SessionLocal()
        try:
            db.execute(text(_DDL))
            row = db.execute(text(
                "SELECT kpis FROM holding_kpi_history ORDER BY captured_at DESC, id DESC LIMIT 1")).fetchone()
            if not row:
                return None
            v = row[0]
            return v if isinstance(v, dict) else json.loads(v)
        finally:
            db.close()
    except Exception:
        return None
