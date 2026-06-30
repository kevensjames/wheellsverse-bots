# KAI Startup Factory — F2a (Roles + Claude CLI Runner) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the real `ClaudeCliRunner`'s agent-work path — role definitions, the `claude -p` argv/env builders, the JSON result parser, and the subprocess driver — verified entirely against a **fake `claude` stub** (no API, no network, $0).

**Architecture:** New `factory/roles.py` (role system prompts + tool allowlists + model tiers) and `factory/runner.py` (a verb-aware `AgentAdapter`). F2a implements only the **agent-work verbs** (architect/implement/review/refactor/debug/optimize/test/next_tasks) via real `subprocess.run` of `claude -p`; the gate/git verbs (build/security/commit_pr) raise `NotImplementedError` (wired in F2b). The mock runner from F1 stays the default everywhere — nothing in F2a is wired into the live cycle yet.

**Tech Stack:** Python 3.11 stdlib (`subprocess`, `json`, `os`, `re`, `dataclasses`, `pathlib`), `pytest`. Drives the `claude` CLI (v2.1.186) but only via a fake stub in tests.

## Global Constraints

- **Language/runtime:** Python 3.11, stdlib only. No new pip packages.
- **Reuse, don't fork:** `ClaudeCliRunner` implements the existing W-MOS `AgentAdapter` protocol (`core.portfolio.actions.AgentAdapter`: `.run(action) -> dict`) and returns the F1 runner contract dict `{"ok": bool, "cost_usd": float, "output": str, "pr_url": str | None}`. Do not modify F1 `factory/*` modules or `core.portfolio`.
- **Confirmed `claude` flags (v2.1.186):** `-p` (print/headless), `--output-format json`, `--append-system-prompt <prompt>`, `--allowedTools <tools...>` (variadic — keep it LAST in argv), `--permission-mode acceptEdits`, `--model <model>`, `--max-budget-usd <n>`. The prompt is passed via **stdin** (`subprocess.run(..., input=brief)`), NOT as a positional, to avoid colliding with the variadic `--allowedTools`. There is **no** `--max-turns` flag.
- **Fail-closed:** unparseable/malformed JSON, non-zero exit, or timeout → `ok = False`. Never raise out of `run()` for agent-work verbs.
- **Synthetic-data invariant:** the subprocess env is a minimal allowlist — no secret-shaped vars leak to the agent beyond the explicit claude-auth set.
- **Determinism / no network:** tests inject a fake `claude` via the `claude_bin` constructor arg. No test invokes the real `claude`. Run tests with `python -m pytest <path> -v` **from the repo root** `/Volumes/Wheellsverse/wheellsverse-bots` (no pytest config — cwd-on-path is how `from factory import ...` resolves).
- **Safety boundary:** no role's `allowed_tools` may contain a push/deploy/merge/secret tool. A test asserts this.

---

### Task 1: `factory/roles.py` — role registry

**Files:**
- Create: `factory/roles.py`
- Test: `tests/test_factory_roles.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces:
  - `@dataclass(frozen=True) Role(key: str, system_prompt: str, allowed_tools: tuple[str, ...], model: str, max_budget_usd: float)`
  - `ROLES: dict[str, Role]` — keyed by the pipeline stage's role string used in F1 `factory/pipeline.py` (`architect, engineer, reviewer, refactorer, debugger, performance, security, qa, daemon, writer, techlead, devops, git`). F2a only *runs* the agent-work roles, but the registry defines all of them.
  - `estimated_cost(model: str) -> float` — rough per-call $ by tier (haiku 0.05, sonnet 0.25, opus 1.0; unknown → 0.25).
  - `FORBIDDEN_TOOL_SUBSTRINGS: tuple[str, ...]` = `("push", "deploy", "merge", "secret")` (lowercase substrings that must never appear in any allowlist).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_roles.py
from factory import roles


def test_registry_has_core_agent_roles():
    for key in ["architect", "engineer", "reviewer", "qa", "techlead"]:
        assert key in roles.ROLES
        assert isinstance(roles.ROLES[key].system_prompt, str)
        assert roles.ROLES[key].system_prompt.strip()


def test_no_role_has_a_forbidden_tool():
    for key, role in roles.ROLES.items():
        joined = " ".join(role.allowed_tools).lower()
        for bad in roles.FORBIDDEN_TOOL_SUBSTRINGS:
            assert bad not in joined, f"role {key} allowlist contains forbidden {bad!r}"


def test_models_are_valid_tiers():
    for role in roles.ROLES.values():
        assert role.model in {"haiku", "sonnet", "opus"}


def test_estimated_cost_by_tier():
    assert roles.estimated_cost("haiku") < roles.estimated_cost("sonnet") < roles.estimated_cost("opus")
    assert roles.estimated_cost("unknown") == 0.25
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Volumes/Wheellsverse/wheellsverse-bots && python -m pytest tests/test_factory_roles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory.roles'`

