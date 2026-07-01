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
