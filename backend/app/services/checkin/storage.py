"""Daily check-in storage — SQLite sidecar (one warm proactive check-in per day).

  checkins:
    id, date_key (YYYYMMDD, unique), message, sent (0/1),
    attempts (delivery attempts so far), last_attempt_at (ISO ts), created_at

The unique date_key makes "once per day" idempotent at the storage layer. A row
is CLAIMED with sent=0 *before* delivery; ``record_attempt`` flips sent=1 only on
a confirmed send and leaves failed rows sent=0 with a bumped attempt count, so
the scheduler can redeliver them with exponential backoff instead of losing them.
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

CHECKIN_DB_PATH = Path(
    os.environ.get("KAI_CHECKIN_DB_PATH", str(_REPO_ROOT / "data" / "checkin" / "checkin.db"))
)
CHECKIN_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class CheckIn:
    id: int
    date_key: str
    message: str
    sent: bool
    created_at: str | None = None
    attempts: int = 0
    last_attempt_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "date_key": self.date_key, "message": self.message,
                "sent": self.sent, "created_at": self.created_at,
                "attempts": self.attempts, "last_attempt_at": self.last_attempt_at}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkins (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date_key        TEXT    NOT NULL UNIQUE,
    message         TEXT    NOT NULL,
    sent            INTEGER NOT NULL DEFAULT 0,
    attempts        INTEGER NOT NULL DEFAULT 0,
    last_attempt_at TEXT,
    created_at      TEXT    NOT NULL
);
"""

# Columns added after the original ship. CREATE TABLE IF NOT EXISTS won't add
# columns to a table that already exists, so migrate pre-existing prod DBs
# explicitly and idempotently.
_MIGRATIONS = (
    ("attempts", "INTEGER NOT NULL DEFAULT 0"),
    ("last_attempt_at", "TEXT"),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_columns(c: sqlite3.Connection) -> None:
    existing = {row["name"] for row in c.execute("PRAGMA table_info(checkins)")}
    for name, decl in _MIGRATIONS:
        if name not in existing:
            try:
                c.execute(f"ALTER TABLE checkins ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError:
                # Another connection won the migration race and added the column
                # first — "duplicate column name" here is a benign no-op.
                pass


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(str(CHECKIN_DB_PATH), isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=5000")
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA)
        _ensure_columns(c)
        yield c
    finally:
        c.close()


def _row_to_checkin(r: sqlite3.Row) -> CheckIn:
    keys = r.keys()
    return CheckIn(
        id=r["id"], date_key=r["date_key"], message=r["message"],
        sent=bool(r["sent"]), created_at=r["created_at"],
        attempts=r["attempts"] if "attempts" in keys else 0,
        last_attempt_at=r["last_attempt_at"] if "last_attempt_at" in keys else None,
    )


def has_checkin(date_key: str) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM checkins WHERE date_key=?", (date_key,)).fetchone() is not None


def record_checkin(date_key: str, message: str, sent: bool,
                   *, pending: bool = False) -> CheckIn | None:
    """Insert the day's check-in. Returns None if one already exists for the day
    (UNIQUE date_key) — the idempotency guard for the scheduler.

    pending=True stamps last_attempt_at at claim time to mark the row as a
    DELIVERABLE claim (deliver=True). That lets retry_due_unsent distinguish a
    crashed real send (claimed, then the process died before the first
    record_attempt) from a deliver=False preview that was never meant to send —
    the former stays retry-eligible, the latter does not."""
    now = _now()
    last_attempt = now if pending else None
    with _conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO checkins (date_key, message, sent, attempts, last_attempt_at, created_at) "
                "VALUES (?, ?, ?, 0, ?, ?)",
                (date_key, message, 1 if sent else 0, last_attempt, now),
            )
        except sqlite3.IntegrityError:
            return None  # already checked in today
        return CheckIn(id=cur.lastrowid, date_key=date_key, message=message,
                       sent=sent, created_at=now, attempts=0, last_attempt_at=last_attempt)


def record_attempt(date_key: str, *, success: bool) -> None:
    """Record one delivery attempt: bump attempts + stamp last_attempt_at, and
    flip sent=1 ONLY on a confirmed success. A failed attempt leaves sent=0 so
    the row stays eligible for backed-off retry."""
    now = _now()
    with _conn() as c:
        if success:
            c.execute(
                "UPDATE checkins SET attempts = attempts + 1, last_attempt_at = ?, "
                "sent = 1 WHERE date_key = ?", (now, date_key),
            )
        else:
            c.execute(
                "UPDATE checkins SET attempts = attempts + 1, last_attempt_at = ? "
                "WHERE date_key = ?", (now, date_key),
            )


def set_sent(date_key: str, sent: bool = True) -> None:
    """Directly set the sent flag. Retained for backward compat; the scheduler
    now prefers record_attempt() so attempt bookkeeping stays consistent."""
    with _conn() as c:
        c.execute("UPDATE checkins SET sent=? WHERE date_key=?",
                  (1 if sent else 0, date_key))


def list_unsent(limit: int = 100) -> list[CheckIn]:
    """Undelivered rows (sent=0), newest first — the retry candidate set."""
    with _conn() as c:
        return [_row_to_checkin(r) for r in c.execute(
            "SELECT * FROM checkins WHERE sent=0 ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 365)),),
        )]


def recent(limit: int = 30) -> list[CheckIn]:
    with _conn() as c:
        return [_row_to_checkin(r) for r in c.execute(
            "SELECT * FROM checkins ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 365)),),
        )]
