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

# seed a VERIFY (kai -> worker=github, DISPATCHES) and a REQUEST_INFO (no worker, in-process)
from app.services.holding import worker_jobs
worker_jobs.enqueue(0, "_ensure", {})  # a committed write creates the table; cleared next
w = SessionLocal(); w.execute(text("DELETE FROM holding_worker_jobs")); w.commit(); w.close()
store.sync_open(prop.build_proposals([
    {"severity": "MEDIUM", "title": "Re-verify KAI", "source": "registry:kai.confidence", "entity": "kai"},
    {"severity": "LOW", "title": "Confirm operator data fields", "source": "registry.needs_confirmation()"},
]))
opened = store.list_proposals(status="proposed")
verify_p = next(p for p in opened if p["action"]["action_class"] == "VERIFY")
info_p = next(p for p in opened if p["action"]["action_class"] == "REQUEST_INFO")

# 1) SAFETY: a 'proposed' (un-approved) proposal cannot execute
r = execute_approved(verify_p["id"])
ck("un-approved proposal is REFUSED (execution bound to approval)",
   r["executed"] is False and "approval" in r["reason"])

# 2) approve + execute a WORKER (github) proposal -> DISPATCHES to the queue (not in-process)
store.decide(verify_p["id"], "approved")
r = execute_approved(verify_p["id"])
ck("approved worker-proposal dispatches a job (read-only)",
   r["executed"] is True and r["evidence"]["kind"] == "DISPATCHED" and r["evidence"].get("job_id") is not None)
ck("a read-only worker job is enqueued (github, list_prs)",
   any(j["worker"] == "github" and j["task"].get("action") == "list_prs"
       for j in worker_jobs.list_jobs(status="dispatched")))
ck("executed proposal leaves the approved set", store.get(verify_p["id"])["status"] == "executed")

# 3) re-executing an already-executed proposal is refused (no longer approved)
ck("re-execute refused (idempotent guard)", execute_approved(verify_p["id"])["executed"] is False)

# 4) approve + execute a NON-worker proposal (REQUEST_INFO) -> runs IN-PROCESS, read-only evidence
store.decide(info_p["id"], "approved")
ri_r = execute_approved(info_p["id"])
ck("non-worker proposal runs in-process (read-only evidence)",
   ri_r["executed"] is True and ri_r["evidence"]["kind"] == "REQUEST_INFO" and ri_r["evidence"].get("read_only"))

# cleanup worker jobs
w = SessionLocal(); w.execute(text("DELETE FROM holding_worker_jobs")); w.commit(); w.close()

# 5) unknown id → refused, not a crash
ck("unknown proposal id refused cleanly", execute_approved(999999)["executed"] is False)

s = SessionLocal(); s.execute(text("DELETE FROM holding_proposals")); s.commit(); s.close()

n = len(res); ok = sum(res)
print(f"\nHOLDING EXECUTOR TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
