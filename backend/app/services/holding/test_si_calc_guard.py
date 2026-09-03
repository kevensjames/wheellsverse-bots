"""CERTIFIED guard suite for the self-improvement BEFORE/AFTER fixture (si_calc.bucket).

Pins the day-0/day-7 boundaries. It FAILS on the seeded defect in si_calc.py and PASSES once the SOURCE
is fixed. This file is AUTHORITY-IMMUTABLE to the A2 worker (denylisted in a2_framework._AUTHORITY_IMMUTABLE
as 'test_si_calc_guard') so the before/after proof's test can never be edited to manufacture a pass — the
worker must fix the source, not the test. Runnable as `python3 .../test_si_calc_guard.py` (prints the
"N passed, N failed" counts the RUN_INTERNAL_TEST parser reads; exits non-zero on any failure).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))   # backend/ on path
from app.services.holding.si_calc import bucket   # noqa: E402

CASES = [(-5, "OVERDUE"), (-1, "OVERDUE"), (0, "DUE_SOON"), (1, "DUE_SOON"),
         (7, "DUE_SOON"), (8, "OK"), (30, "OK")]


def run() -> int:
    passed = failed = 0
    for days, expected in CASES:
        got = bucket(days)
        if got == expected:
            passed += 1
        else:
            failed += 1
            print(f"  FAIL bucket({days}) = {got!r}, expected {expected!r}")
    print(f"{passed} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
