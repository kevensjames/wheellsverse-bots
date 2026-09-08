"""Resource limit and back-pressure checks.

Each test names the unbounded failure it prevents, because a limit without that context
reads as an arbitrary number and gets raised the first time someone hits it.

    cd backend && python3 app/services/holding/test_computer_ops_limits.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

_HERE = os.path.abspath(__file__)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))))

from app.services.holding.computer_ops_limits import (  # noqa: E402
    DEFAULT_MISSION_SECONDS, MAX_CONCURRENT_MISSIONS_GLOBAL,
    MAX_CONCURRENT_MISSIONS_PER_DEVICE, MAX_EVIDENCE_BYTES, MAX_EVIDENCE_ENTRIES,
    MAX_MISSION_SECONDS, MAX_NOTE_CHARS, MAX_REQUEST_BYTES, Deadline, LimitExceeded,
    RateLimiter, assert_capacity, assert_evidence_size, assert_request_size,
    clamp_mission_seconds, trim_evidence, truncate_note)

P, F = [], []


def check(n, c, d=""):
    (P if c else F).append(n)
    print(f"  {'ok ' if c else 'FAIL'} {n}" + (f"  ({d})" if d and not c else ""))


def raises(n, fn, *, status=None, needle=""):
    try:
        fn()
        check(n, False, "no exception")
    except LimitExceeded as e:
        ok = (status is None or e.status == status) and (not needle or needle in str(e))
        check(n, ok, f"status={e.status} msg={e}")
    except Exception as e:  # noqa: BLE001
        check(n, False, f"wrong exception {type(e).__name__}")


print("=== request size: a worker cannot hand us unbounded bytes ===")
assert_request_size(b"x" * (MAX_REQUEST_BYTES - 1))
check("a body under the ceiling is accepted", True)
raises("oversized body refused with 413",
       lambda: assert_request_size(b"x" * (MAX_REQUEST_BYTES + 1)), status=413)

print("\n=== evidence: large output belongs on the volume, not in the record ===")
assert_evidence_size(b"y" * (MAX_EVIDENCE_BYTES - 1))
check("evidence under the ceiling is accepted", True)
raises("oversized evidence refused, and says where output belongs",
       lambda: assert_evidence_size(b"y" * (MAX_EVIDENCE_BYTES + 1)),
       status=413, needle="mission volume")
check("evidence ceiling is below the request ceiling",
      MAX_EVIDENCE_BYTES < MAX_REQUEST_BYTES)

print("\n=== concurrency: one mission per device is a real-resource limit ===")
assert_capacity(device_active=0, global_active=0)
check("an idle device may lease", True)
raises("a busy device is refused with 429 + Retry-After",
       lambda: assert_capacity(device_active=MAX_CONCURRENT_MISSIONS_PER_DEVICE,
                               global_active=0), status=429)
raises("a saturated fleet is refused even if the device is idle",
       lambda: assert_capacity(device_active=0,
                               global_active=MAX_CONCURRENT_MISSIONS_GLOBAL), status=429)
try:
    assert_capacity(device_active=MAX_CONCURRENT_MISSIONS_PER_DEVICE, global_active=0)
except LimitExceeded as e:
    check("back-pressure carries Retry-After so a client waits rather than hammers",
          e.retry_after and e.retry_after > 0, str(e.retry_after))

print("\n=== mission deadlines: a wedged worker cannot hold a lease forever ===")
check("a request over the ceiling is clamped, not honoured",
      clamp_mission_seconds(99999) == MAX_MISSION_SECONDS)
check("a smaller request is respected", clamp_mission_seconds(120) == 120)
check("absent/zero falls back to the default",
      clamp_mission_seconds(None) == DEFAULT_MISSION_SECONDS
      and clamp_mission_seconds(0) == DEFAULT_MISSION_SECONDS)
check("negative is not honoured", clamp_mission_seconds(-5) == DEFAULT_MISSION_SECONDS)
past = Deadline(started_at=datetime.now(timezone.utc) - timedelta(seconds=60), seconds=30)
check("an overdue deadline is detected", past.expired())
check("an expired deadline reports zero remaining", past.remaining() == 0.0)
live = Deadline(started_at=datetime.now(timezone.utc), seconds=300)
check("a live deadline is not expired and reports remaining",
      (not live.expired()) and live.remaining() > 290)

print("\n=== truncation is marked, never silent ===")
short = "a" * 10
check("short notes pass through unchanged", truncate_note(short) == short)
long_note = "b" * (MAX_NOTE_CHARS + 500)
t = truncate_note(long_note)
check("long notes are truncated", len(t) < len(long_note))
check("truncation is visible to a reader", "truncated" in t and str(len(long_note)) in t)

kept, dropped = trim_evidence([{"i": i} for i in range(MAX_EVIDENCE_ENTRIES + 25)])
check("evidence is capped", len(kept) == MAX_EVIDENCE_ENTRIES)
check("the drop count is reported so it can be recorded, not hidden", dropped == 25)
check("the NEWEST entries are kept", kept[-1]["i"] == MAX_EVIDENCE_ENTRIES + 24)
kept2, dropped2 = trim_evidence([{"i": 1}])
check("under the cap nothing is dropped", kept2 == [{"i": 1}] and dropped2 == 0)

print("\n=== rate limiting: a crash-looping connector is bounded, not banned ===")
rl = RateLimiter(per_minute=5)
for i in range(5):
    rl.check("dev", now=1000.0 + i)
check("requests under the limit pass", True)
raises("over the limit is 429", lambda: rl.check("dev", now=1005.0), status=429)
rl.check("other-device", now=1005.0)
check("the limit is per device, not global", True)
rl.check("dev", now=1100.0)
check("the window rolls, so a device recovers without intervention", True)

print(f"\n{len(P)} passed, {len(F)} failed")
if F:
    print("FAILED:", F)
sys.exit(1 if F else 0)
