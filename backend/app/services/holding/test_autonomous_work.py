"""Pure tests for the Autonomous Work Engine + continuous cycle (§16-24, §33, §55, §61 matrix).
Run: python3 backend/app/services/holding/test_autonomous_work.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.plan import PlanTask, AutonomyClass, Assignee, TaskStatus  # noqa: E402
from app.services.holding.autonomous_work import (  # noqa: E402
    HoldingAutonomousWorkEngine, run_cycle, EXECUTED, OWNER_QUEUED, BLOCKED_CAPABILITY,
    AUTONOMY_OFF, NEEDS_CERTIFICATION, FAILED)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


class _Res:
    """Minimal ExecutionResult stand-in."""
    def __init__(self, status, evidence=None, reason="", corr="c1"):
        self.status = status; self.evidence = evidence or {}; self.reason = reason; self.correlation_id = corr


def _task(autonomy=AutonomyClass.A0_OBSERVE, assignee=Assignee.KAI, cid="sol", tid="t1"):
    return PlanTask(task_id=tid, company_id=cid, goal="g", reason="r", source_key=tid,
                    autonomy=int(autonomy), assigned_to=assignee.value)


def _ok_execute(cap, op, inp, *, mission_id=""):
    return _Res("OK", evidence={"probe": "real", "value": 42})


def _resolver(_t):
    return ("yt-dlp", "metadata", {"url": "https://example.com"})


def t_a0_executes_with_verified_evidence():
    """§22: A0 KAI task runs through the service and COMPLETEs only with real evidence."""
    eng = HoldingAutonomousWorkEngine(execute=_ok_execute, resolver=_resolver)
    r = eng.run_task(_task())
    assert r.outcome == EXECUTED and r.verified and r.evidence_present
    assert r.task_status == TaskStatus.COMPLETE.value and r.capability_id == "yt-dlp"


def t_no_evidence_never_completes():
    """Status OK but empty evidence must NOT complete (an agent's word isn't evidence)."""
    eng = HoldingAutonomousWorkEngine(execute=lambda *a, **k: _Res("OK", evidence={}), resolver=_resolver)
    r = eng.run_task(_task())
    assert r.outcome == FAILED and not r.verified and r.task_status == TaskStatus.BLOCKED.value


def t_owner_task_never_auto_executes():
    """§24: owner-required (A3+ / OWNER) work is routed to the owner queue, never run."""
    eng = HoldingAutonomousWorkEngine(execute=_ok_execute, resolver=_resolver)
    r = eng.run_task(_task(autonomy=AutonomyClass.A3_EXTERNAL_HIGH_IMPACT, assignee=Assignee.OWNER))
    assert r.outcome == OWNER_QUEUED and r.task_status == TaskStatus.BLOCKED.value


def t_a2_needs_certification():
    eng = HoldingAutonomousWorkEngine(execute=_ok_execute, resolver=_resolver)
    r = eng.run_task(_task(autonomy=AutonomyClass.A2_REVERSIBLE_INTERNAL_WRITE))
    assert r.outcome == NEEDS_CERTIFICATION


def t_no_capability_path_blocks():
    """§57: no certified capability → BLOCKED_CAPABILITY, not a fabricated success."""
    eng = HoldingAutonomousWorkEngine(execute=_ok_execute, resolver=lambda t: None)
    r = eng.run_task(_task())
    assert r.outcome == BLOCKED_CAPABILITY


def t_kill_switch_global_and_company():
    """§33: global off → nothing runs; company off → that company skipped."""
    off = HoldingAutonomousWorkEngine(execute=_ok_execute, resolver=_resolver, global_autonomy=False)
    assert off.run_task(_task()).outcome == AUTONOMY_OFF
    co = HoldingAutonomousWorkEngine(execute=_ok_execute, resolver=_resolver, company_autonomy={"sol": False})
    assert co.run_task(_task(cid="sol")).outcome == AUTONOMY_OFF
    assert co.run_task(_task(cid="kai")).outcome == EXECUTED   # other companies still on


def t_capability_down_classified():
    """§55: a CAPABILITY_UNAVAILABLE status is classified CAPABILITY_DOWN, bounded (no retry loop)."""
    eng = HoldingAutonomousWorkEngine(execute=lambda *a, **k: _Res("CAPABILITY_UNAVAILABLE", reason="not ready"),
                                      resolver=_resolver)
    r = eng.run_task(_task())
    assert r.outcome == FAILED and r.failure_class == "CAPABILITY_DOWN"


def t_cycle_no_material_change_executes_nothing():
    """§17: identical snapshots → NO_MATERIAL_CHANGE, 0 tasks, 0 autonomous actions."""
    snap = {"companies": [{"company_id": "sol", "status": "LIVE", "active_incidents": [],
                           "owner_actions_required": []}],
            "shared_resources": {"workers_online": 1, "capabilities_available": 7}, "autonomy_overall": "AUTONOMOUS_READ_ONLY"}
    eng = HoldingAutonomousWorkEngine(execute=_ok_execute, resolver=_resolver)
    res = run_cycle(snap, snap, engine=eng, cycle_id="c-nochange")
    assert res["verdict"] == "NO_MATERIAL_CHANGE" and res["auto_executed"] == 0 and res["material_changes"] == 0


def t_cycle_incident_drives_execution():
    """Full loop: an incident appears → A0 task derived → executed with evidence → 1 auto action."""
    a = {"companies": [{"company_id": "sol", "status": "LIVE", "active_incidents": [], "owner_actions_required": []}],
         "shared_resources": {"workers_online": 1, "capabilities_available": 7}, "autonomy_overall": "AUTONOMOUS_READ_ONLY"}
    b = {"companies": [{"company_id": "sol", "status": "LIVE", "active_incidents": ["x"], "owner_actions_required": []}],
         "shared_resources": {"workers_online": 1, "capabilities_available": 7}, "autonomy_overall": "AUTONOMOUS_READ_ONLY"}
    eng = HoldingAutonomousWorkEngine(execute=_ok_execute, resolver=_resolver)
    res = run_cycle(a, b, engine=eng, cycle_id="c1", now="2026-09-01T08:00:00")
    assert res["verdict"] == "MATERIAL_CHANGE" and res["material_changes"] == 1
    assert res["auto_executed"] == 1 and res["failed"] == 0
    assert res["cycle_id"] == "c1"


def t_cycle_owner_blocker_routes_not_executes():
    a = {"companies": [{"company_id": "kai", "status": "LIVE", "active_incidents": [], "owner_actions_required": []}],
         "shared_resources": {"workers_online": 1, "capabilities_available": 7}, "autonomy_overall": "AUTONOMOUS_READ_ONLY"}
    b = {"companies": [{"company_id": "kai", "status": "LIVE", "active_incidents": [], "owner_actions_required": [{}]}],
         "shared_resources": {"workers_online": 1, "capabilities_available": 7}, "autonomy_overall": "AUTONOMOUS_READ_ONLY"}
    eng = HoldingAutonomousWorkEngine(execute=_ok_execute, resolver=_resolver)
    res = run_cycle(a, b, engine=eng, cycle_id="c2", now="2026-09-01T08:00:00")
    assert res["owner_queued"] == 1 and res["auto_executed"] == 0


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
