"""Hosted A0-LIVE EXECUTE certification for the Holding OS — the execute->evidence->COMPLETE proof.

Run this IN-PROCESS on the staging box (so build_live_engine() reads the REAL deployed brakes and the
holding.health provider hits the real signal source):

    railway run --service kai-staging-appb python3 ops/holding-staging/hosted_a0_execute_cert.py

Why in-process, not over HTTP: POST /admin/holding/run-cycle loads the prior snapshot server-side from
the live twin and forbids client snapshots (so the client can never manufacture a MaterialChange). Two
POSTs against a static staging world therefore only ever produce QUIET cycles — the HTTP cert
(autonomy_cert.py STEP 7-9) proves gating + the quiet path but structurally cannot drive a real execute.
Forcing one through the route would need a twin-seed hook = new product code (forbidden). This fixture
uses ONLY existing functions (build_live_engine + run_cycle + the real resolver + the CERTIFIED
holding.health provider) to certify the real execute path with no new product code.

It certifies, against the real live brake config:
  1. A0 EXECUTE      a benign A0 transition -> exactly ONE holding.health READ_ONLY action,
                     EXECUTED, verified real evidence, task COMPLETE, correlation id set.
  2. QUIET FOLLOW-UP an identical follow-up cycle -> 0 work (no re-execution, no dup).
  3. ESCALATION      an owner-blocker transition (A3/OWNER) -> OWNER_QUEUED, 0 auto-executed
                     (above-A0 never auto-executes, even with autonomy live).
  4. BRAKE #2        autonomy off (override) -> the SAME transition executes 0 (autonomy_off).
  5. BRAKE #1        capability execution off (override) -> the SAME transition blocked, executes 0.
  6. CLASS/MONEY     every executed action is READ_ONLY (holding.health); no FINANCIAL/write path.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend")))

from app.services.holding.autonomous_work import run_cycle              # noqa: E402
from app.services.holding.holding_cycle import build_live_engine        # noqa: E402
from app.services.holding.task_resolver import _MAPPINGS                 # noqa: E402
from app.services.capability.manifest import ActionClass                 # noqa: E402

res = []
def ck(n, ok, d=""):
    res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


def snap(status="OK", owner_actions=None):
    return {"companies": [{"company_id": "sol", "status": status, "active_incidents": [],
            "owner_actions_required": owner_actions or [], "deployments": ["sha-abc"]}],
            "shared_resources": {"workers_online": 1, "capabilities_available": 7},
            "autonomy_overall": "AUTONOMOUS_READ_ONLY"}


# Live brake states as the deployed config actually reads them (never printed as secrets).
try:
    from app.config import settings
    B1 = bool(getattr(settings, "KAI_CAPABILITY_EXECUTION_ENABLED", False))   # capability execution
    B2 = bool(getattr(settings, "HOLDING_AUTONOMY_ENABLED", False))           # autonomy
except Exception:
    B1 = B2 = None

print("A0-LIVE EXECUTE CERT (in-process, real brakes)")
print(f"  brake#1 KAI_CAPABILITY_EXECUTION_ENABLED = {B1}")
print(f"  brake#2 HOLDING_AUTONOMY_ENABLED          = {B2}")

print("STEP 1 — A0 EXECUTE: a benign transition executes exactly one READ_ONLY probe, with evidence")
ck("both brakes are lifted (required to certify A0 execute)", B1 is True and B2 is True,
   f"brake#1={B1} brake#2={B2}" if not (B1 and B2) else "live config permits A0 execution")
eng = build_live_engine()                                     # NO override: the REAL deployed brakes
r1 = run_cycle(snap("OK"), snap("DEGRADED"), engine=eng, cycle_id="a0cert", now="2026-09-02T09:00:00")
ck("material change detected", r1["verdict"] == "MATERIAL_CHANGE" and r1["material_changes"] == 1)
ck("exactly one A0 action auto-executed", r1["auto_executed"] == 1, f"executed={r1['auto_executed']}")
ck("no owner action, no failure on the benign A0 path", r1["owner_queued"] == 0 and r1["failed"] == 0)
w = (r1["results"] or [{}])[0]
ck("outcome EXECUTED + task COMPLETE", w.get("outcome") == "EXECUTED" and w.get("task_status") == "COMPLETE",
   f"{w.get('outcome')}/{w.get('task_status')}")
ck("verified REAL evidence (not self-report)", w.get("verified") is True and w.get("evidence_present") is True)
ck("correlation id present (auditable)", bool(w.get("correlation_id")), w.get("correlation_id"))
ck("executed capability is the CERTIFIED holding.health read", w.get("capability_id") == "holding.health",
   w.get("capability_id"))
ck("executed task is A0 (autonomy class 0)", w.get("autonomy") == 0, f"autonomy={w.get('autonomy')}")

print("STEP 2 — QUIET FOLLOW-UP: an identical cycle does 0 work (no re-execution, no dup)")
r2 = run_cycle(snap("DEGRADED"), snap("DEGRADED"), engine=eng, cycle_id="a0cert-quiet", now="2026-09-02T09:05:00")
ck("no material change", r2["verdict"] == "NO_MATERIAL_CHANGE" and r2["material_changes"] == 0)
ck("0 auto-executed on the quiet cycle", r2["auto_executed"] == 0)
ck("0 plan dispositions (nothing carried/kept)", sum(r2["plan_dispositions"].values()) == 0,
   str(r2["plan_dispositions"]))

print("STEP 3 — ESCALATION CONTAINMENT (live autonomy): above-A0 work is owner-queued, never executed")
r3 = run_cycle(snap("OK", owner_actions=[]), snap("OK", owner_actions=["owner must decide"]),
               engine=eng, cycle_id="a0cert-escalation", now="2026-09-02T09:10:00")
ck("owner-blocker routed to the owner queue", r3["owner_queued"] == 1, f"owner_queued={r3['owner_queued']}")
ck("0 auto-executed for owner/A3 work (no escalation)", r3["auto_executed"] == 0)

print("STEP 4 — BRAKE #2 authoritative: autonomy off -> the SAME transition executes 0")
eng_off = build_live_engine(autonomy_on=False, execution_on=True)
r4 = run_cycle(snap("OK"), snap("DEGRADED"), engine=eng_off, cycle_id="a0cert-b2", now="2026-09-02T09:15:00")
ck("autonomy-off -> 0 executed, observation still ran", r4["auto_executed"] == 0 and r4["autonomy_off"] >= 1,
   f"executed={r4['auto_executed']} autonomy_off={r4['autonomy_off']}")

print("STEP 5 — BRAKE #1 authoritative: capability execution off -> the SAME transition blocked, executes 0")
eng_nocap = build_live_engine(autonomy_on=True, execution_on=False)
r5 = run_cycle(snap("OK"), snap("DEGRADED"), engine=eng_nocap, cycle_id="a0cert-b1", now="2026-09-02T09:20:00")
ck("cap-exec-off -> 0 executed, capability blocked", r5["auto_executed"] == 0 and r5["blocked"] >= 1,
   f"executed={r5['auto_executed']} blocked={r5['blocked']}")

print("STEP 6 — CLASS/MONEY: every certified mapping is READ_ONLY (no FINANCIAL/write auto-path)")
non_read = [k for k, m in _MAPPINGS.items() if m.action_class != ActionClass.READ_ONLY]
ck("no auto-executable mapping above READ_ONLY", non_read == [], f"offenders={non_read}")

n = len(res); ok = sum(res)
print(f"\nA0-LIVE EXECUTE CERT: {ok}/{n} —", "PASS" if ok == n else "FAIL")
print("(Certifies the live-brake A0 execute->evidence->COMPLETE chain + both brakes authoritative."
      " Next in order: owner-boundary (HTTP) -> A1 -> limited A2 prepare-only -> self-improvement.)")
sys.exit(0 if ok == n else 1)
