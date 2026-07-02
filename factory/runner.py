# factory/runner.py
"""The real ClaudeCliRunner: an AgentAdapter that drives `claude -p` for agent-work
pipeline stages. F2a implements the agent-work path only; build/security/commit_pr
are wired in F2b. Fail-closed: any subprocess/parse failure -> ok=False."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

from factory.roles import Role, DENY_TOOLS
from factory import roles as _roles
from factory import gates as _gates
from factory import pr as _pr

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
    argv = [
        claude_bin, "-p",
        "--output-format", "json",
        "--append-system-prompt", role.system_prompt,
        "--permission-mode", "acceptEdits",
        "--model", role.model,
        "--max-budget-usd", str(role.max_budget_usd),
        "--disallowedTools", *DENY_TOOLS,
    ]
    if role.allowed_tools:
        argv += ["--allowedTools", *role.allowed_tools]
    return argv


def build_env(source: dict[str, str] | None = None) -> dict[str, str]:
    src = os.environ if source is None else source
    env = {k: src[k] for k in _KEEP if k in src}
    for k in _CLAUDE_AUTH:
        if k in src:
            env[k] = src[k]
    return env


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


class ClaudeCliRunner:
    """Real AgentAdapter for the factory pipeline. F2a: agent-work verbs only."""

    def __init__(self, worktree, *, claude_bin: str = "claude", timeout_s: int = 1800,
                 build_cmd: str = "python -m pytest -q", pr_base: str = "main", gh_bin: str = "gh"):
        self.worktree = Path(worktree)
        self.claude_bin = claude_bin
        self.timeout_s = timeout_s
        self.build_cmd = build_cmd
        self.pr_base = pr_base
        self.gh_bin = gh_bin

    def _brief(self, action) -> str:
        task = (action.payload or {}).get("task", {})
        return (f"Task: {task.get('title', '(untitled)')}\n"
                f"Task id: {task.get('id', '?')}\n"
                f"Work only within this worktree. Satisfy the task; keep the change minimal.")

    def run(self, action) -> dict:
        verb = action.verb
        if verb in AGENT_WORK_VERBS:
            return self._run_agent(action)
        if verb == "build":
            r = _gates.run_build(self.worktree, cmd=self.build_cmd, timeout_s=self.timeout_s)
            return {"ok": r.ok, "cost_usd": 0.0, "output": r.detail, "pr_url": None}
        if verb == "security":
            r = _gates.run_security(self.worktree)
            if not r.ok and r.findings:
                from factory import state as _state
                _state.append_known_issue(action.business, {
                    "kind": "security", "severity": "high", "findings": r.findings,
                    "detail": r.detail, "task_id": (action.payload or {}).get("task", {}).get("id"),
                })
            return {"ok": r.ok, "cost_usd": 0.0, "output": r.detail, "pr_url": None}
        if verb == "commit_pr":
            task = (action.payload or {}).get("task", {})
            url = _pr.open_pr(self.worktree, action.business, task,
                              base=self.pr_base, gh_bin=self.gh_bin)
            return {"ok": url is not None, "cost_usd": 0.0, "output": "", "pr_url": url}
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
