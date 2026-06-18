"""Emotional-intelligence storage — SQLite sidecar (mood samples over time).

One row per detected mood on an operator message. Feeds (a) per-reply tone
adaptation (live), and (b) mood-trend history for the dashboard + future
daily-check-in / relationship features.

  mood_samples:
    id, mood, confidence (0..1), excerpt (short, truncated), created_at
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

EQ_DB_PATH = Path(
    os.environ.get("KAI_EQ_DB_PATH", str(_REPO_ROOT / "data" / "eq" / "eq.db"))
)
EQ_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_EXCERPT_MAX = 160


@dataclass(slots=True)
class MoodSample:
    id: int
    mood: str
    confidence: float
    excerpt: str
    created_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "mood": self.mood, "confidence": self.confidence,
                "excerpt": self.excerpt, "created_at": self.created_at}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS mood_samples (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    mood        TEXT    NOT NULL,
    confidence  REAL    NOT NULL DEFAULT 0,
    excerpt     TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mood_created ON mood_samples(created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(str(EQ_DB_PATH), isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=5000")  # parity: wait briefly vs fail on a contended write
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA)
        yield c
    finally:
        c.close()


def record_mood(mood: str, confidence: float, excerpt: str = "") -> MoodSample:
    now = _now()
    ex = (excerpt or "").strip().replace("\n", " ")[:_EXCERPT_MAX]
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO mood_samples (mood, confidence, excerpt, created_at) "
            "VALUES (?, ?, ?, ?)",
            (mood, float(confidence), ex, now),
        )
        return MoodSample(id=cur.lastrowid, mood=mood, confidence=float(confidence),
                          excerpt=ex, created_at=now)


def recent(limit: int = 50) -> list[MoodSample]:
    with _conn() as c:
        return [
            MoodSample(id=r["id"], mood=r["mood"], confidence=r["confidence"],
                       excerpt=r["excerpt"], created_at=r["created_at"])
            for r in c.execute(
                "SELECT * FROM mood_samples ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            )
        ]


def stats(window: int = 200) -> dict[str, Any]:
    """Mood distribution over the most recent `window` samples + the latest mood."""
    with _conn() as c:
        rows = list(c.execute(
            "SELECT mood, confidence, created_at FROM mood_samples ORDER BY id DESC LIMIT ?",
            (max(1, min(int(window), 1000)),),
        ))
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["mood"]] = counts.get(r["mood"], 0) + 1
    latest = rows[0] if rows else None
    return {
        "total_samples": len(rows),
        "by_mood": counts,
        "latest_mood": latest["mood"] if latest else None,
        "latest_at": latest["created_at"] if latest else None,
    }
