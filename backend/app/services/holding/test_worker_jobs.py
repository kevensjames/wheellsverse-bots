"""Autonomy-cert unit tests for the worker-job queue: state machine, lease, heartbeat, idempotency,
duplicate-claim prevention, crash reclaim, ownership guards. Needs local Postgres.
Run (from backend/): DATABASE_URL=... python3 -m app.services.holding.test_worker_jobs
"""
from app.services.holding import worker_jobs as wj
from sqlalchemy import text
from app.database import SessionLocal

res = []
def ck(n, ok): res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}")


def _reset():
    wj.enqueue(0, "github", {}, idempotency_key="_ensure")   # committed write creates the table
    s = SessionLocal(); s.execute(text("DELETE FROM holding_worker_jobs")); s.commit(); s.close()


def _force_expire(job_id):
    s = SessionLocal()
    s.execute(text("UPDATE holding_worker_jobs SET lease_expires_at = now() - interval '1 hour' WHERE id=:id"), {"id": job_id})
    s.commit(); s.close()


_reset()
TASK = {"action": "list_prs", "repo": "kevensjames/wheellsverse-bots"}

# 1) IDEMPOTENCY — same key returns the same job, no duplicate
j1 = wj.enqueue(11, "github", TASK, idempotency_key="k-1")
j2 = wj.enqueue(11, "github", TASK, idempotency_key="k-1")
ck("idempotent enqueue: same key -> same job, deduped", j1["id"] == j2["id"] and j2["deduped"] is True)
ck("new key -> new job", wj.enqueue(12, "github", TASK, idempotency_key="k-2")["id"] != j1["id"])

# 2) CLAIM — sets running + lease + attempt; correlation id present
c = wj.claim_next("holding-worker-test-01")
ck("claim moves a job to running (attempt=1, has correlation id)",
   c and c["attempt"] == 1 and c["correlation_id"] and wj.get(c["id"])["status"] == "running")

# 3) DUPLICATE-CLAIM PREVENTION — the remaining single job goes to exactly one of two claimers
#    (one job left: k-2; k-1 already claimed above). Two racing claims -> exactly one wins.
a = wj.claim_next("worker-A"); b = wj.claim_next("worker-B")
got = [x for x in (a, b) if x]
ck("duplicate-claim prevention: exactly one worker claims the last job (EXECUTIONS=1)", len(got) == 1)
ck("queue now empty -> claim returns None", wj.claim_next("worker-C") is None)

# 4) OWNERSHIP + STATE guards on complete
jid = c["id"]
ck("complete by the WRONG worker is refused (ownership guard)",
   wj.complete(jid, {"ok": True}, worker_id="someone-else") is False)
ck("complete by the owning worker succeeds", wj.complete(jid, {"status": "completed"}, worker_id="holding-worker-test-01") is True)
ck("re-complete is idempotent (already terminal -> no-op, no dup evidence)",
   wj.complete(jid, {"status": "completed"}, worker_id="holding-worker-test-01") is False and wj.get(jid)["status"] == "succeeded")

# 5) HEARTBEAT extends only a running job owned by the worker
_reset()
hb = wj.enqueue(21, "github", TASK, idempotency_key="hb"); cj = wj.claim_next("hb-worker")
ck("heartbeat by owner on a running job succeeds", wj.heartbeat(cj["id"], "hb-worker") is True)
ck("heartbeat by a non-owner is refused", wj.heartbeat(cj["id"], "intruder") is False)

# 6) CRASH RECOVERY — an expired lease is reclaimed to 'queued', bounded by max_attempts
_force_expire(cj["id"])
ck("reclaim_expired returns the stranded job to the queue", wj.reclaim_expired() == 1 and wj.get(cj["id"])["status"] == "queued")
c2 = wj.claim_next("hb-worker-2")
ck("reclaimed job is re-claimable, attempt increments", c2 and c2["attempt"] == 2)
# exhaust attempts -> becomes 'expired', not retried forever
_force_expire(cj["id"]); wj.reclaim_expired(); wj.claim_next("w")   # attempt 3 (== max)
_force_expire(cj["id"])
wj.reclaim_expired()
ck("attempts exhausted -> job goes 'expired' (bounded, not infinite retry)", wj.get(cj["id"])["status"] == "expired")

# 7) ILLEGAL TRANSITION — completing a queued (never-claimed) job is refused
_reset()
qj = wj.enqueue(31, "github", TASK, idempotency_key="q")
ck("illegal transition refused: complete a 'queued' (un-claimed) job", wj.complete(qj["id"], {"x": 1}) is False)

_reset()
n = len(res); ok = sum(res)
print(f"\nHOLDING WORKER-JOBS TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
raise SystemExit(0 if ok == n else 1)
