"""Disposable A2-certification fixture (non-authority, low-risk).

The limited-A2 closed-loop cert edits THIS file inside an ISOLATED git worktree to prove the prepare-only
flow end to end (worktree -> bounded edit -> authoritative diff -> tests -> independent review ->
READY_FOR_REVIEW) with real git operations. It is intentionally trivial, touches no authority surface,
and is never merged. Nothing in production imports it.
"""


def add(a, b):
    return a + b
