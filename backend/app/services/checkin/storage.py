"""Daily check-in storage — SQLite sidecar (one warm proactive check-in per day).

  checkins:
    id, date_key (YYYYMMDD, unique), message, sent (0/1), created_at

The unique date_key makes "once per day" idempotent at the storage layer.
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

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "date_key": self.date_key, "message": self.message,
                "sent": self.sent, "created_at": self.created_at}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkins (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date_key    TEXT    NOT NULL UNIQUE,
    message     TEXT    NOT NULL,
    sent        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(str(CHECKIN_DB_PATH), isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=5000")
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA)
        yield c
    finally:
        c.close()


def has_checkin(date_key: str) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM checkins WHERE date_key=?", (date_key,)).fetchone() is not None


def record_checkin(date_key: str, message: str, sent: bool) -> CheckIn | None:
    """Insert the day's check-in. Returns None if one already exists for the day
    (UNIQUE date_key) — the idempotency guard for the scheduler."""
    now = _now()
    with _conn() as c:
        try:
            cur = c.execute(
                "INSERT INTO checkins (date_key, message, sent, created_at) VALUES (?, ?, ?, ?)",
                (date_key, message, 1 if sent else 0, now),
            )
        except sqlite3.IntegrityError:
            return None  # already checked in today
        return CheckIn(id=cur.lastrowid, date_key=date_key, message=message,
                       sent=sent, created_at=now)


def get_by_date(date_key: str) -> CheckIn | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM checkins WHERE date_key=?", (date_key,)).fetchone()
    return CheckIn(id=r["id"], date_key=r["date_key"], message=r["message"],
                   sent=bool(r["sent"]), created_at=r["created_at"]) if r else None


def set_sent(date_key: str, sent: bool = True) -> None:
    with _conn() as c:
        c.execute("UPDATE checkins SET sent=? WHERE date_key=?",
                  (1 if sent else 0, date_key))


def recent(limit: int = 30) -> list[CheckIn]:
    with _conn() as c:
        return [
            CheckIn(id=r["id"], date_key=r["date_key"], message=r["message"],
                    sent=bool(r["sent"]), created_at=r["created_at"])
            for r in c.execute(
                "SELECT * FROM checkins ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 365)),),
            )
        ]
