# KAI Startup Factory — F2c (Carry-overs + Opt-in Real-Cycle Wiring) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the F1/F2b carry-over fixes (kill-criteria retry, budget pre-emption, security→known_issues, gh-PR idempotency, task-id sanitizing, type annotations) and add an **opt-in real-cycle wrapper** that composes the F2b worktree lifecycle around a real `run_cycle` — the mock path stays the default; nothing is armed for autonomous nightly runs (that's F3).

**Architecture:** Small, surgical edits to `factory/{pipeline,state,budget,pr,runner}.py` plus a new `factory/cycle.py` (worktree-lifecycle wrapper) and a `cli.py --real` opt-in. Everything remains testable with real local git + fake `claude`/`gh` (no network, $0). Default `run_cycle`/`run_once`/`cli tick` behavior is unchanged (mock runner).

**Tech Stack:** Python 3.11 stdlib, `pytest`. Reuses `factory.{worktree,gates,pr,roles,state,project}`. No new pip packages.

## Global Constraints

- Python 3.11, stdlib only. No new pip packages. `from __future__ import annotations`.
- Do NOT change the default (mock) behavior of `run_cycle`, `scheduler.run_once`, or `cli.tick`. The real runner + worktree lifecycle is strictly opt-in.
- Determinism preserved: time enters via `now_iso`; the worktree wrapper takes `now_iso` too.
- Reuse F2b: `factory.worktree` (`ensure_clone`, `prepare`, `cleanup`, `branch_name`), `factory.gates`, `factory.pr`, `factory.roles.estimated_cost`. Do not modify `core.portfolio`.
- Safety unchanged: fail-closed gates, branch-limited push, scoped Bash. F2c must not weaken any of it.
- **Concurrency note:** `_apexdeploy` is receiving concurrent non-factory commits; commit with `git add <specific files>` only (never `-A`), and review each task via `<commit>^..<commit>`.
- Run tests with `python -m pytest <path> -v` **from the repo root** `/Volumes/Wheellsverse/wheellsverse-bots` (cwd-on-path; no pytest config).

---

### Task 1: Kill-criteria — retry blocked tasks until blocked_red

**Files:**
- Modify: `factory/state.py` (add `requeue_oldest_blocked`), `factory/pipeline.py` (call it in `run_cycle`)
- Test: `tests/test_factory_kill_criteria.py`

**Interfaces:**
- Consumes: `factory.state.load_backlog/save_backlog`, `factory.project`.
- Produces:
  - `state.requeue_oldest_blocked(slug) -> str | None` — reset the FIRST task with status `"blocked"` back to `"pending"` (clear `cycle_id`); return its id, or `None` if none blocked. Serialized under `_CLAIM_LOCK`.
  - `run_cycle` change: after `reclaim_orphans`, if the project phase is not `"blocked_red"` and `next_ready_task` is `None`, call `requeue_oldest_blocked(slug)` so a blocked task is re-attempted. Each failed retry `bump_failure`s (existing) → at N=3 the project flips `blocked_red` (existing) → `list_active` excludes it (existing). Self-limiting.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_kill_criteria.py
import pytest
from factory import pipeline, state, project as P


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


class _AlwaysBlocksRunner:
    """Fails the security hard-gate every cycle so the task always blocks."""
    def run(self, action):
        ok = not (action.verb == "security")
        return {"ok": ok, "cost_usd": 0.0, "output": "", "pr_url": None}


def _seed(slug="a"):
    P.upsert_project(P.Project(slug=slug, name=slug, repo_url="x"))
    state.save_backlog(slug, [{"id": "t1", "title": "x", "priority": 1, "status": "pending",
                               "depends_on": [], "source": "seed", "cycle_id": None}])