- [ ] **Step 3: Write minimal implementation**

```python
# factory/roles.py
"""Factory role definitions: each pipeline stage's role maps to a system prompt
(the operator's role templates), a tool allowlist (the safety boundary — no
push/deploy/merge/secret tools), and a model tier. Consumed by ClaudeCliRunner."""
from __future__ import annotations

from dataclasses import dataclass

FORBIDDEN_TOOL_SUBSTRINGS: tuple[str, ...] = ("push", "deploy", "merge", "secret")

_COST_BY_TIER = {"haiku": 0.05, "sonnet": 0.25, "opus": 1.0}


@dataclass(frozen=True)
class Role:
    key: str
    system_prompt: str
    allowed_tools: tuple[str, ...]
    model: str
    max_budget_usd: float


def estimated_cost(model: str) -> float:
    return _COST_BY_TIER.get(model, 0.25)


_READ_ONLY = ("Read", "Grep", "Glob")
_EDIT = ("Read", "Edit", "Write", "Grep", "Glob", "Bash")

ROLES: dict[str, Role] = {
    "techlead": Role("techlead",
        "Act like a senior technical lead managing a real engineering team. "
        "Pick the single highest-priority task, weigh trade-offs, and keep scope tight.",
        _READ_ONLY, "sonnet", 0.50),
    "architect": Role("architect",
        "Act like a senior systems architect designing infrastructure for a high-growth "
        "startup. Design the change before any code; record the decision.",
        ("Read", "Grep", "Glob", "Write"), "opus", 2.0),
    "engineer": Role("engineer",
        "Act like a senior full-stack engineer building a production-ready startup MVP. "
        "Implement exactly the task in the worktree; keep it minimal but scalable.",
        _EDIT, "sonnet", 2.0),
    "reviewer": Role("reviewer",
        "Act like a senior engineer who just joined an unfamiliar codebase. Reverse-engineer "
        "the change, find defects and risks. Do not change functionality.",
        _READ_ONLY, "opus", 1.0),
    "refactorer": Role("refactorer",
        "Act like a senior software architect improving code quality. Do NOT change product "
        "behavior; only improve structure, clarity, and maintainability.",
        ("Read", "Edit", "Write", "Grep", "Glob"), "haiku", 1.0),
    "debugger": Role("debugger",
        "Act like a senior debugging engineer investigating a failing build. Trace the real "
        "root cause and apply the most robust fix.",
        ("Read", "Edit", "Grep", "Glob", "Bash"), "sonnet", 1.0),
    "performance": Role("performance",
        "Act like a senior performance engineer. Identify and fix a measured hotspot only.",
        ("Read", "Edit", "Grep", "Glob", "Bash"), "sonnet", 1.0),
    "security": Role("security",
        "Act like a senior security engineer auditing a change. Report vulnerabilities, "
        "severity, and fixes.",
        _READ_ONLY, "opus", 1.0),
    "qa": Role("qa",
        "Act like a senior test engineer. Add/extend tests that verify real behavior and "
        "edge cases for the change.",
        ("Read", "Edit", "Write", "Grep", "Glob", "Bash"), "haiku", 1.0),
    "writer": Role("writer",
        "Act like a technical documentation writer. Summarize what changed, clearly.",
        ("Read", "Write"), "haiku", 0.25),
    "daemon": Role("daemon", "(daemon-run stage; not an agent)", (), "haiku", 0.0),
    "devops": Role("devops", "(deploy stage; gated, not run autonomously)", (), "sonnet", 0.0),
    "git": Role("git", "(commit/PR stage; daemon-run in F2b)", (), "haiku", 0.0),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_roles.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/roles.py tests/test_factory_roles.py
git commit -m "feat(factory): role registry (prompts, allowlists, model tiers)"
```

---

### Task 2: `factory/runner.py` — argv + env builders (pure functions)

**Files:**
- Create: `factory/runner.py`
- Test: `tests/test_factory_runner_build.py`

