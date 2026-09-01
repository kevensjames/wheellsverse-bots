"""Pure tests for the CurrentPlan model + generation + reconciliation (§11-14, §18).
Run: python3 backend/app/services/holding/test_plan.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.capability.manifest import ActionClass  # noqa: E402
from app.services.holding.plan import (  # noqa: E402
    AutonomyClass, action_class_for, auto_eligible, tasks_from_changes, reconcile_plan,
    PlanTask, Assignee, Disposition, TaskStatus)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _chg(ct, scope="sol", severity="HIGH", reason=None):
    return {"change_type": ct, "scope": scope, "severity": severity, "reason": reason or ct}


def t_autonomy_maps_to_action_class():
    """§18: A0-A5 map onto the certified ActionClass — no parallel policy."""
    assert action_class_for(AutonomyClass.A0_OBSERVE) == ActionClass.READ_ONLY
    assert action_class_for(AutonomyClass.A2_REVERSIBLE_INTERNAL_WRITE) == ActionClass.REVERSIBLE_WRITE
    assert action_class_for(AutonomyClass.A4_FINANCIAL_CREDENTIAL_DESTRUCTIVE) == ActionClass.FINANCIAL
    assert action_class_for(AutonomyClass.A5_PROHIBITED) == ActionClass.PROHIBITED
    assert auto_eligible(AutonomyClass.A0_OBSERVE) and auto_eligible(AutonomyClass.A1_INTERNAL_SAFE)
    assert not auto_eligible(AutonomyClass.A2_REVERSIBLE_INTERNAL_WRITE)
    assert not auto_eligible(AutonomyClass.A3_EXTERNAL_HIGH_IMPACT)


def t_tasks_derive_from_changes_source_cited():
    """§12: a task originates from a material change and carries it as evidence — not generic advice."""
    tasks = tasks_from_changes([_chg("INCIDENT_OPENED", "nexora", "CRITICAL")], now="2026-09-01T08:00:00")
    assert len(tasks) == 1
    t = tasks[0]
    assert t.company_id == "nexora" and "nexora" in t.goal and t.evidence[0]["change_type"] == "INCIDENT_OPENED"
    assert t.autonomy == int(AutonomyClass.A0_OBSERVE) and t.assigned_to == Assignee.KAI.value
    assert t.priority == 0 and t.created_at == "2026-09-01T08:00:00"


def t_owner_blocker_becomes_owner_task():
    tasks = tasks_from_changes([_chg("OWNER_BLOCKER_ADDED", "kai", "HIGH")])
    assert tasks[0].assigned_to == Assignee.OWNER.value
    assert tasks[0].autonomy == int(AutonomyClass.A3_EXTERNAL_HIGH_IMPACT)   # owner-required, not auto


def t_recovery_changes_make_no_work():
    """INFO/recovery changes must not spawn tasks (no busy-work)."""
    assert tasks_from_changes([_chg("INCIDENT_RESOLVED"), _chg("WORKER_PLANE_RECOVERED"),
                               _chg("CAPABILITY_RECOVERED")]) == []


def t_no_duplicate_proliferation():
    """§13: two identical-source changes in one cycle → one task, not two."""
    tasks = tasks_from_changes([_chg("INCIDENT_OPENED", "sol"), _chg("INCIDENT_OPENED", "sol")])
    assert len(tasks) == 1


def t_reconcile_keep_update_complete_add():
    prior = tasks_from_changes([_chg("INCIDENT_OPENED", "sol", reason="incidents 0 → 1")])
    # same condition, unchanged → KEEP
    same = reconcile_plan(prior, tasks_from_changes([_chg("INCIDENT_OPENED", "sol", reason="incidents 0 → 1")]))
    assert [r.disposition for r in same] == [Disposition.KEEP.value]
    # condition changed reason → UPDATE
    upd = reconcile_plan(prior, tasks_from_changes([_chg("INCIDENT_OPENED", "sol", reason="incidents 1 → 2")]))
    assert upd[0].disposition == Disposition.UPDATE.value
    # condition gone (not re-derived) → COMPLETE
    done = reconcile_plan(prior, [])
    assert done[0].disposition == Disposition.COMPLETE.value
    assert done[0].task.status == TaskStatus.COMPLETE.value
    # brand-new candidate → ADD
    added = reconcile_plan([], tasks_from_changes([_chg("INCIDENT_OPENED", "kai")]))
    assert added[0].disposition == Disposition.ADD.value


def t_owner_task_persists_until_resolved():
    """An owner task not re-derived is NOT auto-completed — it BLOCKs, awaiting the owner."""
    prior = tasks_from_changes([_chg("OWNER_BLOCKER_ADDED", "kai")])
    r = reconcile_plan(prior, [])
    assert r[0].disposition == Disposition.BLOCK.value and r[0].task.assigned_to == Assignee.OWNER.value


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
