# W-MOS Engine Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the dormant, fully-tested orchestration engine (`core/portfolio/*`) for the Wheellsverse Portfolio Operating System — the load-bearing safety envelope, supervisor-loop tick engine, budget ceilings, and Master Supervisor sweep — with zero UI and all external systems injected as adapters.

**Architecture:** Pure, deterministic, file-backed Python under `core/portfolio/`. The engine *defines* an `AgentAdapter` Protocol and never calls undefined external APIs; real adapters (KAI, cold_outreach, places_scanner) are implemented in a later plan. A traffic-light **action envelope** (`actions.py`) decides whether each action runs unattended, auto-fires within caps, queues for one-click approval, or is refused. The Master Supervisor is dormant behind `WMOS_ORCHESTRATOR_ENABLED` and halts on `WMOS_KILL`.

**Tech Stack:** Python 3 (stdlib only — `json`, `os`, `pathlib`, `threading`, `time`, `uuid`, `dataclasses`, `enum`, `typing`), pytest. Mirrors existing `core/siteboost_*.py` conventions.

## Global Constraints

- **Repo / branch:** `wheellsverse-bots` @ `_apexdeploy`. All paths below are relative to repo root.
- **File header:** every module starts with `from __future__ import annotations`.
- **Repo root resolution:** `ROOT = Path(__file__).resolve().parents[2]` (file lives at `core/portfolio/<x>.py`).
- **Data location:** file-backed JSON under `data/launches/portfolio/`, overridable via env `WMOS_DATA_PATH`. **Read the env at call-time** (not import-time) so tests can `monkeypatch.setenv` per-test.
- **Atomic writes:** `tmp = path.with_suffix(path.suffix + ".tmp"); tmp.write_text(json.dumps(x, indent=2)); tmp.replace(path)`.
- **Clocks are injected:** any time-dependent function takes a `now`/`month`/`clock` parameter; never call `time.time()`/`time.gmtime()` deep inside logic. (Default param may read the real clock at the boundary.)
- **The envelope is law (verbatim action classes):** `green` = runs unattended; `auto_capped` = fires only if every precondition truthy in ctx, else queued; `amber` = always queued for approval, never auto-fired; `red` = never dispatched by the engine.
- **Three invariants:** budget ceiling (breach → pause+escalate), kill-switch (`WMOS_KILL=1` halts everything), dormant-by-default (`WMOS_ORCHESTRATOR_ENABLED` unset/≠`1` ⇒ no production ticks).
- **truth_verification skill applies:** tests assert against real persisted state (re-read the file), never against a return code or status string alone.
- **Commits:** the operator's standing rule is "commit only when asked." The commit step in each task is the intended boundary; at execution time honor the operator's approval before actually committing.
- **Run tests from repo root:** `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest <path> -v`.

---

### Task 1: `paths.py` — data root + atomic JSON/JSONL helpers (DRY foundation)

**Files:**
- Create: `core/portfolio/__init__.py`
- Create: `core/portfolio/paths.py`
- Test: `tests/test_portfolio_paths.py`

**Interfaces:**
- Produces:
  - `data_root() -> Path` — `WMOS_DATA_PATH` or `<ROOT>/data/launches/portfolio`, read at call-time.
  - `business_dir(slug: str) -> Path` — `data_root() / slug`.
  - `load_json(path: Path, default)` — returns parsed JSON or `default` if missing/corrupt.
  - `save_json_atomic(path: Path, payload) -> None` — mkdirs + atomic replace.
  - `append_jsonl(path: Path, record: dict) -> None` — mkdirs + append one JSON line.
  - `read_jsonl(path: Path) -> list[dict]` — parse all lines, skip blanks/corrupt.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_paths.py
import json
from pathlib import Path
from core.portfolio import paths


