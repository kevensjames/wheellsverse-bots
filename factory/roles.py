"""Factory role definitions: each pipeline stage's role maps to a system prompt
(the operator's role templates), a tool allowlist (the safety boundary — no
push/deploy/merge/secret tools), and a model tier. Consumed by ClaudeCliRunner."""
from __future__ import annotations

from dataclasses import dataclass

FORBIDDEN_TOOL_SUBSTRINGS: tuple[str, ...] = ("push", "deploy", "merge", "secret")

_BASH_TEST = ("Bash(python *)", "Bash(python3 *)", "Bash(pytest *)", "Bash(pip *)")

# Escape vectors denied for EVERY role (deny wins over allow in claude CLI).
DENY_TOOLS: tuple[str, ...] = (
    "Bash(git push *)", "Bash(git remote *)", "Bash(curl *)", "Bash(wget *)",
    "Bash(ssh *)", "Bash(scp *)", "Bash(nc *)", "Bash(telnet *)",
)

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
_EDIT = ("Read", "Edit", "Write", "Grep", "Glob", *_BASH_TEST)

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
        ("Read", "Edit", "Grep", "Glob", *_BASH_TEST), "sonnet", 1.0),
    "performance": Role("performance",
        "Act like a senior performance engineer. Identify and fix a measured hotspot only.",
        ("Read", "Edit", "Grep", "Glob", *_BASH_TEST), "sonnet", 1.0),
    "security": Role("security",
        "Act like a senior security engineer auditing a change. Report vulnerabilities, "
        "severity, and fixes.",
        _READ_ONLY, "opus", 1.0),
    "qa": Role("qa",
        "Act like a senior test engineer. Add/extend tests that verify real behavior and "
        "edge cases for the change.",
        _EDIT, "haiku", 1.0),
    "writer": Role("writer",
        "Act like a technical documentation writer. Summarize what changed, clearly.",
        ("Read", "Write"), "haiku", 0.25),
    "daemon": Role("daemon", "(daemon-run stage; not an agent)", (), "haiku", 0.0),
    "devops": Role("devops", "(deploy stage; gated, not run autonomously)", (), "sonnet", 0.0),
    "git": Role("git", "(commit/PR stage; daemon-run in F2b)", (), "haiku", 0.0),
}
