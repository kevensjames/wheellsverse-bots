"""Disposable self-improvement BEFORE/AFTER fixture (non-authority, non-production).

A bounded due-date bucket normalizer with a SEEDED boundary defect. The certified guard suite
(test_si_calc_guard.py) FAILS on this defect; the self-improvement worker fixes THIS source file (only),
in an isolated worktree, so the same byte-identical guard suite PASSES. Nothing in production imports it;
it is never merged. Deliberately trivial and side-effect-free.
"""


def bucket(days_until_due: int) -> str:
    """Classify a due-date offset. SEEDED DEFECT: the day-0 boundary is misclassified as OK instead of
    DUE_SOON (the `> 0` should be `>= 0`). The guard suite pins the correct boundaries."""
    if days_until_due < 0:
        return "OVERDUE"
    if days_until_due > 0 and days_until_due <= 7:   # BUG: excludes day 0
        return "DUE_SOON"
    return "OK"
