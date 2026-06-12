"""Continuous-learning storage — SQLite sidecar (mirrors planning/kg).

Two tables:

  feedback — explicit signal on KAI's behavior (the primitive the roadmap
    flagged as 'future'). One row per thumbs-up/down (+ optional note).
      id, target_type ('message'|'conversation'|'general'), target_id (nullable),
      rating ('up'|'down'), note, created_at

  lessons — distilled, actionable guidance synthesized from feedback. Each
    lesson is PROPOSED first; the operator APPROVES (→ active) before it
    injects into KAI's system prompt. Reversible (dismiss).
      id, text, source ('feedback'|'failure'|'self_correction'|'manual'|'mixed'),
      status ('proposed'|'active'|'dismissed'), created_at, updated_at, meta(JSON)

Only 'active' lessons inject into the prompt (see injection.py), and only when
KAI_SCOPE_LEARNING is enabled.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

# backend/app/services/learning/storage.py → parents[4] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]

LEARNING_DB_PATH = Path(
    os.environ.get(
        "KAI_LEARNING_DB_PATH", str(_REPO_ROOT / "data" / "learning" / "learning.db")
    )
)
LEARNING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

RATINGS = ("up", "down")
LESSON_STATUSES = ("proposed", "active", "dismissed")


@dataclass(slots=True)
class Feedback:
    id: int
    target_type: str
    rating: str
    note: str = ""
    target_id: str | None = None
    created_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "target_type": self.target_type, "rating": self.rating,
            "note": self.note, "target_id": self.target_id, "created_at": self.created_at,
        }


@dataclass(slots=True)
class Lesson:
    id: int
    text: str
    source: str = "feedback"
    status: str = "proposed"
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "text": self.text, "source": self.source,
            "status": self.status, "meta": self.meta,
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    target_type TEXT    NOT NULL DEFAULT 'general',
    target_id   TEXT,
    rating      TEXT    NOT NULL,
    note        TEXT    NOT NULL DEFAULT '',
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating);

CREATE TABLE IF NOT EXISTS lessons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT    NOT NULL,
    source      TEXT    NOT NULL DEFAULT 'feedback',
    status      TEXT    NOT NULL DEFAULT 'proposed',
    meta        TEXT    NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lessons_status ON lessons(status);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(str(LEARNING_DB_PATH), isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA)
        yield c
    finally:
        c.close()


# ─── feedback ────────────────────────────────────────────────────────


def record_feedback(
    *, rating: str, target_type: str = "general",
    target_id: str | None = None, note: str = "",
) -> Feedback:
    rating = (rating or "").strip().lower()
    if rating not in RATINGS:
        raise ValueError(f"rating must be one of {RATINGS}, got {rating!r}")
    target_type = (target_type or "general").strip().lower()
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO feedback (target_type, target_id, rating, note, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (target_type, target_id, rating, (note or "").strip(), now),
        )
        return Feedback(
            id=cur.lastrowid, target_type=target_type, target_id=target_id,
            rating=rating, note=(note or "").strip(), created_at=now,
        )


def list_feedback(*, rating: str | None = None, limit: int = 50) -> list[Feedback]:
    sql = "SELECT * FROM feedback"
    params: list[Any] = []
    if rating:
        sql += " WHERE rating = ?"
        params.append(rating.strip().lower())
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with _conn() as c:
        return [_row_to_feedback(r) for r in c.execute(sql, tuple(params))]


# ─── lessons ─────────────────────────────────────────────────────────


def add_lesson(text: str, *, source: str = "feedback", status: str = "proposed",
               meta: dict[str, Any] | None = None) -> Lesson:
    text = (text or "").strip()
    if not text:
        raise ValueError("lesson text cannot be empty")
    status = _validate_status(status)
    now = _now()
    meta = meta or {}
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO lessons (text, source, status, meta, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (text, source, status, json.dumps(meta, default=str), now, now),
        )
        return Lesson(id=cur.lastrowid, text=text, source=source, status=status,
                      meta=meta, created_at=now, updated_at=now)


def list_lessons(*, status: str | None = None, limit: int = 100) -> list[Lesson]:
    sql = "SELECT * FROM lessons"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status.strip().lower())
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with _conn() as c:
        return [_row_to_lesson(r) for r in c.execute(sql, tuple(params))]


def get_lesson(lesson_id: int) -> Lesson | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
        return _row_to_lesson(row) if row else None


def set_lesson_status(lesson_id: int, status: str) -> Lesson:
    status = _validate_status(status)
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "UPDATE lessons SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, lesson_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no lesson with id {lesson_id}")
    updated = get_lesson(lesson_id)
    assert updated is not None
    return updated


def stats() -> dict[str, Any]:
    with _conn() as c:
        fb = {
            r["rating"]: r["n"]
            for r in c.execute("SELECT rating, COUNT(*) AS n FROM feedback GROUP BY rating")
        }
        ls = {
            r["status"]: r["n"]
            for r in c.execute("SELECT status, COUNT(*) AS n FROM lessons GROUP BY status")
        }
    return {
        "feedback_total": sum(fb.values()),
        "feedback_by_rating": fb,
        "lessons_by_status": ls,
        "active_lessons": ls.get("active", 0),
    }


# ─── helpers ─────────────────────────────────────────────────────────


def _validate_status(status: str) -> str:
    s = (status or "").strip().lower()
    if s not in LESSON_STATUSES:
        raise ValueError(f"lesson status must be one of {LESSON_STATUSES}, got {status!r}")
    return s


def _row_to_feedback(row: sqlite3.Row) -> Feedback:
    return Feedback(
        id=row["id"], target_type=row["target_type"], target_id=row["target_id"],
        rating=row["rating"], note=row["note"], created_at=row["created_at"],
    )


def _row_to_lesson(row: sqlite3.Row) -> Lesson:
    return Lesson(
        id=row["id"], text=row["text"], source=row["source"], status=row["status"],
        meta=json.loads(row["meta"]), created_at=row["created_at"], updated_at=row["updated_at"],
    )
