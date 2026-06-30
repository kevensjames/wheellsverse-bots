# KAI Startup Factory — F1 (Loop Core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Factory's autonomous engineering-loop *state machine* with a mock runner — a nightly cycle that claims one task, walks it through the pipeline through the W-MOS safety envelope, and records a cycle + report — with full test coverage and **zero network / zero API spend**.

**Architecture:** New `factory/` package beside `core/portfolio/`. It reuses W-MOS's action envelope (`core.portfolio.actions.dispatch`, `ActionClass`, `Action`) and IO helpers (`core.portfolio.paths`), but keeps its own data root (`data/factory/`), its own env gates (`FACTORY_ENABLED`/`FACTORY_KILL`), and its own state schema (roadmap/backlog/known-issues/cycles). Code-writing agents are abstracted behind the W-MOS `AgentAdapter` protocol (`.run(action) -> dict`); F1 injects a **MockRunner**, F2 will swap in a real `claude -p` adapter with no pipeline changes.

**Tech Stack:** Python 3.11, dataclasses, `pytest`. Reuses `core.portfolio.{actions,paths}`. No new third-party deps.

## Global Constraints

- **Language/runtime:** Python 3.11, standard library + existing repo deps only. No new pip packages in F1.
- **Reuse, don't fork:** import `ActionClass`, `Action`, `dispatch`, `check_preconditions` from `core.portfolio.actions`; import `load_json`, `save_json_atomic`, `append_jsonl`, `read_jsonl` from `core.portfolio.paths`. Do not reimplement the envelope or IO atomics.
- **Data isolation:** all Factory state lives under `data/factory/` (override via `FACTORY_DATA_PATH`). Never write under W-MOS's `data/launches/portfolio/`.
- **Fail-closed:** unknown action classes refuse (inherited from `dispatch`); unknown preconditions are falsy; a stage adapter exception blocks the task.
- **Dormant by default:** `FACTORY_ENABLED=1` arms; `FACTORY_KILL=1` halts. Unset → `run_once` is a no-op.
- **Safety invariants encoded in the PIPELINE (not optional):** `deploy_staging` = AMBER (queued), `deploy_prod` = RED (never dispatched). These classes are part of the pipeline table, asserted by tests.
- **Determinism:** all time enters via an injected `now_iso: str` (ISO-8601) parameter; no `time.time()`/`datetime.now()` inside testable functions. Month = `now_iso[:7]`.
- **Tests:** every task ends green via `pytest`; tests set `FACTORY_DATA_PATH` to a `tmp_path` so nothing touches real data. No network calls anywhere in F1.

---

### Task 1: `factory/paths.py` — data root + IO helpers

**Files:**
- Create: `factory/__init__.py` (empty)
- Create: `factory/paths.py`
- Test: `tests/test_factory_paths.py`

**Interfaces:**
- Consumes: `core.portfolio.paths.{load_json, save_json_atomic, append_jsonl, read_jsonl}`
- Produces:
  - `data_root() -> pathlib.Path` (env `FACTORY_DATA_PATH`, default `<repo>/data/factory`)
  - `project_dir(slug: str) -> Path`
  - `workspaces_root() -> Path`, `worktrees_root() -> Path`
  - re-exports `load_json, save_json_atomic, append_jsonl, read_jsonl`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_paths.py
import os
from pathlib import Path
from factory import paths


def test_data_root_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path / "fx"))
    assert paths.data_root() == tmp_path / "fx"


def test_data_root_default_is_repo_data_factory(monkeypatch):
    monkeypatch.delenv("FACTORY_DATA_PATH", raising=False)
    assert paths.data_root().name == "factory"
    assert paths.data_root().parent.name == "data"


def test_project_and_workspace_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))
    assert paths.project_dir("acme") == tmp_path / "acme"
    assert paths.workspaces_root() == tmp_path / "workspaces"
    assert paths.worktrees_root() == tmp_path / "worktrees"


def test_io_helpers_are_reexported():
    assert callable(paths.load_json)
    assert callable(paths.save_json_atomic)
    assert callable(paths.append_jsonl)
    assert callable(paths.read_jsonl)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_factory_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory'`

- [ ] **Step 3: Write minimal implementation**

```python
# factory/__init__.py
# (empty — marks the package)
```

```python
# factory/paths.py
"""Factory filesystem helpers. Isolated from W-MOS: all state under data/factory/
(override FACTORY_DATA_PATH). Reuses the atomic IO helpers from core.portfolio.paths."""
from __future__ import annotations

import os
from pathlib import Path

from core.portfolio.paths import (  # re-export — single source of truth for atomics
    append_jsonl,
    load_json,
    read_jsonl,
    save_json_atomic,
)

ROOT = Path(__file__).resolve().parents[1]          # wheellsverse-bots/
_DEFAULT_DATA = ROOT / "data" / "factory"

__all__ = [
    "data_root", "project_dir", "workspaces_root", "worktrees_root",
    "load_json", "save_json_atomic", "append_jsonl", "read_jsonl",
]


def data_root() -> Path:
    return Path(os.getenv("FACTORY_DATA_PATH", str(_DEFAULT_DATA)))


def project_dir(slug: str) -> Path:
    return data_root() / slug


def workspaces_root() -> Path:
    return data_root() / "workspaces"


def worktrees_root() -> Path:
    return data_root() / "worktrees"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_paths.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/__init__.py factory/paths.py tests/test_factory_paths.py
git commit -m "feat(factory): paths module (isolated data root + IO re-exports)"
```

---

### Task 2: `factory/project.py` — Project model + registry

**Files:**
- Create: `factory/project.py`
- Test: `tests/test_factory_project.py`

**Interfaces:**
- Consumes: `factory.paths.{data_root, load_json, save_json_atomic}`
- Produces:
  - `@dataclass Project(slug, name, repo_url, phase="active", consecutive_failures=0, autonomy_overrides=dict)`
  - `list_projects() -> list[Project]`
  - `get_project(slug) -> Project | None`
  - `upsert_project(p: Project) -> None`
  - `list_active() -> list[Project]` (phase == "active")
  - `set_phase(slug, phase) -> None`
  - `bump_failure(slug, *, threshold=3) -> int` (increments; auto-sets phase "blocked_red" at threshold; returns new count)
  - `reset_failure(slug) -> None`
  - Registry file: `data_root()/projects.json` → `{"projects": [ {..}, .. ]}`
  - Valid phases: `"active" | "done" | "dormant" | "blocked_red"`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_project.py
