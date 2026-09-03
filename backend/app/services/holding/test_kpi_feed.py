"""KPI feed tests: real day-over-day movement, live-signal priorities, kpi_history round-trip.
Needs local Postgres (uses the same DB App B uses). Run (from backend/):
    DATABASE_URL=... python3 -m app.services.holding.test_kpi_feed
"""
from app.services.holding.reports import build_morning_briefing
from app.services.holding.priorities import derive_priorities
from app.services.holding import kpi_history
from sqlalchemy import text
from app.database import SessionLocal

res = []
def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

# 1. movement: first run (no prior) → honest baseline; with a prior → REAL numeric deltas
base = build_morning_briefing(now_iso="2026-08-30T07:00:00-04:00")            # prev_kpis=None
ck("first run -> honest baseline note (no invented trend)", "status" in base["kpi_movement"])
prev = {"as_of": "2026-08-29", "entities_total": 11, "entities_verified": 2,
        "open_incidents": 0, "open_risks": 2, "fields_awaiting_confirmation": 66}
b = build_morning_briefing(prev_kpis=prev, now_iso="2026-08-30")
mv, cur = b["kpi_movement"], b["kpis"]
ck("movement shows REAL deltas vs the prior snapshot",
   mv["entities_verified"] == cur["entities_verified"] - 2
   and mv["open_risks"] == cur["open_risks"] - 2 and mv["since"] == "2026-08-29")

# 2. live signals → priorities at their own severity, source-cited; healthy signals add nothing
ps = derive_priorities(signals=[{"name": "appA_cpu", "ok": False, "severity": "CRITICAL", "detail": "96%"}])
ck("failing live signal leads as CRITICAL w/ live-signal source",
   ps[0]["severity"] == "CRITICAL" and ps[0]["source"] == "live-signal:appA_cpu")
ok_ps = derive_priorities(signals=[{"name": "appA_cpu", "ok": True, "severity": "OK", "detail": "54%"}])
ck("healthy live signals produce NO signal priority",
   not any(p["source"].startswith("live-signal") for p in ok_ps))

# 3. kpi_history DB round-trip: record → previous_snapshot reads it back
token = "test-kpi-feed-marker"
snap = {"as_of": token, "entities_total": 11, "entities_verified": 4,
        "open_incidents": 0, "open_risks": 1, "fields_awaiting_confirmation": 62}
recorded = kpi_history.record_snapshot(snap)
prev2 = kpi_history.previous_snapshot()
ck("kpi_history persists + reads back the latest snapshot",
   recorded and isinstance(prev2, dict) and prev2.get("as_of") == token and prev2.get("entities_verified") == 4)

# cleanup: remove this test's rows so history stays clean for other runs
try:
    s = SessionLocal()
    s.execute(text("DELETE FROM holding_kpi_history WHERE kpis->>'as_of' = :t"), {"t": token}); s.commit(); s.close()
except Exception:
    pass

n = len(res); ok = sum(res)
print(f"\nHOLDING KPI-FEED TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