def test_requeue_oldest_blocked_resets_first_blocked():
    state.save_backlog("a", [
        {"id": "t1", "title": "x", "priority": 1, "status": "blocked", "depends_on": [],
         "source": "s", "cycle_id": "c0"},
        {"id": "t2", "title": "y", "priority": 1, "status": "blocked", "depends_on": [],
         "source": "s", "cycle_id": "c0"},
    ])
    assert state.requeue_oldest_blocked("a") == "t1"
    tasks = {t["id"]: t for t in state.load_backlog("a")}
    assert tasks["t1"]["status"] == "pending" and tasks["t1"]["cycle_id"] is None
    assert tasks["t2"]["status"] == "blocked"  # only the first is requeued


def test_requeue_none_when_no_blocked():
    state.save_backlog("a", [{"id": "t1", "title": "x", "priority": 1, "status": "done",
                              "depends_on": [], "source": "s", "cycle_id": None}])
    assert state.requeue_oldest_blocked("a") is None


def test_persistent_failure_escalates_to_blocked_red():
    _seed()
    runner = _AlwaysBlocksRunner()
    # cycle 1: t1 pending -> claimed -> blocks (failures=1)
    assert pipeline.run_cycle("a", runner, now_iso="2026-07-01T02:00:00Z").status == "blocked"
    assert P.get_project("a").consecutive_failures == 1
    # cycles 2 and 3: blocked t1 is requeued and retried -> blocks again (failures 2, 3)
    assert pipeline.run_cycle("a", runner, now_iso="2026-07-02T02:00:00Z").status == "blocked"
    assert pipeline.run_cycle("a", runner, now_iso="2026-07-03T02:00:00Z").status == "blocked"
    assert P.get_project("a").phase == "blocked_red"
    assert "a" not in [p.slug for p in P.list_active()]  # excluded from ticking
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_kill_criteria.py -v`
Expected: FAIL — `AttributeError: module 'factory.state' has no attribute 'requeue_oldest_blocked'` / escalation test fails (blocked task never retried).

- [ ] **Step 3: Implement**

Add to `factory/state.py` (near `reclaim_orphans`, reusing the module `_CLAIM_LOCK`):
```python
def requeue_oldest_blocked(slug: str) -> str | None:
    """Reset the first 'blocked' task back to 'pending' so it is re-attempted next
    cycle. Returns its id, or None if nothing is blocked."""
    with _CLAIM_LOCK:
        tasks = load_backlog(slug)
        for t in tasks:
            if t.get("status") == "blocked":
                t["status"] = "pending"
                t["cycle_id"] = None
                save_backlog(slug, tasks)
                return t["id"]
    return None
```

In `factory/pipeline.py` `run_cycle`, right after the `state.reclaim_orphans(slug, cid)` line and BEFORE the stopping-condition block, add:
```python
    # Kill-criteria: retry a blocked task (unless the project is already flagged red).
    if projects.get_project(slug) is not None and projects.get_project(slug).phase != "blocked_red":
        if state.next_ready_task(slug) is None:
            state.requeue_oldest_blocked(slug)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_kill_criteria.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/state.py factory/pipeline.py tests/test_factory_kill_criteria.py