**Interfaces:**
- Consumes: `factory.roles.Role`
- Produces:
  - `build_argv(role: Role, *, claude_bin: str = "claude") -> list[str]` — the `claude -p` argv; prompt goes via stdin (not here); `--allowedTools` is LAST.
  - `build_env(source: dict[str, str] | None = None) -> dict[str, str]` — minimal env allowlist; forwards only `_KEEP` + the explicit claude-auth vars; nothing else.
  - module constants `_KEEP: frozenset[str]`, `_CLAUDE_AUTH: tuple[str, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_runner_build.py
from factory import roles, runner


def test_build_argv_has_required_flags():
    role = roles.ROLES["engineer"]
    argv = runner.build_argv(role, claude_bin="/fake/claude")
    assert argv[0] == "/fake/claude"
    assert "-p" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert argv[argv.index("--model") + 1] == "sonnet"
    assert argv[argv.index("--append-system-prompt") + 1] == role.system_prompt
    assert argv[argv.index("--max-budget-usd") + 1] == str(role.max_budget_usd)


def test_build_argv_allowedtools_is_last_and_variadic():
    role = roles.ROLES["engineer"]
    argv = runner.build_argv(role)
    i = argv.index("--allowedTools")
    assert tuple(argv[i + 1:]) == role.allowed_tools  # nothing after the tool list


def test_build_argv_no_positional_prompt():
    # prompt is delivered via stdin, so no role text should appear as a bare positional
    argv = runner.build_argv(roles.ROLES["reviewer"])
    assert "-p" in argv and argv.count("-p") == 1


def test_build_env_drops_secret_shaped_vars():
    src = {
        "PATH": "/usr/bin", "HOME": "/home/x",
        "OPENAI_API_KEY": "sk-secret", "MY_TOKEN": "t", "DB_PASSWORD": "p",
        "ANTHROPIC_API_KEY": "ak",  # explicit claude-auth — allowed through
    }
    env = runner.build_env(src)
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/x"
    assert "OPENAI_API_KEY" not in env
    assert "MY_TOKEN" not in env
    assert "DB_PASSWORD" not in env
    assert env.get("ANTHROPIC_API_KEY") == "ak"  # only the explicit auth var survives


def test_build_env_only_claude_auth_is_secret_shaped():
    import re
    src = {"PATH": "/usr/bin", "AWS_SECRET_ACCESS_KEY": "x", "ANTHROPIC_API_KEY": "ak"}
    env = runner.build_env(src)
    secretish = [k for k in env if re.search(r"KEY|SECRET|TOKEN|PASSWORD|DSN|CREDENTIAL", k, re.I)]
    assert secretish == ["ANTHROPIC_API_KEY"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_runner_build.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'factory.runner'`

- [ ] **Step 3: Write minimal implementation**

```python
# factory/runner.py
"""The real ClaudeCliRunner: an AgentAdapter that drives `claude -p` for agent-work
pipeline stages. F2a implements the agent-work path only; build/security/commit_pr
are wired in F2b. Fail-closed: any subprocess/parse failure -> ok=False."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from factory.roles import Role

# env allowlist — keep only innocuous vars + the explicit claude-auth set; nothing
# secret-shaped reaches the agent (synthetic-data invariant).
_KEEP: frozenset[str] = frozenset(
    {"PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "SHELL", "USER", "TMPDIR"}
)
_CLAUDE_AUTH: tuple[str, ...] = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")

AGENT_WORK_VERBS: frozenset[str] = frozenset(
    {"architect", "implement", "review", "refactor", "debug", "optimize", "test", "next_tasks"}
)


def build_argv(role: Role, *, claude_bin: str = "claude") -> list[str]:
    # --allowedTools is variadic; keep it LAST so it consumes only the tool list.
    argv = [
        claude_bin, "-p",
        "--output-format", "json",
        "--append-system-prompt", role.system_prompt,
        "--permission-mode", "acceptEdits",
        "--model", role.model,
        "--max-budget-usd", str(role.max_budget_usd),
        "--allowedTools", *role.allowed_tools,
    ]
    return argv


def build_env(source: dict[str, str] | None = None) -> dict[str, str]:
    src = os.environ if source is None else source
    env = {k: src[k] for k in _KEEP if k in src}
    for k in _CLAUDE_AUTH:
        if k in src:
            env[k] = src[k]
    return env
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_runner_build.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/runner.py tests/test_factory_runner_build.py
git commit -m "feat(factory): runner argv + minimal-env builders"
```

