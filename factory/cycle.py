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