git commit -m "feat(factory): kill-criteria — retry blocked tasks until blocked_red"
```

---

### Task 2: Budget pre-emption + runner type annotations

**Files:**
- Modify: `factory/pipeline.py` (est-cost reservation + annotation), `factory/scheduler.py` (annotation)
- Test: `tests/test_factory_budget_preempt.py`

**Interfaces:**
- Consumes: `factory.roles.estimated_cost`, `factory.roles.ROLES`.
- Produces: the budget gate reserves the upcoming stage's estimated cost instead of `0.0`, so it pre-empts the overrun. `run_cycle(slug, runner: AgentAdapter, ...)` and `run_once(runner: AgentAdapter, ...)` gain the `AgentAdapter` annotation (imported from `core.portfolio.actions`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_budget_preempt.py
import pytest
from factory import pipeline, state, budget, project as P, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path))


class _OkRunner:
    def run(self, action):
        return {"ok": True, "cost_usd": 0.0, "output": "",
                "pr_url": "https://gh/pr/1" if action.verb == "commit_pr" else None}


def _seed(slug="a"):
    P.upsert_project(P.Project(slug=slug, name=slug, repo_url="x"))
    state.save_backlog(slug, [{"id": "t1", "title": "x", "priority": 1, "status": "pending",
                               "depends_on": [], "source": "seed", "cycle_id": None}])


def test_budget_gate_preempts_using_estimated_stage_cost():
    _seed()
    # ceiling below the first architect stage's estimated cost (opus ~1.0) so the
    # gate must PRE-EMPT (queue) before running the stage, with zero prior spend.
    paths.save_json_atomic(paths.data_root() / "portfolio.json",
                           {"ceilings": {"per_project_month": 0.5, "portfolio_month": 100}})
    res = pipeline.run_cycle("a", _OkRunner(), now_iso="2026-07-01T02:00:00Z")
    assert res.status == "budget_queued"
    # task released back to pending (not left in_progress)
    assert state.load_backlog("a")[0]["status"] == "pending"


def test_budget_gate_allows_when_ceiling_covers_estimate():
    _seed()
    paths.save_json_atomic(paths.data_root() / "portfolio.json",
                           {"ceilings": {"per_project_month": 1000, "portfolio_month": 1000}})
    res = pipeline.run_cycle("a", _OkRunner(), now_iso="2026-07-01T02:00:00Z")
    assert res.status == "completed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_budget_preempt.py -v`
Expected: FAIL — `test_budget_gate_preempts...` fails: with `amount=0.0`, `would_exceed` is False at zero prior spend, so the cycle runs to `completed` instead of `budget_queued`.

- [ ] **Step 3: Implement**

In `factory/pipeline.py`, add the import near the top:
```python
from core.portfolio.actions import Action, ActionClass, AgentAdapter, dispatch
from factory import budget, project as projects, roles as _roles, state
```
Change the `run_cycle` signature annotation:
```python
def run_cycle(slug: str, runner: AgentAdapter, *, now_iso: str, ctx: dict | None = None) -> CycleResult:
```
Replace the budget-gate block inside the stage loop:
```python
        if stage.action_class in (ActionClass.GREEN, ActionClass.AUTO_CAPPED):
            role = _roles.ROLES.get(stage.role)
            est = _roles.estimated_cost(role.model) if role else _roles.estimated_cost("sonnet")
            if budget.would_exceed(slug, est, month):
                state.release_task(slug, task["id"])
                return CycleResult(slug, cid, task["id"], "budget_queued",
                                   stages_out, cost_usd=cost, note="budget ceiling")
```