import pytest
from factory import project as P


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


def test_upsert_and_get_roundtrip():
    P.upsert_project(P.Project(slug="acme", name="Acme", repo_url="git@x:acme.git"))
    got = P.get_project("acme")
    assert got is not None
    assert got.name == "Acme"
    assert got.phase == "active"
    assert got.consecutive_failures == 0


def test_get_missing_returns_none():
    assert P.get_project("nope") is None


def test_list_active_excludes_non_active():
    P.upsert_project(P.Project(slug="a", name="A", repo_url="x"))
    P.upsert_project(P.Project(slug="b", name="B", repo_url="x", phase="done"))
    actives = [p.slug for p in P.list_active()]
    assert actives == ["a"]


def test_set_phase_persists():
    P.upsert_project(P.Project(slug="a", name="A", repo_url="x"))
    P.set_phase("a", "dormant")
    assert P.get_project("a").phase == "dormant"


def test_bump_failure_flags_red_at_threshold():
    P.upsert_project(P.Project(slug="a", name="A", repo_url="x"))
    assert P.bump_failure("a", threshold=3) == 1
    assert P.bump_failure("a", threshold=3) == 2
    assert P.bump_failure("a", threshold=3) == 3
    assert P.get_project("a").phase == "blocked_red"


def test_reset_failure_zeroes_count():
    P.upsert_project(P.Project(slug="a", name="A", repo_url="x", consecutive_failures=2))
    P.reset_failure("a")
    assert P.get_project("a").consecutive_failures == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_project.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory.project'`

- [ ] **Step 3: Write minimal implementation**

```python
# factory/project.py
"""Factory project registry: the set of software products the daemon builds.
Stored as data/factory/projects.json. A project is 'active' while the daemon
should tick it; 'done' (roadmap complete), 'dormant' (paused), or 'blocked_red'
(too many consecutive failures — needs the operator)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from factory import paths

VALID_PHASES = {"active", "done", "dormant", "blocked_red"}


@dataclass
class Project:
    slug: str
    name: str
    repo_url: str
    phase: str = "active"
    consecutive_failures: int = 0
    autonomy_overrides: dict = field(default_factory=dict)


def _registry_file():
    return paths.data_root() / "projects.json"


def list_projects() -> list[Project]:
    data = paths.load_json(_registry_file(), {"projects": []}) or {"projects": []}
    return [Project(**row) for row in data.get("projects", [])]


def _save(projects: list[Project]) -> None:
    paths.save_json_atomic(_registry_file(), {"projects": [asdict(p) for p in projects]})


def get_project(slug: str) -> Project | None:
    return next((p for p in list_projects() if p.slug == slug), None)


def upsert_project(p: Project) -> None:
    projects = [x for x in list_projects() if x.slug != p.slug]
    projects.append(p)
    _save(projects)


def list_active() -> list[Project]:
    return [p for p in list_projects() if p.phase == "active"]


def set_phase(slug: str, phase: str) -> None:
    if phase not in VALID_PHASES:
        raise ValueError(f"invalid phase: {phase!r}")
    projects = list_projects()
    for p in projects:
        if p.slug == slug:
            p.phase = phase
    _save(projects)


def bump_failure(slug: str, *, threshold: int = 3) -> int:
    projects = list_projects()
    count = 0
    for p in projects:
        if p.slug == slug:
            p.consecutive_failures += 1
            count = p.consecutive_failures
            if count >= threshold:
                p.phase = "blocked_red"
    _save(projects)
    return count


def reset_failure(slug: str) -> None:
    projects = list_projects()
    for p in projects:
        if p.slug == slug:
            p.consecutive_failures = 0
    _save(projects)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_project.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/project.py tests/test_factory_project.py
git commit -m "feat(factory): project registry (phases, failure flagging)"
```

---

### Task 3: `factory/state.py` — engineering state + atomic task claim

**Files:**
- Create: `factory/state.py`
- Test: `tests/test_factory_state.py`