---

### Task 3: `factory/runner.py` — JSON result parser

**Files:**
- Modify: `factory/runner.py` (append `parse_result`)
- Test: `tests/test_factory_runner_parse.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `parse_result(stdout: str) -> tuple[bool, float, str]` returning `(ok, cost_usd, text)`. `ok = (not is_error)` for a well-formed JSON object; unparseable / non-dict / missing keys → fail-closed `(False, 0.0, "")`. Reads `is_error`, `total_cost_usd`, `result` defensively (schema may drift; F2d confirms the live shape).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_runner_parse.py
from factory import runner


def test_parse_success_envelope():
    out = '{"type":"result","subtype":"success","is_error":false,' \
          '"total_cost_usd":0.0123,"result":"done","session_id":"s1"}'
    ok, cost, text = runner.parse_result(out)
    assert ok is True and abs(cost - 0.0123) < 1e-9 and text == "done"


def test_parse_error_envelope_is_not_ok():
    out = '{"is_error":true,"total_cost_usd":0.5,"result":"boom"}'
    ok, cost, text = runner.parse_result(out)
    assert ok is False and abs(cost - 0.5) < 1e-9


def test_parse_unparseable_fails_closed():
    ok, cost, text = runner.parse_result("not json at all")
    assert ok is False and cost == 0.0 and text == ""


def test_parse_non_object_fails_closed():
    ok, cost, text = runner.parse_result('["a","list"]')
    assert ok is False and cost == 0.0 and text == ""


def test_parse_missing_keys_defaults_safely():
    ok, cost, text = runner.parse_result('{"session_id":"s1"}')
    # no is_error -> treated as not-error (ok True), no cost -> 0.0, no result -> ""
    assert ok is True and cost == 0.0 and text == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_runner_parse.py -v`
Expected: FAIL — `AttributeError: module 'factory.runner' has no attribute 'parse_result'`

- [ ] **Step 3: Write minimal implementation (append to `factory/runner.py`)**

```python
def parse_result(stdout: str) -> tuple[bool, float, str]:
    """Parse a `claude -p --output-format json` envelope. Fail-closed on anything
    unexpected. Returns (ok, cost_usd, text)."""
    try:
        data = json.loads(stdout)
    except Exception:
        return (False, 0.0, "")
    if not isinstance(data, dict):
        return (False, 0.0, "")
    is_error = bool(data.get("is_error", False))
    try:
        cost = float(data.get("total_cost_usd", 0.0) or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    text = str(data.get("result", ""))
    return (not is_error, cost, text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_runner_parse.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/runner.py tests/test_factory_runner_parse.py
git commit -m "feat(factory): defensive claude -p JSON result parser"
```

---

### Task 4: `ClaudeCliRunner.run` — agent-work path (against a fake `claude`)

**Files:**
- Modify: `factory/runner.py` (add the `ClaudeCliRunner` class)
- Create: `tests/fixtures/fake_claude.py` (the stub binary)
- Test: `tests/test_factory_runner_run.py`

