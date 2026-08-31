"""Wave 3 tests: executor is bound to approval, runs READ-ONLY actions, records evidence.
Needs local Postgres. Run (from backend/): DATABASE_URL=... python3 -m app.services.holding.test_executor
"""
from app.services.holding import proposals as prop, proposals_store as store
from app.services.holding.executor import execute_approved
from sqlalchemy import text
from app.database import SessionLocal

res = []
def ck(n, ok): res.append(ok); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

s = SessionLocal(); s.execute(text("DELETE FROM holding_proposals")); s.commit(); s.close()

# seed one VERIFY proposal (for kai) and one REQUEST_INFO
store.sync_open(prop.build_proposals([
    {"severity": "MEDIUM", "title": "Re-verify KAI", "source": "registry:kai.confidence", "entity": "kai"},
    {"severity": "LOW", "title": "Confirm operator data fields", "source": "registry.needs_confirmation()"},
]))
opened = store.list_proposals(status="proposed")
verify_p = next(p for p in opened if p["action"]["action_class"] == "VERIFY")

# 1) SAFETY: a 'proposed' (un-approved) proposal cannot execute
r = execute_approved(verify_p["id"])
ck("un-approved proposal is REFUSED (execution bound to approval)",
   r["executed"] is False and "approval" in r["reason"])

# 2) approve, then execute → read-only evidence recorded, status → executed
store.decide(verify_p["id"], "approved")
r = execute_approved(verify_p["id"])
ck("approved proposal executes (read-only)", r["executed"] is True and r["evidence"].get("read_only") is True)
ck("VERIFY evidence carries live + registry status", r["evidence"]["kind"] == "VERIFY"
   and ("live" in r["evidence"] or "registry" in r["evidence"]))
ck("executed proposal leaves the approved set", store.get(verify_p["id"])["status"] == "executed")

# 3) re-executing an already-executed proposal is refused (no longer approved)
r2 = execute_approved(verify_p["id"])
ck("re-execute refused (idempotent guard)", r2["executed"] is False)

# 4) a REJECTED proposal cannot execute
ri = next(p for p in opened if p["action"]["action_class"] == "REQUEST_INFO")
store.decide(ri["id"], "rejected", reason="nope")
ck("rejected proposal cannot execute", execute_approved(ri["id"])["executed"] is False)

# 5) unknown id → refused, not a crash
ck("unknown proposal id refused cleanly", execute_approved(999999)["executed"] is False)

s = SessionLocal(); s.execute(text("DELETE FROM holding_proposals")); s.commit(); s.close()

n = len(res); ok = sum(res)
print(f"\nHOLDING EXECUTOR TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
