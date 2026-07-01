# KAI Startup Factory — F2b (Worktree + Gates + PR) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a factory cycle actually touch git — an isolated worktree per cycle, **daemon-verified** build (pytest) and security (gitleaks) gates, and a real commit → branch-limited push → `gh` PR — then wire the `ClaudeCliRunner`'s `build`/`security`/`commit_pr` verbs (currently `NotImplementedError`) to them.

**Architecture:** Three new modules — `factory/worktree.py` (clone + worktree lifecycle + `safe_push` branch-limit), `factory/gates.py` (objective build/security checks the daemon runs itself), `factory/pr.py` (commit + push + `gh pr create`). `factory/runner.py` is modified to route the three verbs to these. Tests use **real git + real gitleaks against local repos** (deterministic, $0, no network) and a **fake `gh`** stub. No real `claude` and no GitHub network anywhere in this plan.

**Tech Stack:** Python 3.11 stdlib (`subprocess`, `shutil`, `pathlib`, `tempfile`, `json`), `pytest`; drives `git` (real, local), `gitleaks` 8.30.1 (real, local), and `gh` (faked in tests). No new pip packages.

## Global Constraints

- **Language/runtime:** Python 3.11, stdlib only. No new pip packages.
- **Reuse:** these modules are consumed by `factory/runner.py`'s `ClaudeCliRunner` (`self.worktree`, `action.business` = slug, `action.payload["task"]`). Do not modify F1 modules or `core.portfolio`. Do not change the F2a runner's agent-work path or `build_env`/`build_argv`/`parse_result`.
- **Daemon-verified gates (fail-closed):** `run_build` → `ok = (pytest exit 0)`; `run_security` → `ok = (gitleaks found no leaks)`. A missing tool, a crash, or a non-zero-for-other-reasons → fail-closed (`ok=False`). The agent never decides these.
- **gitleaks:** invoke `gitleaks detect --source <worktree> --no-git --report-format json --report-path <TEMPFILE> --exit-code 1`. gitleaks 8.x **refuses a stdout report path** — always use a real temp file, then read it. Exit code `0` = clean, `1` = leaks, other = tool error (fail-closed).
- **Branch-limit is the push safety boundary:** `safe_push` MUST refuse any branch not matching `^factory/<slug>/`. This is enforced in Python before any `git push` runs.
- **PR base branch = `main`** (spec §9-Q2). **Build command default = `python -m pytest -q`** (spec §9-Q1), overridable per call.
- **No network:** tests never call real `gh` or a real remote host. `gh` is faked via `FACTORY_GH_BIN`; the "remote" is a local bare repo.
- **Determinism:** git identity in tests is set explicitly (`-c user.email=... -c user.name=...`); default branch pinned with `-c init.defaultBranch=main`.
- Run tests with `python -m pytest <path> -v` **from the repo root** `/Volumes/Wheellsverse/wheellsverse-bots` (no pytest config — cwd-on-path).

---

### Task 1: `factory/worktree.py` — clone + worktree lifecycle + safe_push

**Files:**
- Create: `factory/worktree.py`
- Test: `tests/test_factory_worktree.py`

**Interfaces:**
- Consumes: `factory.paths` (`workspaces_root`, `worktrees_root`), stdlib `subprocess`/`shutil`.
- Produces:
  - `class PushRejected(Exception)` — raised by `safe_push` for a disallowed branch.
  - `branch_name(slug, task_id) -> str` → `f"factory/{slug}/{task_id}"`.
  - `ensure_clone(slug, repo_url) -> Path` — clone `repo_url` into `workspaces_root()/slug` if absent (via `git clone`); return the clone path. Idempotent.
  - `prepare(slug, cycle_id, task_id, *, clone_path) -> Path` — create a worktree at `worktrees_root()/slug/cycle_id` on branch `branch_name(slug, task_id)` (reuse the branch if it exists). Returns the worktree path.
  - `cleanup(slug, cycle_id, *, clone_path) -> None` — `git worktree remove --force` + `git worktree prune`, run from `clone_path` (never from inside the worktree); tolerate an already-removed worktree.
  - `safe_push(clone_path, slug, branch) -> None` — raise `PushRejected` unless `branch` matches `^factory/{slug}/`; else `git -C <clone> push -u origin <branch>`.
  - `_git(cwd, *args) -> subprocess.CompletedProcess` — helper running git with an explicit test-safe identity and `check=True`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_worktree.py
