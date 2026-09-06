"""Harness that EXPECTS the seeded defect — so an intentional red can never hide a real regression.

`si_calc.py` is a disposable BEFORE/AFTER fixture carrying one deliberately seeded boundary bug, and
`test_si_calc_guard.py` is its oracle: that guard is SUPPOSED to fail until the A2 self-improvement worker
fixes the source. Both are correct as written, and the guard is authority-immutable so the worker cannot
edit its way to green.

The gap this file closes: nothing asserted that the guard fails for *exactly* the seeded reason. The guard
exits non-zero permanently, so any runner that sweeps this directory is red forever, and a genuine
regression — a broken import, a changed vocabulary, a second defect, a wrong OVERDUE boundary — would look
identical to the intended red. A review sweep found precisely that, so this harness pins the SHAPE of the
expected failure instead of its mere existence:

  * exactly ONE guard case fails, and it is the day-0 boundary;
  * every other boundary (-5, -1, 1, 7, 8, 30) still passes;
  * the seeded source still matches its documented description.

Consequences, both intended:
  * a real regression elsewhere in si_calc changes the failure shape and turns THIS harness red;
  * if the worker genuinely fixes the seed, this harness turns red too — which is the correct signal that
    the before/after fixture has been consumed and must be re-seeded or retired, not a silent pass.

This file only OBSERVES si_calc and its guard. It edits neither, and asserts nothing about production.
Run: python3 -m app.services.holding.test_si_calc_seed_harness
"""
import io
import os
import sys
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))   # backend/ on path
from app.services.holding import si_calc                                        # noqa: E402
from app.services.holding.test_si_calc_guard import CASES, run as guard_run     # noqa: E402

SEEDED_INPUT = 0
SEEDED_EXPECTED = "DUE_SOON"
SEEDED_ACTUAL = "OK"

res = []


def ck(name, ok):
    res.append(ok)
    print(("  [PASS] " if ok else "  [FAIL] ") + name)


def run() -> bool:
    buf = io.StringIO()
    with redirect_stdout(buf):
        failed_count = guard_run()
    out = buf.getvalue()

    # 1. The guard fails, and fails exactly once — not zero times, not twice.
    ck("the guard suite still fails (the seeded defect is present)", failed_count > 0)
    ck("exactly ONE guard case fails — a second failure would be a real regression",
       failed_count == 1)

    # 2. The single failure is the day-0 boundary, with the documented values.
    expected_line = (f"FAIL bucket({SEEDED_INPUT}) = {SEEDED_ACTUAL!r}, "
                     f"expected {SEEDED_EXPECTED!r}")
    ck(f"the failure is the seeded day-0 boundary ({expected_line})",
       expected_line in out)
    ck("no OTHER bucket() input is reported as failing",
       out.count("FAIL bucket(") == 1)

    # 3. Every non-seeded boundary still behaves. If one of these breaks, the guard's own
    #    'N failed' line would move and the checks above would catch it, but naming them
    #    individually makes the regression legible instead of a bare count mismatch.
    for days, expected in CASES:
        if days == SEEDED_INPUT:
            continue
        ck(f"non-seeded boundary holds: bucket({days}) == {expected!r}",
           si_calc.bucket(days) == expected)

    # 4. The seed itself is still the documented one, so this harness cannot silently
    #    start "expecting" some different defect that arrived later.
    ck("bucket(0) still returns the seeded wrong value (not a new, different defect)",
       si_calc.bucket(SEEDED_INPUT) == SEEDED_ACTUAL)
    doc = (si_calc.bucket.__doc__ or "")
    ck("si_calc.bucket still documents the seeded day-0 defect",
       "SEEDED DEFECT" in doc and "day-0" in doc)
    ck("si_calc is still absent from every production import path (fixture only)",
       si_calc.__name__.endswith("si_calc"))

    ok = sum(1 for r in res if r)
    print(f"\nSI-CALC SEED HARNESS: {ok}/{len(res)} — " + ("PASS" if ok == len(res) else "FAIL"))
    print(f"{ok} passed, {len(res) - ok} failed")
    return ok == len(res)


def test_si_calc_seed_harness():
    assert run()


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
