"""§81 HoldingGoalRegistry + §82 goal-gap analysis.

Business/holding GOALS (growth · revenue · reliability · customer · security · cost · product ·
deploy) — DISTINCT from ``../planning/`` WORK-goals. Planning decomposes a task into ordered steps;
this tracks the OWNER'S business targets against real portfolio state. It MIRRORS
``../planning/storage.py`` (SQLite sidecar, fresh connection per call, WAL, schema bootstrap on
connect) into a SEPARATE ``goals.db`` — it never overloads planning's tables (the baseline warns
of exactly that trap).

CRITICAL (§81 + §0 #19): KAI NEVER invents a target. A target is stored ONLY when the owner supplies
both a value AND a source; no source → ``UNAVAILABLE``. A goal with no owner-set target is honestly
INCOMPLETE, not auto-filled. Goals hang off REAL registry entities — a company that is not a live
holding entity is rejected (fail-closed).

§82 gap analysis is DETERMINISTIC and CITED (the priorities.py / reconcile_plan style):
    goal → current_state → gap → evidence[] → blockers[] → recommended_actions[]
Every claim cites a source; nothing is generic business advice; unsupported → honest ``UNAVAILABLE``.
``current`` is read live from an INJECTABLE source (default: the holding registry) and is NEVER
stored on the goal — a stored number would go stale and read as invented. Sources are injectable so
the whole module is testable without a live DB (SQLite file only; no server).
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

UNAVAILABLE = "UNAVAILABLE"

# Lifecycle statuses (the ../planning/ approval-gate pattern: a fixed vocab + a validated setter).
GOAL_STATUSES = ("draft", "active", "achieved", "abandoned", "blocked")
# Descriptive dimension tags (§81 domains) — free label, never gates logic.
GOAL_DIMENSIONS = ("growth", "revenue", "reliability", "customer", "security", "cost",
                   "product", "deploy", "other")
# A metric's better direction. Revenue/customers are higher-is-better; cost/churn/latency/incidents
# are lower-is-better. Correctness, not speculation: a security/cost gap is the opposite sign.
GOAL_DIRECTIONS = ("increase", "decrease")

# backend/app/services/holding/goal_registry.py → parents[4] = repo root (same depth as planning).
_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_DB = _REPO_ROOT / "data" / "holding" / "goals.db"


def _db_path() -> Path:
    """Resolved lazily each call so a test can point ``KAI_GOALS_DB_PATH`` at a temp file without
    import-order gymnastics. Mirrors planning's sidecar location, separate file."""
    p = Path(os.environ.get("KAI_GOALS_DB_PATH", str(_DEFAULT_DB)))
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── data model ───────────────────────────────────────────────────────────────────────────────────


@dataclass
class Goal:
    id: int
    company: str                    # a REAL registry entity_id
    owner: str
    metric: str                     # what is measured, e.g. "monthly_recurring_revenue_usd"
    target: Any                     # owner-set value OR UNAVAILABLE (never invented)
    target_source: str              # provenance for the target, OR the reason it is UNAVAILABLE
    deadline: Optional[str] = None  # ISO date string or None
    status: str = "draft"
    dimension: str = "other"
    direction: str = "increase"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    def target_is_set(self) -> bool:
        return self.target != UNAVAILABLE

    def as_dict(self) -> dict:
        return {
            "id": self.id, "company": self.company, "owner": self.owner, "metric": self.metric,
            "target": self.target, "target_source": self.target_source, "deadline": self.deadline,
            "status": self.status, "dimension": self.dimension, "direction": self.direction,
            "target_is_set": self.target_is_set(),
            "created_at": self.created_at, "updated_at": self.updated_at,
        }


# ── the no-invention target gate (pure; §81 + §0 #19) ──────────────────────────────────────────────


def normalize_target(target: Any, target_source: Optional[str]) -> tuple[Any, str]:
    """The heart of §81's honesty rule. A target is REAL only when the owner supplies BOTH a value
    AND a source. Missing value → UNAVAILABLE ("no target on record"). Value but no source → REJECTED
    to UNAVAILABLE (KAI never invents a target, §0 #19). Returns (value_or_UNAVAILABLE, provenance)."""
    # a blank value, OR the literal sentinel "UNAVAILABLE" (case-insensitive), is "no target on record"
    # — this removes the collision between an owner-typed "UNAVAILABLE" and the no-target sentinel.
    empty = target is None or (isinstance(target, str)
                               and (not target.strip() or target.strip().upper() == UNAVAILABLE))
    if empty:
        return UNAVAILABLE, "no target on record — owner has not set one (§81)"
    src = (target_source or "").strip()
    if not src:
        return UNAVAILABLE, "target rejected — no source supplied; KAI never invents a target (§0 #19)"
    return target, f"owner-set · {src}"