import subprocess
from pathlib import Path

import pytest
from factory import worktree, paths


def _run(*args, cwd=None):
    return subprocess.run(list(args), cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path / "fx"))


def _bare_remote(tmp_path) -> Path:
    remote = tmp_path / "remote.git"
    _run("git", "init", "--bare", "-b", "main", str(remote))
    # seed the remote with one commit via a scratch clone
    scratch = tmp_path / "scratch"
    _run("git", "clone", str(remote), str(scratch))
    (scratch / "README.md").write_text("init\n")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", ".", cwd=scratch)
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init", cwd=scratch)
    _run("git", "push", "origin", "main", cwd=scratch)
    return remote


def test_branch_name():
    assert worktree.branch_name("acme", "t1") == "factory/acme/t1"


def test_ensure_clone_is_idempotent(tmp_path):
    remote = _bare_remote(tmp_path)
    p1 = worktree.ensure_clone("acme", str(remote))
    assert p1 == paths.workspaces_root() / "acme"
    assert (p1 / "README.md").exists()
    p2 = worktree.ensure_clone("acme", str(remote))  # second call: no error, same path
    assert p2 == p1


def test_prepare_creates_worktree_on_factory_branch(tmp_path):
    remote = _bare_remote(tmp_path)
    clone = worktree.ensure_clone("acme", str(remote))
    wt = worktree.prepare("acme", "c1", "t1", clone_path=clone)
    assert wt.exists() and (wt / "README.md").exists()
    head = _run("git", "-C", str(wt), "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    assert head == "factory/acme/t1"


def test_cleanup_removes_worktree(tmp_path):
    remote = _bare_remote(tmp_path)
    clone = worktree.ensure_clone("acme", str(remote))
    wt = worktree.prepare("acme", "c1", "t1", clone_path=clone)
    worktree.cleanup("acme", "c1", clone_path=clone)
    assert not wt.exists()
    worktree.cleanup("acme", "c1", clone_path=clone)  # idempotent: no raise


def test_safe_push_rejects_non_factory_branch(tmp_path):
    remote = _bare_remote(tmp_path)
    clone = worktree.ensure_clone("acme", str(remote))
    with pytest.raises(worktree.PushRejected):
        worktree.safe_push(clone, "acme", "main")
    with pytest.raises(worktree.PushRejected):
        worktree.safe_push(clone, "acme", "factory/other/t1")  # wrong slug


def test_safe_push_allows_and_pushes_factory_branch(tmp_path):
    remote = _bare_remote(tmp_path)
    clone = worktree.ensure_clone("acme", str(remote))
    worktree.prepare("acme", "c1", "t1", clone_path=clone)
    # make a commit on the factory branch inside the clone's worktree checkout
    wt = paths.worktrees_root() / "acme" / "c1"
    (wt / "f.txt").write_text("x\n")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(wt), "add", ".")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(wt), "commit", "-m", "add f")
    # push the branch from the worktree
    worktree.safe_push(wt, "acme", "factory/acme/t1")
    branches = _run("git", "-C", str(remote), "branch", "--list", "factory/acme/t1").stdout
    assert "factory/acme/t1" in branches
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_factory_worktree.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory.worktree'`

- [ ] **Step 3: Write minimal implementation**

