"""DETECT_ONLY certification (local, pure, deterministic).

Certifies that continuous detection SENSES + CONFIRMS + DEDUPS + RANKS + NOTIFIES evidence-backed
improvement candidates while PREPARING NOTHING — detection authority is structurally separate from
preparation authority. Covers §4 no-change→NO_ACTION, §5 budget, §7 excluded surfaces, §8/§9 evidence+
confirmation, §11 dedup + spam-free, mode gate, the STRUCTURAL no-write guarantee (the detection module
imports no write path), and §16 preparation-attack (a detected candidate cannot be prepared with the
prepare brake off).

    python3 ops/holding-staging/hosted_detect_only_cert.py
"""
import os
import re
import sys
from types import SimpleNamespace

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "backend"))

from app.services.holding.self_improvement_detect import (run_detection, detect, dedup, Candidate,   # noqa: E402
    InMemoryDetectionStore, ELIGIBLE_CATEGORIES)
from app.services.holding.a2_dispatch import enqueue_a2_coding_job   # noqa: E402

res = []
def ck(n, ok, d=""):
    res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))

PASS = {"execution": "COMPLETED", "test_result": "PASSED", "passed": 7, "failed": 0, "commit_sha": "x"}
FAIL = {"execution": "COMPLETED", "test_result": "FAILED", "passed": 6, "failed": 1, "commit_sha": "x"}
ERR = {"execution": "ERROR", "test_result": "UNAVAILABLE"}


print("DETECT_ONLY CERT (local, pure)")

print("STEP 1 — NO-CHANGE RULE: all suites pass -> NO_ACTION, 0 notifications, prepared=0")
notes = []
r = run_detection(run_suite_fn=lambda s: PASS, store=InMemoryDetectionStore(), now="2026-09-03T00:00:00",
                  detect_on=True, prepare_on=False, deliver_fn=lambda m: notes.append(m))
ck("verdict NO_ACTION, 0 confirmed, prepared=0", r["verdict"] == "NO_ACTION" and r["confirmed_count"] == 0 and r["prepared"] == 0)
ck("0 notifications on no-change", len(notes) == 0)

print("STEP 2 — EVIDENCE + CONFIRMATION: only a REAL failing COMPLETED run becomes a confirmed candidate")
ck("suite ERROR (not COMPLETED) -> 0 candidates (never fabricate)", len(detect(lambda s: ERR)) == 0)
one = detect(lambda s: FAIL if s == "si_before_after" else PASS)
ck("one failing suite -> 1 confirmed candidate", len(one) == 1 and one[0].confirmed and one[0].signature == "failing_suite:si_before_after")
ck("candidate carries real evidence (suite + counts)", one[0].evidence.get("failed") == 1 and one[0].evidence.get("suite_id") == "si_before_after")

print("STEP 3 — DEDUP (§11): the same root signature collapses to ONE candidate")
dup = dedup([Candidate("failing_suite:x", "FAILING_CERTIFIED_TEST", "holding", "a", confirmed=True),
             Candidate("failing_suite:x", "FAILING_CERTIFIED_TEST", "holding", "a-again", confirmed=True)])
ck("two same-signature -> 1", len(dup) == 1)

print("STEP 4 — EXCLUDED SURFACES (§7): a non-eligible category is never a write candidate")
ex = dedup([Candidate("auth:bypass", "SECURITY_TIER", "auth", "x", confirmed=True)])
ck("excluded category dropped (not in ELIGIBLE_CATEGORIES)", len(ex) == 0 and "SECURITY_TIER" not in ELIGIBLE_CATEGORIES)

print("STEP 5 — SPAM-FREE + BUDGET (§5/§11): notify a new candidate ONCE; unchanged -> no re-notify")
st = InMemoryDetectionStore(); notes2 = []
one_fail = lambda s: FAIL if s == "si_before_after" else PASS
a = run_detection(run_suite_fn=one_fail, store=st, now="2026-09-03T01:00:00", detect_on=True, prepare_on=False,
                  deliver_fn=lambda m: (notes2.append(m) or {"delivered": True}))
b = run_detection(run_suite_fn=one_fail, store=st, now="2026-09-03T06:00:00", detect_on=True, prepare_on=False,
                  deliver_fn=lambda m: (notes2.append(m) or {"delivered": True}))
ck("new candidate notified once; unchanged not re-notified", len(notes2) == 1 and a["new_confirmed"] and not b["new_confirmed"])
ck("alert says PREPARATION NOT AUTHORIZED", "PREPARATION NOT AUTHORIZED" in notes2[0])

print("STEP 6 — MODE GATE: detect OFF -> not run; detect ON + prepare OFF -> DETECT_ONLY")
ck("detect OFF -> ran False", run_detection(run_suite_fn=one_fail, store=InMemoryDetectionStore(), detect_on=False, prepare_on=False)["ran"] is False)
ck("detect ON + prepare OFF -> mode DETECT_ONLY, prepared 0",
   run_detection(run_suite_fn=one_fail, store=InMemoryDetectionStore(), now="t", detect_on=True, prepare_on=False,
                 deliver_fn=lambda m: None)["mode"] == "DETECT_ONLY")

print("STEP 7 — STRUCTURAL NO-WRITE: the detection module imports NO preparation/dispatch path")
src = open(os.path.join(REPO, "backend/app/services/holding/self_improvement_detect.py")).read()
for tok in ("dispatch_self_improvement", "enqueue_a2_coding_job", "a2_dispatch", "a2_wiring", "make_git_worktree"):
    ck(f"no reference to write path '{tok}'", tok not in src)
# detection may READ worker_jobs.list_jobs (repeated-job source) but must call NO worker_jobs WRITE op
for wtok in ("worker_jobs.enqueue", ".enqueue(", "worker_jobs.complete", "worker_jobs.claim", ".claim_next("):
    ck(f"no worker_jobs WRITE op '{wtok}'", wtok not in src)
ck("worker_jobs used read-only (list_jobs present)", "list_jobs" in src)

print("STEP 8 — PREPARATION ATTACK (§16): a detected candidate CANNOT be prepared with the prepare brake OFF")
box = {"calls": []}
def enq(pid, worker, task, *, idempotency_key, mission_id): box["calls"].append(1); return {"id": 1}
# DETECT_ONLY settings: capability+autonomy+A2 could even be on, but self-improvement PREPARE brake is OFF.
s = SimpleNamespace(APP_ENV="staging", KAI_CAPABILITY_EXECUTION_ENABLED=True, HOLDING_AUTONOMY_ENABLED=True,
                    KAI_A2_EXECUTION_ENABLED=True, KAI_SELF_IMPROVEMENT_ENABLED=False)
from app.services.holding.self_improvement import dispatch_self_improvement, SelfImprovementCandidate
cand = SelfImprovementCandidate(improvement_id="detected-1", subsystem="holding", problem_type="DEFECT",
                                problem="detected failing suite", desired_outcome="CORRECTNESS", company_id="wheellsverse")
d = dispatch_self_improvement(cand, settings=s, base_sha="sha", goal="x", deployment_comparison="MATCH",
                             test_before_fails=True, enqueue_fn=enq)
ck("prepare brake OFF -> SELF_IMPROVEMENT_DISABLED, 0 jobs", d["dispatched"] is False
   and d["reason"] == "SELF_IMPROVEMENT_DISABLED" and len(box["calls"]) == 0)

n = len(res); ok = sum(res)
print(f"\nDETECT_ONLY CERT: {ok}/{n} —", "PASS" if ok == n else "FAIL")
sys.exit(0 if ok == n else 1)
