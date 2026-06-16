"""Planning storage — SQLite over a single .db file.

Mirrors the KG storage pattern (WAL, fresh connection per call, schema
bootstrap on connect) so the planning module slots in next to the other
sidecar features with zero migration risk.

Schema — the "linear list with optional branches" plan shape:

  plans:
    id          INTEGER PK
    title       TEXT    NOT NULL   — short human label
    goal        TEXT    NOT NULL   — the original goal prompt KAI decomposed
    status      TEXT    NOT NULL   — draft / approved / executing / blocked / done / abandoned
    meta        TEXT (JSON)        — free-form (created_by, source, …)
    created_at  TEXT               — ISO-8601 UTC
    updated_at  TEXT

  steps:
    id          INTEGER PK
    plan_id     INTEGER NOT NULL → plans(id)
    seq         INTEGER NOT NULL   — 1-based order (the "n")
    action      TEXT    NOT NULL   — what to do
    kind        TEXT    NOT NULL   — chat (run via the LLM) / tool (named tool)
    tool_name   TEXT               — set when kind=tool
    status      TEXT    NOT NULL   — pending / running / done / failed / skipped
    on_fail     TEXT               — optional branch directive: goto:<seq> | revise | stop
    on_done     TEXT               — optional branch directive: goto:<seq>
    result      TEXT               — last run's output summary
    created_at  TEXT
    updated_at  TEXT
    UNIQUE(plan_id, seq)           — one step per slot

  step_runs:                       — append-only execution history
    id          INTEGER PK
    step_id     INTEGER NOT NULL → steps(id)
    plan_id     INTEGER NOT NULL → plans(id)
    seq         INTEGER NOT NULL   — snapshot of the step's seq at run time
    status      TEXT    NOT NULL   — done / failed
    output      TEXT               — the run's text output
    cost_usd    REAL               — LLM cost for the run
    error       TEXT               — set when status=failed
    started_at  TEXT
    finished_at TEXT

The branch directive is just a string stored here; the executor owns the
grammar (see executor.parse_directive). A null on_fail means "block the
plan and propose a revision" — the safe default.

Concurrency: same posture as KG — the daemon is single-process/single-
worker, so a fresh connection per call (cheap under WAL) is enough.
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

# backend/app/services/planning/storage.py → parents[4] = repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]

PLANNING_DB_PATH = Path(
    os.environ.get(
        "KAI_PLANNING_DB_PATH", str(_REPO_ROOT / "data" / "planning" / "planning.db")
    )
)
PLANNING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ─── status vocab ────────────────────────────────────────────────────

PLAN_STATUSES = ("draft", "approved", "executing", "blocked", "done", "abandoned")
STEP_STATUSES = ("pending", "running", "done", "failed", "skipped")
STEP_KINDS = ("chat", "tool")


# ─── data models ─────────────────────────────────────────────────────


@dataclass(slots=True)
class Step:
    id: int
    plan_id: int
    seq: int
    action: str
    kind: str = "chat"
    tool_name: str | None = None
    status: str = "pending"
    on_fail: str | None = None
    on_done: str | None = None
    result: str | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "seq": self.seq,
            "action": self.action,
            "kind": self.kind,
            "tool_name": self.tool_name,
            "status": self.status,
            "on_fail": self.on_fail,
            "on_done": self.on_done,
            "result": self.result,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


@dataclass(slots=True)
class Plan:
    id: int
    title: str
    goal: str
    status: str = "draft"
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    steps: list[Step] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "goal": self.goal,
            "status": self.status,
            "meta": self.meta,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "steps": [s.as_dict() for s in self.steps],
        }


@dataclass(slots=True)
class StepRun:
    id: int
    step_id: int
    plan_id: int
    seq: int
    status: str
    output: str = ""
    cost_usd: float = 0.0
    error: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "step_id": self.step_id,
            "plan_id": self.plan_id,
            "seq": self.seq,
            "status": self.status,
            "output": self.output,
            "cost_usd": self.cost_usd,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


# ─── schema bootstrap ────────────────────────────────────────────────


_SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    goal        TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'draft',
    meta        TEXT    NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_plans_status ON plans(status);

CREATE TABLE IF NOT EXISTS steps (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id     INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    action      TEXT    NOT NULL,
    kind        TEXT    NOT NULL DEFAULT 'chat',
    tool_name   TEXT,
    status      TEXT    NOT NULL DEFAULT 'pending',
    on_fail     TEXT,
    on_done     TEXT,
    result      TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    UNIQUE(plan_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_steps_plan ON steps(plan_id);

CREATE TABLE IF NOT EXISTS step_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    step_id     INTEGER NOT NULL REFERENCES steps(id) ON DELETE CASCADE,
    plan_id     INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
    seq         INTEGER NOT NULL,
    status      TEXT    NOT NULL,
    output      TEXT    NOT NULL DEFAULT '',
    cost_usd    REAL    NOT NULL DEFAULT 0,
    error       TEXT,
    started_at  TEXT    NOT NULL,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_step_runs_plan ON step_runs(plan_id);
CREATE INDEX IF NOT EXISTS idx_step_runs_step ON step_runs(step_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """Open a connection with WAL + foreign keys enabled. Autocommit mode;
    the schema is (cheaply) re-asserted on each connect."""
    c = sqlite3.connect(str(PLANNING_DB_PATH), isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(_SCHEMA)
        yield c
    finally:
        c.close()


# ─── plans ───────────────────────────────────────────────────────────


def create_plan(
    title: str,
    goal: str,
    *,
    status: str = "draft",
    meta: dict[str, Any] | None = None,
) -> Plan:
    """Insert a new plan (no steps). Returns the created Plan."""
    title = (title or "").strip()
    goal = (goal or "").strip()
    if not title:
        raise ValueError("plan title cannot be empty")
    if not goal:
        raise ValueError("plan goal cannot be empty")
    status = _validate_plan_status(status)
    now = _now()
    meta = meta or {}
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO plans (title, goal, status, meta, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (title, goal, status, json.dumps(meta, default=str), now, now),
        )
        return Plan(
            id=cur.lastrowid, title=title, goal=goal, status=status,
            meta=meta, created_at=now, updated_at=now, steps=[],
        )


def get_plan(plan_id: int) -> Plan | None:
    """Fetch a plan with its steps (ordered by seq). None if not found."""
    with _conn() as c:
        row = c.execute(
            "SELECT id, title, goal, status, meta, created_at, updated_at "
            "FROM plans WHERE id = ?",
            (plan_id,),
        ).fetchone()
        if row is None:
            return None
        plan = _row_to_plan(row)
        plan.steps = [
            _row_to_step(r)
            for r in c.execute(
                "SELECT * FROM steps WHERE plan_id = ? ORDER BY seq ASC",
                (plan_id,),
            )
        ]
        return plan


def list_plans(*, status: str | None = None, limit: int = 50) -> list[Plan]:
    """List plans (without steps), most-recently-updated first. Optional
    status filter."""
    sql = "SELECT id, title, goal, status, meta, created_at, updated_at FROM plans"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(status.strip().lower())
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    with _conn() as c:
        return [_row_to_plan(r) for r in c.execute(sql, tuple(params))]


def update_plan_status(plan_id: int, status: str) -> Plan:
    """Set a plan's status. Raises ValueError on unknown plan/status."""
    status = _validate_plan_status(status)
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "UPDATE plans SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, plan_id),
        )
        if cur.rowcount == 0:
            raise ValueError(f"no plan with id {plan_id}")
    plan = get_plan(plan_id)
    assert plan is not None
    return plan