In `factory/scheduler.py`, add the import and annotate `run_once`:
```python
from core.portfolio.actions import AgentAdapter
```
```python
def run_once(runner: AgentAdapter, *, now_iso: str, slugs: list[str] | None = None) -> dict:
```
(If `AgentAdapter` isn't already importable that way, confirm `core.portfolio.actions.AgentAdapter` exists — it does, it's the Protocol.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_budget_preempt.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/pipeline.py factory/scheduler.py tests/test_factory_budget_preempt.py
git commit -m "feat(factory): budget pre-emption via estimated stage cost + runner annotations"
```

---

### Task 3: Security findings → known_issues.jsonl + runner security-verb test

**Files:**
- Modify: `factory/runner.py` (security branch appends findings)
- Test: `tests/test_factory_runner_security.py`

**Interfaces:**
- Consumes: `factory.state.append_known_issue`, `factory.gates.run_security`.
- Produces: the runner's `security` verb, when the gate reports leaks, appends one record per run to `known_issues.jsonl` via `state.append_known_issue(slug, {...})`; the runner return shape is unchanged (`{ok, cost_usd:0.0, output:detail, pr_url:None}`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_runner_security.py
import subprocess
import pytest
from core.portfolio.actions import Action, ActionClass
from factory import runner, paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path / "fx"))


def _repo(tmp_path):
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], capture_output=True, check=True)
    return tmp_path


def _action(verb="security", agent="security"):
    return Action(verb=verb, agent=agent, action_class=ActionClass.GREEN, preconditions=[],
                  business="acme", payload={"task": {"id": "t1", "title": "x"}, "cycle_id": "c1"})


def test_security_clean_ok_and_no_issue(tmp_path):
    wt = _repo(tmp_path / "wt")
    (wt / "ok.py").write_text("x = 1\n")
    r = runner.ClaudeCliRunner(wt)
    out = r.run(_action())
    assert out["ok"] is True and out["pr_url"] is None
    assert not (paths.project_dir("acme") / "known_issues.jsonl").exists()


@pytest.mark.skipif(__import__("shutil").which("gitleaks") is None, reason="gitleaks not installed")
def test_security_leak_blocks_and_records_issue(tmp_path):
    wt = _repo(tmp_path / "wt")
    (wt / "leak.py").write_text('aws_secret_access_key = "k3n29cXx9b1ZQm7U+mLwNr6yT4oKhDf8JsVpAeRi"\n')
    r = runner.ClaudeCliRunner(wt)
    out = r.run(_action())
    assert out["ok"] is False
    issues = paths.read_jsonl(paths.project_dir("acme") / "known_issues.jsonl")
    assert len(issues) == 1 and issues[0]["kind"] == "security" and issues[0]["findings"] >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_runner_security.py -v`
Expected: FAIL — the leak test finds no `known_issues.jsonl` (runner security branch doesn't record).

- [ ] **Step 3: Implement**

In `factory/runner.py`, change the `security` branch of `run()`:
```python
        if verb == "security":
            r = _gates.run_security(self.worktree)
            if not r.ok and r.findings:
                from factory import state as _state
                _state.append_known_issue(action.business, {
                    "kind": "security", "severity": "high", "findings": r.findings,
                    "detail": r.detail, "task_id": (action.payload or {}).get("task", {}).get("id"),
                })
            return {"ok": r.ok, "cost_usd": 0.0, "output": r.detail, "pr_url": None}
```
(Import `factory.state` lazily inside the branch to avoid a module-level import cycle if one exists; a top-level `from factory import state as _state` is also fine if there's no cycle — verify by running the suite.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_runner_security.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/runner.py tests/test_factory_runner_security.py
git commit -m "feat(factory): record security leaks to known_issues.jsonl + runner security test"
```

---

### Task 4: gh-PR idempotency + backlog task-id sanitizing

**Files:**
- Modify: `factory/pr.py` (recover existing PR url), `tests/fixtures/fake_gh.py` ("exists" mode), `factory/state.py` (sanitize on save_backlog)
- Test: `tests/test_factory_pr_idempotent.py`, extend `tests/test_factory_state.py`

**Interfaces:**
- Consumes: `factory.worktree.branch_name` (component validator for ids).
- Produces:
  - `pr.open_pr` — on a `gh pr create` failure whose stderr indicates a PR already exists, recover the url via `gh pr view <branch> --json url -q .url` (using the same `gh_bin`); return that url instead of `None`.
  - `state.save_backlog` — reject any task whose `id` is not a safe ref component (`[A-Za-z0-9._-]+`) by raising `ValueError` (defense-in-depth against a hallucinated/injection id reaching `branch_name`; complements F2b's `safe_push`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_pr_idempotent.py
import subprocess
import sys
from pathlib import Path

import pytest
from factory import pr, worktree, paths

FAKE_GH = str(Path(__file__).parent / "fixtures" / "fake_gh.py")


def _run(*a, cwd=None):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path / "fx"))


def _wt(tmp_path):
    remote = tmp_path / "remote.git"
    _run("git", "init", "--bare", "-b", "main", str(remote))
    scratch = tmp_path / "scratch"
    _run("git", "clone", str(remote), str(scratch))
    (scratch / "README.md").write_text("i\n")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", ".", cwd=scratch)
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "i", cwd=scratch)
    _run("git", "push", "origin", "main", cwd=scratch)
    clone = worktree.ensure_clone("acme", str(remote))
    return worktree.prepare("acme", "c1", "t1", clone_path=clone)


def test_open_pr_recovers_existing_pr_url(tmp_path):
    wt = _wt(tmp_path)
    (wt / "f.py").write_text("x=1\n")
    # 'exists' mode: `pr create` fails 'already exists', `pr view` returns the url
    url = pr.open_pr(wt, "acme", {"id": "t1", "title": "add"},
                     gh_bin=f"{sys.executable} {FAKE_GH} exists")
    assert url == "https://example.invalid/acme/pull/7"
```

Add to `tests/test_factory_state.py`:
```python
def test_save_backlog_rejects_unsafe_task_id():
    import pytest
    with pytest.raises(ValueError):
        state.save_backlog("a", [{"id": "t1:refs/heads/main", "title": "x", "priority": 1,
                                  "status": "pending", "depends_on": [], "source": "s",
                                  "cycle_id": None}])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_pr_idempotent.py tests/test_factory_state.py -v`
Expected: FAIL — no "exists" mode in fake_gh / open_pr returns None; `save_backlog` accepts the unsafe id.

- [ ] **Step 3: Implement**

In `tests/fixtures/fake_gh.py`, extend `main`:
```python
def main() -> int:
    args = sys.argv[1:]
    mode = args[0] if args else ""
    if mode == "fail":
        sys.stderr.write("gh: simulated failure\n")
        return 1
    if mode == "exists":
        # args after 'exists' are the gh subcommand
        sub = args[1:]
        if sub[:2] == ["pr", "create"]:
            sys.stderr.write("a pull request for branch ... already exists\n")
            return 1
        if sub[:2] == ["pr", "view"]:
            print("https://example.invalid/acme/pull/7")
            return 0
        return 1
    print("https://example.invalid/acme/pull/1")
    return 0
```

In `factory/pr.py`, replace the `gh pr create` try/except:
```python
    head = shlex.split(gh_bin)
    cmd = head + ["pr", "create", "--head", branch, "--base", base,
                  "--title", f"factory: {title}", "--body",
                  f"Automated by KAI Factory for task {task.get('id')}."]
    try:
        proc = subprocess.run(cmd, cwd=str(worktree), capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        # idempotency: if a PR already exists for this branch, recover its url
        if "already exists" in (e.stderr or ""):
            view = head + ["pr", "view", branch, "--json", "url", "-q", ".url"]
            try:
                vp = subprocess.run(view, cwd=str(worktree), capture_output=True, text=True, check=True)
                u = vp.stdout.strip().splitlines()[-1] if vp.stdout.strip() else None
                return u or None
            except subprocess.CalledProcessError:
                return None
        return None  # fail-soft: branch pushed, PR not opened
    url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else None
    return url or None
```

In `factory/state.py`, add validation at the top of `save_backlog`:
```python
import re
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]+$")

def save_backlog(slug: str, tasks: list[dict]) -> None:
    for t in tasks:
        tid = t.get("id", "")
        if not _SAFE_ID.fullmatch(str(tid)):
            raise ValueError(f"unsafe task id {tid!r} (must match [A-Za-z0-9._-]+)")
    paths.save_json_atomic(_backlog_file(slug), {"tasks": tasks})
```
(If `re` is already imported at the top of state.py from a prior task, reuse it — one import.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_pr_idempotent.py tests/test_factory_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add factory/pr.py factory/state.py tests/fixtures/fake_gh.py tests/test_factory_pr_idempotent.py tests/test_factory_state.py
git commit -m "feat(factory): gh-PR idempotency (recover existing url) + sanitize backlog task ids"
```

---

### Task 5: `factory/cycle.py` — opt-in real-cycle worktree wrapper + `cli --real`

**Files:**
- Create: `factory/cycle.py`
- Modify: `factory/cli.py` (add `--real`)
- Test: `tests/test_factory_cycle.py`

**Interfaces:**
- Consumes: `factory.{worktree, pipeline, project, state}`.
- Produces:
  - `run_with_worktree(slug, *, now_iso, make_runner, repo_url=None) -> pipeline.CycleResult` — resolve `repo_url` from the project record if not given; if no ready task, return an idle `CycleResult` without provisioning; else `ensure_clone` → peek `next_ready_task` (for the branch) → `prepare(slug, cycle_id, task_id)` → `runner = make_runner(worktree)` → `pipeline.run_cycle(slug, runner, now_iso=now_iso)` → **cleanup in a `finally`**. Single-threaded assumption: the peeked task equals the one `run_cycle` claims.
  - `cli.py` gains `tick --real <slug>`: constructs a real `ClaudeCliRunner(worktree)` via `run_with_worktree` (a `make_runner` that returns `ClaudeCliRunner(wt)`), default `claude`/`gh` bins. Without `--real`, unchanged mock behavior.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_cycle.py
import subprocess
import pytest
from factory import cycle, worktree, state, project as P, paths


def _run(*a, cwd=None):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path / "fx"))


class _MockRunner:
    def __init__(self, wt):
        self.wt = wt
    def run(self, action):
        return {"ok": True, "cost_usd": 0.0, "output": "",
                "pr_url": "https://gh/pr/1" if action.verb == "commit_pr" else None}


def _project_with_repo(tmp_path):
    remote = tmp_path / "remote.git"
    _run("git", "init", "--bare", "-b", "main", str(remote))
    scratch = tmp_path / "scratch"
    _run("git", "clone", str(remote), str(scratch))
    (scratch / "README.md").write_text("i\n")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", ".", cwd=scratch)
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "i", cwd=scratch)
    _run("git", "push", "origin", "main", cwd=scratch)
    P.upsert_project(P.Project(slug="acme", name="acme", repo_url=str(remote)))
    state.save_backlog("acme", [{"id": "t1", "title": "x", "priority": 1, "status": "pending",
                                 "depends_on": [], "source": "seed", "cycle_id": None}])
    return remote


def test_run_with_worktree_provisions_runs_and_cleans_up(tmp_path):
    _project_with_repo(tmp_path)
    res = cycle.run_with_worktree("acme", now_iso="2026-07-01T02:00:00Z",
                                  make_runner=lambda wt: _MockRunner(wt))
    assert res.status == "completed"
    assert state.load_backlog("acme")[0]["status"] == "done"
    # worktree cleaned up
    assert not (paths.worktrees_root() / "acme").glob("*").__iter__().__next__() if False else True
    leftover = list((paths.worktrees_root() / "acme").glob("*")) if (paths.worktrees_root() / "acme").exists() else []
    assert leftover == []


def test_run_with_worktree_idle_when_no_task(tmp_path):
    _project_with_repo(tmp_path)
    state.save_backlog("acme", [])  # nothing ready
    res = cycle.run_with_worktree("acme", now_iso="2026-07-01T02:00:00Z",
                                  make_runner=lambda wt: _MockRunner(wt))
    assert res.status in ("idle", "done")
    # no worktree provisioned
    assert not (paths.worktrees_root() / "acme").exists() or \
           list((paths.worktrees_root() / "acme").glob("*")) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_cycle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory.cycle'`

- [ ] **Step 3: Implement**

```python
# factory/cycle.py
"""Opt-in real-cycle wrapper: compose the F2b worktree lifecycle around a real
run_cycle. The daemon default stays the mock path; this is invoked only by the
--real CLI path (and, later, F3 arming). Single-threaded: the peeked ready task
is the one run_cycle claims."""
from __future__ import annotations

from factory import pipeline, project as projects, state, worktree


def run_with_worktree(slug: str, *, now_iso: str, make_runner, repo_url: str | None = None):
    if repo_url is None:
        p = projects.get_project(slug)
        repo_url = p.repo_url if p else None
    cid = pipeline._cycle_id(slug, now_iso)

    # Peek the ready task to name the worktree branch; if none, don't provision.
    task = state.next_ready_task(slug)
    if task is None:
        return pipeline.run_cycle(slug, _NoopRunner(), now_iso=now_iso)  # returns idle/done cheaply

    clone = worktree.ensure_clone(slug, repo_url)
    wt = worktree.prepare(slug, cid, task["id"], clone_path=clone)
    try:
        runner = make_runner(wt)
        return pipeline.run_cycle(slug, runner, now_iso=now_iso)
    finally:
        worktree.cleanup(slug, cid, clone_path=clone)


class _NoopRunner:
    def run(self, action):
        return {"ok": True, "cost_usd": 0.0, "output": "", "pr_url": None}
```

In `factory/cli.py`, add a `--real` flag to the `tick` subparser and route it:
```python
    t.add_argument("--real", action="store_true", help="use the real claude/gh runner + worktree")
```
In `main`, after resolving `now_iso`:
```python
    if getattr(args, "real", False):
        from factory import cycle, runner as _runner
        from dataclasses import asdict
        res = cycle.run_with_worktree(args.slug, now_iso=now_iso,
                                      make_runner=lambda wt: _runner.ClaudeCliRunner(wt))
        print(json.dumps(asdict(res), indent=2))
        return 0
    print(json.dumps(tick(args.slug, now_iso=now_iso), indent=2))
    return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_cycle.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/cycle.py factory/cli.py tests/test_factory_cycle.py
git commit -m "feat(factory): opt-in real-cycle worktree wrapper + cli --real"
```

---

### Task 6: F2c suite green + no regressions

**Files:** none (verification).

- [ ] **Step 1: Full factory suite**

Run: `python -m pytest tests/test_factory_*.py -v`
Expected: PASS — F2b's 93 + F2c's new (~12) = ~105 green.

- [ ] **Step 2: Confirm the mock default path is unchanged**

Run: `python -m pytest tests/test_factory_scheduler.py tests/test_factory_pipeline.py tests/test_factory_cli.py -q`
Expected: PASS — the F1 mock-path tests still green (default behavior unchanged).

- [ ] **Step 3: W-MOS regression (note the known exogenous failures)**

Run: `python -m pytest tests/test_portfolio_*.py -q`
Expected: the 4 known adapter failures from the concurrent `30e4add` commit may still be present — confirm the count did NOT grow (F2c touched no `core/portfolio`).

- [ ] **Step 4: Commit**

```bash
git commit --allow-empty -m "test(factory): F2c suite green, mock default path unchanged"
```

---

## Self-Review

**1. Spec coverage (F2 spec §→task):** §6 kill-criteria retry (T1), budget pre-emption (T2), runner annotations (T2), synthetic-data env (already F2a); §5 security→known_issues (T3); §8 F2c opt-in wiring (T5, cli --real; scheduler stays mock-default). Ledger carry-overs: gh idempotency (T4), task-id sanitize (T4), runner security test (T3).

**2. Placeholder scan:** none — every step has complete code. The one `assert ... if False else True` in the T5 test is a deliberate no-op guard; the real assertion is the `leftover == []` line below it.

**3. Type consistency:** `run_with_worktree(slug, *, now_iso, make_runner, repo_url=None) -> CycleResult` consistent T5. `requeue_oldest_blocked(slug) -> str|None` T1. Runner return dict `{ok,cost_usd,output,pr_url}` unchanged across T3. `estimated_cost(model)` (F2a) used in T2.

**Out of F2c scope (F3/F2d):** autonomous nightly arming of the real runner; the operator-gated real-`claude`+real-`gh` smoke; dashboard.
