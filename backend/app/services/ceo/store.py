from __future__ import annotations
import json, os, sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
CEO_DB_PATH = Path(os.environ.get("KAI_CEO_DB_PATH", str(_REPO_ROOT / "data" / "ceo" / "ceo.db")))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS company (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  goal TEXT NOT NULL, metric TEXT NOT NULL DEFAULT 'net_revenue',
  target_value REAL, target_deadline TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS kpi_snapshot (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS decision (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, kind TEXT NOT NULL,
  rationale TEXT NOT NULL, linked_plan_id INTEGER,
  is_catastrophic INTEGER NOT NULL DEFAULT 0, approved INTEGER NOT NULL DEFAULT 0,
  outcome TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS budget_ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, amount REAL NOT NULL,
  category TEXT NOT NULL, linked_decision_id INTEGER
);
CREATE TABLE IF NOT EXISTS org_member (
  id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT NOT NULL UNIQUE,
  capabilities TEXT NOT NULL DEFAULT '', reports_to TEXT,
  budget REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active'
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _conn():
    CEO_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(CEO_DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        c.executescript(_SCHEMA)
        yield c
        c.commit()
    finally:
        c.close()


def get_company() -> dict[str, Any] | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM company WHERE id = 1").fetchone()
        return dict(r) if r else None


def upsert_company(goal: str, *, metric: str = "net_revenue", target_value: float | None = None,
                   target_deadline: str | None = None, status: str = "active") -> dict[str, Any]:
    goal = (goal or "").strip()
    if not goal:
        raise ValueError("company goal cannot be empty")
    now = _now()
    with _conn() as c:
        exists = c.execute("SELECT created_at FROM company WHERE id = 1").fetchone()
        created = exists["created_at"] if exists else now
        c.execute(
            "INSERT INTO company (id, goal, metric, target_value, target_deadline, status, created_at, updated_at) "
            "VALUES (1, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET goal=excluded.goal, metric=excluded.metric, "
            "target_value=excluded.target_value, target_deadline=excluded.target_deadline, "
            "status=excluded.status, updated_at=excluded.updated_at",
            (goal, metric, target_value, target_deadline, status, created, now),
        )
    return get_company()  # type: ignore[return-value]


def record_snapshot(snapshot: dict[str, Any]) -> int:
    with _conn() as c:
        cur = c.execute("INSERT INTO kpi_snapshot (ts, data) VALUES (?, ?)",
                        (_now(), json.dumps(snapshot, default=str)))
        return int(cur.lastrowid)


def latest_snapshot() -> dict[str, Any] | None:
    with _conn() as c:
        r = c.execute("SELECT data FROM kpi_snapshot ORDER BY id DESC LIMIT 1").fetchone()
        return json.loads(r["data"]) if r else None


def record_decision(kind: str, rationale: str, *, linked_plan_id: int | None = None,
                    is_catastrophic: bool = False, approved: bool = False, outcome: str = "") -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO decision (ts, kind, rationale, linked_plan_id, is_catastrophic, approved, outcome) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (_now(), kind, rationale, linked_plan_id, int(is_catastrophic), int(approved), outcome),
        )
        return int(cur.lastrowid)


def list_decisions(limit: int = 50) -> list[dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM decision ORDER BY id DESC LIMIT ?",
                         (max(1, min(int(limit), 500)),)).fetchall()
        return [dict(r) for r in rows]


def add_ledger(amount: float, category: str, *, linked_decision_id: int | None = None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO budget_ledger (ts, amount, category, linked_decision_id) VALUES (?, ?, ?, ?)",
            (_now(), float(amount), category, linked_decision_id))
        return int(cur.lastrowid)


def period_spend(since_iso: str) -> float:
    with _conn() as c:
        r = c.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM budget_ledger WHERE ts >= ?",
                      (since_iso,)).fetchone()
        return float(r["s"] or 0.0)


def list_org() -> list[dict[str, Any]]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM org_member ORDER BY id").fetchall()]


def upsert_org_member(role: str, capabilities: str, *, reports_to: str | None = None,
                      budget: float = 0.0, status: str = "active") -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO org_member (role, capabilities, reports_to, budget, status) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(role) DO UPDATE SET capabilities=excluded.capabilities, "
            "reports_to=excluded.reports_to, budget=excluded.budget, status=excluded.status",
            (role, capabilities, reports_to, float(budget), status),
        )
        return int(cur.lastrowid or 0)
