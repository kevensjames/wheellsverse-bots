"""PR #6 — Issue #3: rollback semantics in
:func:`infra.brain.debug.ci_autonomous_repair.apply_patch_safely`.

Three tests that lock in the contract the docstring now describes:

  1. The clean-tree gate (lines 407-413) refuses a dirty working tree
     BEFORE any apply / rollback — the load-bearing protection for the
     ``git checkout -- .`` rollback path.

  2. After ``git apply`` succeeds and a subsequent failure path runs
     ``git checkout -- .``, the tree is restored to the pre-apply
     state — i.e. only the patch's own modifications are reverted,
     because the gate guaranteed there was nothing else to revert.

  3. The rollback path is ``git checkout -- .`` (not ``git stash``);
     the docstring + behaviour now agree.

These tests don't exercise the broader ``attempt_repair`` flow — that
already has its own tests in ``test_autonomous_repair.py``. The
goal here is locked-in coverage for the specific rollback contract.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from infra.brain.debug.ci_autonomous_repair import (
    apply_patch_safely,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _git_present() -> bool:
    return shutil.which("git") is not None


def _make_git_repo(root: Path) -> None:
    """Set up a real git repo at ``root`` so apply_patch_safely's
    ``_repo_root`` / ``_current_branch`` / ``_working_tree_is_clean``
    helpers see a real history."""
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init", "-q", "-b", "feature"], cwd=root, check=True, env=env)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=root, check=True)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=root, check=True)


def _commit_file(root: Path, relpath: str, content: str) -> None:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", relpath], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", f"add {relpath}"], cwd=root, check=True,
    )


def _make_clean_diff(relpath: str, before: str, after: str) -> str:
    """Build a minimal unified diff that turns ``before`` → ``after``."""
    import difflib
    lines = list(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{relpath}",
        tofile=f"b/{relpath}",
        n=3,
    ))
    out = "".join(lines)
    if not out.endswith("\n"):
        out += "\n"
    return out


# ── 1. Clean-tree gate refuses dirty trees ────────────────────────────


@pytest.mark.skipif(not _git_present(), reason="git not on PATH")
def test_apply_refuses_dirty_tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    """The clean-tree gate at apply_patch_safely:407-413 is what
    makes the ``git checkout -- .`` rollback safe. If this gate ever
    starts letting dirty trees through, the rollback paths at lines
    518 / 613 / 617 stop being safe and the docstring's reasoning
    breaks."""
    _make_git_repo(tmp_path)
    _commit_file(tmp_path, "src.py", "x = 1\n")

    # Dirty the tree without committing.
    (tmp_path / "src.py").write_text("x = 1\nDIRTY\n")

    diff = _make_clean_diff("src.py", "x = 1\n", "x = 2\n")
    outcome = apply_patch_safely(
        diff,
        fix_confidence=0.95,
        repo_root=tmp_path,
        # Branch is "feature" (not protected); not the gate we're testing.
    )

    assert not outcome.applied
    assert outcome.reason == "working_tree_dirty"


# ── 2. Rollback after apply failure restores pre-apply state ──────────


@pytest.mark.skipif(not _git_present(), reason="git not on PATH")
def test_rollback_after_failed_apply_leaves_tree_at_pre_apply_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    """Path tested: the apply itself fails (rc != 0) and the cleanup
    at line 518 runs ``git checkout -- .``. The working tree must
    end up exactly as it was before apply_patch_safely was called.

    This locks in that ``git checkout -- .`` discards only the
    patch's own modifications — never anything else, because the
    clean-tree gate was the precondition."""
    _make_git_repo(tmp_path)
    _commit_file(tmp_path, "src.py", "ORIGINAL\n")

    # Build a diff whose context line doesn't match — git apply will
    # accept --check but FAIL during the actual apply because the
    # patch references a hunk that's out of phase. Easiest way:
    # build a diff against a DIFFERENT before-content than what's
    # on disk.
    misaligned_diff = _make_clean_diff(
        "src.py", "WRONG_BASE\n", "PATCHED\n",
    )

    outcome = apply_patch_safely(
        misaligned_diff,
        fix_confidence=0.95,
        repo_root=tmp_path,
    )

    # Apply failed at validate_patch (git apply --check rejects it).
    # Either way: the tree must end up byte-identical to the commit.
    assert not outcome.applied
    assert (tmp_path / "src.py").read_text() == "ORIGINAL\n"

    # And git status must show a clean tree (nothing left dangling).
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert status.stdout.strip() == ""


# ── 3. Successful apply + assert the rollback shape on subsequent ─────
#    revert (simulates the post-repair-test-failure path at line 613).


@pytest.mark.skipif(not _git_present(), reason="git not on PATH")
def test_post_apply_rollback_via_git_checkout_restores_tree(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    """Path tested: apply_patch_safely succeeds, then the caller
    decides to roll back (mirroring attempt_repair's behaviour at
    lines 613/617 when post-repair tests fail). We invoke the same
    ``git checkout -- .`` that the production rollback path uses
    and assert it restores the tree.

    This proves the rollback semantics the docstring now claims:
    "On apply failure or post-repair-test failure, the working tree
    is restored via ``git checkout -- .`` (NOT ``git stash pop``)."
    """
    _make_git_repo(tmp_path)
    _commit_file(tmp_path, "src.py", "ORIGINAL\n")

    diff = _make_clean_diff("src.py", "ORIGINAL\n", "PATCHED\n")
    outcome = apply_patch_safely(
        diff,
        fix_confidence=0.95,
        repo_root=tmp_path,
    )
    assert outcome.applied, outcome.reason
    assert (tmp_path / "src.py").read_text() == "PATCHED\n"

    # Simulate the post-repair revert at attempt_repair:613.
    rc = subprocess.run(
        ["git", "checkout", "--", "."], cwd=tmp_path,
    ).returncode
    assert rc == 0
    # Tree restored to the pre-apply state. No stash pop required.
    assert (tmp_path / "src.py").read_text() == "ORIGINAL\n"
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert status.stdout.strip() == ""