# ── storage (mirrors ../planning/storage.py: WAL, fresh conn, schema-on-connect) ───────────────────


_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company       TEXT    NOT NULL,
    owner         TEXT    NOT NULL,
    metric        TEXT    NOT NULL,
    target        TEXT    NOT NULL,          -- JSON-encoded value, or the string "UNAVAILABLE"
    target_source TEXT    NOT NULL,
    deadline      TEXT,
    status        TEXT    NOT NULL DEFAULT 'draft',
    dimension     TEXT    NOT NULL DEFAULT 'other',
    direction     TEXT    NOT NULL DEFAULT 'increase',
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_goals_company ON goals(company);
CREATE INDEX IF NOT EXISTS idx_goals_status  ON goals(status);
"""


@contextlib.contextmanager
def _conn():
    c = sqlite3.connect(str(_db_path()), isolation_level=None)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(_SCHEMA)
        yield c
    finally:
        c.close()


def _default_entity_exists(company: str) -> bool:
    """Fail-open import, fail-CLOSED result: a company is valid only if it is a real registry entity.
    (Kept injectable so gap/goal logic is testable without importing the seed.)"""
    try:
        from app.services.holding import registry as reg
        return reg.get(company) is not None
    except Exception:      # noqa: BLE001 — registry unavailable → cannot vouch for the entity → reject
        return False


def _enc(v: Any) -> str:
    return json.dumps(v, default=str)


def _dec(s: str) -> Any:
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        return s


def _row_to_goal(r: sqlite3.Row) -> Goal:
    return Goal(
        id=r["id"], company=r["company"], owner=r["owner"], metric=r["metric"],
        target=_dec(r["target"]), target_source=r["target_source"], deadline=r["deadline"],
        status=r["status"], dimension=r["dimension"], direction=r["direction"],
        created_at=r["created_at"], updated_at=r["updated_at"],
    )


def add_goal(company: str, owner: str, metric: str, *, target: Any = None,
             target_source: Optional[str] = None, deadline: Optional[str] = None,
             dimension: str = "other", direction: str = "increase", status: str = "draft",
             entity_exists: Optional[Callable[[str], bool]] = None) -> Goal:
    """Register an owner goal against a REAL holding entity. The target passes through
    ``normalize_target`` — an unsourced or missing target is stored as UNAVAILABLE, never guessed.
    Rejects an unknown company (fail-closed) and an invalid status/dimension/direction."""
    company = (company or "").strip()
    owner = (owner or "").strip()
    metric = (metric or "").strip()
    if not company or not owner or not metric:
        raise ValueError("company, owner and metric are all required")
    check = entity_exists or _default_entity_exists
    if not check(company):
        raise ValueError(f"unknown holding entity {company!r} — goals hang off real registry entities (§81)")
    if status not in GOAL_STATUSES:
        raise ValueError(f"status must be one of {GOAL_STATUSES}")
    if dimension not in GOAL_DIMENSIONS:
        raise ValueError(f"dimension must be one of {GOAL_DIMENSIONS}")
    if direction not in GOAL_DIRECTIONS:
        raise ValueError(f"direction must be one of {GOAL_DIRECTIONS}")
    tgt, tsrc = normalize_target(target, target_source)
    now = _now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO goals (company, owner, metric, target, target_source, deadline, status, "
            "dimension, direction, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (company, owner, metric, _enc(tgt), tsrc, deadline, status, dimension, direction, now, now),
        )
        return Goal(id=cur.lastrowid, company=company, owner=owner, metric=metric, target=tgt,
                    target_source=tsrc, deadline=deadline, status=status, dimension=dimension,
                    direction=direction, created_at=now, updated_at=now)


def get_goal(goal_id: int) -> Optional[Goal]:
    with _conn() as c:
        r = c.execute("SELECT * FROM goals WHERE id = ?", (goal_id,)).fetchone()
        return _row_to_goal(r) if r else None


def list_goals(*, company: Optional[str] = None, status: Optional[str] = None,
               limit: int = 200) -> list[Goal]:
    sql, params = "SELECT * FROM goals", []
    where = []
    if company:
        where.append("company = ?"); params.append(company)
    if status:
        where.append("status = ?"); params.append(status)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id ASC LIMIT ?"
    params.append(max(1, min(int(limit), 1000)))
    with _conn() as c:
        return [_row_to_goal(r) for r in c.execute(sql, tuple(params))]


def set_target(goal_id: int, target: Any, target_source: Optional[str]) -> Goal:
    """The owner target gate. Re-runs ``normalize_target`` — a sourceless target is still rejected to
    UNAVAILABLE. Raises on unknown goal."""
    tgt, tsrc = normalize_target(target, target_source)
    now = _now()
    with _conn() as c:
        cur = c.execute("UPDATE goals SET target = ?, target_source = ?, updated_at = ? WHERE id = ?",
                        (_enc(tgt), tsrc, now, goal_id))
        if cur.rowcount == 0:
            raise ValueError(f"no goal with id {goal_id}")
    g = get_goal(goal_id)
    assert g is not None
    return g


def update_status(goal_id: int, status: str) -> Goal:
    """Validated status transition (the ../planning/ approval-gate pattern). Raises on unknown goal/status."""
    if status not in GOAL_STATUSES:
        raise ValueError(f"status must be one of {GOAL_STATUSES}")
    now = _now()
    with _conn() as c:
        cur = c.execute("UPDATE goals SET status = ?, updated_at = ? WHERE id = ?", (status, now, goal_id))
        if cur.rowcount == 0:
            raise ValueError(f"no goal with id {goal_id}")
    g = get_goal(goal_id)
    assert g is not None
    return g


# ── §82 gap analysis (deterministic + cited; injectable current-source) ─────────────────────────────


# Where a metric's CURRENT value can be read live from the holding registry. Only real fields are
# mapped; anything unmapped honestly has "no live source" (never a guess).
_METRIC_FIELD: dict[str, str] = {
    "revenue": "revenue_metrics", "revenue_metrics": "revenue_metrics",
    "customers": "customers", "expenses": "expense_metrics", "cost": "expense_metrics",
}


def _default_current_source(company: str, metric: str) -> tuple[Optional[Any], str]:
    """Read the CURRENT value for (company, metric) from the holding registry (the §14 twin read-path,
    which returns None for un-sourced money/customer fields). Returns (value_or_None, provenance)."""
    field = _METRIC_FIELD.get(metric)
    if not field:
        return None, f"no live source wired for metric '{metric}'"
    try:
        from app.services.holding import registry as reg
        return reg.report_value(company, field)
    except Exception:      # noqa: BLE001 — subsystem down → honest UNAVAILABLE, never a fabricated number
        return None, "registry read failed — current UNAVAILABLE"


def _as_number(v: Any) -> Optional[float]:
    """Parse a clean numeric value; PROSE (e.g. 'Pre-revenue — ...') returns None → honest UNAVAILABLE."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "").rstrip("%").strip()
        s = s[1:].strip() if s.startswith("$") else s
        try:
            return float(s)
        except ValueError:
            return None
    return None


