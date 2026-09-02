"""Tests for the persistent Holding cycle (Part D, §18-24).
Run: python3 backend/app/services/holding/test_holding_cycle.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.autonomous_work import HoldingAutonomousWorkEngine  # noqa: E402
from app.services.holding.task_resolver import TaskCapabilityResolver, make_engine_resolver, build_holding_executor  # noqa: E402
from app.services.holding.holding_cycle import (  # noqa: E402
    run_persistent_cycle, category_due, self_improve_allowed, restart_reconcile_count,
    CycleRecord, SELF_IMPROVE_DAILY_CEILING)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _co(cid, status="LIVE", incidents=0, owner_actions=0):
    return {"company_id": cid, "status": status, "active_incidents": ["x"] * incidents,
            "owner_actions_required": [{}] * owner_actions, "deployments": []}


def _snap(companies, workers_online=1, caps=7, autonomy="AUTONOMOUS_READ_ONLY"):
    return {"companies": companies, "shared_resources": {"workers_online": workers_online,
            "capabilities_available": caps}, "autonomy_overall": autonomy}


def _engine(global_autonomy=True):
    return HoldingAutonomousWorkEngine(execute=build_holding_executor(),
                                       resolver=make_engine_resolver(TaskCapabilityResolver()),
                                       global_autonomy=global_autonomy)


def t_bounded_schedule():
    """§19: intervals gate re-runs; 90-day planning is not every 15 minutes."""
    assert category_due("health", "", "2026-09-02T00:00:00") is True         # never run
    assert category_due("health", "2026-09-02T00:00:00", "2026-09-02T00:02:00") is False   # 2min < 5min
    assert category_due("health", "2026-09-02T00:00:00", "2026-09-02T00:10:00") is True    # 10min > 5min
    assert category_due("planning_90d", "2026-09-02T00:00:00", "2026-09-02T00:15:00") is False  # 15min « weekly
    assert category_due("planning_90d", "2026-08-01T00:00:00", "2026-09-02T00:00:00") is True


def t_no_change_cycle_zero_work():
    """§20: a persistent cycle with no material change → 0 executed / 0 owner actions / 0 plan changes."""
    s = _snap([_co("sol"), _co("kai")])
    rec = run_persistent_cycle(s, s, engine=_engine(), cycle_id="c1", now="2026-09-02T08:00:00",
                               companies_reviewed=2)
    assert rec.verdict == "NO_MATERIAL_CHANGE" and rec.tasks_executed == 0
    assert rec.owner_actions_created == 0 and rec.plan_changes == 0 and rec.material_changes == 0


def t_material_change_records_work():
    a = _snap([_co("sol", status="LIVE")]); b = _snap([_co("sol", status="DEGRADED")])
    # inject a fixture health provider so the derived HEALTH_PROBE actually executes
    from app.services.holding.autonomous_work import HoldingAutonomousWorkEngine as E
    eng = E(execute=build_holding_executor(providers={
        "holding.health": lambda args: {"source": "fixture", "target": args["target"],
                                        "observed_state": "DEGRADED", "observed_at": "now"}}),
            resolver=make_engine_resolver(TaskCapabilityResolver()))
    rec = run_persistent_cycle(a, b, engine=eng, cycle_id="c2", now="2026-09-02T08:00:00", companies_reviewed=1)
    assert rec.verdict == "MATERIAL_CHANGE" and rec.material_changes == 1 and rec.tasks_executed == 1
    assert rec.evidence_refs and isinstance(rec.as_dict(), dict)


def t_kill_switch_observes_but_executes_zero():
    """§24: autonomy OFF → material change still observed, autonomous execution = 0."""
    a = _snap([_co("sol", status="LIVE")]); b = _snap([_co("sol", status="DEGRADED")])
    rec = run_persistent_cycle(a, b, engine=_engine(global_autonomy=False), cycle_id="c3",
                               now="2026-09-02T08:00:00", companies_reviewed=1)
    assert rec.material_changes == 1 and rec.tasks_executed == 0 and rec.autonomy_off >= 1


def t_self_improve_ceiling():
    """§21: bounded daily self-improvement attempts."""
    assert self_improve_allowed(0) and self_improve_allowed(SELF_IMPROVE_DAILY_CEILING - 1)
    assert not self_improve_allowed(SELF_IMPROVE_DAILY_CEILING)
    assert not self_improve_allowed(99)


def t_restart_reconciles_once():
    """§23: after restart, reconcile once — never replay every missed interval."""
    assert restart_reconcile_count(0) == 1
    assert restart_reconcile_count(500) == 1


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
