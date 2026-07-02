"""Isolated git worktree lifecycle for a factory cycle + the branch-limited push.
Real git; no network beyond the configured remote. safe_push is the physical
guarantee that the daemon can only push factory/<slug>/* branches."""
from __future__ import annotations

import re
import shutil
import subprocess

from factory import paths

_IDENT = ("-c", "user.email=factory@kai.local", "-c", "user.name=KAI Factory")

# Strict token pattern: only alphanumerics, dots, underscores, hyphens.
# No colons, slashes, spaces, or other characters that git interprets in refspecs.
_REF_COMPONENT = re.compile(r"^[A-Za-z0-9._-]+$")


class PushRejected(Exception):
    pass


def _git(cwd, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=True)


def branch_name(slug: str, task_id: str) -> str:
    for label, val in (("slug", slug), ("task_id", task_id)):
        if not _REF_COMPONENT.fullmatch(val):
            raise ValueError(f"unsafe {label} for branch: {val!r}")
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
    # idempotent: clear any stale registration and any existing worktree at this path
    try:
        _git(clone_path, "worktree", "prune")
    except subprocess.CalledProcessError:
        pass
    if wt.exists():
        try:
            _git(clone_path, "worktree", "remove", "--force", str(wt))
        except subprocess.CalledProcessError:
            pass
        if wt.exists():
            shutil.rmtree(wt, ignore_errors=True)
        try:
            _git(clone_path, "worktree", "prune")
        except subprocess.CalledProcessError:
            pass
    existing = _git(clone_path, "branch", "--list", branch).stdout.strip()
    if existing:
        # --force allows checking out a branch already checked out by a stale worktree
        _git(clone_path, "worktree", "add", "--force", str(wt), branch)
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
    if not _REF_COMPONENT.fullmatch(slug):
        raise PushRejected(f"unsafe slug {slug!r}")
    if not re.fullmatch(rf"factory/{re.escape(slug)}/[A-Za-z0-9._-]+", branch):
        raise PushRejected(f"refusing to push non-factory/unsafe branch {branch!r} for {slug!r}")
    subprocess.run(
        ["git", "-C", str(clone_path), *_IDENT, "push", "-u", "origin",
         f"refs/heads/{branch}:refs/heads/{branch}"],
        capture_output=True, text=True, check=True,
    )
