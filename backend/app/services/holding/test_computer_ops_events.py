"""Mission event stream checks.

The stream is a PROJECTION. These tests exist mostly to prove it cannot become anything
more: no event can advance mission state, no replay can exceed its bound silently, and no
secret can ride out on an event.

    cd backend && python3 app/services/holding/test_computer_ops_events.py
"""
from __future__ import annotations

import json
import os
import sys

_HERE = os.path.abspath(__file__)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))))

from app.services.holding.computer_ops_dispatch import Mission  # noqa: E402
from app.services.holding.computer_ops_events import (  # noqa: E402
    MAX_EVENT_BYTES, MAX_REPLAY_EVENTS, events_for, latest_seq, status_event)

P, F = [], []


def check(n, c, d=""):
    (P if c else F).append(n)
    print(f"  {'ok ' if c else 'FAIL'} {n}" + (f"  ({d})" if d and not c else ""))


def mission(n_events=5, **kw):
    m = Mission(mission_id="cop-test", tenant="t", device_id="dev-1",
                autonomy_mode="OBSERVE", objective="x", **kw)
    m.correlation_id = "corr-1"
    for i in range(n_events):
        m.log(f"event_{i}", index=i)
    return m


print("=== monotonic sequence ===")
m = mission(5)
evs, trunc = events_for(m)
check("one event per history entry", len(evs) == 5, str(len(evs)))
check("sequence is 1..n and strictly increasing",
      [e.seq for e in evs] == [1, 2, 3, 4, 5], str([e.seq for e in evs]))
check("latest_seq matches the history length", latest_seq(m) == 5)

print("\n=== reconnect cursor ===")
evs, _ = events_for(m, after_seq=3)
check("a cursor returns only newer events", [e.seq for e in evs] == [4, 5], str([e.seq for e in evs]))
check("a cursor at the head returns nothing", events_for(m, after_seq=5)[0] == [])
check("a cursor beyond the head returns nothing (no negative window)",
      events_for(m, after_seq=99)[0] == [])
check("a negative-ish cursor is treated as from the start",
      len(events_for(m, after_seq=0)[0]) == 5)

print("\n=== appending never renumbers ===")
before = [(e.seq, e.event_type) for e in events_for(m)[0]]
m.log("event_new")
after = [(e.seq, e.event_type) for e in events_for(m)[0]]
check("existing events keep their sequence numbers", after[:5] == before)
check("the new event extends the sequence", after[-1][0] == 6)

print("\n=== bounded replay ===")
big = mission(MAX_REPLAY_EVENTS + 50)
evs, trunc = events_for(big)
check("replay is capped", len(evs) == MAX_REPLAY_EVENTS, str(len(evs)))
check("truncation is REPORTED, not silent", trunc is True)
check("the OLDEST of the window is kept so a cursor has no gap",
      evs[0].seq == 1 and evs[-1].seq == MAX_REPLAY_EVENTS,
      f"{evs[0].seq}..{evs[-1].seq}")
evs2, trunc2 = events_for(big, after_seq=MAX_REPLAY_EVENTS)
check("continuing from the cursor returns the remainder without a gap",
      evs2[0].seq == MAX_REPLAY_EVENTS + 1 and trunc2 is False, str(evs2[0].seq))
small, t3 = events_for(big, limit=10)
check("an explicit smaller limit is honoured", len(small) == 10 and t3 is True)

print("\n=== redaction ===")
r = mission(0)
r.log("device_auth", signature="AAAA", public_key="BBBB", api_key="CCCC",
      pairing_code="123456789", nonce="deadbeef", note="safe value")
e = events_for(r)[0][0]
for k in ("signature", "public_key", "api_key", "pairing_code", "nonce"):
    check(f"{k} is redacted in the stream", e.data.get(k) == "<redacted>", str(e.data.get(k)))
check("non-secret fields survive", e.data.get("note") == "safe value")
r2 = mission(0)
r2.log("big", blob="z" * 2000)
check("an over-long value is trimmed with its size shown",
      "chars]" in events_for(r2)[0][0].data["blob"])

print("\n=== SSE framing ===")
frame = events_for(m)[0][0].to_sse()
check("frame carries id: for Last-Event-ID reconnect", frame.startswith("id: 1"))
check("frame declares the event type", "event: mission" in frame)
check("frame ends with a blank line", frame.endswith("\n\n"))
payload = json.loads(frame.split("data: ", 1)[1].strip())
check("payload carries seq, mission, correlation and server time",
      {"seq", "mission_id", "correlation_id", "server_time", "type"} <= set(payload))

# A single huge field cannot produce an oversized frame -- _redact() already trims any
# string over 500 chars. The realistic path is MANY fields, each individually under that
# cap, which is what this constructs.
one_big = mission(0)
one_big.log("big_single", blob="q" * (MAX_EVENT_BYTES * 2))
check("a single over-long field is trimmed by redaction before framing",
      len(one_big.history[0]["blob"]) if False else
      "chars]" in events_for(one_big)[0][0].data["blob"])

many = mission(0)
many.log("many_fields", **{f"f{i}": "q" * 400 for i in range(200)})
mf = events_for(many)[0][0].to_sse()
check("an oversized event is replaced by a truncation marker, not dropped",
      "_truncated" in mf and len(mf) < MAX_EVENT_BYTES * 2, str(len(mf)))
check("the truncation marker reports the original size",
      "_original_bytes" in mf)

print("\n=== snapshot carries no authority ===")
snap = status_event(mission(3))
check("snapshot is seq 0 so it can never advance a cursor", snap.seq == 0)
check("snapshot reports worker claim and KAI verdict separately",
      snap.data["worker_claimed_success"] is False and snap.data["kai_verified_complete"] is False)
done = mission(1, status="COMPLETED")
check("kai_verified_complete follows mission status, never a claim",
      status_event(done).data["kai_verified_complete"] is True)
claimed = mission(1)
claimed.evidence.append({"claim": "succeeded"})
sc = status_event(claimed)
check("a worker claim does NOT set verified completion",
      sc.data["worker_claimed_success"] is True and sc.data["kai_verified_complete"] is False)

print(f"\n{len(P)} passed, {len(F)} failed")
if F:
    print("FAILED:", F)
sys.exit(1 if F else 0)
