"""PREPARE_ALLOWED guardrails certification (local, pure, deterministic).

Certifies the §5/§12/§23 admission bounds that gate a CONTINUOUS self-improvement preparation, wired into
dispatch_self_improvement(enforce_guardrails=True): yield-to-operational, one-at-a-time concurrency,
one-preparation-per-root, and the daily budget — each refusing with a typed reason and 0 dispatch. Also
proves backward-compat (enforce_guardrails=False keeps the prior behavior) and correct composition with the
confirm() gate + the §22 prepare brake. Undeployed until PREPARE_ALLOWED is approved.

    python3 ops/holding-staging/hosted_prepare_guardrails_cert.py
"""
import os
import sys
from types import SimpleNamespace

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "backend"))

from app.services.holding.self_improvement import dispatch_self_improvement, SelfImprovementCandidate  # noqa: E402
from app.services.holding.self_improvement_guardrails import JobView, describe   # noqa: E402
from app.services.holding.deployment_status import MATCH   # noqa: E402

BASE = "deadbeefcafe"
D = "2026-09-03"
res = []
def ck(n, ok, d=""):
    res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


def _settings(si=True):
    return SimpleNamespace(APP_ENV="staging", KAI_CAPABILITY_EXECUTION_ENABLED=True, HOLDING_AUTONOMY_ENABLED=True,
                           KAI_A2_EXECUTION_ENABLED=True, KAI_SELF_IMPROVEMENT_ENABLED=si)


def _cap():
    box = {"calls": []}
    def enq(pid, worker, task, *, idempotency_key, mission_id):
        box["calls"].append({"task": task, "idem": idempotency_key}); return {"id": len(box["calls"])}
    return box, enq


def _cand(root="failing_suite:si_x"):
    return SelfImprovementCandidate(improvement_id=root, subsystem="holding", problem_type="DEFECT",
                                    problem="p", desired_outcome="CORRECTNESS", company_id="wheellsverse")


def _disp(jobs, *, si=True, root="failing_suite:si_x", ceiling=3):
    box, enq = _cap()
    r = dispatch_self_improvement(_cand(root), settings=_settings(si), base_sha=BASE, goal="fix", suite_id="si_before_after",
                                  deployment_comparison=MATCH, test_before_fails=True, enqueue_fn=enq,
                                  enforce_guardrails=True, prep_jobs=jobs, now_date=D, ceiling=ceiling)
    return r, box


def sv(root, status, date=D): return {"worker": "coding", "status": status, "created_at": date, "task": {"task_id": f"si:{root}"}}
def ov(status, date=D): return {"worker": "coding", "status": status, "created_at": date, "task": {"task_id": "op-123"}}


print("PREPARE_ALLOWED GUARDRAILS CERT (local, pure)")

print("STEP 1 — CLEAN QUEUE -> ADMIT + dispatch, mission tagged 'si:<root>' (queue classifiable)")
r, box = _disp([])
ck("dispatched OK", r["dispatched"] and r["reason"] == "OK")
ck("enqueued task_id tagged si:<root>", box["calls"] and box["calls"][0]["task"].get("task_id") == "si:failing_suite:si_x")
ck("idempotency wraps the tagged mission (a2:si:...)", box["calls"][0]["idem"] == "a2:si:failing_suite:si_x")

print("STEP 2 — YIELD_TO_OPERATIONAL: operational work active -> 0 dispatch")
r, box = _disp([ov("running")])
ck("YIELD_TO_OPERATIONAL, 0 jobs", r["dispatched"] is False and r["reason"] == "YIELD_TO_OPERATIONAL" and not box["calls"])
r, box = _disp([ov("queued")])
ck("also yields to QUEUED operational", r["reason"] == "YIELD_TO_OPERATIONAL" and not box["calls"])

print("STEP 3 — CONCURRENCY_LIMIT: another self-improvement preparation in flight -> 0 dispatch")
r, box = _disp([sv("other_root", "running")])
ck("CONCURRENCY_LIMIT, 0 jobs", r["dispatched"] is False and r["reason"] == "CONCURRENCY_LIMIT" and not box["calls"])

print("STEP 4 — DUPLICATE_ROOT: same root already prepared today -> 0 dispatch")
r, box = _disp([sv("failing_suite:si_x", "succeeded")])
ck("DUPLICATE_ROOT, 0 jobs", r["dispatched"] is False and r["reason"] == "DUPLICATE_ROOT" and not box["calls"])

print("STEP 5 — BUDGET_EXHAUSTED: 3 self-improvement preparations already today -> 0 dispatch")
three = [sv(f"r{i}", "succeeded") for i in range(3)]
r, box = _disp(three, root="failing_suite:brand_new")
ck("BUDGET_EXHAUSTED, 0 jobs", r["dispatched"] is False and r["reason"] == "BUDGET_EXHAUSTED" and not box["calls"])
# yesterday's do not count
old = [{"worker": "coding", "status": "succeeded", "task": {"task_id": f"si:r{i}"},
        } for i in range(5)]
for j in old:
    j["created_at"] = "2026-09-02"
# describe pulls created_at from the row; inject via a row-shaped dict
old_rows = [{"worker": "coding", "status": "succeeded", "created_at": "2026-09-02", "task": {"task_id": f"si:r{i}"}} for i in range(5)]
r, box = _disp(old_rows, root="failing_suite:today_new")
ck("yesterday's preparations do NOT exhaust today's budget -> dispatched", r["dispatched"] and r["reason"] == "OK")

print("STEP 6 — COMPOSITION: brake + confirm gates still fire BEFORE guardrails")
r, box = _disp([], si=False)
ck("prepare brake OFF -> SELF_IMPROVEMENT_DISABLED (before guardrails)", r["reason"] == "SELF_IMPROVEMENT_DISABLED" and not box["calls"])
box2, enq2 = _cap()
rr = dispatch_self_improvement(_cand(), settings=_settings(True), base_sha=BASE, goal="x", suite_id="si_before_after",
                               deployment_comparison=MATCH, test_before_fails=False,   # no reproduced test
                               enqueue_fn=enq2, enforce_guardrails=True, prep_jobs=[], now_date=D)
ck("unconfirmed candidate -> not dispatched (confirm before guardrails)", rr["dispatched"] is False and not box2["calls"])

print("STEP 7 — BACKWARD COMPAT: enforce_guardrails=False keeps prior behavior (no admission gate)")
box3, enq3 = _cap()
rc = dispatch_self_improvement(_cand(), settings=_settings(True), base_sha=BASE, goal="x", suite_id="si_before_after",
                               deployment_comparison=MATCH, test_before_fails=True, enqueue_fn=enq3)   # guardrails off
ck("no guardrails -> dispatched with untagged mission (existing behavior)",
   rc["dispatched"] and box3["calls"] and box3["calls"][0]["task"].get("task_id") == "failing_suite:si_x")

n = len(res); ok = sum(res)
print(f"\nPREPARE_ALLOWED GUARDRAILS CERT: {ok}/{n} —", "PASS" if ok == n else "FAIL")
sys.exit(0 if ok == n else 1)
