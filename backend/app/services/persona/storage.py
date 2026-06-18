"""KAI persona storage — SQLite sidecar (mirrors twin/learning).

This is KAI's OWN personality — distinct from the digital twin (which models the
OPERATOR). One row per persona trait, grouped by section. Operator-authored or
seeded traits land 'active'; KAI-suggested ones land 'proposed'. Only 'active'
traits inject into the system prompt.

  entries:
    id, section ('identity'|'voice'|'humor'|'values'|'boundaries'),
    text, source ('operator'|'seed'|'feedback'|'llm'),
    status ('proposed'|'active'|'archived'), created_at, updated_at

A sensible warm-companion persona is SEEDED on first init (seed_defaults) so KAI
feels like a friend out of the box; the operator reshapes it via the dashboard.
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

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[4]

PERSONA_DB_PATH = Path(
    os.environ.get("KAI_PERSONA_DB_PATH", str(_REPO_ROOT / "data" / "persona" / "persona.db"))
)
PERSONA_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SECTIONS = ("identity", "voice", "humor", "values", "boundaries")
ENTRY_STATUSES = ("proposed", "active", "archived")

# A warm, capable companion — friend first, world-class operator second. Seeded
# active on first run so KAI is friendly immediately; every line is editable.
_DEFAULT_PERSONA: tuple[tuple[str, str], ...] = (
    ("identity",
     "You are KAI — Jhon's personal AI companion and partner, not a generic "
     "assistant. You've worked alongside him building WheellsVerse, Sol, and your "
     "own systems, and you speak as a familiar friend who also happens to be a "
     "world-class engineer, operator, and life-coach."),
    ("voice",
     "Warm, direct, and encouraging. Talk like a trusted friend in first person — "
     "natural and a little informal, never a corporate bot. Match the user's "
     "energy and use their name sometimes. Be concise, but never cold or clipped."),
    ("humor",
     "Light, dry, occasionally playful — a well-placed bit of wit is welcome. "
     "Never forced, never sarcastic at the user's expense."),
    ("values",
     "Loyalty to Jhon and his goals. Honesty over flattery — tell him the truth "
     "even when it's not what he wants to hear. Initiative: anticipate what he "
     "needs next. Calm and steady under pressure; celebrate his real wins."),
    ("boundaries",
     "Never fake enthusiasm or invent facts; if you don't know, say so plainly. "
     "Protect his time, money, and trust. Don't inflate progress or flatter — a "
     "real friend is straight with you."),
)


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
CREATE INDEX IF NOT EXISTS idx_persona_status ON entries(status);
CREATE INDEX IF NOT EXISTS idx_persona_section ON entries(section);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(str(PERSONA_DB_PATH), isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=5000")  # parity: wait briefly vs fail on a contended write
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA)
        yield c
    finally:
        c.close()


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


def count_entries() -> int:
    with _conn() as c:
        return c.execute("SELECT COUNT(*) AS n FROM entries").fetchone()["n"]


def seed_defaults() -> int:
    """Insert the default warm-companion persona as 'active' IF the table is
    empty. Idempotent: a no-op once any entry exists (so it never clobbers the
    operator's edits). Returns the number of rows inserted."""
    if count_entries() > 0:
        return 0
    inserted = 0
    for section, text in _DEFAULT_PERSONA:
        add_entry(section, text, source="seed", status="active")
        inserted += 1
    logger.info("persona: seeded %d default trait(s)", inserted)
    return inserted


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
    return {
        "active_entries": by_status.get("active", 0),
        "entries_by_status": by_status,
        "active_by_section": by_section,
    }


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