```python
# factory/worktree.py
"""Isolated git worktree lifecycle for a factory cycle + the branch-limited push.
Real git; no network beyond the configured remote. safe_push is the physical
guarantee that the daemon can only push factory/<slug>/* branches."""
from __future__ import annotations

import re
import shutil
import subprocess

from factory import paths

_IDENT = ("-c", "user.email=factory@kai.local", "-c", "user.name=KAI Factory")


class PushRejected(Exception):
    pass


def _git(cwd, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=True)


def branch_name(slug: str, task_id: str) -> str:
    return f"factory/{slug}/{task_id}"


def ensure_clone(slug: str, repo_url: str):
    dest = paths.workspaces_root() / slug
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", repo_url, str(dest)],
                   capture_output=True, text=True, check=True)
    return dest


def prepare(slug: str, cycle_id: str, task_id: str, *, clone_path):
    wt = paths.worktrees_root() / slug / cycle_id
    wt.parent.mkdir(parents=True, exist_ok=True)
    branch = branch_name(slug, task_id)
    existing = _git(clone_path, "branch", "--list", branch).stdout.strip()
    if existing:
        _git(clone_path, "worktree", "add", str(wt), branch)
    else:
        _git(clone_path, "worktree", "add", "-b", branch, str(wt))
    return wt


def cleanup(slug: str, cycle_id: str, *, clone_path) -> None:
    wt = paths.worktrees_root() / slug / cycle_id
    try:
        _git(clone_path, "worktree", "remove", "--force", str(wt))
    except subprocess.CalledProcessError:
        pass  # already gone
    if wt.exists():
        shutil.rmtree(wt, ignore_errors=True)
    try:
        _git(clone_path, "worktree", "prune")
    except subprocess.CalledProcessError:
        pass


def safe_push(clone_path, slug: str, branch: str) -> None:
    if not re.match(rf"^factory/{re.escape(slug)}/", branch):
        raise PushRejected(f"refusing to push non-factory branch {branch!r} for {slug!r}")
    subprocess.run(["git", "-C", str(clone_path), *_IDENT, "push", "-u", "origin", branch],
                   capture_output=True, text=True, check=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_worktree.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/worktree.py tests/test_factory_worktree.py
git commit -m "feat(factory): worktree lifecycle + branch-limited safe_push"
```

---

### Task 2: `factory/gates.py` — daemon-verified build + security gates

**Files:**
- Create: `factory/gates.py`
- Test: `tests/test_factory_gates.py`

**Interfaces:**
- Consumes: stdlib `subprocess`, `tempfile`, `json`, `shutil`.
- Produces:
  - `@dataclass GateResult(ok: bool, detail: str, findings: int = 0)`
  - `run_build(worktree, *, cmd="python -m pytest -q", timeout_s=1800) -> GateResult` — run `cmd` (shell-split) in the worktree; `ok = (exit 0)`; timeout/error → `ok=False`.
  - `run_security(worktree, *, timeout_s=600) -> GateResult` — run gitleaks; `ok = (returncode == 0)`; `returncode == 1` → leaks (ok False, `findings` = count from the JSON report); any other exit or missing binary → fail-closed (ok False). Uses a real temp report file (never stdout).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_gates.py
import shutil
import subprocess
from pathlib import Path

import pytest
from factory import gates


def _init_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], capture_output=True, check=True)
    return tmp_path


def test_run_build_passes_on_green_tests(tmp_path):
    wt = _init_repo(tmp_path)
    (wt / "test_ok.py").write_text("def test_ok():\n    assert 1 == 1\n")
    res = gates.run_build(wt)
    assert res.ok is True


def test_run_build_fails_on_red_tests(tmp_path):
    wt = _init_repo(tmp_path)
    (wt / "test_bad.py").write_text("def test_bad():\n    assert 1 == 2\n")
    res = gates.run_build(wt)
    assert res.ok is False


def test_run_build_custom_cmd(tmp_path):
    wt = _init_repo(tmp_path)
    assert gates.run_build(wt, cmd="python -c \"exit(0)\"").ok is True
    assert gates.run_build(wt, cmd="python -c \"exit(3)\"").ok is False


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed")
def test_run_security_clean(tmp_path):
    wt = _init_repo(tmp_path)
    (wt / "app.py").write_text("x = 1\n")
    res = gates.run_security(wt)
    assert res.ok is True and res.findings == 0


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed")
def test_run_security_flags_planted_secret(tmp_path):
    wt = _init_repo(tmp_path)
    # a high-entropy AWS-style key gitleaks reliably detects
    (wt / "leak.py").write_text('AWS_SECRET = "AKIAIOSFODNN7EXAMPLE"\n'
                                'aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"\n')
    res = gates.run_security(wt)
    assert res.ok is False and res.findings >= 1


