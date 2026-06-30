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
