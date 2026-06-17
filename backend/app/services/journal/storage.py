"""Voice/text journal storage — SQLite sidecar.

  journal_entries:
    id, raw_text, summary, mood, created_at

Raw thoughts (typed, or transcribed audio via routers/transcribe.py) get an
LLM summary + a detected mood, then are stored here AND surfaced to long-term
memory — so journaling deepens KAI's understanding over time.
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

JOURNAL_DB_PATH = Path(
    os.environ.get("KAI_JOURNAL_DB_PATH", str(_REPO_ROOT / "data" / "journal" / "journal.db"))
)
JOURNAL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass(slots=True)
class JournalEntry:
    id: int
    raw_text: str
    summary: str
    mood: str
    created_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "raw_text": self.raw_text, "summary": self.summary,
                "mood": self.mood, "created_at": self.created_at}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS journal_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_text    TEXT    NOT NULL,
    summary     TEXT    NOT NULL DEFAULT '',
    mood        TEXT    NOT NULL DEFAULT 'neutral',
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_journal_created ON journal_entries(created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(str(JOURNAL_DB_PATH), isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA)
        yield c
    finally:
        c.close()


def add(raw_text: str, summary: str, mood: str) -> JournalEntry:
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise ValueError("journal text cannot be empty")
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO journal_entries (raw_text, summary, mood, created_at) "
            "VALUES (?, ?, ?, ?)",
            (raw_text, summary or "", mood or "neutral", now),
        )
        return JournalEntry(id=cur.lastrowid, raw_text=raw_text, summary=summary or "",
                            mood=mood or "neutral", created_at=now)


def recent(limit: int = 50) -> list[JournalEntry]:
    with _conn() as c:
        return [
            JournalEntry(id=r["id"], raw_text=r["raw_text"], summary=r["summary"],
                         mood=r["mood"], created_at=r["created_at"])
            for r in c.execute(
                "SELECT * FROM journal_entries ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            )
        ]


def stats() -> dict[str, Any]:
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM journal_entries").fetchone()["n"]
        by_mood = {r["mood"]: r["c"] for r in c.execute(
            "SELECT mood, COUNT(*) AS c FROM journal_entries GROUP BY mood")}
    return {"total_entries": n, "by_mood": by_mood}
