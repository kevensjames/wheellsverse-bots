"""Owner-boundary certification (pure, python3) — KAI never takes an owner's decision.

The A0-live cert proved KAI executes exactly one READ_ONLY probe on a benign change. This certifies the
OTHER half of the guarantee: work that requires the owner is surfaced, prepared, and WAITS — KAI never
executes it, never resolves it while it is still live, and never dumps a vague ask. Pure + DB-free
(reuses the real engine/resolver/owner_queue functions); run:  python3 test_owner_boundary_cert.py

Certifies:
  1. CLASS WALL     anything >= A3 (incl. an A4 financial task MIS-assigned to KAI) -> OWNER_QUEUED,
                    never EXECUTED — the wall is the ActionClass ladder, not who the task is assigned to.
  2. NO PATH        the resolver refuses a certified capability path for owner/above-A0 work (fail-closed).
  3. PREPARED       an owner blocker becomes a specific, deduped OwnerAction with the irreducible human
                    step + what KAI already did; a generic ask ("review startup") is refused.
  4. NO AUTO-CLOSE  a still-active owner item is NEVER auto-resolved (only a vanished blocker is), and an
                    un-re-derived owner task BLOCKs (persists) — it is never auto-COMPLETEd.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.autonomous_work import run_cycle, HoldingAutonomousWorkEngine, OWNER_QUEUED, EXECUTED  # noqa: E402
from app.services.holding.holding_cycle import build_live_engine  # noqa: E402
from app.services.holding.state_reconciler import reconcile_result  # noqa: E402
from app.services.holding.plan import (  # noqa: E402
    tasks_from_changes, reconcile_plan, PlanTask, Assignee, AutonomyClass, TaskStatus, Disposition)
from app.services.holding.task_resolver import TaskCapabilityResolver  # noqa: E402
from app.services.holding.owner_queue import (  # noqa: E402
    prepare_owner_actions, reconcile_owner_queue, OwnerAction)

res = []
def ck(n, ok, d=""):
    res.append(bool(ok)); print(f"  [{'PASS' if ok else 'FAIL'}] {n}" + (f" — {d}" if d else ""))


def snap(status="OK", owner=None):
    return {"companies": [{"company_id": "sol", "status": status, "active_incidents": [],
            "owner_actions_required": owner or [], "deployments": ["sha-abc"]}],
            "shared_resources": {"workers_online": 1, "capabilities_available": 7},
            "autonomy_overall": "AUTONOMOUS_READ_ONLY"}


def _task(autonomy, assignee, *, task_type="", goal="Owner decision required on sol", source_key="k1"):
    return PlanTask(task_id=source_key, company_id="sol", goal=goal, reason="r", source_key=source_key,
                    task_type=task_type, autonomy=int(autonomy), assigned_to=assignee.value)


print("OWNER-BOUNDARY CERT (pure)")

print("STEP 1 — CLASS WALL: anything >= A3 is owner-queued, never executed (even mis-assigned to KAI)")
eng = build_live_engine(autonomy_on=True, execution_on=True)   # both brakes lifted: still must not execute owner work
# an owner-blocker transition through the real cycle
r = run_cycle(snap("OK", owner=[]), snap("OK", owner=["decide pricing"]), engine=eng, cycle_id="ob", now="t")
ck("owner-blocker -> owner_queued=1, auto_executed=0", r["owner_queued"] == 1 and r["auto_executed"] == 0,
   f"owner_queued={r['owner_queued']} executed={r['auto_executed']}")
# an A4 FINANCIAL task deliberately mis-assigned to KAI must STILL be owner-queued (class wall, not assignment)
a4 = eng.run_task(_task(AutonomyClass.A4_FINANCIAL_CREDENTIAL_DESTRUCTIVE, Assignee.KAI, source_key="a4"))
ck("A4 financial mis-assigned to KAI -> OWNER_QUEUED (class wall)", a4.outcome == OWNER_QUEUED, a4.outcome)
ck("A4 task did not execute", a4.outcome != EXECUTED and a4.verified is False)
# an A3 external task assigned OWNER -> owner-queued
a3 = eng.run_task(_task(AutonomyClass.A3_EXTERNAL_HIGH_IMPACT, Assignee.OWNER, source_key="a3"))
ck("A3 owner task -> OWNER_QUEUED", a3.outcome == OWNER_QUEUED, a3.outcome)

print("STEP 2 — NO PATH: the resolver refuses a certified capability path for above-A0 work")
rv = TaskCapabilityResolver()
ck("A3 owner task resolves to NO capability path", rv.resolve(_task(AutonomyClass.A3_EXTERNAL_HIGH_IMPACT, Assignee.OWNER)) is None)
# even if an owner task carried a READ_ONLY-mapped task_type, the class mismatch (HIGH_IMPACT != READ_ONLY) refuses it
ck("A3 task with a READ_ONLY task_type still refused (class mismatch)",
   rv.resolve(_task(AutonomyClass.A3_EXTERNAL_HIGH_IMPACT, Assignee.KAI, task_type="HEALTH_PROBE")) is None)

print("STEP 3 — PREPARED: owner blocker -> specific, deduped OwnerAction; generic ask refused")
recon = reconcile_result(snap("OK", owner=[]), snap("OK", owner=["decide pricing"]))
cands = tasks_from_changes(recon["changes"])
reconciled = reconcile_plan([], cands)
actions = prepare_owner_actions(reconciled, [], now="t")
ck("exactly one prepared owner action", len(actions) == 1, f"n={len(actions)}")
a = actions[0] if actions else OwnerAction("", "", 0, "", "", "", "")
ck("carries the irreducible human step", bool(a.exact_owner_action) and a.exact_owner_action.strip() != "")
ck("states what KAI already did (§2 preparation)", bool(a.kai_completed))
ck("stable dedup source_key", bool(a.source_key))
# dedup: the same reconciled set never produces two items for one requirement
ck("deduped by source_key (no proliferation)", len(prepare_owner_actions(reconciled + reconciled, [], now="t")) == 1)
# generic titles are refused (§2)
generic = prepare_owner_actions([type("RT", (), {"task": _task(AutonomyClass.A3_EXTERNAL_HIGH_IMPACT,
          Assignee.OWNER, goal="review startup", source_key="g")})()], [], now="t")
ck("a generic ask ('review startup') is NOT queued", generic == [], f"n={len(generic)}")

print("STEP 4 — NO AUTO-CLOSE: a live owner item is never auto-resolved; an un-re-derived owner task BLOCKs")
still_active = reconcile_owner_queue([{"source_key": "K"}], [OwnerAction("sol", "K", 1, "t", "r", "kc", "eo")])
ck("still-active owner item -> would_resolve is empty (never closed under KAI)", still_active["would_resolve"] == [],
   str(still_active["would_resolve"]))
vanished = reconcile_owner_queue([{"source_key": "K"}], [])
ck("vanished blocker -> resolvable (only then)", vanished["would_resolve"] == ["K"], str(vanished["would_resolve"]))
# plan level: an owner task not re-derived this cycle BLOCKs (persists), never auto-COMPLETE
owner_prior = _task(AutonomyClass.A3_EXTERNAL_HIGH_IMPACT, Assignee.OWNER, source_key="op")
disp = {rt.task.source_key: rt.disposition for rt in reconcile_plan([owner_prior], [])}
ck("un-re-derived owner task -> BLOCK (kept), not COMPLETE", disp.get("op") == Disposition.BLOCK.value, str(disp))
# F1 regression: owner-required is (OWNER or >=A3) — an A3+ task mis-assigned to KAI also BLOCKs, never COMPLETE
a3_kai_prior = _task(AutonomyClass.A3_EXTERNAL_HIGH_IMPACT, Assignee.KAI, source_key="a3kai")
d2 = {rt.task.source_key: rt.disposition for rt in reconcile_plan([a3_kai_prior], [])}
ck("un-re-derived A3 task assigned KAI -> BLOCK, not auto-COMPLETE (F1)", d2.get("a3kai") == Disposition.BLOCK.value, str(d2))
# an A0 KAI task that resolved is still correctly COMPLETEd (fix must not over-persist non-owner work)
a0_kai_prior = _task(AutonomyClass.A0_OBSERVE, Assignee.KAI, source_key="a0kai")
d3 = {rt.task.source_key: rt.disposition for rt in reconcile_plan([a0_kai_prior], [])}
ck("un-re-derived A0 KAI task -> COMPLETE (not over-persisted)", d3.get("a0kai") == Disposition.COMPLETE.value, str(d3))

n = len(res); ok = sum(res)
print(f"\nOWNER-BOUNDARY CERT: {ok}/{n} —", "PASS" if ok == n else "FAIL")
sys.exit(0 if ok == n else 1)