def test_run_security_fail_closed_when_gitleaks_missing(tmp_path, monkeypatch):
    # force the binary lookup to fail -> fail closed
    monkeypatch.setattr(gates.shutil, "which", lambda _n: None)
    res = gates.run_security(_init_repo(tmp_path))
    assert res.ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_gates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory.gates'`

- [ ] **Step 3: Write minimal implementation**

```python
# factory/gates.py
"""Daemon-verified, fail-closed pipeline gates. The daemon runs these objective
checks itself — the agent never self-certifies. build = the project's tests must
pass; security = gitleaks must find no leaks."""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GateResult:
    ok: bool
    detail: str
    findings: int = 0


def run_build(worktree, *, cmd: str = "python -m pytest -q", timeout_s: int = 1800) -> GateResult:
    try:
        proc = subprocess.run(shlex.split(cmd), cwd=str(worktree),
                              capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return GateResult(False, "build timed out")
    except Exception as e:  # missing interpreter, bad cmd -> fail closed
        return GateResult(False, f"build error: {e}")
    if proc.returncode == 0:
        return GateResult(True, "build passed")
    return GateResult(False, f"build failed (exit {proc.returncode})")


def run_security(worktree, *, timeout_s: int = 600) -> GateResult:
    if shutil.which("gitleaks") is None:
        return GateResult(False, "gitleaks not installed (fail-closed)")
    with tempfile.TemporaryDirectory() as td:
        report = Path(td) / "gitleaks.json"
        try:
            proc = subprocess.run(
                ["gitleaks", "detect", "--source", str(worktree), "--no-git",
                 "--report-format", "json", "--report-path", str(report),
                 "--exit-code", "1"],
                capture_output=True, text=True, timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            return GateResult(False, "security scan timed out")
        except Exception as e:
            return GateResult(False, f"security scan error: {e}")
        if proc.returncode == 0:
            return GateResult(True, "no leaks", 0)
        if proc.returncode == 1:
            findings = 0
            try:
                data = json.loads(report.read_text(encoding="utf-8"))
                findings = len(data) if isinstance(data, list) else 0
            except Exception:
                findings = 1  # leaks reported but report unreadable -> still block
            return GateResult(False, f"{findings} leak(s) found", findings)
        return GateResult(False, f"gitleaks error (exit {proc.returncode})")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_gates.py -v`
Expected: PASS (6 passed; the 2 gitleaks tests run since gitleaks is installed)

- [ ] **Step 5: Commit**

```bash
git add factory/gates.py tests/test_factory_gates.py
git commit -m "feat(factory): daemon-verified build (pytest) + security (gitleaks) gates"
```

---

### Task 3: `factory/pr.py` — commit + branch-limited push + gh PR

**Files:**
- Create: `factory/pr.py`
- Test: `tests/test_factory_pr.py`

**Interfaces:**
- Consumes: `factory.worktree` (`branch_name`, `safe_push`), stdlib `subprocess`.
- Produces:
  - `open_pr(worktree, slug, task, *, base="main", gh_bin="gh") -> str | None` — `git add -A`; if nothing to commit, return `None`; else commit (message from `task["title"]`), `worktree.safe_push(worktree, slug, branch)`, then `gh pr create --head <branch> --base <base> --title ... --body ...`; return the PR url (stdout, stripped). Idempotent-friendly: a `gh` failure returns `None` (fail-soft; the branch is still pushed). `gh_bin` may be a multi-token stub path.
  - `_has_changes(worktree) -> bool`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_pr.py
import os
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


