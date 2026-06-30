"""Digital-twin storage — SQLite sidecar (mirrors learning/planning).

Two tables:

  entries — the structured operator self-model. One row per profile fact,
    grouped by section. Operator-authored entries land 'active'; KAI-suggested
    ones land 'proposed' (operator approves → active). Only 'active' entries
    inject into the prompt / feed drafts.
      id, section ('identity'|'voice'|'values'|'preferences'|'goals'),
      text, source ('operator'|'kg'|'memory'|'feedback'|'llm'),
      status ('proposed'|'active'|'archived'), created_at, updated_at

  drafts — history of content KAI drafted IN THE OPERATOR'S VOICE (never sent).
      id, task, content, cost_usd, created_at

The twin is the stable, always-on self-model of the principal — distinct from
episodic memory (per-message retrieval) and learning lessons (behavioral fixes).
"""
from __future__ import annotations

import contextlib
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.services._sqlite_util import ensure_schema

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]

TWIN_DB_PATH = Path(
    os.environ.get("KAI_TWIN_DB_PATH", str(_REPO_ROOT / "data" / "twin" / "twin.db"))
)
TWIN_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SECTIONS = ("identity", "voice", "values", "preferences", "goals")
ENTRY_STATUSES = ("proposed", "active", "archived")


@dataclass(slots=True)
class Entry:
    id: int
    section: str
    text: str
    source: str = "operator"
    status: str = "active"
    created_at: str | None = None
    updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "section": self.section, "text": self.text,
            "source": self.source, "status": self.status,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class Draft:
    id: int
    task: str
    content: str
    cost_usd: float = 0.0
    created_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "task": self.task, "content": self.content,
            "cost_usd": self.cost_usd, "created_at": self.created_at,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    section     TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'operator',
    status      TEXT    NOT NULL DEFAULT 'active',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_status ON entries(status);
CREATE INDEX IF NOT EXISTS idx_entries_section ON entries(section);

CREATE TABLE IF NOT EXISTS drafts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task        TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    cost_usd    REAL    NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(str(TWIN_DB_PATH), isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        ensure_schema(c, str(TWIN_DB_PATH), _SCHEMA)  # PERF-F4: run schema once per path
        yield c
    finally:
        c.close()


# ─── entries ─────────────────────────────────────────────────────────


def add_entry(section: str, text: str, *, source: str = "operator",
              status: str = "active") -> Entry:
    section = _validate_section(section)
    text = (text or "").strip()
    if not text:
        raise ValueError("entry text cannot be empty")
    status = _validate_status(status)
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO entries (section, text, source, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (section, text, source, status, now, now),
        )
        return Entry(id=cur.lastrowid, section=section, text=text, source=source,
                     status=status, created_at=now, updated_at=now)


def list_entries(*, section: str | None = None, status: str | None = None,
                 limit: int = 200) -> list[Entry]:
    sql = "SELECT * FROM entries"
    where: list[str] = []
    params: list[Any] = []
    if section:
        where.append("section = ?"); params.append(section.strip().lower())
    if status:
        where.append("status = ?"); params.append(status.strip().lower())
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY section ASC, id ASC LIMIT ?"
    params.append(max(1, min(int(limit), 1000)))
    with _conn() as c:
        return [_row_to_entry(r) for r in c.execute(sql, tuple(params))]


def get_entry(entry_id: int) -> Entry | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        return _row_to_entry(row) if row else None


def set_entry_status(entry_id: int, status: str) -> Entry:
    status = _validate_status(status)
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "UPDATE entries SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, entry_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no entry with id {entry_id}")
    e = get_entry(entry_id)
    assert e is not None
    return e


# ─── drafts ──────────────────────────────────────────────────────────


def add_draft(task: str, content: str, *, cost_usd: float = 0.0) -> Draft:
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO drafts (task, content, cost_usd, created_at) VALUES (?, ?, ?, ?)",
            ((task or "").strip(), content or "", float(cost_usd), now),
        )
        return Draft(id=cur.lastrowid, task=(task or "").strip(), content=content or "",
                     cost_usd=float(cost_usd), created_at=now)


def list_drafts(limit: int = 50) -> list[Draft]:
    with _conn() as c:
        return [
            _row_to_draft(r)
            for r in c.execute(
                "SELECT * FROM drafts ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            )
        ]


def stats() -> dict[str, Any]:
    with _conn() as c:
        by_status = {
            r["status"]: r["n"]
            for r in c.execute("SELECT status, COUNT(*) AS n FROM entries GROUP BY status")
        }
        by_section = {
            r["section"]: r["n"]
            for r in c.execute(
                "SELECT section, COUNT(*) AS n FROM entries WHERE status='active' GROUP BY section"
            )
        }
        drafts = c.execute("SELECT COUNT(*) AS n FROM drafts").fetchone()["n"]
    return {
        "active_entries": by_status.get("active", 0),
        "entries_by_status": by_status,
        "active_by_section": by_section,
        "drafts": drafts,
    }


# ─── helpers ─────────────────────────────────────────────────────────


def _validate_section(section: str) -> str:
    s = (section or "").strip().lower()
    if s not in SECTIONS:
        raise ValueError(f"section must be one of {SECTIONS}, got {section!r}")
    return s


def _validate_status(status: str) -> str:
    s = (status or "").strip().lower()
    if s not in ENTRY_STATUSES:
        raise ValueError(f"status must be one of {ENTRY_STATUSES}, got {status!r}")
    return s


def _row_to_entry(row: sqlite3.Row) -> Entry:
    return Entry(
        id=row["id"], section=row["section"], text=row["text"], source=row["source"],
        status=row["status"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_draft(row: sqlite3.Row) -> Draft:
    return Draft(
        id=row["id"], task=row["task"], content=row["content"],
        cost_usd=row["cost_usd"], created_at=row["created_at"],
    )
