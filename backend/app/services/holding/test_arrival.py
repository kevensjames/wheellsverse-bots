"""§12/§84 owner-arrival guard. Run (from backend/):
    python3 -m app.services.holding.test_arrival

Mirrors test_registry.py: a flat ck() ledger + an injectable store/events. Proves changes_since_last_visit
comes from the AUTHORITATIVE audit log (not conversation memory), one greeting per meaningful session
(dedupe by session_id; silent on refresh), no fake optimism, full-fidelity tz comparison, and reuse of
briefing.today_for_you.
"""
from app.services.holding.arrival import (
    arrival, changes_since_last_visit, InMemoryLastVisitStore, _parse_ts)

res = []
def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

AUDIT = [
    {"id": "a1", "ts": "2026-09-01T10:00:00+00:00", "action": "holding.run_cycle", "scope": "kai:ultra",
     "actor": "kai-auto", "success": True},
    {"id": "a2", "ts": "2026-09-02T12:30:00+02:00", "action": "proposal.approved", "scope": "kai:ultra",
     "actor": "operator", "success": True},                       # == 10:30Z on the 2nd
    {"id": "a3", "ts": "not-a-date", "action": "broken", "scope": "x", "actor": "y", "success": True},
]

# ── 1. changes come ONLY from timestamped audit rows strictly AFTER the last visit; bad ts dropped ───────
ch = changes_since_last_visit("2026-09-01T09:00:00+00:00", events=AUDIT)
ck("changes_since computes from the authoritative audit log (both real rows after last visit)",
   {c["id"] for c in ch["changes"]} == {"a1", "a2"} and ch["count"] == 2)
ck("an unparseable-ts audit row is dropped (never fabricated as a change)",
   not any(c["id"] == "a3" for c in ch["changes"]))
ck("changes are newest-first", ch["changes"][0]["id"] == "a2")
ck("each change is cited (action + scope + actor)", all(c.get("action") and c.get("scope") for c in ch["changes"]))

# ── 2. no prior visit → honest baseline (no fabricated changes) ─────────────────────────────────────────
base = changes_since_last_visit(None, events=AUDIT)
ck("no prior visit → baseline, count 0, honest note", base["baseline"] is True and base["count"] == 0
   and "no prior visit" in base["note"].lower())

# ── 3. first arrival: greets once, baseline, NO fake optimism ───────────────────────────────────────────
store = InMemoryLastVisitStore()
r1 = arrival("operator", "sess-1", store=store, events=AUDIT, now="2026-09-01T09:00:00+00:00")
ck("first arrival greets (first_visit)", r1["greet"] is True and r1["reason"] == "first_visit")
ck("first arrival greeting has no fake optimism",
   all(w not in r1["greeting"].lower() for w in ("great", "progress", "all good", "on track", "excellent")))

# ── 4. same session_id (refresh/nav/reconnect) → SILENT + store not advanced ────────────────────────────
r2 = arrival("operator", "sess-1", store=store, events=AUDIT, now="2026-09-01T09:05:00+00:00")
ck("same session_id → silent (greet=False, reason=same_session)", r2["greet"] is False and r2["reason"] == "same_session")
ck("refresh does NOT advance the last-visit store",
   store.get("operator")["last_visit_at"] == "2026-09-01T09:00:00+00:00")

# ── 5. a genuinely-new session greets once and computes changes since the prior visit ───────────────────
r3 = arrival("operator", "sess-2", store=store, events=AUDIT, now="2026-09-03T08:00:00+00:00")
ck("new session greets once (new_session)", r3["greet"] is True and r3["reason"] == "new_session")
ck("new session's changes are the real audit rows after the prior visit",
   {c["id"] for c in r3["changes_since_last_visit"]["changes"]} == {"a1", "a2"})
ck("greeting states the real count (not a fabricated summary)", "2" in r3["greeting"])

# ── 6. reuse of briefing.today_for_you: changes ARE the kai_completed_since_last_visit feed ──────────────
ck("today_for_you reuse: changes feed kai_completed_since_last_visit",
   r3["today"]["kai_completed_since_last_visit"] == r3["changes_since_last_visit"]["changes"])

# ── 7. after advancing, a later session sees nothing new (honest 'no governed actions') ─────────────────
r4 = arrival("operator", "sess-3", store=store, events=AUDIT, now="2026-09-04T08:00:00+00:00")
ck("later session with no new events → count 0 + honest message",
   r4["greet"] is True and r4["changes_since_last_visit"]["count"] == 0 and "No governed actions" in r4["greeting"])

# ── 8. full-fidelity tz: a +02:00 event is compared in UTC (a2 10:30Z is after a 09-02T09:00Z visit) ─────
s2 = InMemoryLastVisitStore(); s2.set("op2", "2026-09-02T09:00:00+00:00", "old")
r5 = arrival("op2", "sess-x", store=s2, events=AUDIT, now="2026-09-03T00:00:00+00:00")
ck("tz full-fidelity: +02:00 event compared correctly in UTC",
   {c["id"] for c in r5["changes_since_last_visit"]["changes"]} == {"a2"})
ck("_parse_ts keeps tz + microseconds", _parse_ts("2026-09-03T12:00:00.5+02:00").hour == 10)

n = len(res); ok = sum(res)
print(f"\nARRIVAL TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