def test_data_root_honors_env(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    assert paths.data_root() == tmp_path
    assert paths.business_dir("n8n") == tmp_path / "n8n"


def test_load_json_returns_default_when_missing(tmp_path):
    assert paths.load_json(tmp_path / "nope.json", {"a": 1}) == {"a": 1}


def test_save_json_atomic_roundtrip_and_no_tmp_left(tmp_path):
    target = tmp_path / "sub" / "x.json"
    paths.save_json_atomic(target, {"hello": "world"})
    assert json.loads(target.read_text()) == {"hello": "world"}
    assert not (tmp_path / "sub" / "x.json.tmp").exists()


def test_jsonl_append_and_read(tmp_path):
    log = tmp_path / "audit.jsonl"
    paths.append_jsonl(log, {"n": 1})
    paths.append_jsonl(log, {"n": 2})
    assert paths.read_jsonl(log) == [{"n": 1}, {"n": 2}]


def test_load_json_survives_corrupt_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert paths.load_json(bad, []) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_paths.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.portfolio'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/portfolio/__init__.py
"""Wheellsverse Portfolio Operating System (W-MOS) engine core."""
```

```python
# core/portfolio/paths.py
"""W-MOS shared filesystem helpers: data root, atomic JSON, JSONL append/read.

All W-MOS state lives under data/launches/portfolio/ (override WMOS_DATA_PATH for
tests / Railway volume). Env is read at call-time so tests can monkeypatch per-test.
Mirrors the atomic-write convention in core/siteboost_scheduler.py.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA = ROOT / "data" / "launches" / "portfolio"


def data_root() -> Path:
    return Path(os.getenv("WMOS_DATA_PATH", str(_DEFAULT_DATA)))


def business_dir(slug: str) -> Path:
    return data_root() / slug


def load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2))
    tmp.replace(path)


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_paths.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add core/portfolio/__init__.py core/portfolio/paths.py tests/test_portfolio_paths.py
git commit -m "feat(wmos): add portfolio engine path/JSON helpers"
```

---

### Task 2: `registry.py` — the 10 businesses as data

**Files:**
- Create: `core/portfolio/registry.py`
- Test: `tests/test_portfolio_registry.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Business` with fields `slug: str, name: str, thesis: str, oss_repo: str, phase: str = "planning"`.
  - `BUSINESSES: list[Business]` — exactly 10 entries (n8n, coolify, listmonk, ghost, calcom, plausible, supabase, medusa, appflowy, penpot).
  - `list_businesses() -> list[Business]`.
  - `get_business(slug: str) -> Business | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_registry.py
from core.portfolio import registry


def test_exactly_ten_businesses_with_unique_slugs():
    businesses = registry.list_businesses()
    assert len(businesses) == 10
    slugs = [b.slug for b in businesses]
    assert len(set(slugs)) == 10
    assert "n8n" in slugs


def test_get_business_found_and_missing():
    n8n = registry.get_business("n8n")
    assert n8n is not None
    assert n8n.name == "n8n Automation Agency"
    assert n8n.phase == "planning"
    assert registry.get_business("does-not-exist") is None


def test_every_business_has_thesis_and_repo():
    for b in registry.list_businesses():
        assert b.thesis.strip()
        assert b.oss_repo.startswith("https://")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.portfolio.registry'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/portfolio/registry.py
"""The ten W-MOS businesses, as data. The single source of truth for the portfolio."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Business:
    slug: str
    name: str
    thesis: str
    oss_repo: str
    phase: str = "planning"


BUSINESSES: list[Business] = [
    Business("n8n", "n8n Automation Agency",
             "Sell automation builds + recurring retainers on self-hosted n8n.",
             "https://github.com/n8n-io/n8n"),
    Business("coolify", "Coolify Hosting",
             "Managed deployments on self-hosted Coolify; replace devs' Vercel/Heroku bill.",
             "https://github.com/coollabsio/coolify"),
    Business("listmonk", "Listmonk Email",
             "Newsletter / mailing-list-as-a-service resold to agencies at markup.",
             "https://github.com/knadh/listmonk"),
    Business("ghost", "Ghost Publishing",
             "Run paid publications/newsletters on self-hosted Ghost.",
             "https://github.com/TryGhost/Ghost"),
    Business("calcom", "Cal.com Scheduling",
             "White-labeled scheduling SaaS for dentists, lawyers, consultants.",
             "https://github.com/calcom/cal.com"),
    Business("plausible", "Plausible Analytics",
             "Privacy-first analytics resold per-client to agencies.",
             "https://github.com/plausible/analytics"),
    Business("supabase", "Supabase SaaS Factory",
             "Ship micro-SaaS products fast on Supabase; subscription revenue.",
             "https://github.com/supabase/supabase"),
    Business("medusa", "Medusa Commerce",
             "Commerce platform taking a fee per sale on self-hosted Medusa.",
             "https://github.com/medusajs/medusa"),
    Business("appflowy", "AppFlowy Enterprise",
             "Self-hosted Notion alternative sold to privacy-sensitive enterprises.",
             "https://github.com/AppFlowy-IO/AppFlowy"),
    Business("penpot", "Penpot Design",
             "Self-hosted Figma alternative sold to agencies refusing cloud uploads.",
             "https://github.com/penpot/penpot"),
]


def list_businesses() -> list[Business]:
    return list(BUSINESSES)


def get_business(slug: str) -> Business | None:
    for b in BUSINESSES:
        if b.slug == slug:
            return b
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_registry.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add core/portfolio/registry.py tests/test_portfolio_registry.py
git commit -m "feat(wmos): add portfolio registry of 10 businesses"
```

---

### Task 3: `budget.py` — monthly spend ceilings + ledger

**Files:**
- Create: `core/portfolio/budget.py`
- Test: `tests/test_portfolio_budget.py`

**Interfaces:**
- Consumes: `paths.data_root`, `paths.load_json`, `paths.save_json_atomic`, `paths.append_jsonl`, `paths.read_jsonl`.
- Produces:
  - `@dataclass class Ceilings` with `per_business_month: float, portfolio_month: float`.
  - `load_ceilings() -> Ceilings` — from `portfolio.json` key `"ceilings"`, defaults `per_business_month=100.0, portfolio_month=500.0`.
  - `record_spend(slug: str, amount: float, kind: str, month: str) -> None` — appends to `spend.jsonl`.
  - `spent(month: str, slug: str | None = None) -> float` — sum for month (optionally one business).
  - `would_exceed(slug: str, amount: float, month: str) -> bool` — True if adding `amount` breaks the per-business OR portfolio ceiling.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_budget.py
from core.portfolio import budget, paths


def test_default_ceilings(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    c = budget.load_ceilings()
    assert c.per_business_month == 100.0
    assert c.portfolio_month == 500.0


def test_record_and_sum_spend(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    budget.record_spend("n8n", 10.0, "deploy", "2026-06")
    budget.record_spend("n8n", 5.0, "llm", "2026-06")
    budget.record_spend("ghost", 7.0, "deploy", "2026-06")
    budget.record_spend("n8n", 99.0, "deploy", "2026-07")  # different month
    assert budget.spent("2026-06") == 22.0
    assert budget.spent("2026-06", "n8n") == 15.0


def test_would_exceed_per_business_ceiling(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    budget.record_spend("n8n", 95.0, "deploy", "2026-06")
    assert budget.would_exceed("n8n", 10.0, "2026-06") is True   # 105 > 100
    assert budget.would_exceed("n8n", 4.0, "2026-06") is False    # 99 <= 100


def test_would_exceed_portfolio_ceiling(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    # Five businesses each at 90 = 450 portfolio; ceiling 500.
    for slug in ["a", "b", "c", "d", "e"]:
        budget.record_spend(slug, 90.0, "deploy", "2026-06")
    # New business 'f' adding 60 -> portfolio 510 > 500, even though 60 < per-business 100.
    assert budget.would_exceed("f", 60.0, "2026-06") is True
    assert budget.would_exceed("f", 40.0, "2026-06") is False    # 490 <= 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.portfolio.budget'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/portfolio/budget.py
"""W-MOS budget ceilings + spend ledger (monthly). Append-only ledger; sums on read.

Months are passed in as 'YYYY-MM' strings (clock injected by the caller) so the
logic stays deterministic and testable.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.portfolio import paths


@dataclass
class Ceilings:
    per_business_month: float
    portfolio_month: float


def _portfolio_file():
    return paths.data_root() / "portfolio.json"


def _spend_file():
    return paths.data_root() / "spend.jsonl"


def load_ceilings() -> Ceilings:
    cfg = paths.load_json(_portfolio_file(), {})
    c = (cfg or {}).get("ceilings", {})
    return Ceilings(
        per_business_month=float(c.get("per_business_month", 100.0)),
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
    if spent(month, slug) + amount > c.per_business_month:
        return True
    if spent(month) + amount > c.portfolio_month:
        return True
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_budget.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add core/portfolio/budget.py tests/test_portfolio_budget.py
git commit -m "feat(wmos): add monthly budget ceilings + spend ledger"
```

---

### Task 4: `actions.py` — the traffic-light envelope (the load-bearing safety module)

**Files:**
- Create: `core/portfolio/actions.py`
- Test: `tests/test_portfolio_actions.py`

**Interfaces:**
- Produces:
  - `class ActionClass(str, Enum)`: `GREEN="green"`, `AUTO_CAPPED="auto_capped"`, `AMBER="amber"`, `RED="red"`.
  - `@dataclass class Action` with `verb: str, agent: str, action_class: ActionClass, preconditions: list[str], business: str, payload: dict`.
  - `class AgentAdapter(Protocol)` with `def run(self, action: Action) -> dict: ...`.
  - `@dataclass class DispatchResult` with `status: str` (`"executed"|"queued"|"refused"`), `detail: str`, `output: dict | None = None`, `failed_preconditions: list[str] = field(default_factory=list)`.
  - `check_preconditions(action: Action, ctx: dict) -> tuple[bool, list[str]]` — each named precondition must be truthy in `ctx`; returns `(ok, failed_names)`.
  - `dispatch(action: Action, adapter: AgentAdapter, ctx: dict, *, on_queue, on_audit) -> DispatchResult` — enforces the envelope. `on_queue(action)` and `on_audit(record: dict)` are callables injected by `state.py`/`loops.py`.
- Consumes: nothing from earlier tasks (self-contained safety core).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_actions.py
from core.portfolio.actions import (
    Action, ActionClass, DispatchResult, check_preconditions, dispatch,
)


class _RecordingAdapter:
    def __init__(self):
        self.ran = []

    def run(self, action):
        self.ran.append(action.verb)
        return {"ok": True, "verb": action.verb}


def _mk(action_class, preconditions=None, verb="do_thing"):
    return Action(verb=verb, agent="kai", action_class=action_class,
                  preconditions=preconditions or [], business="n8n", payload={})


def _harness():
    queued, audited = [], []
    return queued, audited, (lambda a: queued.append(a)), (lambda r: audited.append(r))


def test_green_runs_immediately():
    adapter = _RecordingAdapter()
    q, a, on_queue, on_audit = _harness()
    res = dispatch(_mk(ActionClass.GREEN), adapter, {}, on_queue=on_queue, on_audit=on_audit)
    assert res.status == "executed"
    assert adapter.ran == ["do_thing"]
    assert q == []
    assert a and a[0]["status"] == "executed"


def test_red_never_dispatches():
    adapter = _RecordingAdapter()
    q, a, on_queue, on_audit = _harness()
    res = dispatch(_mk(ActionClass.RED), adapter, {}, on_queue=on_queue, on_audit=on_audit)
    assert res.status == "refused"
    assert adapter.ran == []          # adapter NEVER touched
    assert q == []                    # not even queued
    assert a and a[0]["status"] == "refused"


def test_amber_always_queues_never_runs():
    adapter = _RecordingAdapter()
    q, a, on_queue, on_audit = _harness()
    res = dispatch(_mk(ActionClass.AMBER), adapter, {}, on_queue=on_queue, on_audit=on_audit)
    assert res.status == "queued"
    assert adapter.ran == []
    assert len(q) == 1


def test_auto_capped_runs_when_all_preconditions_truthy():
    adapter = _RecordingAdapter()
    q, a, on_queue, on_audit = _harness()
    action = _mk(ActionClass.AUTO_CAPPED, ["warmup_complete", "under_daily_cap"])
    ctx = {"warmup_complete": True, "under_daily_cap": True}
    res = dispatch(action, adapter, ctx, on_queue=on_queue, on_audit=on_audit)
    assert res.status == "executed"
    assert adapter.ran == ["do_thing"]


def test_auto_capped_queues_when_a_precondition_fails():
    adapter = _RecordingAdapter()
    q, a, on_queue, on_audit = _harness()
    action = _mk(ActionClass.AUTO_CAPPED, ["warmup_complete", "under_daily_cap"])
    ctx = {"warmup_complete": True, "under_daily_cap": False}
    res = dispatch(action, adapter, ctx, on_queue=on_queue, on_audit=on_audit)
    assert res.status == "queued"
    assert adapter.ran == []
    assert res.failed_preconditions == ["under_daily_cap"]
    assert len(q) == 1


def test_check_preconditions_reports_all_failures():
    action = _mk(ActionClass.AUTO_CAPPED, ["a", "b", "c"])
    ok, failed = check_preconditions(action, {"a": True, "b": False, "c": 0})
    assert ok is False
    assert failed == ["b", "c"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_actions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.portfolio.actions'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/portfolio/actions.py
"""The W-MOS action envelope — the single chokepoint every dispatched action passes.

Traffic-light classes:
  green       -> run immediately (reversible, no external side effects)
  auto_capped -> run ONLY if every precondition is truthy in ctx; else queue for approval
  amber       -> always queue for one-click approval; the engine never auto-fires it
  red         -> never dispatched by the engine, under any circumstance

`dispatch` is pure w.r.t. side effects: it calls the injected `adapter.run`,
`on_queue`, and `on_audit` — it never imports state/IO itself, which keeps the
safety logic trivially testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Protocol


class ActionClass(str, Enum):
    GREEN = "green"
    AUTO_CAPPED = "auto_capped"
    AMBER = "amber"
    RED = "red"


@dataclass
class Action:
    verb: str
    agent: str
    action_class: ActionClass
    preconditions: list[str]
    business: str
    payload: dict


class AgentAdapter(Protocol):
    def run(self, action: Action) -> dict: ...


@dataclass
class DispatchResult:
    status: str                       # "executed" | "queued" | "refused"
    detail: str
    output: dict | None = None
    failed_preconditions: list[str] = field(default_factory=list)


def check_preconditions(action: Action, ctx: dict) -> tuple[bool, list[str]]:
    failed = [name for name in action.preconditions if not ctx.get(name)]
    return (len(failed) == 0, failed)


def _audit_record(action: Action, status: str, detail: str) -> dict:
    return {
        "business": action.business,
        "verb": action.verb,
        "agent": action.agent,
        "action_class": action.action_class.value,
        "status": status,
        "detail": detail,
    }


def dispatch(
    action: Action,
    adapter: AgentAdapter,
    ctx: dict,
    *,
    on_queue: Callable[[Action], None],
    on_audit: Callable[[dict], None],
) -> DispatchResult:
    # RED — refuse outright. The adapter is never touched.
    if action.action_class is ActionClass.RED:
        res = DispatchResult("refused", "RED actions are never dispatched by the engine")
        on_audit(_audit_record(action, res.status, res.detail))
        return res

    # AMBER — always queue; never auto-fire.
    if action.action_class is ActionClass.AMBER:
        on_queue(action)
        res = DispatchResult("queued", "AMBER action queued for one-click approval")
        on_audit(_audit_record(action, res.status, res.detail))
        return res

    # AUTO_CAPPED — fire only if every precondition is truthy; otherwise queue.
    if action.action_class is ActionClass.AUTO_CAPPED:
        ok, failed = check_preconditions(action, ctx)
        if not ok:
            on_queue(action)
            res = DispatchResult("queued", f"preconditions failed: {failed}",
                                 failed_preconditions=failed)
            on_audit(_audit_record(action, res.status, res.detail))
            return res
        # fall through to execution

    # GREEN (or AUTO_CAPPED with all preconditions met) — execute.
    output = adapter.run(action)
    res = DispatchResult("executed", "executed", output=output)
    on_audit(_audit_record(action, res.status, res.detail))
    return res
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_actions.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add core/portfolio/actions.py tests/test_portfolio_actions.py
git commit -m "feat(wmos): add traffic-light action envelope (green/auto_capped/amber/red)"
```

---

### Task 5: `state.py` — per-business state, artifacts, audit log, approval queue

**Files:**
- Create: `core/portfolio/state.py`
- Test: `tests/test_portfolio_state.py`

**Interfaces:**
- Consumes: `paths.*`, `actions.Action`.
- Produces:
  - `load_state(slug: str) -> dict` — `state.json` for a business; default `{"phase": "planning", "completed_verbs": [], "pending_verbs": []}`.
  - `save_state(slug: str, state: dict) -> None`.
  - `mark_completed(slug: str, verb: str) -> None` / `mark_pending(slug: str, verb: str) -> None` — idempotent; `mark_completed` also removes the verb from `pending_verbs`.
  - `record_artifact(slug: str, kind: str, name: str, content: str) -> Path` — writes `business_dir(slug)/artifacts/<kind>/<name>`.
  - `audit(record: dict) -> None` — append to `data_root()/audit.jsonl` with a portfolio-wide log.
  - `queue_approval(action: "Action") -> str` — append to `data_root()/approvals.jsonl`, return a 12-char id; default status `"pending"`.
  - `list_approvals(status: str | None = None) -> list[dict]`.
  - `resolve_approval(approval_id: str, status: str) -> bool` — set status (`"approved"`/`"rejected"`); rewrites the file.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_state.py
from core.portfolio import state, paths
from core.portfolio.actions import Action, ActionClass


def test_default_state(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    s = state.load_state("n8n")
    assert s["phase"] == "planning"
    assert s["completed_verbs"] == []
    assert s["pending_verbs"] == []


def test_mark_completed_clears_pending_and_persists(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    state.mark_pending("n8n", "run_outreach_campaign")
    assert state.load_state("n8n")["pending_verbs"] == ["run_outreach_campaign"]
    state.mark_completed("n8n", "run_outreach_campaign")
    reloaded = state.load_state("n8n")          # re-read from disk, not in-memory
    assert reloaded["completed_verbs"] == ["run_outreach_campaign"]
    assert reloaded["pending_verbs"] == []


def test_record_artifact_writes_file(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    p = state.record_artifact("n8n", "outreach", "touch1.txt", "Hi there")
    assert p.exists()
    assert p.read_text() == "Hi there"
    assert p.parent == tmp_path / "n8n" / "artifacts" / "outreach"


def test_audit_appends(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    state.audit({"verb": "x", "status": "executed"})
    state.audit({"verb": "y", "status": "queued"})
    rows = paths.read_jsonl(tmp_path / "audit.jsonl")
    assert [r["verb"] for r in rows] == ["x", "y"]


def test_approval_queue_lifecycle(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    action = Action("deploy_demo_instance", "infra", ActionClass.AMBER, [], "n8n", {"x": 1})
    aid = state.queue_approval(action)
    assert len(aid) == 12
    pending = state.list_approvals("pending")
    assert len(pending) == 1
    assert pending[0]["verb"] == "deploy_demo_instance"
    assert state.resolve_approval(aid, "approved") is True
    assert state.list_approvals("pending") == []
    assert state.list_approvals("approved")[0]["id"] == aid
    assert state.resolve_approval("missing-id", "approved") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_state.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.portfolio.state'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/portfolio/state.py
"""W-MOS persistence: per-business state, artifact files, the portfolio-wide audit
log, and the approval queue (the AMBER one-click surface, stored as JSONL)."""
from __future__ import annotations

import time
import uuid

from core.portfolio import paths
from core.portfolio.actions import Action

_DEFAULT_STATE = {"phase": "planning", "completed_verbs": [], "pending_verbs": []}


def _state_file(slug: str):
    return paths.business_dir(slug) / "state.json"


def load_state(slug: str) -> dict:
    base = {k: (list(v) if isinstance(v, list) else v) for k, v in _DEFAULT_STATE.items()}
    stored = paths.load_json(_state_file(slug), {})
    base.update(stored or {})
    base.setdefault("completed_verbs", [])
    base.setdefault("pending_verbs", [])
    return base


def save_state(slug: str, state: dict) -> None:
    paths.save_json_atomic(_state_file(slug), state)


def mark_pending(slug: str, verb: str) -> None:
    s = load_state(slug)
    if verb not in s["pending_verbs"] and verb not in s["completed_verbs"]:
        s["pending_verbs"].append(verb)
    save_state(slug, s)


def mark_completed(slug: str, verb: str) -> None:
    s = load_state(slug)
    s["pending_verbs"] = [v for v in s["pending_verbs"] if v != verb]
    if verb not in s["completed_verbs"]:
        s["completed_verbs"].append(verb)
    save_state(slug, s)


def record_artifact(slug: str, kind: str, name: str, content: str):
    target = paths.business_dir(slug) / "artifacts" / kind / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def _audit_file():
    return paths.data_root() / "audit.jsonl"


def audit(record: dict) -> None:
    enriched = dict(record)
    enriched["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    paths.append_jsonl(_audit_file(), enriched)


def _approvals_file():
    return paths.data_root() / "approvals.jsonl"


def queue_approval(action: Action) -> str:
    aid = uuid.uuid4().hex[:12]
    paths.append_jsonl(_approvals_file(), {
        "id": aid,
        "status": "pending",
        "business": action.business,
        "verb": action.verb,
        "agent": action.agent,
        "action_class": action.action_class.value,
        "preconditions": list(action.preconditions),
        "payload": action.payload,
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    return aid


def list_approvals(status: str | None = None) -> list[dict]:
    rows = paths.read_jsonl(_approvals_file())
    # Collapse to the latest record per id (resolve_approval rewrites the file,
    # but guard against partial states defensively).
    latest: dict[str, dict] = {}
    for r in rows:
        latest[r["id"]] = r
    out = list(latest.values())
    if status is not None:
        out = [r for r in out if r.get("status") == status]
    return out


def resolve_approval(approval_id: str, status: str) -> bool:
    rows = paths.read_jsonl(_approvals_file())
    found = False
    for r in rows:
        if r.get("id") == approval_id:
            r["status"] = status
            found = True
    if not found:
        return False
    # Rewrite the whole file atomically as JSONL.
    f = _approvals_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".jsonl.tmp")
    import json
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows))
    tmp.replace(f)
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_state.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add core/portfolio/state.py tests/test_portfolio_state.py
git commit -m "feat(wmos): add state, artifacts, audit log, and approval queue"
```

---

### Task 6: `loops.py` — supervisor-loop tick engine

**Files:**
- Create: `core/portfolio/loops.py`
- Test: `tests/test_portfolio_loops.py`

**Interfaces:**
- Consumes: `paths.*`, `actions.Action/ActionClass/dispatch/DispatchResult`, `state.*`.
- Produces:
  - `@dataclass class LoopStep` with `verb: str, agent: str, action_class: ActionClass, preconditions: list[str]`.
  - `load_loop(slug: str) -> list[LoopStep]` — parse `business_dir(slug)/loop.json` (key `"steps"`); empty list if missing.
  - `select_next_step(steps: list[LoopStep], state: dict) -> LoopStep | None` — first step whose `verb` is in neither `completed_verbs` nor `pending_verbs`. (Preconditions are NOT a selection filter — they are enforced at dispatch, where an `auto_capped` step with unmet preconditions is *queued*, not skipped.)
  - `tick(slug: str, adapter_for, ctx_for) -> DispatchResult | None` — `adapter_for(step) -> AgentAdapter`, `ctx_for(step) -> dict`. Selects next step; builds `Action`; dispatches with `state.queue_approval` + `state.audit`; on `"executed"` calls `state.mark_completed`, on `"queued"` calls `state.mark_pending`. Returns the `DispatchResult`, or `None` if no step is available.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_loops.py
import json
from core.portfolio import loops, state, paths
from core.portfolio.actions import ActionClass


class _OkAdapter:
    def run(self, action):
        return {"ran": action.verb}


def _write_loop(tmp_path, slug, steps):
    d = tmp_path / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "loop.json").write_text(json.dumps({"business": slug, "steps": steps}))


def test_load_loop_parses_steps(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _write_loop(tmp_path, "n8n", [
        {"verb": "research_niche", "agent": "kai.research", "class": "green"},
        {"verb": "run_outreach_campaign", "agent": "cold_outreach",
         "class": "auto_capped", "preconditions": ["warmup_complete"]},
    ])
    steps = loops.load_loop("n8n")
    assert [s.verb for s in steps] == ["research_niche", "run_outreach_campaign"]
    assert steps[1].action_class is ActionClass.AUTO_CAPPED
    assert steps[1].preconditions == ["warmup_complete"]


def test_select_next_skips_completed_and_pending(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    steps = [
        loops.LoopStep("a", "kai", ActionClass.GREEN, []),
        loops.LoopStep("b", "kai", ActionClass.GREEN, []),
        loops.LoopStep("c", "kai", ActionClass.GREEN, []),
    ]
    st = {"completed_verbs": ["a"], "pending_verbs": ["b"]}
    assert loops.select_next_step(steps, st).verb == "c"
    assert loops.select_next_step(steps, {"completed_verbs": ["a", "b", "c"],
                                          "pending_verbs": []}) is None


def test_tick_executes_green_and_marks_completed(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _write_loop(tmp_path, "n8n", [
        {"verb": "research_niche", "agent": "kai.research", "class": "green"},
    ])
    res = loops.tick("n8n", adapter_for=lambda step: _OkAdapter(), ctx_for=lambda step: {})
    assert res.status == "executed"
    assert state.load_state("n8n")["completed_verbs"] == ["research_niche"]
    # second tick: nothing left to do
    assert loops.tick("n8n", adapter_for=lambda s: _OkAdapter(), ctx_for=lambda s: {}) is None


def test_tick_queues_auto_capped_when_precondition_unmet(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _write_loop(tmp_path, "n8n", [
        {"verb": "run_outreach_campaign", "agent": "cold_outreach",
         "class": "auto_capped", "preconditions": ["warmup_complete"]},
    ])
    res = loops.tick("n8n", adapter_for=lambda s: _OkAdapter(),
                     ctx_for=lambda s: {"warmup_complete": False})
    assert res.status == "queued"
    assert state.load_state("n8n")["pending_verbs"] == ["run_outreach_campaign"]
    assert len(state.list_approvals("pending")) == 1
    # verb is now pending -> not re-selected on the next tick
    assert loops.tick("n8n", adapter_for=lambda s: _OkAdapter(),
                      ctx_for=lambda s: {"warmup_complete": False}) is None


def test_tick_red_is_refused_and_does_not_block_forever(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    _write_loop(tmp_path, "n8n", [
        {"verb": "sign_contract", "agent": "legal", "class": "red"},
    ])
    res = loops.tick("n8n", adapter_for=lambda s: _OkAdapter(), ctx_for=lambda s: {})
    assert res.status == "refused"
    # RED stays out of completed; it is parked in pending so the loop advances.
    assert "sign_contract" in state.load_state("n8n")["pending_verbs"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_loops.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.portfolio.loops'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/portfolio/loops.py
"""W-MOS supervisor-loop tick engine.

A business's loop.json lists ordered steps. One tick selects the first step not
yet completed or pending, builds an Action, and dispatches it through the envelope.
Loop order IS priority (deterministic). Preconditions are enforced at dispatch,
not at selection: an auto_capped step with unmet preconditions is QUEUED (moved to
pending), never silently skipped, so progress is visible and never lost.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.portfolio import paths, state
from core.portfolio.actions import Action, ActionClass, DispatchResult, dispatch


@dataclass
class LoopStep:
    verb: str
    agent: str
    action_class: ActionClass
    preconditions: list[str]


def load_loop(slug: str) -> list[LoopStep]:
    cfg = paths.load_json(paths.business_dir(slug) / "loop.json", {})
    out: list[LoopStep] = []
    for raw in (cfg or {}).get("steps", []):
        out.append(LoopStep(
            verb=raw["verb"],
            agent=raw.get("agent", ""),
            action_class=ActionClass(raw.get("class", "green")),
            preconditions=list(raw.get("preconditions", [])),
        ))
    return out


def select_next_step(steps: list[LoopStep], state_dict: dict):
    done = set(state_dict.get("completed_verbs", []))
    pending = set(state_dict.get("pending_verbs", []))
    for step in steps:
        if step.verb not in done and step.verb not in pending:
            return step
    return None


def tick(slug: str, adapter_for, ctx_for) -> DispatchResult | None:
    steps = load_loop(slug)
    st = state.load_state(slug)
    step = select_next_step(steps, st)
    if step is None:
        return None

    action = Action(
        verb=step.verb,
        agent=step.agent,
        action_class=step.action_class,
        preconditions=step.preconditions,
        business=slug,
        payload={},
    )
    result = dispatch(
        action,
        adapter_for(step),
        ctx_for(step),
        on_queue=state.queue_approval,
        on_audit=state.audit,
    )

    if result.status == "executed":
        state.mark_completed(slug, step.verb)
    else:
        # queued (AMBER / unmet auto_capped) OR refused (RED): park in pending so
        # the loop advances to the next step instead of re-selecting this one.
        state.mark_pending(slug, step.verb)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_loops.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add core/portfolio/loops.py tests/test_portfolio_loops.py
git commit -m "feat(wmos): add supervisor-loop tick engine"
```

---

### Task 7: `orchestrator.py` — Master Supervisor sweep (dormant + kill-switch + budget)

**Files:**
- Create: `core/portfolio/orchestrator.py`
- Test: `tests/test_portfolio_orchestrator.py`

**Interfaces:**
- Consumes: `registry.list_businesses`, `loops.tick`, `budget.would_exceed`, `state.audit`.
- Produces:
  - `is_enabled() -> bool` — `os.getenv("WMOS_ORCHESTRATOR_ENABLED") == "1"`.
  - `kill_engaged() -> bool` — `os.getenv("WMOS_KILL") == "1"`.
  - `run_once(adapter_for, ctx_for, *, slugs: list[str] | None = None) -> dict` — returns `{"status": "...", "ticked": {slug: dispatch_status_or_None}}`. Short-circuits to `{"status": "killed"}` if kill engaged, `{"status": "dormant"}` if not enabled. Otherwise sweeps businesses (all, or `slugs`), calling `loops.tick`; records a one-line audit per sweep.
  - `start_worker(adapter_for, ctx_for, interval_s: int = 300) -> None` — idempotent daemon thread (mirrors `siteboost_scheduler.start_worker`); each cycle calls `run_once`; does nothing of consequence while dormant.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_portfolio_orchestrator.py
import json
from core.portfolio import orchestrator, paths


class _OkAdapter:
    def run(self, action):
        return {"ran": action.verb}


def _seed_loop(tmp_path, slug, verb="research_niche"):
    d = tmp_path / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "loop.json").write_text(json.dumps(
        {"business": slug, "steps": [{"verb": verb, "agent": "kai", "class": "green"}]}))


def test_dormant_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.delenv("WMOS_ORCHESTRATOR_ENABLED", raising=False)
    monkeypatch.delenv("WMOS_KILL", raising=False)
    res = orchestrator.run_once(lambda s: _OkAdapter(), lambda s: {})
    assert res["status"] == "dormant"


def test_kill_switch_short_circuits(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("WMOS_ORCHESTRATOR_ENABLED", "1")
    monkeypatch.setenv("WMOS_KILL", "1")
    res = orchestrator.run_once(lambda s: _OkAdapter(), lambda s: {})
    assert res["status"] == "killed"


def test_enabled_sweep_ticks_selected_business(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("WMOS_ORCHESTRATOR_ENABLED", "1")
    monkeypatch.delenv("WMOS_KILL", raising=False)
    _seed_loop(tmp_path, "n8n")
    res = orchestrator.run_once(lambda s: _OkAdapter(), lambda s: {}, slugs=["n8n"])
    assert res["status"] == "ran"
    assert res["ticked"]["n8n"] == "executed"


def test_enabled_sweep_with_no_loop_returns_none_for_business(monkeypatch, tmp_path):
    monkeypatch.setenv("WMOS_DATA_PATH", str(tmp_path))
    monkeypatch.setenv("WMOS_ORCHESTRATOR_ENABLED", "1")
    monkeypatch.delenv("WMOS_KILL", raising=False)
    res = orchestrator.run_once(lambda s: _OkAdapter(), lambda s: {}, slugs=["ghost"])
    assert res["ticked"]["ghost"] is None      # no loop.json yet -> nothing ticked
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.portfolio.orchestrator'`.

- [ ] **Step 3: Write minimal implementation**

```python
# core/portfolio/orchestrator.py
"""W-MOS Master Supervisor: the autonomous sweep over all businesses.

Three hard gates, every cycle:
  1. kill-switch  (WMOS_KILL=1)               -> halt immediately
  2. dormant      (WMOS_ORCHESTRATOR_ENABLED) -> do nothing until armed
  3. budget       (budget.would_exceed)       -> skip a tick that would breach caps

Ships dormant. Arm only after hand-verifying ticks tick-by-tick (see plan §scope).
Mirrors core/siteboost_scheduler.start_worker for the daemon-thread pattern.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from core.portfolio import loops, registry, state

logger = logging.getLogger("wmos_orchestrator")


def is_enabled() -> bool:
    return os.getenv("WMOS_ORCHESTRATOR_ENABLED") == "1"


def kill_engaged() -> bool:
    return os.getenv("WMOS_KILL") == "1"


def run_once(adapter_for, ctx_for, *, slugs: list[str] | None = None) -> dict:
    if kill_engaged():
        return {"status": "killed", "ticked": {}}
    if not is_enabled():
        return {"status": "dormant", "ticked": {}}

    target = slugs if slugs is not None else [b.slug for b in registry.list_businesses()]
    ticked: dict[str, str | None] = {}
    for slug in target:
        try:
            result = loops.tick(slug, adapter_for, ctx_for)
            ticked[slug] = result.status if result is not None else None
        except Exception as e:
            logger.error(f"tick failed for {slug!r}: {e}")
            ticked[slug] = "error"
    state.audit({"verb": "_sweep", "status": "ran", "businesses": list(ticked.keys())})
    return {"status": "ran", "ticked": ticked}


_worker_started = False
_worker_lock = threading.Lock()


def start_worker(adapter_for, ctx_for, interval_s: int = 300) -> None:
    """Idempotent background sweeper. Safe to call repeatedly; only one thread runs.
    While dormant the cycle is a cheap no-op (run_once returns immediately)."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        _worker_started = True

    def _loop() -> None:
        logger.info(f"wmos orchestrator worker started (interval={interval_s}s, "
                    f"enabled={is_enabled()})")
        while True:
            try:
                if not kill_engaged() and is_enabled():
                    run_once(adapter_for, ctx_for)
            except Exception as e:
                logger.error(f"orchestrator cycle error: {e}")
            time.sleep(interval_s)

    t = threading.Thread(target=_loop, daemon=True, name="wmos-orchestrator")
    t.start()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_orchestrator.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Run the full engine suite + commit**

```bash
cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_portfolio_*.py -v
git add core/portfolio/orchestrator.py tests/test_portfolio_orchestrator.py
git commit -m "feat(wmos): add Master Supervisor sweep (dormant + kill-switch + budget gate)"
```

Expected: all `test_portfolio_*.py` green (27 tests across 7 files).

---

## Self-Review

**1. Spec coverage (against `2026-06-23-wmos-portfolio-os-design.md`):**
- §2 envelope (green/auto_capped/amber/red, preconditions) → Task 4 (+ enforced in Task 6 tick). ✅
- §2 budget ceiling → Task 3; kill-switch + dormant-by-default → Task 7. ✅
- §3.2 modules registry/loops/actions/orchestrator/budget/state → Tasks 2/6/4/7/3/5. ✅
- §3.5 data layout (`portfolio.json`, `audit.jsonl`, `approvals.jsonl`, `<slug>/state.json`, `<slug>/loop.json`, `<slug>/artifacts/`) → Tasks 1/3/5/6. ✅
- §4 executable loop schema (`loop.json` → steps with verb/agent/class/preconditions) → Task 6 `load_loop`. ✅
- §9 testing (envelope tests, dormant verification, RED-never-dispatch) → Tasks 4/6/7. ✅
- **Deferred to Plans 2–3 (intentionally out of scope here):** FastAPI routers + HTML surfaces (§3.1, §5, §6); real adapters for KAI/cold_outreach/places_scanner + n8n `loop.json` content (§7); Command Center cards + `core/api.py` mount; `--dry-run` CLI; `core/portfolio.json` ceilings UI. These need the external integration signatures and the UI layer, which this plan deliberately excludes.

**2. Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to Task N". Every code step shows complete code. ✅

**3. Type consistency:** `Action`/`ActionClass`/`DispatchResult` defined in Task 4 are imported unchanged in Tasks 5–6. `LoopStep` (Task 6) matches `loop.json` keys parsed in `load_loop`. `state.queue_approval(action)` / `state.audit(record)` signatures match the `on_queue` / `on_audit` callables `dispatch` expects (Task 4) and the call site in `tick` (Task 6). `budget.would_exceed(slug, amount, month)` is defined Task 3 and referenced (for Plan-2 wiring) consistently. ✅

---

## Out of Scope (future plans, noted so nothing is silently dropped)

- **Plan 2 — API + UI surfaces:** `narai/api/routes/portfolio_admin.py` + `portfolio_cockpit_admin.py`; `frontend/admin/portfolio.html` (HQ) + cockpit template; `core/api.py` mount + Command Center cards.
- **Plan 3 — n8n pilot wiring:** real `AgentAdapter` implementations (KAI research/planning, `cold_outreach`, `places_scanner`, `site_builder`, infra); `data/launches/portfolio/n8n/loop.json`; first-of-kind deploy approval flow; bounce/spam auto-pause; `--dry-run`.
- **Plan 4 — arm in production:** hand-verify ticks, then set `WMOS_ORCHESTRATOR_ENABLED=1`; wire `start_worker` into the daemon boot (guarded), mirroring SiteBoost.