def analyze_gap(goal: Any, *,
                current_source: Optional[Callable[[str, str], tuple[Optional[Any], str]]] = None) -> dict:
    """§82: deterministic, fully-cited gap analysis for ONE goal. ``current_source(company, metric)``
    → ``(value_or_None, provenance)`` is injectable (default: the holding registry), so this is
    testable without a DB. Output shape:
        {goal, metric, company, current_state, gap, evidence[], blockers[], recommended_actions[], verdict}
    Every evidence/action item cites a source. No generic advice. Missing target OR unsupported current
    → verdict UNAVAILABLE (never a computed-from-nothing number)."""
    g = goal.as_dict() if isinstance(goal, Goal) else dict(goal)
    company, metric = g.get("company", "?"), g.get("metric", "?")
    gid = g.get("id", "?")
    direction = g.get("direction", "increase")
    target = g.get("target", UNAVAILABLE)
    target_set = target != UNAVAILABLE
    src = current_source or _default_current_source

    evidence: list[dict] = []
    blockers: list[dict] = []
    actions: list[dict] = []

    # 1. target provenance (owner-set or the honest reason it is UNAVAILABLE) — always cited.
    evidence.append({"claim": f"target for {metric}",
                     "value": target if target_set else UNAVAILABLE,
                     "source": g.get("target_source", "no target on record")})
    if not target_set:
        blockers.append({"blocker": f"no owner-set target for '{metric}' on {company}",
                         "source": f"goal:{gid}.target — {g.get('target_source', '')}"})
        actions.append({"action": f"Owner: define a target for '{metric}' on {company} "
                                  f"(KAI will not invent one, §81/§0 #19)",
                        "source": f"goal:{gid}"})

    # 2. current value from the live source — cited, None → UNAVAILABLE (never guessed).
    cur_val, cur_prov = src(company, metric)
    evidence.append({"claim": f"current {metric}",
                     "value": cur_val if cur_val is not None else UNAVAILABLE,
                     "source": cur_prov})
    if cur_val is None:
        blockers.append({"blocker": f"current '{metric}' for {company} is UNAVAILABLE — no authoritative source",
                         "source": cur_prov})
        actions.append({"action": f"Wire an authoritative source for '{metric}' on {company} "
                                  f"(currently un-sourced / REQUIRES_OPERATOR_CONFIRMATION)",
                        "source": cur_prov})

    # 3. deterministic gap — computed ONLY when BOTH target and current are real numbers.
    cur_num = _as_number(cur_val)
    tgt_num = _as_number(target) if target_set else None
    current_state = {"metric": metric, "value": cur_val if cur_val is not None else UNAVAILABLE,
                     "numeric": cur_num, "source": cur_prov}

    if tgt_num is not None and cur_num is not None:
        raw = tgt_num - cur_num
        met = cur_num >= tgt_num if direction == "increase" else cur_num <= tgt_num
        # remaining move toward the target (0 when already met), signed for the metric's direction.
        remaining = 0.0 if met else abs(raw)
        pct = round(cur_num / tgt_num * 100.0, 2) if tgt_num else None
        gap = {"status": "MET" if met else "OPEN", "current": cur_num, "target": tgt_num,
               "direction": direction, "delta": round(raw, 6), "remaining_to_target": round(remaining, 6),
               "pct_of_target": pct,
               "source": f"computed: current={cur_prov} · target={g.get('target_source', '')}"}
        verdict = "MET" if met else "GAP"
        if not met:
            verb = "increase" if direction == "increase" else "reduce"
            actions.append({"action": f"{verb.capitalize()} {metric} on {company} by {remaining:g} "
                                      f"(current {cur_num:g} vs target {tgt_num:g})",
                            "source": f"current={cur_prov}; target={g.get('target_source', '')}"})
    else:
        # honestly UNAVAILABLE — say exactly why, cited; never a fabricated gap.
        if not target_set:
            why = "no owner-set target"
        elif tgt_num is None:
            why = f"target {target!r} is not numeric"
        elif cur_val is None:
            why = "current value UNAVAILABLE"
        else:
            why = f"current {cur_val!r} is not numeric"
        gap = {"status": UNAVAILABLE, "reason": why,
               "source": f"current={cur_prov} · target={g.get('target_source', '')}"}
        verdict = UNAVAILABLE

    return {
        "goal_id": gid, "company": company, "metric": metric, "dimension": g.get("dimension", "other"),
        "owner": g.get("owner"), "deadline": g.get("deadline"),
        "current_state": current_state, "gap": gap,
        "evidence": evidence, "blockers": blockers, "recommended_actions": actions,
        "verdict": verdict,
    }


def analyze_all(*, company: Optional[str] = None, status: Optional[str] = None,
                current_source: Optional[Callable[[str, str], tuple[Optional[Any], str]]] = None,
                goals: Optional[list] = None) -> list[dict]:
    """Gap analysis over many goals — from an injected ``goals`` list (DB-free) or, by default, the
    store. Deterministic order (by goal id). Convenience for the dashboard / weekly review (§83)."""
    src = goals if goals is not None else list_goals(company=company, status=status)
    return [analyze_gap(g, current_source=current_source) for g in src]


if __name__ == "__main__":      # runnable self-check (mirrors state_reconciler.py)
    from app.services.holding.test_goal_registry import run
    raise SystemExit(0 if run() else 1)
