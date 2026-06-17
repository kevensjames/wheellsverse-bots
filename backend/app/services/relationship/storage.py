"""Relationship state — SQLite sidecar tracking the KAI↔operator bond.

Gives KAI continuity across months: how long they've worked together, how many
conversations, an earned-trust signal, and shared milestones it can reference
naturally. Grounded in REAL counters (no faked intimacy):

  relationship_state — a single row (id=1):
    interaction_count, trust_score (0..100), first_met (ISO date),
    last_interaction, created_at, updated_at
  milestones — notable shared moments:
    id, text, kind ('win'|'goal'|'moment'|'shared'), created_at

familiarity is DERIVED from interaction_count (not stored) so it can't drift.
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

REL_DB_PATH = Path(
    os.environ.get("KAI_RELATIONSHIP_DB_PATH", str(_REPO_ROOT / "data" / "relationship" / "relationship.db"))
)
REL_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

MILESTONE_KINDS = ("win", "goal", "moment", "shared")
_TRUST_START = 50
_TRUST_MAX = 100
_TRUST_MIN = 0


@dataclass(slots=True)
class Milestone:
    id: int
    text: str
    kind: str
    created_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text, "kind": self.kind,
                "created_at": self.created_at}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS relationship_state (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    interaction_count INTEGER NOT NULL DEFAULT 0,
    trust_score      INTEGER NOT NULL DEFAULT 50,
    first_met        TEXT    NOT NULL,
    last_interaction TEXT,
    created_at       TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS milestones (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    text        TEXT    NOT NULL,
    kind        TEXT    NOT NULL DEFAULT 'moment',
    created_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_milestones_created ON milestones(created_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    c = sqlite3.connect(str(REL_DB_PATH), isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA busy_timeout=5000")
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA)
        yield c
    finally:
        c.close()


def _ensure_state(c: sqlite3.Connection) -> None:
    row = c.execute("SELECT 1 FROM relationship_state WHERE id=1").fetchone()
    if not row:
        now = _now()
        c.execute(
            "INSERT INTO relationship_state (id, interaction_count, trust_score, "
            "first_met, last_interaction, created_at, updated_at) "
            "VALUES (1, 0, ?, ?, NULL, ?, ?)",
            (_TRUST_START, now, now, now),
        )


def familiarity_from_count(count: int) -> int:
    """Derive a 0..100 familiarity from interaction count (fast early growth,
    asymptotic). 0→10, ~40 interactions→~60, caps at 100."""
    return max(0, min(100, int(10 + count * 1.2)))


def get_state() -> dict[str, Any]:
    with _conn() as c:
        _ensure_state(c)
        r = c.execute("SELECT * FROM relationship_state WHERE id=1").fetchone()
    count = r["interaction_count"]
    first_met = r["first_met"]
    days_known = 0
    try:
        days_known = max(0, (datetime.now(timezone.utc)
                             - datetime.fromisoformat(first_met)).days)
    except Exception:  # pragma: no cover - defensive
        pass
    return {
        "interaction_count": count,
        "trust_score": r["trust_score"],
        "familiarity_score": familiarity_from_count(count),
        "first_met": first_met,
        "last_interaction": r["last_interaction"],
        "days_known": days_known,
    }


def record_interaction() -> None:
    """+1 conversation turn; bumps last_interaction. Cheap, called per message."""
    now = _now()
    with _conn() as c:
        _ensure_state(c)
        c.execute(
            "UPDATE relationship_state SET interaction_count = interaction_count + 1, "
            "last_interaction = ?, updated_at = ? WHERE id = 1",
            (now, now),
        )


def adjust_trust(delta: int) -> int:
    now = _now()
    with _conn() as c:
        _ensure_state(c)
        c.execute(
            "UPDATE relationship_state SET trust_score = "
            "MAX(?, MIN(?, trust_score + ?)), updated_at = ? WHERE id = 1",
            (_TRUST_MIN, _TRUST_MAX, int(delta), now),
        )
        return c.execute("SELECT trust_score FROM relationship_state WHERE id=1").fetchone()[0]


def add_milestone(text: str, kind: str = "moment") -> Milestone:
    text = (text or "").strip()
    if not text:
        raise ValueError("milestone text cannot be empty")
    k = (kind or "moment").strip().lower()
    if k not in MILESTONE_KINDS:
        raise ValueError(f"kind must be one of {MILESTONE_KINDS}, got {kind!r}")
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO milestones (text, kind, created_at) VALUES (?, ?, ?)",
            (text, k, now),
        )
        mid = cur.lastrowid
    # A logged 'win' nudges earned trust upward.
    if k == "win":
        adjust_trust(2)
    return Milestone(id=mid, text=text, kind=k, created_at=now)


def list_milestones(limit: int = 50) -> list[Milestone]:
    with _conn() as c:
        return [
            Milestone(id=r["id"], text=r["text"], kind=r["kind"], created_at=r["created_at"])
            for r in c.execute(
                "SELECT * FROM milestones ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 500)),),
            )
        ]


def stats() -> dict[str, Any]:
    state = get_state()
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM milestones").fetchone()["n"]
    state["milestone_count"] = n
    return state