def stats() -> dict[str, Any]:
    """Counts by plan status + total steps. Cheap header for the dashboard."""
    with _conn() as c:
        by_status = {
            r["status"]: r["n"]
            for r in c.execute(
                "SELECT status, COUNT(*) AS n FROM plans GROUP BY status"
            )
        }
        total = c.execute("SELECT COUNT(*) AS n FROM plans").fetchone()["n"]
        step_total = c.execute("SELECT COUNT(*) AS n FROM steps").fetchone()["n"]
    active = by_status.get("approved", 0) + by_status.get("executing", 0)
    return {
        "total": total,
        "by_status": by_status,
        "active": active,
        "blocked": by_status.get("blocked", 0),
        "done": by_status.get("done", 0),
        "step_total": step_total,
    }


# ─── steps ───────────────────────────────────────────────────────────


def add_step(
    plan_id: int,
    action: str,
    *,
    kind: str = "chat",
    tool_name: str | None = None,
    on_fail: str | None = None,
    on_done: str | None = None,
    seq: int | None = None,
    status: str = "pending",
) -> Step:
    """Append a step to a plan. If seq is None, it's placed after the last
    existing step. Returns the created Step."""
    action = (action or "").strip()
    if not action:
        raise ValueError("step action cannot be empty")
    kind = (kind or "chat").strip().lower()
    if kind not in STEP_KINDS:
        raise ValueError(f"step kind must be one of {STEP_KINDS}, got {kind!r}")
    status = _validate_step_status(status)
    now = _now()
    with _conn() as c:
        if not _plan_exists(c, plan_id):
            raise ValueError(f"no plan with id {plan_id}")
        if seq is None:
            row = c.execute(
                "SELECT COALESCE(MAX(seq), 0) AS m FROM steps WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
            seq = int(row["m"]) + 1
        cur = c.execute(
            "INSERT INTO steps (plan_id, seq, action, kind, tool_name, status, "
            "on_fail, on_done, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (plan_id, seq, action, kind, tool_name, status, on_fail, on_done, now, now),
        )
        return Step(
            id=cur.lastrowid, plan_id=plan_id, seq=seq, action=action, kind=kind,
            tool_name=tool_name, status=status, on_fail=on_fail, on_done=on_done,
            result=None, created_at=now, updated_at=now,
        )


def replace_steps(plan_id: int, steps: list[dict[str, Any]]) -> list[Step]:
    """Atomically replace ALL steps for a plan with the given list.

    Used when a freshly-generated or operator-edited plan is saved. Each
    dict may contain: action (required), kind, tool_name, on_fail, on_done.
    Steps are renumbered 1..N in list order. Existing step_runs cascade-
    delete with their steps, so this is a clean reset of the plan body.
    """
    now = _now()
    out: list[Step] = []
    with _conn() as c:
        if not _plan_exists(c, plan_id):
            raise ValueError(f"no plan with id {plan_id}")
        c.execute("DELETE FROM steps WHERE plan_id = ?", (plan_id,))
        for i, raw in enumerate(steps, start=1):
            action = (str(raw.get("action") or "")).strip()
            if not action:
                continue  # skip empty rows rather than fail the whole save
            kind = (str(raw.get("kind") or "chat")).strip().lower()
            if kind not in STEP_KINDS:
                kind = "chat"
            tool_name = raw.get("tool_name")
            on_fail = raw.get("on_fail")
            on_done = raw.get("on_done")
            cur = c.execute(
                "INSERT INTO steps (plan_id, seq, action, kind, tool_name, status, "
                "on_fail, on_done, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
                (plan_id, i, action, kind, tool_name, on_fail, on_done, now, now),
            )
            out.append(
                Step(
                    id=cur.lastrowid, plan_id=plan_id, seq=i, action=action,
                    kind=kind, tool_name=tool_name, status="pending",
                    on_fail=on_fail, on_done=on_done, result=None,
                    created_at=now, updated_at=now,
                )
            )
        c.execute(
            "UPDATE plans SET updated_at = ? WHERE id = ?", (now, plan_id)
        )
    return out


def get_step(step_id: int) -> Step | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM steps WHERE id = ?", (step_id,)).fetchone()
        return _row_to_step(row) if row else None


def get_step_by_seq(plan_id: int, seq: int) -> Step | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM steps WHERE plan_id = ? AND seq = ?", (plan_id, seq)
        ).fetchone()
        return _row_to_step(row) if row else None