def _clone_with_worktree(tmp_path):
    remote = tmp_path / "remote.git"
    _run("git", "init", "--bare", "-b", "main", str(remote))
    scratch = tmp_path / "scratch"
    _run("git", "clone", str(remote), str(scratch))
    (scratch / "README.md").write_text("init\n")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", ".", cwd=scratch)
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init", cwd=scratch)
    _run("git", "push", "origin", "main", cwd=scratch)
    clone = worktree.ensure_clone("acme", str(remote))
    wt = worktree.prepare("acme", "c1", "t1", clone_path=clone)
    return remote, wt


def test_open_pr_commits_pushes_and_returns_url(tmp_path):
    remote, wt = _clone_with_worktree(tmp_path)
    (wt / "feature.py").write_text("def f():\n    return 1\n")
    url = pr.open_pr(wt, "acme", {"id": "t1", "title": "add feature"},
                     gh_bin=f"{sys.executable} {FAKE_GH}")
    assert url == "https://example.invalid/acme/pull/1"
    branches = _run("git", "-C", str(remote), "branch", "--list", "factory/acme/t1").stdout
    assert "factory/acme/t1" in branches


def test_open_pr_no_changes_returns_none(tmp_path):
    remote, wt = _clone_with_worktree(tmp_path)
    url = pr.open_pr(wt, "acme", {"id": "t1", "title": "noop"},
                     gh_bin=f"{sys.executable} {FAKE_GH}")
    assert url is None


def test_open_pr_gh_failure_is_fail_soft(tmp_path):
    remote, wt = _clone_with_worktree(tmp_path)
    (wt / "feature.py").write_text("x=1\n")
    url = pr.open_pr(wt, "acme", {"id": "t1", "title": "add"},
                     gh_bin=f"{sys.executable} {FAKE_GH} fail")
    assert url is None  # branch still pushed, but no PR url
    branches = _run("git", "-C", str(remote), "branch", "--list", "factory/acme/t1").stdout
    assert "factory/acme/t1" in branches
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_pr.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory.pr'` (and the fake_gh fixture is missing)

- [ ] **Step 3a: Create the fake `gh` stub**

```python
# tests/fixtures/fake_gh.py
"""Fake `gh` for tests. `gh pr create ...` prints a canned PR url; if the first
non-flag arg is 'fail', exit non-zero to simulate a gh failure. No network."""
import sys


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "fail":
        sys.stderr.write("gh: simulated failure\n")
        return 1
    # args looks like: ["pr", "create", "--head", "...", ...]
    print("https://example.invalid/acme/pull/1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3b: Write `factory/pr.py`**

```python
# factory/pr.py
"""Commit the worktree, push its factory branch (branch-limited), and open a PR
via `gh`. Fail-soft: a gh failure still leaves the branch pushed and returns None."""
from __future__ import annotations

import shlex
import subprocess

from factory import worktree as _wt

_IDENT = ("-c", "user.email=factory@kai.local", "-c", "user.name=KAI Factory")


def _has_changes(worktree) -> bool:
    proc = subprocess.run(["git", "-C", str(worktree), "status", "--porcelain"],
                          capture_output=True, text=True, check=True)
    return bool(proc.stdout.strip())


