# KAI Autonomous CEO — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CEO "executive cortex" above KAI's existing organs: one company goal, a scheduled heartbeat that reads KPIs and autonomously assigns initiatives (as Planning plans) inside a hard safety floor.

**Architecture:** New scoped subsystem `backend/app/services/ceo/` mirroring the DIGEST template (store + scheduler + admin router + system-prompt injection), flowing through the existing `@audited` governance decorator. Initiatives reuse the Planning store; KPIs reuse digest/audit sources; the floor (budget ceiling + catastrophic gate + kill switch) is enforced in `ceo/floor.py` independently of the LLM brain.

**Tech Stack:** Python 3.11+, FastAPI, SQLite (stdlib `sqlite3`), pytest. LLM via the existing `Router.complete(...)` failover ladder. No new third-party deps.

## Global Constraints

- Master scope flag: `KAI_SCOPE_CEO` (uses existing `is_scope_enabled` semantics: `KAI_SCOPE_CEO=1` truthy = 1/true/yes/on).
- Heartbeat gating: `KAI_CEO_HEARTBEAT_ENABLED=1` to arm the scheduler; `KAI_CEO_DRY_RUN` defaults to `1` (decide+log, execute nothing).
- Floor env (operator-set, all read at call time): `KAI_CEO_BUDGET_CEILING` (float USD, default `0` = block all spend), `KAI_CEO_PERIOD` (`weekly` default), `KAI_CEO_CATASTROPHIC_USD` (float, default `50`), `KAI_CEO_MASS_SEND_N` (int, default `25`), `KAI_CEO_CADENCE` (`daily` default), `KAI_CEO_HEARTBEAT_HOUR_UTC` (int, default `14`).
- Store path: `KAI_CEO_DB_PATH` env, default `data/ceo/ceo.db`. Create parent dir on import (mirror digest).
- Audit: every mutating action goes through `@audited(scope="ceo.<action>", destructive=...)`; log path is the existing `data/governance/audit.jsonl`.
- North-star metric: `net_revenue` (company singleton). Floor classification is re-derived in `floor.py` from action shape — the brain's self-assessment is never trusted for gating.
- Tests live in `backend/tests/`, run from `backend/` via `pytest`. Each suite isolates its DB via `monkeypatch.setattr(<module>, "CEO_DB_PATH", tmp_path/"ceo.db")` and sets scope env via `monkeypatch.setenv`.
- Decision kinds (string enum): `reprioritize | new_initiative | assignment | spend | escalation`.
- Floor verdicts (string enum): `in_policy | catastrophic | over_ceiling`.

---

### Task 1: `ceo/store.py` — persistence

**Files:**
- Create: `backend/app/services/ceo/__init__.py`
- Create: `backend/app/services/ceo/store.py`
- Test: `backend/tests/test_ceo_store.py`

**Interfaces:**
- Consumes: nothing (stdlib `sqlite3`, `json`, `os`, `pathlib`, `datetime`).
- Produces:
  - `CEO_DB_PATH: Path`
  - `get_company() -> dict | None`
  - `upsert_company(goal: str, *, metric: str = "net_revenue", target_value: float | None = None, target_deadline: str | None = None, status: str = "active") -> dict` (singleton, id=1)
  - `record_snapshot(snapshot: dict) -> int` (returns row id)
  - `latest_snapshot() -> dict | None`
  - `record_decision(kind: str, rationale: str, *, linked_plan_id: int | None = None, is_catastrophic: bool = False, approved: bool = False, outcome: str = "") -> int`
  - `list_decisions(limit: int = 50) -> list[dict]`
  - `add_ledger(amount: float, category: str, *, linked_decision_id: int | None = None) -> int`
  - `period_spend(since_iso: str) -> float`
  - `list_org() -> list[dict]`; `upsert_org_member(role: str, capabilities: str, *, reports_to: str | None = None, budget: float = 0.0, status: str = "active") -> int`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ceo_store.py
import importlib
import pytest
from app.services.ceo import store as st


@pytest.fixture(autouse=True)
def _isolated_ceo_db(tmp_path, monkeypatch):
    db = tmp_path / "ceo.db"
    monkeypatch.setattr(st, "CEO_DB_PATH", db)
    yield db


def test_company_is_singleton():
    assert st.get_company() is None
    a = st.upsert_company("Grow WheellsVerse net revenue", target_value=100000.0)
    assert a["id"] == 1
    assert a["metric"] == "net_revenue"
    b = st.upsert_company("Grow WheellsVerse net revenue to $1M")
    assert b["id"] == 1               # still singleton
    assert st.get_company()["goal"].endswith("$1M")


def test_decisions_and_ledger_roundtrip():
    did = st.record_decision("new_initiative", "Launch KDP bundle", linked_plan_id=7)
    assert did > 0
    rows = st.list_decisions()
    assert rows[0]["kind"] == "new_initiative"
    assert rows[0]["linked_plan_id"] == 7
    st.add_ledger(12.50, "ads", linked_decision_id=did)
    st.add_ledger(7.25, "ads")
    assert st.period_spend("1970-01-01T00:00:00+00:00") == pytest.approx(19.75)