def next_pending_step(plan_id: int) -> Step | None:
    """Lowest-seq step still pending. None when the plan has no work left."""
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM steps WHERE plan_id = ? AND status = 'pending' "
            "ORDER BY seq ASC LIMIT 1",
            (plan_id,),
        ).fetchone()
        return _row_to_step(row) if row else None


def update_step(
    step_id: int,
    *,
    action: str | None = None,
    kind: str | None = None,
    tool_name: str | None = None,
    status: str | None = None,
    on_fail: str | None = None,
    on_done: str | None = None,
    result: str | None = None,
) -> Step:
    """Patch a step. Only the kwargs you pass are changed. Returns the
    updated Step."""
    sets: list[str] = []
    params: list[Any] = []
    if action is not None:
        a = action.strip()
        if not a:
            raise ValueError("step action cannot be empty")
        sets.append("action = ?")
        params.append(a)
    if kind is not None:
        k = kind.strip().lower()
        if k not in STEP_KINDS:
            raise ValueError(f"step kind must be one of {STEP_KINDS}")
        sets.append("kind = ?")
        params.append(k)
    if tool_name is not None:
        sets.append("tool_name = ?")
        params.append(tool_name)
    if status is not None:
        sets.append("status = ?")
        params.append(_validate_step_status(status))
    if on_fail is not None:
        sets.append("on_fail = ?")
        params.append(on_fail)
    if on_done is not None:
        sets.append("on_done = ?")
        params.append(on_done)
    if result is not None:
        sets.append("result = ?")
        params.append(result)
    if not sets:
        existing = get_step(step_id)
        if existing is None:
            raise ValueError(f"no step with id {step_id}")
        return existing
    sets.append("updated_at = ?")
    params.append(_now())
    params.append(step_id)
    with _conn() as c:
        cur = c.execute(
            f"UPDATE steps SET {', '.join(sets)} WHERE id = ?", tuple(params)
        )
        if cur.rowcount == 0:
            raise ValueError(f"no step with id {step_id}")
    updated = get_step(step_id)
    assert updated is not None
    return updated