**Interfaces:**
- Consumes: `core.portfolio.actions.Action`, `factory.roles.ROLES`, `build_argv`, `build_env`, `parse_result`.
- Produces:
  - `class ClaudeCliRunner` with `__init__(self, worktree, *, claude_bin="claude", timeout_s=1800)` and `run(self, action) -> dict` returning `{"ok","cost_usd","output","pr_url"}`.
  - Agent-work verbs → real `subprocess.run([...], cwd=worktree, input=<brief>, env=build_env(), capture_output=True, text=True, timeout=timeout_s)`. Non-zero exit/timeout/parse-fail → `ok=False`. Unknown role → `ok=False`.
  - Gate/git verbs (`build`, `security`, `commit_pr`) → raise `NotImplementedError` ("wired in F2b").
  - Other verbs (`report` etc.) → `{"ok": True, "cost_usd": 0.0, "output": "", "pr_url": None}`.
  - `_brief(self, action) -> str` builds the task brief text from `action.payload["task"]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_factory_runner_run.py
import sys
from pathlib import Path

import pytest
from core.portfolio.actions import Action, ActionClass
from factory import runner

FAKE = str(Path(__file__).parent / "fixtures" / "fake_claude.py")


def _action(verb="implement", agent="engineer"):
    return Action(verb=verb, agent=agent, action_class=ActionClass.GREEN,
                  preconditions=[], business="acme",
                  payload={"task": {"id": "t1", "title": "add health endpoint"},
                           "cycle_id": "c1"})


def _runner(tmp_path, mode):
    # fake_claude.py reads FAKE_CLAUDE_MODE to decide what JSON to emit
    r = runner.ClaudeCliRunner(tmp_path, claude_bin=f"{sys.executable} {FAKE}")
    r._mode = mode  # not used by runner; the env carries the mode (see fixture)
    return r


def test_agent_work_success(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "success")
    r = runner.ClaudeCliRunner(tmp_path, claude_bin=f"{sys.executable} {FAKE}")
    out = r.run(_action())
    assert out["ok"] is True
    assert out["cost_usd"] == 0.01
    assert out["pr_url"] is None


def test_agent_work_error_is_not_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "error")
    r = runner.ClaudeCliRunner(tmp_path, claude_bin=f"{sys.executable} {FAKE}")
    out = r.run(_action())
    assert out["ok"] is False


def test_agent_work_timeout_is_not_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "hang")
    r = runner.ClaudeCliRunner(tmp_path, claude_bin=f"{sys.executable} {FAKE}", timeout_s=1)
    out = r.run(_action())
    assert out["ok"] is False
    assert "timeout" in out["output"].lower()


def test_unknown_role_is_not_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "success")
    r = runner.ClaudeCliRunner(tmp_path, claude_bin=f"{sys.executable} {FAKE}")
    out = r.run(_action(agent="nonexistent"))
    assert out["ok"] is False


def test_gate_verbs_not_implemented_in_f2a(tmp_path):
    r = runner.ClaudeCliRunner(tmp_path, claude_bin=f"{sys.executable} {FAKE}")
    for verb in ("build", "security", "commit_pr"):
        with pytest.raises(NotImplementedError):
            r.run(_action(verb=verb, agent="daemon"))


def test_report_verb_is_noop_ok(tmp_path):
    r = runner.ClaudeCliRunner(tmp_path, claude_bin=f"{sys.executable} {FAKE}")
    out = r.run(_action(verb="report", agent="writer"))
    assert out["ok"] is True and out["cost_usd"] == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_factory_runner_run.py -v`
Expected: FAIL — `AttributeError: module 'factory.runner' has no attribute 'ClaudeCliRunner'` (and the fixture does not exist yet)

- [ ] **Step 3a: Create the fake `claude` stub**

```python
# tests/fixtures/fake_claude.py
"""A fake `claude` for tests. Reads FAKE_CLAUDE_MODE and emits a canned
--output-format json envelope on stdout. Never calls the network."""
import os
import sys
import time


def main() -> int:
    mode = os.environ.get("FAKE_CLAUDE_MODE", "success")
    # drain stdin (the runner pipes the prompt in); we ignore it
    try:
        sys.stdin.read()
    except Exception:
        pass
    if mode == "hang":
        time.sleep(30)
        return 0
    if mode == "error":
        print('{"type":"result","is_error":true,"total_cost_usd":0.0,"result":"failed"}')
        return 1
    # success
    print('{"type":"result","subtype":"success","is_error":false,'
          '"total_cost_usd":0.01,"result":"done","session_id":"s1"}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3b: Add `ClaudeCliRunner` to `factory/runner.py`**

```python
# append to factory/runner.py
import shlex

from factory import roles as _roles


class ClaudeCliRunner:
    """Real AgentAdapter for the factory pipeline. F2a: agent-work verbs only."""

    def __init__(self, worktree, *, claude_bin: str = "claude", timeout_s: int = 1800):
        self.worktree = Path(worktree)
        self.claude_bin = claude_bin
        self.timeout_s = timeout_s

    def _brief(self, action) -> str:
        task = (action.payload or {}).get("task", {})
        return (f"Task: {task.get('title', '(untitled)')}\n"
                f"Task id: {task.get('id', '?')}\n"
                f"Work only within this worktree. Satisfy the task; keep the change minimal.")

    def run(self, action) -> dict:
        verb = action.verb
        if verb in AGENT_WORK_VERBS:
            return self._run_agent(action)
        if verb in {"build", "security", "commit_pr"}:
            raise NotImplementedError(f"{verb} runner path is wired in F2b")
        return {"ok": True, "cost_usd": 0.0, "output": "", "pr_url": None}

    def _run_agent(self, action) -> dict:
        role = _roles.ROLES.get(action.agent)
        if role is None:
            return {"ok": False, "cost_usd": 0.0,
                    "output": f"no role for agent {action.agent!r}", "pr_url": None}
        # claude_bin may be "python /path/fake_claude.py"; split into argv head.
        head = shlex.split(self.claude_bin)
        argv = head[1:] if len(head) > 1 else []
        cmd = [head[0], *argv] + build_argv(role)[1:]  # drop the placeholder bin from build_argv
        try:
            proc = subprocess.run(
                cmd, cwd=str(self.worktree), input=self._brief(action),
                capture_output=True, text=True, timeout=self.timeout_s, env=build_env(),
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "cost_usd": 0.0, "output": "timeout", "pr_url": None}
        if proc.returncode != 0:
            _, cost, _ = parse_result(proc.stdout)
            return {"ok": False, "cost_usd": cost,
                    "output": (proc.stdout or proc.stderr or "")[:2000], "pr_url": None}
        ok, cost, text = parse_result(proc.stdout)
        return {"ok": ok, "cost_usd": cost, "output": text[:2000], "pr_url": None}
