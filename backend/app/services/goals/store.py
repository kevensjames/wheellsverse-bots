"""Persistent goal store — KAI v1 build #4 (long-horizon autonomy).

A Goal is a DURABLE, cross-session objective KAI pursues (e.g. "Register the
WheellsVerse LLC", "Reach 100 qualified Boston leads"). Unlike a plan (a concrete
step sequence, services/planning), a goal persists until done/abandoned and may
span many plans. The engine (engine.py) advances goals with a HUMAN GATE — it
never auto-executes irreversible/money actions; it assesses progress and PROPOSES
the next step, which flows into the existing planning/governance approval path.

SQLite sidecar, same conventions as the other KAI subsystem stores (ensure_schema
runs the DDL once per path).
"""
from __future__ import annotations

import contextlib
import os
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from app.services._sqlite_util import ensure_schema

_REPO_ROOT = Path(__file__).resolve().parents[4]
GOALS_DB_PATH = Path(
    os.environ.get("KAI_GOALS_DB_PATH", str(_REPO_ROOT / "data" / "goals" / "goals.db"))
)
GOALS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

STATUSES = ("active", "blocked", "done", "abandoned")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
  id             TEXT PRIMARY KEY,
  title          TEXT NOT NULL,
  done_when      TEXT NOT NULL DEFAULT '',
  status         TEXT NOT NULL DEFAULT 'active',
  progress       TEXT NOT NULL DEFAULT '',
  next_action    TEXT NOT NULL DEFAULT '',
  blocked_reason TEXT NOT NULL DEFAULT '',
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_goals_status ON goals(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(str(GOALS_DB_PATH), isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        ensure_schema(c, str(GOALS_DB_PATH), _SCHEMA)  # PERF-F4: run schema once per path
        yield c
    finally:
        c.close()


@dataclass
class Goal:
    id: str
    title: str
    done_when: str
    status: str
    progress: str
    next_action: str
    blocked_reason: str
    created_at: str
    updated_at: str

    def as_dict(self) -> dict:
        return asdict(self)


def _row(r: sqlite3.Row) -> Goal:
    return Goal(**{k: r[k] for k in r.keys()})


def create_goal(title: str, *, done_when: str = "") -> Goal:
    gid = uuid.uuid4().hex
    now = _now()
    with _conn() as c:
        c.execute(
            "INSERT INTO goals (id,title,done_when,status,progress,next_action,"
            "blocked_reason,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (gid, title.strip(), done_when.strip(), "active", "", "", "", now, now),
        )
    goal = get_goal(gid)
    assert goal is not None
    return goal


def get_goal(gid: str) -> Optional[Goal]:
    with _conn() as c:
        r = c.execute("SELECT * FROM goals WHERE id=?", (gid,)).fetchone()
    return _row(r) if r else None


def list_goals(*, status: Optional[str] = None) -> list[Goal]:
    with _conn() as c:
        if status:
            rows = c.execute(
                "SELECT * FROM goals WHERE status=? ORDER BY created_at", (status,)
            ).fetchall()
        else:
            rows = c.execute("SELECT * FROM goals ORDER BY created_at").fetchall()
    return [_row(r) for r in rows]


def update_goal(gid: str, **fields) -> Optional[Goal]:
    allowed = {"title", "done_when", "status", "progress", "next_action", "blocked_reason"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return get_goal(gid)
    if "status" in sets and sets["status"] not in STATUSES:
        raise ValueError(f"invalid status: {sets['status']}")
    sets["updated_at"] = _now()
    cols = ",".join(f"{k}=?" for k in sets)
    with _conn() as c:
        c.execute(f"UPDATE goals SET {cols} WHERE id=?", (*sets.values(), gid))
    return get_goal(gid)