def test_snapshot_roundtrip():
    rid = st.record_snapshot({"revenue": 0, "spend_period": 0, "alerts": 2})
    assert rid > 0
    assert st.latest_snapshot()["alerts"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ceo_store.py -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ceo'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/ceo/__init__.py
"""KAI CEO subsystem — executive cortex above the existing organs."""
```

```python
# backend/app/services/ceo/store.py
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
        cur = c.execute("INSERT INTO budget_ledger (ts, amount, category, linked_decision_id) VALUES (?, ?, ?, ?)",
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ceo_store.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ceo/__init__.py backend/app/services/ceo/store.py backend/tests/test_ceo_store.py
git commit -m "feat(ceo): store — company singleton, kpi snapshots, decisions, budget ledger, org chart"
```

---

### Task 2: `ceo/floor.py` — the safety floor (most-tested unit)

**Files:**
- Create: `backend/app/services/ceo/floor.py`
- Test: `backend/tests/test_ceo_floor.py`

**Interfaces:**
- Consumes: `ceo.store.period_spend`, `ceo.store.CEO_DB_PATH` (for period window).
- Produces:
  - `CATASTROPHIC_KINDS: frozenset[str]` = `{"money_transfer", "data_deletion", "prod_deploy", "secret_rotation", "mass_send", "new_account"}`
  - `is_catastrophic(action: dict) -> bool`
  - `within_ceiling(amount: float) -> bool`
  - `is_killed() -> bool`
  - `classify(action: dict) -> str` (`in_policy | catastrophic | over_ceiling`)
- An `action` dict shape: `{"type": str, "kind": str, "amount": float, "recipients": int}` (all optional except `type`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ceo_floor.py
import pytest
from app.services.ceo import floor as fl
from app.services.ceo import store as st


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CEO_DB_PATH", tmp_path / "ceo.db")
    monkeypatch.setenv("KAI_CEO_BUDGET_CEILING", "100")
    monkeypatch.setenv("KAI_CEO_PERIOD", "weekly")
    monkeypatch.setenv("KAI_CEO_CATASTROPHIC_USD", "50")
    monkeypatch.setenv("KAI_CEO_MASS_SEND_N", "25")
    monkeypatch.delenv("KAI_CEO_KILLED", raising=False)
    yield


def test_catastrophic_kinds_flagged():
    assert fl.is_catastrophic({"type": "deploy", "kind": "prod_deploy"})
    assert fl.is_catastrophic({"type": "money", "kind": "money_transfer", "amount": 80})  # > 50
    assert not fl.is_catastrophic({"type": "money", "kind": "money_transfer", "amount": 10})
    assert fl.is_catastrophic({"type": "email", "kind": "mass_send", "recipients": 100})
    assert not fl.is_catastrophic({"type": "chat", "kind": "assignment"})


def test_ceiling_blocks_over_budget():
    assert fl.within_ceiling(40)
    st.add_ledger(80, "ads")
    assert not fl.within_ceiling(40)   # 80 + 40 > 100
    assert fl.within_ceiling(10)       # 80 + 10 <= 100


def test_classify_precedence():
    assert fl.classify({"type": "chat", "kind": "assignment"}) == "in_policy"
    assert fl.classify({"type": "deploy", "kind": "prod_deploy"}) == "catastrophic"
    st.add_ledger(95, "ads")
    assert fl.classify({"type": "spend", "kind": "spend", "amount": 20}) == "over_ceiling"


def test_kill_switch(monkeypatch):
    monkeypatch.setenv("KAI_CEO_KILLED", "1")
    assert fl.is_killed()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ceo_floor.py -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ceo.floor'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/ceo/floor.py
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from . import store

CATASTROPHIC_KINDS = frozenset(
    {"money_transfer", "data_deletion", "prod_deploy", "secret_rotation", "mass_send", "new_account"}
)

def _f(env: str, default: float) -> float:
    try:
        return float(os.environ.get(env, default))
    except (TypeError, ValueError):
        return default

def is_killed() -> bool:
    v = (os.environ.get("KAI_CEO_KILLED") or "").strip().lower()
    return v in {"1", "true", "yes", "on"}

def is_catastrophic(action: dict) -> bool:
    kind = (action.get("kind") or "").strip()
    if kind not in CATASTROPHIC_KINDS:
        return False
    if kind == "money_transfer":
        return float(action.get("amount", 0) or 0) > _f("KAI_CEO_CATASTROPHIC_USD", 50)
    if kind == "mass_send":
        return int(action.get("recipients", 0) or 0) > int(_f("KAI_CEO_MASS_SEND_N", 25))
    return True  # prod_deploy / secret_rotation / data_deletion / new_account always escalate

def _period_start() -> str:
    period = (os.environ.get("KAI_CEO_PERIOD") or "weekly").lower()
    days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period, 7)
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

def within_ceiling(amount: float) -> bool:
    ceiling = _f("KAI_CEO_BUDGET_CEILING", 0)
    spent = store.period_spend(_period_start())
    return (spent + float(amount or 0)) <= ceiling

def classify(action: dict) -> str:
    if is_catastrophic(action):
        return "catastrophic"
    amount = float(action.get("amount", 0) or 0)
    if amount > 0 and not within_ceiling(amount):
        return "over_ceiling"
    return "in_policy"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ceo_floor.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ceo/floor.py backend/tests/test_ceo_floor.py
git commit -m "feat(ceo): safety floor — catastrophic gate, budget ceiling, kill switch (floor-independent of the brain)"
```

---

### Task 3: `ceo/kpis.py` — sensing (fail-soft)

**Files:**
- Create: `backend/app/services/ceo/kpis.py`
- Test: `backend/tests/test_ceo_kpis.py`

**Interfaces:**
- Consumes: `app.services.planning.storage.list_plans` (status counts), `ceo.store.record_snapshot`. Other sources (revenue, security) are pulled via small private helpers that each fail-soft to `None`/`0`.
- Produces: `build_snapshot() -> dict` with keys `{revenue, spend_period, security_score, alerts, plans_active, plans_total, ts}`, and persists it via `store.record_snapshot`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ceo_kpis.py
import pytest
from app.services.ceo import kpis, store as st


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CEO_DB_PATH", tmp_path / "ceo.db")
    yield


def test_build_snapshot_failsoft(monkeypatch):
    # Force every source to error → snapshot still returns with safe defaults.
    monkeypatch.setattr(kpis, "_plan_counts", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(kpis, "_revenue", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(kpis, "_security_score", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(kpis, "_alerts", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    snap = kpis.build_snapshot()
    assert snap["plans_active"] == 0
    assert snap["revenue"] == 0
    assert snap["security_score"] is None
    assert "ts" in snap
    assert st.latest_snapshot() is not None   # persisted


def test_build_snapshot_uses_sources(monkeypatch):
    monkeypatch.setattr(kpis, "_plan_counts", lambda: (3, 9))
    monkeypatch.setattr(kpis, "_revenue", lambda: 1234.5)
    monkeypatch.setattr(kpis, "_security_score", lambda: 72)
    monkeypatch.setattr(kpis, "_alerts", lambda: 2)
    snap = kpis.build_snapshot()
    assert snap == {**snap, "plans_active": 3, "plans_total": 9, "revenue": 1234.5,
                    "security_score": 72, "alerts": 2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ceo_kpis.py -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ceo.kpis'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/ceo/kpis.py
from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Any
from . import store

logger = logging.getLogger(__name__)

def _safe(fn, default):
    try:
        return fn()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("ceo.kpis: source %s failed: %s", getattr(fn, "__name__", fn), e)
        return default

def _plan_counts() -> tuple[int, int]:
    from app.services.planning import storage
    plans = storage.list_plans(limit=500)
    active = sum(1 for p in plans if p.status in ("approved", "executing"))
    return active, len(plans)

def _revenue() -> float:
    # Placeholder source: revenue aggregation is wired to the real billing
    # surface in a later task. Until then this returns 0 (fail-soft default),
    # which the brain reads as "no revenue signal yet".
    return 0.0

def _security_score() -> int | None:
    from app.services.security import scoring  # type: ignore
    return scoring.latest_overall()  # returns int|None

def _alerts() -> int:
    from app.services.supreme import storage as sup  # type: ignore
    latest = sup.latest_proposal()
    return len((latest or {}).get("findings", []))

def build_snapshot() -> dict[str, Any]:
    active, total = _safe(_plan_counts, (0, 0))
    snap = {
        "revenue": _safe(_revenue, 0.0),
        "spend_period": 0.0,
        "security_score": _safe(_security_score, None),
        "alerts": _safe(_alerts, 0),
        "plans_active": active,
        "plans_total": total,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    store.record_snapshot(snap)
    return snap
```

> NOTE: `_revenue`, `_security_score`, `_alerts` import modules that may not expose these exact helpers yet. They are wrapped in `_safe(...)`, so a missing helper fails soft to the default and the snapshot still builds. Wiring them to real billing/security/supreme accessors is a follow-up (logged in Task 11), not a blocker.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ceo_kpis.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ceo/kpis.py backend/tests/test_ceo_kpis.py
git commit -m "feat(ceo): kpis — fail-soft system snapshot (plans/revenue/security/alerts), persisted"
```

---

### Task 4: `ceo/brain.py` — executive cognition

**Files:**
- Create: `backend/app/services/ceo/brain.py`
- Test: `backend/tests/test_ceo_brain.py`

**Interfaces:**
- Consumes: a `router` object exposing `.complete(user_id=..., messages=..., system=..., max_tokens=..., temperature=..., prefer_local=...) -> result` with `result.content` (the existing `Router`); `ceo.store.get_company`.
- Produces: `decide(*, router, user_id, company: dict, snapshot: dict, org: list[dict]) -> dict` returning a validated `DecisionSet`: `{"initiatives": [{"title": str, "rationale": str, "expected_impact": str}], "reprioritize": [str], "escalations": [str]}`. On malformed/empty LLM output → returns an empty-but-valid DecisionSet (fail-soft).
- `EXEC_SYSTEM: str` — the executive prompt.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ceo_brain.py
import json, uuid
from types import SimpleNamespace
from unittest.mock import MagicMock
from app.services.ceo import brain


def _router(content):
    r = MagicMock()
    r.complete.return_value = SimpleNamespace(content=content)
    return r


def test_decide_parses_json():
    payload = {"initiatives": [{"title": "Launch KDP bundle", "rationale": "low CAC",
                                "expected_impact": "+$2k/mo"}],
               "reprioritize": ["pause cold email"], "escalations": []}
    out = brain.decide(router=_router(json.dumps(payload)), user_id=uuid.uuid4(),
                       company={"goal": "grow revenue"}, snapshot={"revenue": 0}, org=[])
    assert out["initiatives"][0]["title"] == "Launch KDP bundle"
    assert out["reprioritize"] == ["pause cold email"]


def test_decide_failsoft_on_garbage():
    out = brain.decide(router=_router("not json at all"), user_id=uuid.uuid4(),
                       company={"goal": "grow revenue"}, snapshot={}, org=[])
    assert out == {"initiatives": [], "reprioritize": [], "escalations": []}


def test_decide_extracts_fenced_json():
    payload = {"initiatives": [], "reprioritize": [], "escalations": ["budget ceiling near"]}
    fenced = "Here is my plan:\n```json\n" + json.dumps(payload) + "\n```\n"
    out = brain.decide(router=_router(fenced), user_id=uuid.uuid4(),
                       company={"goal": "x"}, snapshot={}, org=[])
    assert out["escalations"] == ["budget ceiling near"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ceo_brain.py -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ceo.brain'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/ceo/brain.py
from __future__ import annotations
import json, logging, re
from typing import Any
logger = logging.getLogger(__name__)

EXEC_SYSTEM = (
    "You are KAI operating as the autonomous CEO of WheellsVerse. Your single "
    "north-star is growing NET REVENUE. Given the company goal, the latest KPI "
    "snapshot, and your org/plan status, decide what to do THIS cycle. Reply with "
    "ONLY a JSON object of the form:\n"
    '{"initiatives":[{"title":"...","rationale":"...","expected_impact":"..."}],'
    '"reprioritize":["..."],"escalations":["..."]}\n'
    "Each initiative must trace to the company goal. Keep it to the few highest-"
    "leverage moves. Do not include commentary outside the JSON."
)

_EMPTY = {"initiatives": [], "reprioritize": [], "escalations": []}

def _extract_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = m.group(1) if m else text
    if not m:
        s, e = candidate.find("{"), candidate.rfind("}")
        if s == -1 or e == -1 or e < s:
            return None
        candidate = candidate[s : e + 1]
    try:
        obj = json.loads(candidate)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None

def _coerce(obj: dict[str, Any] | None) -> dict[str, Any]:
    if not obj:
        return dict(_EMPTY)
    inits = []
    for it in obj.get("initiatives", []) or []:
        if isinstance(it, dict) and (it.get("title") or "").strip():
            inits.append({"title": str(it["title"]).strip(),
                          "rationale": str(it.get("rationale", "")).strip(),
                          "expected_impact": str(it.get("expected_impact", "")).strip()})
    repr_ = [str(x).strip() for x in (obj.get("reprioritize", []) or []) if str(x).strip()]
    esc = [str(x).strip() for x in (obj.get("escalations", []) or []) if str(x).strip()]
    return {"initiatives": inits, "reprioritize": repr_, "escalations": esc}

def decide(*, router, user_id, company: dict, snapshot: dict, org: list[dict]) -> dict[str, Any]:
    user_msg = (
        "COMPANY GOAL:\n" + json.dumps(company, default=str)
        + "\n\nKPI SNAPSHOT:\n" + json.dumps(snapshot, default=str)
        + "\n\nORG / WORKFORCE:\n" + json.dumps(org, default=str)
        + "\n\nDecide this cycle. JSON only."
    )
    try:
        result = router.complete(user_id=user_id, messages=[{"role": "user", "content": user_msg}],
                                 system=EXEC_SYSTEM, max_tokens=900, temperature=0.4)
        content = getattr(result, "content", "") or ""
    except Exception as e:
        logger.warning("ceo.brain: router failed: %s", e)
        return dict(_EMPTY)
    return _coerce(_extract_json(content))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ceo_brain.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ceo/brain.py backend/tests/test_ceo_brain.py
git commit -m "feat(ceo): brain — executive decision LLM call with robust JSON extraction + fail-soft"
```

---

### Task 5: `ceo/executor.py` — acting through the floor

**Files:**
- Create: `backend/app/services/ceo/executor.py`
- Test: `backend/tests/test_ceo_executor.py`

**Interfaces:**
- Consumes: `ceo.floor.classify`, `ceo.store.record_decision`, `app.services.planning.storage.create_plan`.
- Produces: `apply(decision_set: dict, *, dry_run: bool = True) -> dict` returning `{"created": [plan_id...], "queued": [{"title", "verdict"}...], "decisions": int}`. In-policy initiatives → `create_plan(...)` (status `draft`, so the operator still approves the steps) + `record_decision(... linked_plan_id=...)`. Catastrophic/over_ceiling → recorded as `escalation` decisions, NOT executed. `dry_run=True` → records decisions but creates NO plans.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ceo_executor.py
import pytest
from app.services.ceo import executor, store as st
from app.services.planning import storage as pl


@pytest.fixture(autouse=True)
def _dbs(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CEO_DB_PATH", tmp_path / "ceo.db")
    monkeypatch.setattr(pl, "PLANNING_DB_PATH", tmp_path / "planning.db")
    monkeypatch.setenv("KAI_CEO_BUDGET_CEILING", "100")
    monkeypatch.setenv("KAI_CEO_CATASTROPHIC_USD", "50")
    yield


def test_inpolicy_creates_plan_when_live():
    ds = {"initiatives": [{"title": "Launch KDP bundle", "rationale": "low CAC",
                           "expected_impact": "+$2k"}], "reprioritize": [], "escalations": []}
    out = executor.apply(ds, dry_run=False)
    assert len(out["created"]) == 1
    plan = pl.get_plan(out["created"][0])
    assert plan.status == "draft"           # operator still approves the steps
    assert "Launch KDP bundle" in plan.title


def test_dry_run_creates_nothing_but_records():
    ds = {"initiatives": [{"title": "X", "rationale": "y", "expected_impact": "z"}],
          "reprioritize": [], "escalations": []}
    out = executor.apply(ds, dry_run=True)
    assert out["created"] == []
    assert out["decisions"] >= 1
    assert pl.list_plans() == []


def test_escalations_recorded_not_executed():
    ds = {"initiatives": [], "reprioritize": [], "escalations": ["rotate prod secret"]}
    out = executor.apply(ds, dry_run=False)
    assert out["created"] == []
    kinds = [d["kind"] for d in st.list_decisions()]
    assert "escalation" in kinds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ceo_executor.py -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ceo.executor'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/ceo/executor.py
from __future__ import annotations
import logging
from typing import Any
from . import store, floor
logger = logging.getLogger(__name__)

def apply(decision_set: dict[str, Any], *, dry_run: bool = True) -> dict[str, Any]:
    created: list[int] = []
    queued: list[dict[str, Any]] = []
    decisions = 0

    for init in decision_set.get("initiatives", []):
        title = (init.get("title") or "").strip()
        if not title:
            continue
        # Initiatives are chat/assignment work → in_policy unless they declare a
        # catastrophic kind or a spend amount. The floor re-derives this; the
        # brain's opinion is never trusted.
        action = {"type": "initiative", "kind": init.get("kind", "assignment"),
                  "amount": float(init.get("amount", 0) or 0)}
        verdict = floor.classify(action)
        rationale = (init.get("rationale") or "") + (
            f" | expected: {init.get('expected_impact')}" if init.get("expected_impact") else "")
        if verdict != "in_policy":
            store.record_decision("escalation", f"{title}: {rationale}", is_catastrophic=(verdict == "catastrophic"))
            queued.append({"title": title, "verdict": verdict})
            decisions += 1
            continue
        if dry_run:
            store.record_decision("new_initiative", f"[dry-run] {title}: {rationale}")
            decisions += 1
            continue
        try:
            from app.services.planning import storage as pl
            plan = pl.create_plan(title[:120], f"{title}. {rationale}".strip(), status="draft",
                                  meta={"source": "ceo", "expected_impact": init.get("expected_impact", "")})
            store.record_decision("new_initiative", f"{title}: {rationale}", linked_plan_id=plan.id)
            created.append(plan.id)
            decisions += 1
        except Exception as e:
            logger.warning("ceo.executor: create_plan failed for %r: %s", title, e)
            store.record_decision("new_initiative", f"FAILED {title}: {e}", outcome="error")
            decisions += 1

    for note in decision_set.get("reprioritize", []):
        store.record_decision("reprioritize", str(note)); decisions += 1
    for esc in decision_set.get("escalations", []):
        store.record_decision("escalation", str(esc)); decisions += 1

    return {"created": created, "queued": queued, "decisions": decisions}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ceo_executor.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ceo/executor.py backend/tests/test_ceo_executor.py
git commit -m "feat(ceo): executor — in-policy initiatives become draft plans; catastrophic/over-ceiling escalate; dry-run safe"
```

---

### Task 6: `ceo/heartbeat.py` — the autonomy engine + scheduler

**Files:**
- Create: `backend/app/services/ceo/heartbeat.py`
- Test: `backend/tests/test_ceo_heartbeat.py`

**Interfaces:**
- Consumes: `ceo.kpis.build_snapshot`, `ceo.brain.decide`, `ceo.executor.apply`, `ceo.store.get_company/list_org`, `ceo.floor.is_killed`, `governance.is_scope_enabled`.
- Produces:
  - `run_cycle(*, router, user_id, dry_run: bool | None = None) -> dict` — one beat: sense→think→act. Returns `{"ran": bool, "reason": str, "result": dict|None}`. Skips (ran=False) if scope off, killed, or no company goal.
  - `start() -> bool` / `stop() -> None` (scheduler thread, mirrors digest; gated by `KAI_CEO_HEARTBEAT_ENABLED` + per-tick `is_scope_enabled("ceo")` + `is_killed()`).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ceo_heartbeat.py
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock
import json, pytest
from app.services.ceo import heartbeat, store as st
from app.services.planning import storage as pl


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CEO_DB_PATH", tmp_path / "ceo.db")
    monkeypatch.setattr(pl, "PLANNING_DB_PATH", tmp_path / "planning.db")
    monkeypatch.setenv("KAI_SCOPE_CEO", "1")
    monkeypatch.setenv("KAI_CEO_BUDGET_CEILING", "100")
    monkeypatch.delenv("KAI_CEO_KILLED", raising=False)
    yield


def _router(payload):
    r = MagicMock()
    r.complete.return_value = SimpleNamespace(content=json.dumps(payload))
    return r


def test_cycle_skips_without_company():
    out = heartbeat.run_cycle(router=_router({}), user_id=uuid.uuid4(), dry_run=True)
    assert out["ran"] is False
    assert "company" in out["reason"]


def test_cycle_runs_dry_then_live():
    st.upsert_company("Grow net revenue")
    payload = {"initiatives": [{"title": "Launch KDP bundle", "rationale": "low CAC",
                                "expected_impact": "+$2k"}], "reprioritize": [], "escalations": []}
    dry = heartbeat.run_cycle(router=_router(payload), user_id=uuid.uuid4(), dry_run=True)
    assert dry["ran"] is True and dry["result"]["created"] == []
    live = heartbeat.run_cycle(router=_router(payload), user_id=uuid.uuid4(), dry_run=False)
    assert len(live["result"]["created"]) == 1


def test_cycle_blocked_by_kill(monkeypatch):
    st.upsert_company("Grow net revenue")
    monkeypatch.setenv("KAI_CEO_KILLED", "1")
    out = heartbeat.run_cycle(router=_router({}), user_id=uuid.uuid4(), dry_run=False)
    assert out["ran"] is False and "kill" in out["reason"].lower()


def test_cycle_blocked_by_scope(monkeypatch):
    st.upsert_company("Grow net revenue")
    monkeypatch.delenv("KAI_SCOPE_CEO", raising=False)
    out = heartbeat.run_cycle(router=_router({}), user_id=uuid.uuid4(), dry_run=False)
    assert out["ran"] is False and "scope" in out["reason"].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ceo_heartbeat.py -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ceo.heartbeat'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/ceo/heartbeat.py
from __future__ import annotations
import logging, os, threading
from datetime import datetime, timezone
from . import store, kpis, brain, executor, floor
logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop: threading.Event | None = None
_POLL = 300  # seconds

def _dry_default() -> bool:
    v = (os.environ.get("KAI_CEO_DRY_RUN", "1") or "1").strip().lower()
    return v in {"1", "true", "yes", "on"}

def _scope_on() -> bool:
    from app.services.governance import is_scope_enabled
    return is_scope_enabled("ceo")

def run_cycle(*, router, user_id, dry_run: bool | None = None) -> dict:
    if not _scope_on():
        return {"ran": False, "reason": "scope KAI_SCOPE_CEO not enabled", "result": None}
    if floor.is_killed():
        return {"ran": False, "reason": "kill switch active (KAI_CEO_KILLED)", "result": None}
    company = store.get_company()
    if not company:
        return {"ran": False, "reason": "no company goal set", "result": None}
    if dry_run is None:
        dry_run = _dry_default()
    snapshot = kpis.build_snapshot()
    ds = brain.decide(router=router, user_id=user_id, company=company,
                      snapshot=snapshot, org=store.list_org())
    result = executor.apply(ds, dry_run=dry_run)
    logger.info("ceo: cycle ran (dry=%s) created=%d decisions=%d",
                dry_run, len(result["created"]), result["decisions"])
    return {"ran": True, "reason": "ok", "result": result}

# ── scheduler (mirrors digest) ─────────────────────────────────
def _enabled() -> bool:
    v = (os.environ.get("KAI_CEO_HEARTBEAT_ENABLED") or "").strip().lower()
    return v in {"1", "true", "yes", "on"}

def _hour() -> int:
    try:
        return int(os.environ.get("KAI_CEO_HEARTBEAT_HOUR_UTC", "14"))
    except ValueError:
        return 14

def _loop(router_factory) -> None:
    import uuid as _uuid
    last_day: str | None = None
    while _stop is not None and not _stop.is_set():
        now = datetime.now(timezone.utc)
        key = now.strftime("%Y%m%d")
        if now.hour == _hour() and key != last_day and _scope_on() and not floor.is_killed():
            try:
                router, user_id = router_factory()
                run_cycle(router=router, user_id=user_id)
                last_day = key
            except Exception as e:  # pragma: no cover
                logger.exception("ceo: scheduled cycle crashed: %s", e)
        if _stop is not None and _stop.wait(timeout=_POLL):
            break

def start(router_factory=None) -> bool:
    global _thread, _stop
    if not _enabled():
        logger.info("ceo: scheduler not started (KAI_CEO_HEARTBEAT_ENABLED not set)")
        return False
    if _thread is not None and _thread.is_alive():
        return False
    if router_factory is None:
        logger.info("ceo: no router_factory provided; scheduler idle")
        return False
    _stop = threading.Event()
    _thread = threading.Thread(target=_loop, args=(router_factory,), name="kai-ceo", daemon=True)
    _thread.start()
    logger.info("ceo: scheduler started (hour=%d UTC, dry=%s)", _hour(), _dry_default())
    return True

def stop() -> None:
    global _thread, _stop
    if _stop is not None:
        _stop.set()
    _thread = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ceo_heartbeat.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ceo/heartbeat.py backend/tests/test_ceo_heartbeat.py
git commit -m "feat(ceo): heartbeat — sense→think→act cycle + daily scheduler (scope+kill re-checked per tick, dry-run default)"
```

---

### Task 7: `routers/admin_ceo.py` — operator board + main.py wiring

**Files:**
- Create: `backend/app/routers/admin_ceo.py`
- Modify: `backend/app/main.py` (add `admin_ceo` to the router import line ~15; add `app.include_router(admin_ceo.router)` near line 196; add startup/shutdown hooks like the digest block at ~87-100)
- Test: `backend/tests/test_ceo_router.py`

**Interfaces:**
- Consumes: `require_admin_token` dep (same import as `admin_digest.py`), `ceo.store`, `ceo.heartbeat.run_cycle`, the app's router/session builders (copy `_build_router`/session pattern from `admin_digest.py`).
- Produces endpoints under prefix `/admin/ceo`: `GET /` (board: company+latest snapshot+recent decisions), `POST /company` (set goal — audited `ceo.set_goal`, destructive), `POST /run` (manual beat — audited `ceo.run`, destructive), `GET /decisions`, `POST /kill` (sets a runtime kill flag), `GET /kill` (status).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ceo_router.py
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.services.ceo import store as st

H = {"X-Admin-Token": "test-admin-token"}  # conftest configures the accepted token


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CEO_DB_PATH", tmp_path / "ceo.db")
    monkeypatch.setenv("KAI_SCOPE_CEO", "1")
    yield


def test_board_empty_then_set_goal():
    c = TestClient(app)
    r = c.get("/admin/ceo/", headers=H)
    assert r.status_code == 200
    assert r.json()["company"] is None
    r = c.post("/admin/ceo/company", json={"goal": "Grow net revenue", "approved": True}, headers=H)
    assert r.status_code == 200
    assert c.get("/admin/ceo/", headers=H).json()["company"]["goal"] == "Grow net revenue"


def test_set_goal_requires_approval(monkeypatch):
    c = TestClient(app)
    r = c.post("/admin/ceo/company", json={"goal": "x", "approved": False}, headers=H)
    assert r.status_code == 409  # PendingApproval


def test_kill_switch_endpoint():
    c = TestClient(app)
    assert c.post("/admin/ceo/kill", json={}, headers=H).status_code == 200
    assert c.get("/admin/ceo/kill", headers=H).json()["killed"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ceo_router.py -x`
Expected: FAIL — `ImportError`/404 (router not registered)

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/routers/admin_ceo.py
from __future__ import annotations
import os
from typing import Any
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.routers.deps import require_admin_token   # match admin_digest.py's import
from app.services.governance import is_scope_enabled
from app.services.governance.actions import audited, ScopeDenied, PendingApproval
from app.services.ceo import store, floor

router = APIRouter(prefix="/admin/ceo", tags=["admin"], dependencies=[Depends(require_admin_token)])

class GoalBody(BaseModel):
    goal: str
    target_value: float | None = None
    target_deadline: str | None = None
    approved: bool = False

@audited(scope="ceo.set_goal", destructive=True)
def _set_goal(*, goal: str, target_value: float | None, target_deadline: str | None) -> dict:
    return store.upsert_company(goal, target_value=target_value, target_deadline=target_deadline)

@router.get("/")
def board() -> dict[str, Any]:
    return {"company": store.get_company(), "snapshot": store.latest_snapshot(),
            "decisions": store.list_decisions(limit=20), "org": store.list_org(),
            "killed": floor.is_killed(), "scope_on": is_scope_enabled("ceo")}

@router.post("/company")
def set_company(body: GoalBody):
    try:
        return _set_goal(goal=body.goal, target_value=body.target_value,
                         target_deadline=body.target_deadline, approved=body.approved)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/decisions")
def decisions(limit: int = 50):
    return {"decisions": store.list_decisions(limit=limit)}

@router.post("/kill")
def kill():
    os.environ["KAI_CEO_KILLED"] = "1"
    return {"killed": True}

@router.get("/kill")
def kill_status():
    return {"killed": floor.is_killed()}
```

> NOTE: confirm the admin-token dependency import path by matching the top of `backend/app/routers/admin_digest.py` (it may be `from app.routers.deps import require_admin_token` or a local helper). Use whatever that file uses. The `/run` endpoint (manual heartbeat) is added in the same file once the router/session builder pattern is copied from `admin_digest.py::digest_run`; its test mirrors `test_board_empty_then_set_goal` using a monkeypatched `heartbeat.run_cycle`.

main.py edits (mirror the digest block exactly):
```python
# line ~15 import list — add admin_ceo
from app.routers import (..., admin_ceo, admin_digest, ...)
# near line 196 with the other includes
app.include_router(admin_ceo.router)
# near the digest startup hook (~87)
@app.on_event("startup")
def _start_ceo_scheduler():
    from app.services.ceo.heartbeat import start as _start
    # router_factory is None for now → scheduler stays idle until wired; manual
    # /admin/ceo/run still works. Wiring the factory is Task 11.
    _start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ceo_router.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/admin_ceo.py backend/app/main.py backend/tests/test_ceo_router.py
git commit -m "feat(ceo): admin board router (board/set-goal/decisions/kill) + main.py wiring"
```

---

### Task 8: `ceo_query` tool — KAI can introspect its own company

**Files:**
- Create: `backend/app/services/tools/ceo_query.py`
- Modify: `backend/app/services/tools/__init__.py` (register in `build_default_registry`)
- Test: `backend/tests/test_ceo_tool.py`

**Interfaces:**
- Consumes: the `Tool` protocol (`name`, `description`, `parameters`, `execute(ctx, **kwargs)`), `ToolContext`, `ceo.store`.
- Produces: `CeoQueryTool` with actions `board | decisions`. Read-only.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ceo_tool.py
import uuid, pytest
from unittest.mock import MagicMock
from app.services.ceo import store as st
from app.services.tools.ceo_query import CeoQueryTool
from app.services.tools.base import ToolContext


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CEO_DB_PATH", tmp_path / "ceo.db")
    yield


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def test_board_action_reports_company():
    st.upsert_company("Grow net revenue")
    out = CeoQueryTool().execute(_ctx(), action="board")
    assert out["company"]["goal"] == "Grow net revenue"


def test_decisions_action():
    st.record_decision("reprioritize", "pause cold email")
    out = CeoQueryTool().execute(_ctx(), action="decisions")
    assert out["decisions"][0]["kind"] == "reprioritize"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ceo_tool.py -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.tools.ceo_query'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/tools/ceo_query.py
from __future__ import annotations
from typing import Any
from app.services.tools.base import ToolContext, ToolError
from app.services.ceo import store

class CeoQueryTool:
    name = "ceo_query"
    description = (
        "Read KAI's own CEO state (READ-ONLY). action='board' → the company "
        "goal, latest KPI snapshot, and recent executive decisions. "
        "action='decisions' → recent decisions only. The operator runs the "
        "company from the CEO dashboard tab; this tool only reports."
    )
    parameters = {
        "type": "object",
        "properties": {"action": {"type": "string", "enum": ["board", "decisions"]},
                       "limit": {"type": "integer", "description": "decisions only — max rows (default 20)"}},
        "required": ["action"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        action = (kwargs.get("action") or "").strip().lower()
        if action == "board":
            return {"company": store.get_company(), "snapshot": store.latest_snapshot(),
                    "decisions": store.list_decisions(limit=10)}
        if action == "decisions":
            return {"decisions": store.list_decisions(limit=int(kwargs.get("limit") or 20))}
        raise ToolError("action must be 'board' or 'decisions'")
```

Registry edit in `backend/app/services/tools/__init__.py` (inside `build_default_registry`, next to `reg.register(PlanQueryTool())`):
```python
from app.services.tools.ceo_query import CeoQueryTool
reg.register(CeoQueryTool())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ceo_tool.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/tools/ceo_query.py backend/app/services/tools/__init__.py backend/tests/test_ceo_tool.py
git commit -m "feat(ceo): ceo_query read-only tool + registry wiring"
```

---

### Task 9: system-prompt injection — chat is CEO-aware

**Files:**
- Create: `backend/app/services/ceo/injection.py`
- Modify: `backend/app/services/nai_brain/system_prompt.py` (add `_auto_ceo_preamble()` + include it in `parts`, mirroring `_auto_twin_preamble`)
- Test: `backend/tests/test_ceo_injection.py`

**Interfaces:**
- Consumes: `governance.is_scope_enabled`, `ceo.store.get_company`.
- Produces: `ceo_preamble() -> str` — `""` when scope off / no company / on any error; else a 1-2 line "you operate as CEO toward goal X" block.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_ceo_injection.py
import pytest
from app.services.ceo import injection, store as st


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "CEO_DB_PATH", tmp_path / "ceo.db")
    yield


def test_preamble_empty_when_scope_off(monkeypatch):
    monkeypatch.delenv("KAI_SCOPE_CEO", raising=False)
    st.upsert_company("Grow net revenue")
    assert injection.ceo_preamble() == ""


def test_preamble_present_when_on(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_CEO", "1")
    st.upsert_company("Grow net revenue to $1M")
    out = injection.ceo_preamble()
    assert "CEO" in out and "$1M" in out


def test_preamble_empty_without_company(monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_CEO", "1")
    assert injection.ceo_preamble() == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_ceo_injection.py -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.ceo.injection'`

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/services/ceo/injection.py
from __future__ import annotations
import logging
logger = logging.getLogger(__name__)

def ceo_preamble() -> str:
    try:
        from app.services.governance import is_scope_enabled
        if not is_scope_enabled("ceo"):
            return ""
        from app.services.ceo import store
        company = store.get_company()
    except Exception as e:  # pragma: no cover
        logger.warning("ceo.injection: skipped (%s)", e)
        return ""
    if not company or not (company.get("goal") or "").strip():
        return ""
    return (
        "You operate as the autonomous CEO of WheellsVerse. Company north-star: "
        f"{company['goal']}. When the operator asks about strategy, priorities, "
        "or 'the company', answer from this goal and the CEO board (ceo_query tool)."
    )
```

Edit `system_prompt.py` (mirror `_auto_twin_preamble`):
```python
def _auto_ceo_preamble() -> str:
    try:
        from app.services.ceo.injection import ceo_preamble
        return ceo_preamble()
    except Exception:
        return ""
```
and add `ceo = _auto_ceo_preamble()` then `if ceo: parts.append(ceo.strip())` right after the `twin` block in `build_system_prompt`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_ceo_injection.py -v && pytest tests/test_system_prompt.py -v`
Expected: PASS (new file 3 tests; existing system-prompt tests still green)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/ceo/injection.py backend/app/services/nai_brain/system_prompt.py backend/tests/test_ceo_injection.py
git commit -m "feat(ceo): system-prompt injection — chat is CEO-aware (scope-gated, fail-open)"
```

---

### Task 10: CEO dashboard tab (#18)

**Files:**
- Modify: `backend/app/static/nai/admin.html` (add a `data-tab="ceo"` button + `#admin-pane-ceo` with: company-goal form, KPI snapshot card, decisions table, "run cycle" + "🛑 kill" buttons)
- Modify: `backend/app/static/nai/admin.js` (add a `loadCeo()` wired in `activateTab`'s `else if (name === "ceo")`, plus button handlers calling `/admin/ceo/*` via the existing `apiGet`/`apiPost` helpers)

**Interfaces:**
- Consumes: existing `apiGet`/`apiPost`/`activateTab` patterns; `/admin/ceo/*` endpoints from Task 7.
- Produces: a working CEO board tab.

- [ ] **Step 1: Add the tab button + pane (follow the exact markup pattern of the `audit` tab in admin.html).** Add `<button class="admin-tab" data-tab="ceo">👔 CEO</button>` to the nav, and an `#admin-pane-ceo` pane with the cards described above (reuse `.admin-card`, `.admin-table`, `.admin-plan-create` classes).

- [ ] **Step 2: Add `loadCeo()` to admin.js** mirroring `loadPlanning()` — fetch `/admin/ceo/`, render company goal + snapshot + decisions table; wire `#ceo-run` → `apiPost("/admin/ceo/run", {approved:true})`, `#ceo-kill` → `apiPost("/admin/ceo/kill", {})`, and the goal form → `apiPost("/admin/ceo/company", {goal, approved:true})`. Add `else if (name === "ceo") loadCeo();` in `activateTab`, and register the click handlers in the `DOMContentLoaded` block.

- [ ] **Step 3: Smoke-test in the browser** (daemon serves it live): enter admin token, open the 👔 CEO tab, set a goal, click "run cycle" with `KAI_SCOPE_CEO=1` + `KAI_CEO_DRY_RUN=1`, confirm a decision appears in the table and `data/governance/audit.jsonl` gets a `ceo.run` entry. (No automated test — this is DOM wiring; the endpoints are covered by Task 7.)

- [ ] **Step 4: Commit**

```bash
git add backend/app/static/nai/admin.html backend/app/static/nai/admin.js
git commit -m "feat(ceo): CEO board dashboard tab (#18) — goal, KPIs, decisions, run + kill"
```

---

### Task 11: rollout doc + follow-ups

**Files:**
- Create: `backend/app/services/ceo/SETUP.md`
- Modify: `docs/superpowers/specs/2026-06-19-kai-autonomous-ceo-design.md` (append "Implemented" note + remaining wiring)

- [ ] **Step 1: Write `SETUP.md`** documenting: dormant-by-default; activation order (set `KAI_SCOPE_CEO=1`, set the goal + `KAI_CEO_BUDGET_CEILING` + `KAI_CEO_CATASTROPHIC_USD`, run **dry-run** ≥1 cycle, review decisions, then `KAI_CEO_DRY_RUN=0`, finally `KAI_CEO_HEARTBEAT_ENABLED=1`); the kill switch (`POST /admin/ceo/kill` or `KAI_CEO_KILLED=1`); and the two follow-ups: (a) wire `kpis._revenue/_security_score/_alerts` to the real billing/security/supreme accessors, (b) provide a `router_factory` to `heartbeat.start()` in main.py so the scheduler can run autonomously.

- [ ] **Step 2: Run the full CEO suite + a sanity import**

Run: `cd backend && pytest tests/test_ceo_*.py -v && python -c "import app.main"`
Expected: all CEO tests PASS; app imports cleanly.

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/ceo/SETUP.md docs/superpowers/specs/2026-06-19-kai-autonomous-ceo-design.md
git commit -m "docs(ceo): setup runbook + implemented note + follow-up wiring"
```

---

## Self-Review

**Spec coverage:** Every §-component of the design spec maps to a task — store (§4.1→T1), floor (§4.4→T2), kpis (§4.2→T3), brain (§4.3→T4), executor (§4.5→T5), heartbeat+scheduler (§4.6→T6), operator surface/router (§4.8→T7), ceo_query tool (§4.8→T8), system-prompt injection (§4.8→T9), board tab (§5→T10), config/rollout (§6,§8→T11). Self-modify-code path (§4.7) is intentionally deferred — it reuses the existing worktree/executor and the prod-deploy catastrophic gate already lands in `floor.py` (`prod_deploy` ∈ CATASTROPHIC_KINDS); building the engineering-initiative runner is a follow-on plan, noted in SETUP.md.

**Placeholder scan:** No "TBD"/"implement later". Two explicit fail-soft stubs (`kpis._revenue` returns 0; `_security_score/_alerts` import accessors that may not exist yet) are wrapped in `_safe(...)` and flagged as follow-ups — they don't block the subsystem and the tests monkeypatch them.

**Type consistency:** `DecisionSet` keys (`initiatives`/`reprioritize`/`escalations`) are identical across brain (T4), executor (T5), heartbeat (T6). Floor verdicts (`in_policy`/`catastrophic`/`over_ceiling`) identical across floor (T2) and executor (T5). `create_plan(title, goal, *, status=, meta=)` and `Plan.status`/`.id` match the recon. `audited(scope=..., destructive=...)` + `approved=`/HTTP 403/409 mapping matches `admin_digest.py`. Store function names are identical between definitions (T1) and call sites (T3/T5/T7/T8/T9).

**Ambiguity:** The admin-token dependency import (T7) is explicitly flagged to match `admin_digest.py`'s actual import rather than assumed.