def set_step_status(step_id: int, status: str, *, result: str | None = None) -> Step:
    """Convenience wrapper used by the executor."""
    return update_step(step_id, status=status, result=result)


# ─── step runs ───────────────────────────────────────────────────────


def add_step_run(
    step_id: int,
    plan_id: int,
    seq: int,
    *,
    status: str,
    output: str = "",
    cost_usd: float = 0.0,
    error: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> StepRun:
    """Record one execution attempt of a step."""
    started_at = started_at or _now()
    finished_at = finished_at or _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO step_runs (step_id, plan_id, seq, status, output, "
            "cost_usd, error, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (step_id, plan_id, seq, status, output, float(cost_usd), error,
             started_at, finished_at),
        )
        return StepRun(
            id=cur.lastrowid, step_id=step_id, plan_id=plan_id, seq=seq,
            status=status, output=output, cost_usd=float(cost_usd), error=error,
            started_at=started_at, finished_at=finished_at,
        )


def list_step_runs(plan_id: int, *, limit: int = 100) -> list[StepRun]:
    """Run history for a plan, newest first."""
    with _conn() as c:
        return [
            _row_to_step_run(r)
            for r in c.execute(
                "SELECT * FROM step_runs WHERE plan_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (plan_id, max(1, min(int(limit), 1000))),
            )
        ]


# ─── helpers ─────────────────────────────────────────────────────────


def _plan_exists(c: sqlite3.Connection, plan_id: int) -> bool:
    return c.execute("SELECT 1 FROM plans WHERE id = ?", (plan_id,)).fetchone() is not None


def _validate_plan_status(status: str) -> str:
    s = (status or "").strip().lower()
    if s not in PLAN_STATUSES:
        raise ValueError(f"plan status must be one of {PLAN_STATUSES}, got {status!r}")
    return s


def _validate_step_status(status: str) -> str:
    s = (status or "").strip().lower()
    if s not in STEP_STATUSES:
        raise ValueError(f"step status must be one of {STEP_STATUSES}, got {status!r}")
    return s


def _row_to_plan(row: sqlite3.Row) -> Plan:
    return Plan(
        id=row["id"], title=row["title"], goal=row["goal"], status=row["status"],
        meta=json.loads(row["meta"]),
        created_at=row["created_at"], updated_at=row["updated_at"], steps=[],
    )


def _row_to_step(row: sqlite3.Row) -> Step:
    return Step(
        id=row["id"], plan_id=row["plan_id"], seq=row["seq"], action=row["action"],
        kind=row["kind"], tool_name=row["tool_name"], status=row["status"],
        on_fail=row["on_fail"], on_done=row["on_done"], result=row["result"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_step_run(row: sqlite3.Row) -> StepRun:
    return StepRun(
        id=row["id"], step_id=row["step_id"], plan_id=row["plan_id"], seq=row["seq"],
        status=row["status"], output=row["output"], cost_usd=row["cost_usd"],
        error=row["error"], started_at=row["started_at"], finished_at=row["finished_at"],
    )