**Interfaces:**
- Consumes: `factory.paths.*`, `core.portfolio.actions.Action`
- Produces:
  - `load_backlog(slug) -> list[dict]` / `save_backlog(slug, tasks) -> None` (file: `<project_dir>/backlog.json` → `{"tasks": [...]}`). Task shape: `{"id": str, "title": str, "priority": int, "status": str, "depends_on": list[str], "source": str, "cycle_id": str|None}`. Lower `priority` int = more important.
  - `load_roadmap(slug) -> dict` / `save_roadmap(slug, data) -> None` (file: `roadmap.json` → `{"milestones": [{"id","title","status","features":[...]}]}`)
  - `roadmap_complete(slug) -> bool` (True when there is ≥1 milestone and all milestone `status == "done"`)
  - `next_ready_task(slug) -> dict | None` (status `"pending"`, all `depends_on` are ids of `"done"` tasks; lowest `priority`, ties broken by id)
  - `claim_task(slug, task_id, cycle_id) -> bool` (atomic compare-and-set `pending` → `in_progress`, stamps `cycle_id`)
  - `complete_task(slug, task_id) -> None` / `block_task(slug, task_id) -> None` / `release_task(slug, task_id) -> None` (back to `pending`, clears `cycle_id`)
  - `append_known_issue(slug, issue: dict) -> None` (file: `known_issues.jsonl`)
  - `append_cycle(slug, record: dict) -> None` (file: `cycles.jsonl`)
  - `audit(record: dict, *, now_iso: str) -> None` (factory-wide `data_root()/audit.jsonl`, stamps `at=now_iso`)
  - `queue_approval(action: Action, *, now_iso: str) -> str` (factory-wide `approvals.jsonl`, returns id `hex[:12]`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_state.py
import pytest
from core.portfolio.actions import Action, ActionClass
from factory import state, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


def _task(tid, prio=1, status="pending", deps=None):
    return {"id": tid, "title": tid, "priority": prio, "status": status,
            "depends_on": deps or [], "source": "seed", "cycle_id": None}


def test_backlog_roundtrip():
    state.save_backlog("a", [_task("t1")])
    assert state.load_backlog("a")[0]["id"] == "t1"


def test_next_ready_task_picks_lowest_priority():
    state.save_backlog("a", [_task("t2", prio=2), _task("t1", prio=1)])
    assert state.next_ready_task("a")["id"] == "t1"


def test_next_ready_task_respects_unmet_deps():
    state.save_backlog("a", [_task("t1", deps=["t0"]), _task("t0")])
    # t1 depends on t0 (still pending) -> t0 is the only ready one
    assert state.next_ready_task("a")["id"] == "t0"


def test_next_ready_task_allows_met_deps():
    state.save_backlog("a", [_task("t1", prio=1, deps=["t0"]),
                             _task("t0", prio=9, status="done")])
    assert state.next_ready_task("a")["id"] == "t1"


def test_next_ready_task_none_when_empty():
    state.save_backlog("a", [_task("t0", status="done")])
    assert state.next_ready_task("a") is None


def test_claim_task_is_compare_and_set():
    state.save_backlog("a", [_task("t1")])
    assert state.claim_task("a", "t1", "c1") is True
    # second claim fails — already in_progress
    assert state.claim_task("a", "t1", "c2") is False
    t = state.load_backlog("a")[0]
    assert t["status"] == "in_progress" and t["cycle_id"] == "c1"


def test_complete_block_release_transitions():
    state.save_backlog("a", [_task("t1")])
    state.claim_task("a", "t1", "c1")
    state.complete_task("a", "t1")
    assert state.load_backlog("a")[0]["status"] == "done"

    state.save_backlog("a", [_task("t2")])
    state.claim_task("a", "t2", "c2")
    state.release_task("a", "t2")
    rel = state.load_backlog("a")[0]
    assert rel["status"] == "pending" and rel["cycle_id"] is None


def test_roadmap_complete():
    assert state.roadmap_complete("a") is False  # no milestones
    state.save_roadmap("a", {"milestones": [{"id": "m1", "title": "x",
                                             "status": "done", "features": []}]})
    assert state.roadmap_complete("a") is True


def test_audit_and_approval_stamp_now_iso():
    state.audit({"verb": "x", "status": "ran"}, now_iso="2026-06-30T02:00:00Z")
    rows = paths.read_jsonl(paths.data_root() / "audit.jsonl")
    assert rows[0]["at"] == "2026-06-30T02:00:00Z"

    a = Action("deploy", "devops", ActionClass.AMBER, [], "a", {})
    aid = state.queue_approval(a, now_iso="2026-06-30T02:00:00Z")
    qrows = paths.read_jsonl(paths.data_root() / "approvals.jsonl")
    assert len(aid) == 12 and qrows[0]["status"] == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory.state'`

- [ ] **Step 3: Write minimal implementation**

```python
# factory/state.py
"""Per-project engineering state (backlog, roadmap, issues, cycles) plus the
factory-wide audit log and approval queue. Atomic writes + a module lock around
the compare-and-set task claim so a crashed/concurrent cycle never double-claims."""
from __future__ import annotations

import json
import threading
import uuid

from core.portfolio.actions import Action
from factory import paths

_CLAIM_LOCK = threading.Lock()


# ---- backlog -------------------------------------------------------------
def _backlog_file(slug: str):
    return paths.project_dir(slug) / "backlog.json"


def load_backlog(slug: str) -> list[dict]:
    data = paths.load_json(_backlog_file(slug), {"tasks": []}) or {"tasks": []}
    return data.get("tasks", [])


def save_backlog(slug: str, tasks: list[dict]) -> None:
    paths.save_json_atomic(_backlog_file(slug), {"tasks": tasks})


def _by_id(tasks: list[dict]) -> dict[str, dict]:
    return {t["id"]: t for t in tasks}


def next_ready_task(slug: str) -> dict | None:
    tasks = load_backlog(slug)
    done = {t["id"] for t in tasks if t.get("status") == "done"}
    ready = [
        t for t in tasks
        if t.get("status") == "pending"
        and all(dep in done for dep in t.get("depends_on", []))
    ]
    if not ready:
        return None
    ready.sort(key=lambda t: (t.get("priority", 0), t["id"]))
    return ready[0]


def claim_task(slug: str, task_id: str, cycle_id: str) -> bool:
    with _CLAIM_LOCK:
        tasks = load_backlog(slug)
        idx = _by_id(tasks)
        t = idx.get(task_id)
        if t is None or t.get("status") != "pending":
            return False
        t["status"] = "in_progress"
        t["cycle_id"] = cycle_id
        save_backlog(slug, tasks)
        return True


def _set_status(slug: str, task_id: str, status: str, *, clear_cycle: bool) -> None:
    with _CLAIM_LOCK:
        tasks = load_backlog(slug)
        for t in tasks:
            if t["id"] == task_id:
                t["status"] = status
                if clear_cycle:
                    t["cycle_id"] = None
        save_backlog(slug, tasks)


def complete_task(slug: str, task_id: str) -> None:
    _set_status(slug, task_id, "done", clear_cycle=False)


def block_task(slug: str, task_id: str) -> None:
    _set_status(slug, task_id, "blocked", clear_cycle=False)


def release_task(slug: str, task_id: str) -> None:
    _set_status(slug, task_id, "pending", clear_cycle=True)


# ---- roadmap -------------------------------------------------------------
def _roadmap_file(slug: str):
    return paths.project_dir(slug) / "roadmap.json"


def load_roadmap(slug: str) -> dict:
    return paths.load_json(_roadmap_file(slug), {"milestones": []}) or {"milestones": []}


def save_roadmap(slug: str, data: dict) -> None:
    paths.save_json_atomic(_roadmap_file(slug), data)


def roadmap_complete(slug: str) -> bool:
    ms = load_roadmap(slug).get("milestones", [])
    return bool(ms) and all(m.get("status") == "done" for m in ms)


# ---- issues + cycles -----------------------------------------------------
def append_known_issue(slug: str, issue: dict) -> None:
    paths.append_jsonl(paths.project_dir(slug) / "known_issues.jsonl", issue)


def append_cycle(slug: str, record: dict) -> None:
    paths.append_jsonl(paths.project_dir(slug) / "cycles.jsonl", record)


# ---- factory-wide audit + approvals -------------------------------------
def audit(record: dict, *, now_iso: str) -> None:
    enriched = dict(record)
    enriched["at"] = now_iso
    paths.append_jsonl(paths.data_root() / "audit.jsonl", enriched)


def queue_approval(action: Action, *, now_iso: str) -> str:
    aid = uuid.uuid4().hex[:12]
    paths.append_jsonl(paths.data_root() / "approvals.jsonl", {
        "id": aid,
        "status": "pending",
        "business": action.business,
        "verb": action.verb,
        "agent": action.agent,
        "action_class": action.action_class.value,
        "preconditions": list(action.preconditions),
        "payload": action.payload,
        "at": now_iso,
    })
    return aid
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_state.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/state.py tests/test_factory_state.py
git commit -m "feat(factory): engineering state + atomic compare-and-set task claim"
```

---

### Task 4: `factory/budget.py` — factory ceilings + spend gate

**Files:**
- Create: `factory/budget.py`
- Test: `tests/test_factory_budget.py`

**Interfaces:**
- Consumes: `factory.paths.*`
- Produces:
  - `@dataclass Ceilings(per_project_month: float, portfolio_month: float)`
  - `load_ceilings() -> Ceilings` (from `data_root()/portfolio.json` key `"ceilings"`; defaults 100.0 / 500.0)
  - `record_spend(slug, amount, kind, month) -> None` (append `data_root()/spend.jsonl`)
  - `spent(month, slug=None) -> float`
  - `would_exceed(slug, amount, month) -> bool`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_budget.py
import pytest
from factory import budget, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


def test_default_ceilings():
    c = budget.load_ceilings()
    assert c.per_project_month == 100.0 and c.portfolio_month == 500.0


def test_ceilings_from_file():
    paths.save_json_atomic(paths.data_root() / "portfolio.json",
                           {"ceilings": {"per_project_month": 10, "portfolio_month": 25}})
    c = budget.load_ceilings()
    assert c.per_project_month == 10.0 and c.portfolio_month == 25.0


def test_spent_sums_by_month_and_slug():
    budget.record_spend("a", 3.0, "step", "2026-06")
    budget.record_spend("a", 2.0, "step", "2026-06")
    budget.record_spend("b", 5.0, "step", "2026-06")
    budget.record_spend("a", 9.0, "step", "2026-07")
    assert budget.spent("2026-06", "a") == 5.0
    assert budget.spent("2026-06") == 10.0


def test_would_exceed_per_project():
    paths.save_json_atomic(paths.data_root() / "portfolio.json",
                           {"ceilings": {"per_project_month": 10, "portfolio_month": 100}})
    budget.record_spend("a", 9.0, "step", "2026-06")
    assert budget.would_exceed("a", 2.0, "2026-06") is True
    assert budget.would_exceed("a", 0.5, "2026-06") is False


def test_would_exceed_portfolio():
    paths.save_json_atomic(paths.data_root() / "portfolio.json",
                           {"ceilings": {"per_project_month": 1000, "portfolio_month": 10}})
    budget.record_spend("a", 6.0, "step", "2026-06")
    budget.record_spend("b", 3.0, "step", "2026-06")
    assert budget.would_exceed("a", 2.0, "2026-06") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_budget.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory.budget'`

- [ ] **Step 3: Write minimal implementation**

```python
# factory/budget.py
"""Factory budget ceilings + spend ledger (monthly). Mirrors core.portfolio.budget
but on the factory data root. Append-only ledger, summed on read. Month is a
'YYYY-MM' string supplied by the caller (deterministic)."""
from __future__ import annotations

from dataclasses import dataclass

from factory import paths


@dataclass
class Ceilings:
    per_project_month: float
    portfolio_month: float


def _portfolio_file():
    return paths.data_root() / "portfolio.json"


def _spend_file():
    return paths.data_root() / "spend.jsonl"


def load_ceilings() -> Ceilings:
    cfg = paths.load_json(_portfolio_file(), {}) or {}
    c = cfg.get("ceilings", {})
    return Ceilings(
        per_project_month=float(c.get("per_project_month", 100.0)),
        portfolio_month=float(c.get("portfolio_month", 500.0)),
    )


def record_spend(slug: str, amount: float, kind: str, month: str) -> None:
    paths.append_jsonl(_spend_file(), {
        "slug": slug, "amount": float(amount), "kind": kind, "month": month,
    })


def spent(month: str, slug: str | None = None) -> float:
    total = 0.0
    for row in paths.read_jsonl(_spend_file()):
        if row.get("month") != month:
            continue
        if slug is not None and row.get("slug") != slug:
            continue
        total += float(row.get("amount", 0.0))
    return total


def would_exceed(slug: str, amount: float, month: str) -> bool:
    c = load_ceilings()
    if spent(month, slug) + amount > c.per_project_month:
        return True
    if spent(month) + amount > c.portfolio_month:
        return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_budget.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/budget.py tests/test_factory_budget.py
git commit -m "feat(factory): budget ceilings + monthly spend gate"
```

---

### Task 5: `factory/pipeline.py` — the engineering-loop state machine

**Files:**
- Create: `factory/pipeline.py`
- Test: `tests/test_factory_pipeline.py`

**Interfaces:**
- Consumes: `core.portfolio.actions.{Action, ActionClass, dispatch}`, `factory.{state, budget, project}`
- Produces:
  - `@dataclass(frozen=True) Stage(verb, role, action_class, preconditions=(), hard_gate=False)`
  - `PIPELINE: list[Stage]` (the ordered stages; encodes `deploy_staging`=AMBER, `deploy_prod`=RED)
  - `@dataclass CycleResult(slug, cycle_id, task_id, status, stages=[], pr_url=None, cost_usd=0.0, note="")` where `status ∈ {"completed","blocked","idle","done","budget_queued"}`
  - `run_cycle(slug, runner, *, now_iso, ctx=None) -> CycleResult`
  - Runner contract (W-MOS `AgentAdapter`): `runner.run(action) -> dict` returning `{"ok": bool, "cost_usd": float, "output": str, "pr_url": str|None}`. Hard-gate stages are "failed" when `ok is False`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_pipeline.py
import pytest
from core.portfolio.actions import ActionClass
from factory import pipeline, state, project as P, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


class MockRunner:
    """Scripted AgentAdapter. script maps verb -> dict overrides."""
    def __init__(self, script=None):
        self.script = script or {}
        self.calls = []

    def run(self, action):
        self.calls.append(action.verb)
        spec = self.script.get(action.verb, {})
        return {
            "ok": spec.get("ok", True),
            "cost_usd": spec.get("cost_usd", 0.0),
            "output": spec.get("output", ""),
            "pr_url": spec.get("pr_url"),
        }


def _seed(slug="a"):
    P.upsert_project(P.Project(slug=slug, name=slug, repo_url="x"))
    state.save_backlog(slug, [{"id": "t1", "title": "do thing", "priority": 1,
                               "status": "pending", "depends_on": [], "source": "seed",
                               "cycle_id": None}])


def test_pipeline_encodes_safety_classes():
    by_verb = {s.verb: s for s in pipeline.PIPELINE}
    assert by_verb["deploy_staging"].action_class is ActionClass.AMBER
    assert by_verb["deploy_prod"].action_class is ActionClass.RED


def test_happy_path_completes_and_opens_pr():
    _seed()
    runner = MockRunner({"commit_pr": {"pr_url": "https://gh/pr/1"}})
    res = pipeline.run_cycle("a", runner, now_iso="2026-06-30T02:00:00Z")
    assert res.status == "completed"
    assert res.pr_url == "https://gh/pr/1"
    assert state.load_backlog("a")[0]["status"] == "done"


def test_amber_deploy_is_queued_not_run():
    _seed()
    runner = MockRunner()
    pipeline.run_cycle("a", runner, now_iso="2026-06-30T02:00:00Z")
    assert "deploy_staging" not in runner.calls          # AMBER never reaches adapter
    approvals = paths.read_jsonl(paths.data_root() / "approvals.jsonl")
    assert any(r["verb"] == "deploy_staging" for r in approvals)


def test_red_deploy_is_refused_not_run():
    _seed()
    runner = MockRunner()
    pipeline.run_cycle("a", runner, now_iso="2026-06-30T02:00:00Z")
    assert "deploy_prod" not in runner.calls
    approvals = paths.read_jsonl(paths.data_root() / "approvals.jsonl")
    assert not any(r["verb"] == "deploy_prod" for r in approvals)  # RED isn't even queued


def test_security_hard_gate_blocks_task():
    _seed()
    runner = MockRunner({"security": {"ok": False}})
    res = pipeline.run_cycle("a", runner, now_iso="2026-06-30T02:00:00Z")
    assert res.status == "blocked"
    assert "commit_pr" not in runner.calls               # gate stops before PR
    assert state.load_backlog("a")[0]["status"] == "blocked"
    assert P.get_project("a").consecutive_failures == 1


def test_idle_when_no_ready_task():
    P.upsert_project(P.Project(slug="a", name="a", repo_url="x"))
    state.save_backlog("a", [])
    res = pipeline.run_cycle("a", MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert res.status == "idle"


def test_done_when_roadmap_complete_and_no_tasks():
    P.upsert_project(P.Project(slug="a", name="a", repo_url="x"))
    state.save_backlog("a", [])
    state.save_roadmap("a", {"milestones": [{"id": "m1", "title": "x",
                                             "status": "done", "features": []}]})
    res = pipeline.run_cycle("a", MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert res.status == "done"
    assert P.get_project("a").phase == "done"


def test_budget_overrun_queues_and_releases_task():
    _seed()
    paths.save_json_atomic(paths.data_root() / "portfolio.json",
                           {"ceilings": {"per_project_month": 1, "portfolio_month": 1}})
    from factory import budget
    budget.record_spend("a", 5.0, "prior", "2026-06")    # already over ceiling
    res = pipeline.run_cycle("a", MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert res.status == "budget_queued"
    assert state.load_backlog("a")[0]["status"] == "pending"   # released
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory.pipeline'`

- [ ] **Step 3: Write minimal implementation**

```python
# factory/pipeline.py
"""The Factory engineering loop. run_cycle claims ONE ready task and walks it
through PIPELINE via the W-MOS action envelope. GREEN/AUTO_CAPPED stages call the
injected runner (a claude -p adapter in F2, a mock in F1); AMBER stages are queued;
RED stages are refused. Hard-gate stages (security, build) block the task — and the
PR — when the agent reports ok=False. Deterministic: all time enters via now_iso."""
from __future__ import annotations

from dataclasses import dataclass, field

from core.portfolio.actions import Action, ActionClass, dispatch
from factory import budget, project as projects, state


@dataclass(frozen=True)
class Stage:
    verb: str
    role: str
    action_class: ActionClass
    preconditions: tuple[str, ...] = ()
    hard_gate: bool = False


PIPELINE: list[Stage] = [
    Stage("architect", "architect", ActionClass.GREEN),
    Stage("implement", "engineer", ActionClass.GREEN),
    Stage("review", "reviewer", ActionClass.GREEN),
    Stage("refactor", "refactorer", ActionClass.AUTO_CAPPED, ("review_found_issues",)),
    Stage("security", "security", ActionClass.GREEN, hard_gate=True),
    Stage("test", "qa", ActionClass.GREEN),
    Stage("build", "daemon", ActionClass.GREEN, hard_gate=True),
    Stage("report", "writer", ActionClass.GREEN),
    Stage("next_tasks", "techlead", ActionClass.GREEN),
    Stage("commit_pr", "git", ActionClass.GREEN),
    Stage("deploy_staging", "devops", ActionClass.AMBER),
    Stage("deploy_prod", "devops", ActionClass.RED),
]


@dataclass
class CycleResult:
    slug: str
    cycle_id: str
    task_id: str | None
    status: str
    stages: list[dict] = field(default_factory=list)
    pr_url: str | None = None
    cost_usd: float = 0.0
    note: str = ""


def _cycle_id(slug: str, now_iso: str) -> str:
    stamp = now_iso.replace("-", "").replace(":", "").replace("T", "").rstrip("Z")
    return f"{stamp[:14]}-{slug}"


def run_cycle(slug: str, runner, *, now_iso: str, ctx: dict | None = None) -> CycleResult:
    ctx = ctx or {}
    month = now_iso[:7]
    cid = _cycle_id(slug, now_iso)

    # Stopping condition: roadmap done and nothing ready.
    if state.roadmap_complete(slug) and state.next_ready_task(slug) is None:
        projects.set_phase(slug, "done")
        return CycleResult(slug, cid, None, "done")

    task = state.next_ready_task(slug)
    if task is None:
        return CycleResult(slug, cid, None, "idle", note="no ready task")
    if not state.claim_task(slug, task["id"], cid):
        return CycleResult(slug, cid, task["id"], "idle", note="claim lost")

    cost = 0.0
    stages_out: list[dict] = []
    pr_url = None
    blocked = False

    for stage in PIPELINE:
        # Budget gate before any executable stage: if already over ceiling, stop.
        if stage.action_class in (ActionClass.GREEN, ActionClass.AUTO_CAPPED):
            if budget.would_exceed(slug, 0.0, month):
                state.release_task(slug, task["id"])
                return CycleResult(slug, cid, task["id"], "budget_queued",
                                   stages_out, cost_usd=cost, note="budget ceiling")

        action = Action(
            verb=stage.verb, agent=stage.role, action_class=stage.action_class,
            preconditions=list(stage.preconditions), business=slug,
            payload={"task": task, "cycle_id": cid},
        )
        result = dispatch(
            action, runner, ctx,
            on_queue=lambda a: state.queue_approval(a, now_iso=now_iso),
            on_audit=lambda r: state.audit(r, now_iso=now_iso),
        )
        out = result.output or {}
        step_cost = float(out.get("cost_usd", 0.0))
        if step_cost:
            cost += step_cost
            budget.record_spend(slug, step_cost, stage.verb, month)

        rec = {"verb": stage.verb, "status": result.status, "detail": result.detail}
        if result.status == "executed" and stage.verb == "commit_pr":
            pr_url = out.get("pr_url")

        adapter_failed = result.status == "failed"
        gate_failed = (stage.hard_gate and result.status == "executed"
                       and not out.get("ok", True))
        if adapter_failed or gate_failed:
            rec["blocked"] = True
            stages_out.append(rec)
            blocked = True
            break
        stages_out.append(rec)

    if blocked:
        state.block_task(slug, task["id"])
        projects.bump_failure(slug)
        status = "blocked"
    else:
        state.complete_task(slug, task["id"])
        projects.reset_failure(slug)
        status = "completed"

    res = CycleResult(slug, cid, task["id"], status, stages_out, pr_url, cost)
    state.append_cycle(slug, {
        "cycle_id": cid, "slug": slug, "task_id": task["id"], "status": status,
        "stages": stages_out, "pr_url": pr_url, "cost_usd": cost, "at": now_iso,
    })
    return res
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_pipeline.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/pipeline.py tests/test_factory_pipeline.py
git commit -m "feat(factory): engineering-loop state machine (run_cycle + PIPELINE)"
```

---

### Task 6: `factory/report.py` — morning report

**Files:**
- Create: `factory/report.py`
- Test: `tests/test_factory_report.py`

**Interfaces:**
- Consumes: `factory.paths.{project_dir, save... (via Path.write_text)}`
- Produces:
  - `render_report(cycle: dict) -> str` (markdown from an `append_cycle` record: title line with slug + status, task id, PR link or "no PR", per-stage status list, total cost)
  - `write_report(slug, cycle: dict, *, date: str) -> pathlib.Path` (writes `<project_dir>/reports/<date>.md`, returns the path)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_report.py
import pytest
from factory import report, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


def _cycle():
    return {"cycle_id": "c1", "slug": "acme", "task_id": "t1", "status": "completed",
            "stages": [{"verb": "implement", "status": "executed", "detail": "executed"},
                       {"verb": "deploy_staging", "status": "queued", "detail": "queued"}],
            "pr_url": "https://gh/pr/1", "cost_usd": 0.42, "at": "2026-06-30T02:00:00Z"}


def test_render_includes_status_pr_and_cost():
    md = report.render_report(_cycle())
    assert "acme" in md and "completed" in md
    assert "https://gh/pr/1" in md
    assert "0.42" in md
    assert "implement" in md and "deploy_staging" in md


def test_render_handles_no_pr():
    c = _cycle()
    c["pr_url"] = None
    md = report.render_report(c)
    assert "no PR" in md.lower()


def test_write_report_creates_file():
    p = report.write_report("acme", _cycle(), date="2026-06-30")
    assert p == paths.project_dir("acme") / "reports" / "2026-06-30.md"
    assert "completed" in p.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_report.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory.report'`

- [ ] **Step 3: Write minimal implementation**

```python
# factory/report.py
"""Render a cycle record into a human morning report (markdown)."""
from __future__ import annotations

from pathlib import Path

from factory import paths


def render_report(cycle: dict) -> str:
    pr = cycle.get("pr_url") or "no PR"
    lines = [
        f"# Factory report — {cycle.get('slug')} ({cycle.get('at', '')})",
        "",
        f"- **Status:** {cycle.get('status')}",
        f"- **Task:** {cycle.get('task_id')}",
        f"- **PR:** {pr}",
        f"- **Cost:** ${float(cycle.get('cost_usd', 0.0)):.2f}",
        "",
        "## Stages",
    ]
    for s in cycle.get("stages", []):
        lines.append(f"- `{s.get('verb')}` → {s.get('status')} ({s.get('detail')})")
    return "\n".join(lines) + "\n"


def write_report(slug: str, cycle: dict, *, date: str) -> Path:
    target = paths.project_dir(slug) / "reports" / f"{date}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_report(cycle), encoding="utf-8")
    return target
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_report.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/report.py tests/test_factory_report.py
git commit -m "feat(factory): morning report renderer"
```

---

### Task 7: `factory/scheduler.py` — gates + nightly sweep

**Files:**
- Create: `factory/scheduler.py`
- Test: `tests/test_factory_scheduler.py`

**Interfaces:**
- Consumes: `factory.{project, pipeline, report, paths}`
- Produces:
  - `is_enabled() -> bool` (`FACTORY_ENABLED=1` or `portfolio.json.control.enabled`)
  - `kill_engaged() -> bool` (`FACTORY_KILL=1` or `portfolio.json.control.kill`)
  - `set_enabled(bool) -> None`, `engage_kill() -> None`, `disengage_kill() -> None`, `control_state() -> dict`
  - `run_once(runner, *, now_iso, slugs=None) -> dict` → `{"status": "ran"|"dormant"|"killed", "ticked": {slug: status}}`; writes a morning report per ticked project that ran a cycle
  - `start_worker(runner, *, interval_s=60) -> None` (idempotent daemon thread; **not asserted to fire in tests**)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_scheduler.py
import pytest
from factory import scheduler, project as P, state, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("FACTORY_ENABLED", raising=False)
    monkeypatch.delenv("FACTORY_KILL", raising=False)


class MockRunner:
    def run(self, action):
        return {"ok": True, "cost_usd": 0.0, "output": "",
                "pr_url": "https://gh/pr/1" if action.verb == "commit_pr" else None}


def _seed(slug="a"):
    P.upsert_project(P.Project(slug=slug, name=slug, repo_url="x"))
    state.save_backlog(slug, [{"id": "t1", "title": "x", "priority": 1,
                               "status": "pending", "depends_on": [], "source": "seed",
                               "cycle_id": None}])


def test_dormant_by_default():
    _seed()
    out = scheduler.run_once(MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert out["status"] == "dormant" and out["ticked"] == {}


def test_kill_halts_even_if_enabled(monkeypatch):
    _seed()
    monkeypatch.setenv("FACTORY_ENABLED", "1")
    monkeypatch.setenv("FACTORY_KILL", "1")
    out = scheduler.run_once(MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert out["status"] == "killed"


def test_enabled_ticks_active_projects_and_writes_report(monkeypatch):
    _seed()
    monkeypatch.setenv("FACTORY_ENABLED", "1")
    out = scheduler.run_once(MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert out["status"] == "ran"
    assert out["ticked"] == {"a": "completed"}
    assert (paths.project_dir("a") / "reports" / "2026-06-30.md").exists()


def test_set_enabled_via_control_file():
    _seed()
    scheduler.set_enabled(True)
    assert scheduler.is_enabled() is True
    out = scheduler.run_once(MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert out["status"] == "ran"


def test_only_active_projects_ticked(monkeypatch):
    _seed("a")
    P.upsert_project(P.Project(slug="b", name="b", repo_url="x", phase="dormant"))
    monkeypatch.setenv("FACTORY_ENABLED", "1")
    out = scheduler.run_once(MockRunner(), now_iso="2026-06-30T02:00:00Z")
    assert "b" not in out["ticked"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory.scheduler'`

- [ ] **Step 3: Write minimal implementation**

```python
# factory/scheduler.py
"""The nightly Factory daemon. Two gates every sweep: kill-switch (FACTORY_KILL)
halts immediately; dormancy (FACTORY_ENABLED) does nothing until armed. Mirrors
core.portfolio.orchestrator. run_once ticks each ACTIVE project once and writes a
morning report. Ships dormant."""
from __future__ import annotations

import logging
import os
import threading
import time

from factory import paths, pipeline, project as projects, report

logger = logging.getLogger("factory_scheduler")


def _control() -> dict:
    cfg = paths.load_json(paths.data_root() / "portfolio.json", {}) or {}
    return cfg.get("control", {}) or {}


def is_enabled() -> bool:
    return os.getenv("FACTORY_ENABLED") == "1" or bool(_control().get("enabled"))


def kill_engaged() -> bool:
    return os.getenv("FACTORY_KILL") == "1" or bool(_control().get("kill"))


def _set_control(key: str, value: bool) -> None:
    f = paths.data_root() / "portfolio.json"
    cfg = paths.load_json(f, {}) or {}
    cfg.setdefault("control", {})[key] = bool(value)
    paths.save_json_atomic(f, cfg)


def set_enabled(enabled: bool) -> None:
    _set_control("enabled", enabled)


def engage_kill() -> None:
    _set_control("kill", True)


def disengage_kill() -> None:
    _set_control("kill", False)


def control_state() -> dict:
    return {"enabled": is_enabled(), "kill": kill_engaged()}


def run_once(runner, *, now_iso: str, slugs: list[str] | None = None) -> dict:
    if kill_engaged():
        return {"status": "killed", "ticked": {}}
    if not is_enabled():
        return {"status": "dormant", "ticked": {}}

    target = slugs if slugs is not None else [p.slug for p in projects.list_active()]
    ticked: dict[str, str] = {}
    date = now_iso[:10]
    for slug in target:
        try:
            res = pipeline.run_cycle(slug, runner, now_iso=now_iso)
            ticked[slug] = res.status
            if res.status in ("completed", "blocked"):
                report.write_report(slug, {
                    "cycle_id": res.cycle_id, "slug": slug, "task_id": res.task_id,
                    "status": res.status, "stages": res.stages, "pr_url": res.pr_url,
                    "cost_usd": res.cost_usd, "at": now_iso,
                }, date=date)
        except Exception as e:  # fail-soft: one project's failure never stops the sweep
            logger.error(f"factory tick failed for {slug!r}: {e}")
            ticked[slug] = "error"
    return {"status": "ran", "ticked": ticked}


_worker_started = False
_worker_lock = threading.Lock()


def start_worker(runner, *, interval_s: int = 60) -> None:
    """Idempotent nightly worker. Wakes every interval, fires run_once at the
    configured local hour (FACTORY_TICK_HOUR, default 2) at most once per day.
    Time is read here (not in run_once) so the testable core stays deterministic."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True

    hour = int(os.getenv("FACTORY_TICK_HOUR", "2"))

    def _loop() -> None:
        last_date = None
        logger.info(f"factory worker started (tick hour={hour}, enabled={is_enabled()})")
        while True:
            try:
                lt = time.localtime()
                today = time.strftime("%Y-%m-%d", lt)
                if lt.tm_hour == hour and today != last_date and not kill_engaged() and is_enabled():
                    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    run_once(runner, now_iso=now_iso)
                    last_date = today
            except Exception as e:
                logger.error(f"factory worker cycle error: {e}")
            time.sleep(interval_s)

    t = threading.Thread(target=_loop, daemon=True, name="factory-scheduler")
    t.start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_scheduler.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/scheduler.py tests/test_factory_scheduler.py
git commit -m "feat(factory): nightly scheduler with kill-switch + dormancy gates"
```

---

### Task 8: `factory/cli.py` — manual `tick` entry point

**Files:**
- Create: `factory/cli.py`
- Test: `tests/test_factory_cli.py`

**Interfaces:**
- Consumes: `factory.{pipeline, project}`
- Produces:
  - `class MockRunner` (the F1 built-in runner so the CLI is runnable with no network; F2 replaces it)
  - `tick(slug: str, *, now_iso: str) -> dict` (runs one cycle, returns `CycleResult` as a dict via `dataclasses.asdict`)
  - `main(argv: list[str] | None = None) -> int` (supports `tick <slug>`; prints JSON; returns exit code)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_cli.py
import pytest
from factory import cli, project as P, state


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


def _seed(slug="a"):
    P.upsert_project(P.Project(slug=slug, name=slug, repo_url="x"))
    state.save_backlog(slug, [{"id": "t1", "title": "x", "priority": 1,
                               "status": "pending", "depends_on": [], "source": "seed",
                               "cycle_id": None}])


def test_tick_runs_a_cycle():
    _seed()
    out = cli.tick("a", now_iso="2026-06-30T02:00:00Z")
    assert out["status"] == "completed"
    assert out["slug"] == "a"


def test_main_tick_returns_zero():
    _seed()
    rc = cli.main(["tick", "a", "--now", "2026-06-30T02:00:00Z"])
    assert rc == 0


def test_main_unknown_command_returns_nonzero():
    assert cli.main(["bogus"]) != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# factory/cli.py
"""Manual Factory entry point for dev/testing: `python -m factory tick <slug>`.
Uses a built-in MockRunner in F1 (no network); F2 swaps in the real claude -p
adapter. NOT the production path — the daemon (scheduler.start_worker) is."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from factory import pipeline


class MockRunner:
    def run(self, action):
        return {"ok": True, "cost_usd": 0.0, "output": "",
                "pr_url": "https://example.invalid/pr/mock" if action.verb == "commit_pr" else None}


def tick(slug: str, *, now_iso: str) -> dict:
    return asdict(pipeline.run_cycle(slug, MockRunner(), now_iso=now_iso))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="factory")
    sub = parser.add_subparsers(dest="cmd")
    t = sub.add_parser("tick")
    t.add_argument("slug")
    t.add_argument("--now", default=None, help="ISO-8601 timestamp (default: now, UTC)")

    args = parser.parse_args(argv)
    if args.cmd != "tick":
        parser.print_usage()
        return 2

    now_iso = args.now
    if now_iso is None:
        import time
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    print(json.dumps(tick(args.slug, now_iso=now_iso), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_cli.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/cli.py tests/test_factory_cli.py
git commit -m "feat(factory): manual tick CLI (mock runner)"
```

---

### Task 9: F1 integration smoke + full suite green

**Files:**
- Test: `tests/test_factory_integration.py`

**Interfaces:**
- Consumes: all factory modules.
- Produces: an end-to-end proof that an armed daemon takes a seeded project from a pending task to a `completed` cycle with a PR url and a written report, all under a temp data root.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_integration.py
import pytest
from factory import scheduler, project as P, state, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("FACTORY_ENABLED", "1")
    monkeypatch.delenv("FACTORY_KILL", raising=False)


class MockRunner:
    def run(self, action):
        return {"ok": True, "cost_usd": 0.01, "output": "",
                "pr_url": "https://gh/pr/42" if action.verb == "commit_pr" else None}


def test_end_to_end_nightly_sweep():
    P.upsert_project(P.Project(slug="hello", name="Hello Service", repo_url="x"))
    state.save_backlog("hello", [{"id": "t1", "title": "scaffold", "priority": 1,
                                  "status": "pending", "depends_on": [], "source": "seed",
                                  "cycle_id": None}])

    out = scheduler.run_once(MockRunner(), now_iso="2026-06-30T02:00:00Z")

    assert out == {"status": "ran", "ticked": {"hello": "completed"}}
    assert state.load_backlog("hello")[0]["status"] == "done"
    cycles = paths.read_jsonl(paths.project_dir("hello") / "cycles.jsonl")
    assert cycles[-1]["pr_url"] == "https://gh/pr/42"
    assert (paths.project_dir("hello") / "reports" / "2026-06-30.md").exists()
    # spend recorded, audit written
    assert paths.read_jsonl(paths.data_root() / "audit.jsonl")
    assert paths.read_jsonl(paths.data_root() / "spend.jsonl")
```

- [ ] **Step 2: Run test to verify it fails (or passes immediately)**

Run: `python -m pytest tests/test_factory_integration.py -v`
Expected: PASS (the components already exist) — if it FAILS, fix the integration seam, not the test.

- [ ] **Step 3: Run the full factory suite**

Run: `python -m pytest tests/test_factory_*.py -v`
Expected: PASS (all factory tests green, ~40 tests)

- [ ] **Step 4: Confirm no W-MOS regressions**

Run: `python -m pytest tests/test_portfolio_*.py -q`
Expected: PASS (factory imports reuse but do not modify `core.portfolio`)

- [ ] **Step 5: Commit**

```bash
git add tests/test_factory_integration.py
git commit -m "test(factory): F1 end-to-end nightly sweep smoke"
```

---

## Self-Review

**1. Spec coverage (spec §→task):**
- §3 new `factory/` package — Tasks 1–9 create `paths, project, state, budget, pipeline, report, scheduler, cli`. *(roles.py, runner.py, worktree.py are F2 — out of F1 scope by design.)*
- §4 data flow (scheduler → run_cycle → dispatch → runner) — Tasks 5, 7, 9.
- §5 pipeline stages + autonomy classes + idempotency + stopping — Task 5 (`PIPELINE`, `run_cycle`, compare-and-set claim, `done`/`idle`/`blocked` statuses, kill-criteria via `bump_failure`).
- §8 envelope (GREEN/AUTO_CAPPED/AMBER/RED), dormant-by-default, kill-switch, budget ceiling — Tasks 4, 5, 7 (asserted: AMBER queued, RED refused, budget_queued, dormant/killed).
- §8 HIPAA invariants — encoded structurally: `deploy_prod` is RED in `PIPELINE` (Task 5 test asserts it). Synthetic-data invariant has no executable surface in F1 (no real runner) — it lands as a runner constraint in F2; noted here so it isn't lost.
- §9 state schema (backlog/roadmap/known_issues/cycles, factory-wide audit/approvals) — Task 3.
- §10 governance/audit — Task 3 `audit()`; full `@audited` HTTP integration is F3 (dashboard).
- §11 F1 acceptance ("prove full state machine on a throwaway project, no network") — Task 9.

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N". Every code step shows complete code; every run step shows the exact command + expected result.

**3. Type consistency:** Runner contract `{"ok","cost_usd","output","pr_url"}` is identical across Tasks 5, 7, 8, 9. `CycleResult` field names (`status`, `pr_url`, `cost_usd`, `stages`, `task_id`, `cycle_id`) consistent between `pipeline.run_cycle` (Task 5) and its consumers in `scheduler.run_once` (Task 7) and `cli.tick` (Task 8). Task dict shape (`id/title/priority/status/depends_on/source/cycle_id`) identical across Tasks 3, 5, 7, 8, 9. `now_iso` keyword-only on every time-dependent function. `Project` fields consistent (Tasks 2, 5, 7).

**Out of F1 scope (tracked for F2/F3):** real `claude -p` AgentRunner + `roles.py` + `worktree.py` + git push-wrapper + PR opener (F2); admin dashboard tab + `@audited` HTTP routes + Telegram report + AMBER approval UI (F3); synthetic-data enforcement at the runner boundary (F2).