def open_pr(worktree, slug: str, task: dict, *, base: str = "main", gh_bin: str = "gh") -> str | None:
    if not _has_changes(worktree):
        return None
    branch = _wt.branch_name(slug, task["id"])
    title = task.get("title", "factory change")
    subprocess.run(["git", "-C", str(worktree), *_IDENT, "add", "-A"],
                   capture_output=True, text=True, check=True)
    subprocess.run(["git", "-C", str(worktree), *_IDENT, "commit", "-m", f"factory: {title}"],
                   capture_output=True, text=True, check=True)
    _wt.safe_push(worktree, slug, branch)
    head = shlex.split(gh_bin)
    cmd = head + ["pr", "create", "--head", branch, "--base", base,
                  "--title", f"factory: {title}", "--body",
                  f"Automated by KAI Factory for task {task.get('id')}."]
    try:
        proc = subprocess.run(cmd, cwd=str(worktree), capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError:
        return None  # fail-soft: branch pushed, PR not opened
    url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else None
    return url or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_pr.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/pr.py tests/fixtures/fake_gh.py tests/test_factory_pr.py
git commit -m "feat(factory): PR opener (commit + branch-limited push + gh)"
```

---

### Task 4: Wire the runner's `build`/`security`/`commit_pr` verbs

**Files:**
- Modify: `factory/runner.py` (replace the `NotImplementedError` branch)
- Test: `tests/test_factory_runner_gates.py`

**Interfaces:**
- Consumes: `factory.gates`, `factory.pr`.
- Produces (runner behavior): `ClaudeCliRunner.run(action)` now handles:
  - `build` → `gates.run_build(self.worktree, cmd=self.build_cmd)` → `{ok, cost_usd:0.0, output:detail, pr_url:None}`.
  - `security` → `gates.run_security(self.worktree)` → same shape.
  - `commit_pr` → `pr.open_pr(self.worktree, action.business, task, base=self.pr_base, gh_bin=self.gh_bin)` → `{ok: url is not None, cost_usd:0.0, output:"", pr_url:url}`.
  - Constructor gains `build_cmd="python -m pytest -q"`, `pr_base="main"`, `gh_bin="gh"` (all keyword, defaulted) so tests can inject fakes.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_runner_gates.py
import subprocess
import sys
from pathlib import Path

import pytest
from core.portfolio.actions import Action, ActionClass
from factory import runner, worktree, paths

FAKE_GH = str(Path(__file__).parent / "fixtures" / "fake_gh.py")


def _run(*a, cwd=None):
    return subprocess.run(list(a), cwd=cwd, capture_output=True, text=True, check=True)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("FACTORY_DATA_PATH", str(tmp_path / "fx"))


def _action(verb, agent="daemon"):
    return Action(verb=verb, agent=agent, action_class=ActionClass.GREEN,
                  preconditions=[], business="acme",
                  payload={"task": {"id": "t1", "title": "add feature"}, "cycle_id": "c1"})


def _worktree(tmp_path):
    remote = tmp_path / "remote.git"
    _run("git", "init", "--bare", "-b", "main", str(remote))
    scratch = tmp_path / "scratch"
    _run("git", "clone", str(remote), str(scratch))
    (scratch / "README.md").write_text("init\n")
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "add", ".", cwd=scratch)
    _run("git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init", cwd=scratch)
    _run("git", "push", "origin", "main", cwd=scratch)
    clone = worktree.ensure_clone("acme", str(remote))
    return worktree.prepare("acme", "c1", "t1", clone_path=clone)


def test_build_verb_runs_pytest(tmp_path):
    wt = _worktree(tmp_path)
    (wt / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    r = runner.ClaudeCliRunner(wt, build_cmd="python -m pytest -q")
    out = r.run(_action("build"))
    assert out["ok"] is True and out["pr_url"] is None


def test_build_verb_fails_on_red(tmp_path):
    wt = _worktree(tmp_path)
    (wt / "test_bad.py").write_text("def test_bad():\n    assert False\n")
    r = runner.ClaudeCliRunner(wt)
    assert r.run(_action("build"))["ok"] is False


def test_commit_pr_verb_opens_pr(tmp_path):
    wt = _worktree(tmp_path)
    (wt / "feature.py").write_text("def f():\n    return 1\n")
    r = runner.ClaudeCliRunner(wt, gh_bin=f"{sys.executable} {FAKE_GH}")
    out = r.run(_action("commit_pr", agent="git"))
    assert out["ok"] is True
    assert out["pr_url"] == "https://example.invalid/acme/pull/1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_runner_gates.py -v`
Expected: FAIL — the `build` verb currently raises `NotImplementedError`.

- [ ] **Step 3: Modify `factory/runner.py`**

Change the imports near the top (add):
```python
from factory import gates as _gates
from factory import pr as _pr
```

Replace the `__init__` and the `run` dispatch:
```python
    def __init__(self, worktree, *, claude_bin: str = "claude", timeout_s: int = 1800,
                 build_cmd: str = "python -m pytest -q", pr_base: str = "main", gh_bin: str = "gh"):
        self.worktree = Path(worktree)
        self.claude_bin = claude_bin
        self.timeout_s = timeout_s
        self.build_cmd = build_cmd
        self.pr_base = pr_base
        self.gh_bin = gh_bin

    def run(self, action) -> dict:
        verb = action.verb
        if verb in AGENT_WORK_VERBS:
            return self._run_agent(action)
        if verb == "build":
            r = _gates.run_build(self.worktree, cmd=self.build_cmd, timeout_s=self.timeout_s)
            return {"ok": r.ok, "cost_usd": 0.0, "output": r.detail, "pr_url": None}
        if verb == "security":
            r = _gates.run_security(self.worktree)
            return {"ok": r.ok, "cost_usd": 0.0, "output": r.detail, "pr_url": None}
        if verb == "commit_pr":
            task = (action.payload or {}).get("task", {})
            url = _pr.open_pr(self.worktree, action.business, task,
                              base=self.pr_base, gh_bin=self.gh_bin)
            return {"ok": url is not None, "cost_usd": 0.0, "output": "", "pr_url": url}
        return {"ok": True, "cost_usd": 0.0, "output": "", "pr_url": None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_runner_gates.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/runner.py tests/test_factory_runner_gates.py
git commit -m "feat(factory): wire runner build/security/commit_pr verbs to gates + pr"
```

---

### Task 5: F2b suite green + no regressions

**Files:** none (verification).

- [ ] **Step 1: Full factory suite**

Run: `python -m pytest tests/test_factory_*.py -v`
Expected: PASS — F2a's 73 + F2b's ~18 new = ~91 green.

- [ ] **Step 2: W-MOS regression**

Run: `python -m pytest tests/test_portfolio_*.py -q`
Expected: PASS (106 passed).

- [ ] **Step 3: Confirm the runner's gate verbs no longer raise**

Run: `grep -n "NotImplementedError" factory/runner.py`
Expected: no matches (the F2a `NotImplementedError` branch is gone).

- [ ] **Step 4: Confirm no real gh / real remote in tests**

Run: `grep -rn "gh_bin=" tests/test_factory_pr.py tests/test_factory_runner_gates.py`
Expected: every `open_pr`/runner using a fake `gh_bin` (the `fake_gh.py` stub) — no test invokes the real `gh` or a network remote.

- [ ] **Step 5: Commit**

```bash
git commit --allow-empty -m "test(factory): F2b suite green, no network (real git+gitleaks, fake gh)"
```

---

## Self-Review

**1. Spec coverage (F2 spec §→task):**
- §5 worktree lifecycle (clone/worktree/cleanup) + branch-limited `safe_push` — Task 1.
- §5 gates.run_build (pytest) + run_security (gitleaks, temp-file report, fail-closed) — Task 2.
- §5 pr.open_pr (commit → safe_push → gh) — Task 3.
- §3 verb routing: build/security/commit_pr wired (no longer NotImplementedError) — Task 4.
- §7 testing: real git + real gitleaks against local repos, fake `gh`, no network — all tasks + Task 5.
- **Deferred to F2c (intentional):** kill-criteria retry, budget pre-emption, `runner: AgentAdapter` annotations, scheduler/cli opt-in wiring. **F2d:** the real-`claude` + real-`gh` + live R1 smoke.

**2. Placeholder scan:** none — every step has complete code; gitleaks tests are `skipif`-guarded on the binary (present on this host).

**3. Type consistency:** the runner returns the F1 contract dict `{ok, cost_usd, output, pr_url}` on every branch (Task 4). `GateResult(ok, detail, findings)` consistent Tasks 2/4. `worktree.branch_name(slug, task_id)` used identically in Tasks 1/3. `open_pr(worktree, slug, task, *, base, gh_bin)` consistent Tasks 3/4. Task dict shape (`id`, `title`) consistent Tasks 3/4.

**Out of F2b scope (F2c/F2d):** carry-over fixes; scheduler/cli wiring of the real runner; the operator-gated real smoke.