```

Note: `build_argv(role)` returns argv starting with the placeholder `"claude"`; we drop element 0 and prepend the real (possibly multi-token) `claude_bin`. This keeps `build_argv` a pure, bin-agnostic function while supporting a `"python fake_claude.py"` test bin.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_factory_runner_run.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add factory/runner.py tests/fixtures/fake_claude.py tests/test_factory_runner_run.py
git commit -m "feat(factory): ClaudeCliRunner agent-work path (fake-stub tested)"
```

---

### Task 5: F2a suite green + no regressions

**Files:** none (verification task).

- [ ] **Step 1: Run the full factory suite**

Run: `python -m pytest tests/test_factory_*.py -v`
Expected: PASS — F1's 49 + F2a's ~20 new = ~69 green.

- [ ] **Step 2: Confirm no W-MOS regressions**

Run: `python -m pytest tests/test_portfolio_*.py -q`
Expected: PASS (106 passed).

- [ ] **Step 3: Confirm the real `claude` is never invoked by the suite**

Run: `grep -rn "claude_bin=" tests/test_factory_runner_run.py`
Expected: every `ClaudeCliRunner` in tests is constructed with a fake `claude_bin` (the `fake_claude.py` stub) — no test uses the default `"claude"`.

- [ ] **Step 4: Commit (if any doc/cleanup)**

```bash
git commit --allow-empty -m "test(factory): F2a runner suite green, no real claude in tests"
```

---

## Self-Review

**1. Spec coverage (F2 spec §→task):**
- §3 verb routing — Task 4 (`run` dispatches agent-work / NotImplementedError gates / no-op report).
- §4 roles (prompts, allowlists, model tiers) — Task 1; `claude -p` argv (confirmed flags, stdin prompt, variadic `--allowedTools` last, `--max-budget-usd`) — Task 2; JSON cost/`is_error` parse, defensive — Task 3; timeout + fail-closed — Task 4.
- §6 synthetic-data env (minimal allowlist, no secret-shaped leak) — Task 2 (`build_env`).
- §7 fake-stub testing, no network/$0 — Tasks 4-5.
- §8 F2a acceptance (roles + runner agent-work against fake stub; R1 denial *designed for*, verified live in F2d) — Tasks 1-5.
- **Deferred to F2b (intentional, not gaps):** `worktree.py`, `gates.py` (build/security daemon-verified), `pr.py` (commit/push/gh), and the gate/git verb bodies (Task 4 raises `NotImplementedError` for them). **Deferred to F2c:** kill-criteria retry, budget pre-emption, `runner: AgentAdapter` annotations, scheduler/cli wiring. **F2d:** the real-`claude` smoke + live R1 check.

**2. Placeholder scan:** none — every code/test step is complete; the gate verbs are explicitly `NotImplementedError` (a real, tested behavior, not a placeholder).

**3. Type consistency:** runner returns the F1 contract dict `{ok, cost_usd, output, pr_url}` everywhere (Tasks 4) — matches what `factory/pipeline.py` consumes. `Role` fields (`system_prompt, allowed_tools, model, max_budget_usd`) consistent across Tasks 1-2-4. `parse_result -> (ok, cost, text)` consistent Tasks 3-4. `build_argv`/`build_env` signatures consistent Tasks 2-4.

**Out of F2a scope (tracked for F2b/c/d):** real worktree/gates/PR; carry-over fixes; live `claude`/`gh` smoke + R1 confirmation.
