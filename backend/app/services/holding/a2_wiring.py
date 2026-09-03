"""Limited-A2 wiring (Part D Phase 1) — the FIRST grant + the REAL isolated-worktree/test ops that plug
into the already-certified A2Framework (a2_framework.py). Prepare-only: A2 creates an isolated worktree,
makes a bounded change, runs the certified suite, gets an INDEPENDENT review, and stops at
READY_FOR_REVIEW. It never merges, never deploys, never touches an authority-immutable surface.

Safety posture: A2 is OFF by default (KAI_A2_EXECUTION_ENABLED false) and subordinate to both global
brakes. Even ON, the LIVE cycle keeps A2 at NEEDS_CERTIFICATION until a real coding worker is wired here
(build_live_engine passes no framework). This module supplies the grant + real git ops; the coding
worker is injected (the cert injects a deterministic one; a real worker plane plugs in unchanged).
"""
from __future__ import annotations

import re
import subprocess

from app.services.holding.a2_framework import A2Framework, A2GrantRegistry, A2Grant
from app.services.capability.coding import WorktreeAssignment

# ── FIRST GRANT — SELF_IMPROVEMENT_NONPROD_CODE_FIX_V1 ─────────────────────────────────────────────
# Exactly one action_type, one capability, one repo, staging only. Deliberately NOT broadened. A2Grant
# construction itself rejects production + forbidden actions (a2_framework.A2GrantRegistry.grant).
SELF_IMPROVEMENT_NONPROD_CODE_FIX_V1 = [
    A2Grant(action_type="EDIT_CODE_IN_WORKTREE", capability="coding",
            company_id="wheellsverse", environment="staging"),
]


def build_a2_grant_registry() -> A2GrantRegistry:
    return A2GrantRegistry(list(SELF_IMPROVEMENT_NONPROD_CODE_FIX_V1))


def make_git_worktree_fn(repo_dir: str):
    """Return worktree_fn(mission_id, base_sha, base_dir) that creates a REAL isolated git worktree +
    feature branch at base_sha, off `repo_dir`. Disposable; the caller removes it. Never touches the
    primary checkout (a worktree is a separate working tree sharing the object store)."""
    def _worktree(mission_id, base_sha, base_dir):
        wid = "a2"
        branch = f"kai/{mission_id}/{wid}"
        path = f"{base_dir.rstrip('/')}/{mission_id}-{wid}"
        # Idempotent: a RECLAIMED/retried mission (a worker crashed mid-job, its lease expired, another
        # worker re-claims — attempt 2) must not collide with attempt-1's stale worktree/branch. Clear any
        # leftover first so exactly ONE authoritative execution proceeds cleanly. Best-effort; never raises.
        subprocess.run(["git", "-C", repo_dir, "worktree", "remove", "--force", path],
                       capture_output=True, text=True, timeout=30)
        subprocess.run(["git", "-C", repo_dir, "worktree", "prune"], capture_output=True, text=True, timeout=15)
        subprocess.run(["git", "-C", repo_dir, "branch", "-D", branch], capture_output=True, text=True, timeout=15)
        r = subprocess.run(["git", "-C", repo_dir, "worktree", "add", "-b", branch, path, base_sha or "HEAD"],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError(f"worktree add failed: {(r.stderr or '')[:200]}")
        return WorktreeAssignment(worker_id=wid, mission_id=mission_id, branch=branch, worktree=path,
                                  starting_sha=base_sha or "HEAD")
    return _worktree


def remove_worktree(repo_dir: str, path: str, branch: str = "") -> None:
    """Best-effort cleanup: remove the disposable worktree and its branch. Never raises."""
    subprocess.run(["git", "-C", repo_dir, "worktree", "remove", "--force", path],
                   capture_output=True, text=True, timeout=30)
    if branch:
        subprocess.run(["git", "-C", repo_dir, "branch", "-D", branch],
                       capture_output=True, text=True, timeout=15)


# certified suite RUN_INTERNAL_TEST executes in the worktree (path relative to the worktree root)
_DEFAULT_SUITE = ["python3", "backend/app/services/holding/test_self_model.py"]


def make_worktree_test_fn(suite_cmd=None):
    """Return test_fn(wt) that runs a certified suite IN the worktree and returns real counts — the
    §40 independent test evidence (never the worker's self-report). A non-zero exit with no parsed
    failure still counts as a failure (fail closed)."""
    cmd = list(suite_cmd or _DEFAULT_SUITE)

    def _test(wt):
        r = subprocess.run(cmd, cwd=wt.worktree, capture_output=True, text=True, timeout=120)
        out = (r.stdout or "") + (r.stderr or "")

        def n(k):
            m = re.search(rf"(\d+) {k}", out)
            return int(m.group(1)) if m else 0
        passed, failed, skipped = n("passed"), n("failed"), n("skipped")
        if r.returncode != 0 and failed == 0:
            failed = 1                                   # fail closed on a non-zero exit
        run = passed + failed + skipped
        if r.returncode != 0 and run == 0:
            run = 1
        return {"tests_run": run, "tests_passed": passed, "tests_failed": failed}
    return _test


def build_a2_framework(*, repo_dir: str, worker_fn=None, test_fn=None,
                       reviewer: str = "kai-independent-reviewer") -> A2Framework:
    """Construct the limited-A2 framework with the first grant + REAL git worktree + independent test.
    worker_fn is the coding worker (injected; None → prepares the worktree only, no change). The default
    diff/diff-lines come from A2Framework (real `git diff` from the worktree, not the worker self-report)."""
    return A2Framework(build_a2_grant_registry(),
                       worktree_fn=make_git_worktree_fn(repo_dir),
                       worker_fn=worker_fn,
                       test_fn=test_fn or make_worktree_test_fn(),
                       reviewer=reviewer)
