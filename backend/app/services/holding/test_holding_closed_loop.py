"""End-to-end closed-loop tests (§23-27): twin snapshot → reconcile → plan → resolver → executor →
engine → owner queue. Uses fixture runtime providers so the CHAIN is proven deterministically without
overstating that pending runtimes are live. Run: python3 backend/app/services/holding/test_holding_closed_loop.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.holding.autonomous_work import (  # noqa: E402
    HoldingAutonomousWorkEngine, run_cycle, EXECUTED, OWNER_QUEUED, BLOCKED_CAPABILITY)
from app.services.holding.task_resolver import (  # noqa: E402
    TaskCapabilityResolver, make_engine_resolver, build_holding_executor, HoldingTaskType)
from app.services.holding.plan import tasks_from_changes, reconcile_plan, PlanTask, AutonomyClass, Assignee  # noqa: E402
from app.services.holding.state_reconciler import reconcile_result  # noqa: E402
from app.services.holding.owner_queue import prepare_owner_actions  # noqa: E402

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _co(cid, status="LIVE", incidents=0, owner_actions=0, deployment=None):
    return {"company_id": cid, "status": status, "active_incidents": ["x"] * incidents,
            "owner_actions_required": [{}] * owner_actions, "deployments": [deployment] if deployment else []}


def _snap(companies, workers_online=1, caps=7, autonomy="AUTONOMOUS_READ_ONLY"):
    return {"companies": companies, "shared_resources": {"workers_online": workers_online,
            "capabilities_available": caps}, "autonomy_overall": autonomy}


def _engine(providers=None):
    return HoldingAutonomousWorkEngine(
        execute=build_holding_executor(providers=providers or {}),
        resolver=make_engine_resolver(TaskCapabilityResolver(), cycle_id="c"))


def t_incident_closed_loop_completes_with_evidence():
    """§23: HEALTHY→DEGRADED → HEALTH_PROBE → certified health read → evidence → COMPLETE, no owner task."""
    a = _snap([_co("sol", status="LIVE")])
    b = _snap([_co("sol", status="DEGRADED")])
    health_fixture = {"holding.health": lambda args: {"source": "fixture", "target": args["target"],
                      "observed_state": "DEGRADED", "observed_at": "2026-09-01"}}
    res = run_cycle(a, b, engine=_engine(health_fixture), cycle_id="c1", now="2026-09-01T08:00:00")
    assert res["verdict"] == "MATERIAL_CHANGE" and res["auto_executed"] == 1 and res["failed"] == 0
    assert res["owner_queued"] == 0
    r = res["results"][0]
    assert r["outcome"] == EXECUTED and r["verified"] and r["capability_id"] == "holding.health"


def t_deployment_closed_loop():
    """§24: deployment changed → DEPLOYMENT_STATUS → read-only evidence (fixture runtime) → no owner."""
    a = _snap([_co("kai", deployment="sha-aaaa")])
    b = _snap([_co("kai", deployment="sha-bbbb")])
    dep_fixture = {"holding.deployment": lambda args: {"service_id": args.get("service_id", "kai"),
                   "deployment_id": "d99", "deployed_sha": "sha-bbbb", "sha_comparison": "MATCH",
                   "status": "SUCCESS", "observed_at": "2026-09-01"}}
    res = run_cycle(a, b, engine=_engine(dep_fixture), cycle_id="c2", now="2026-09-01T08:00:00")
    assert res["auto_executed"] == 1 and res["owner_queued"] == 0
    assert res["results"][0]["capability_id"] == "holding.deployment"


def t_deployment_without_runtime_blocks():
    """§37: with NO deployment provider, the pending runtime fails closed to BLOCKED_CAPABILITY."""
    a = _snap([_co("kai", deployment="sha-aaaa")])
    b = _snap([_co("kai", deployment="sha-bbbb")])
    res = run_cycle(a, b, engine=_engine(), cycle_id="c2b", now="2026-09-01T08:00:00")
    assert res["auto_executed"] == 0 and res["blocked"] == 1
    assert res["results"][0]["outcome"] == BLOCKED_CAPABILITY


def t_log_inspect_bounded_redacted_in_loop():
    """§25: a LOG_INSPECT task runs through the engine with a fixture logs provider; secrets redacted."""
    log_task = PlanTask("log:kai", "kai", "inspect logs", "incident", "log:kai",
                        task_type=HoldingTaskType.LOG_INSPECT.value, autonomy=int(AutonomyClass.A0_OBSERVE),
                        assigned_to=Assignee.KAI.value)
    eng = _engine({"holding.logs": lambda a: {"service": a["service"], "time_window": a.get("time_window"),
                   "lines_redacted": ["ok", "Authorization: Bearer secret.jwt.token"]}})
    r = eng.run_task(log_task)
    assert r.outcome == EXECUTED and "secret.jwt" not in str(r.__dict__)


def t_owner_boundary_loop_no_kai_deploy():
    """§26: an owner blocker → OWNER_QUEUED (never executed) → prepared owner action; KAI does not deploy."""
    a = _snap([_co("kai", owner_actions=0)])
    b = _snap([_co("kai", owner_actions=1)])
    changes = reconcile_result(a, b)["changes"]
    tasks = tasks_from_changes(changes, now="2026-09-01T08:00:00")
    reconciled = reconcile_plan([], tasks)
    results = _engine().run([rt.task for rt in reconciled])
    assert all(r.outcome != EXECUTED for r in results)
    owner_result = next(r for r in results if r.outcome == OWNER_QUEUED)
    actions = prepare_owner_actions(reconciled, results)
    assert len(actions) == 1 and actions[0].company_id == "kai"
    assert actions[0].exact_owner_action and owner_result.task_status == "BLOCKED"


def t_no_change_second_cycle():
    """§27: identical second cycle → 0 executions, 0 owner proposals, 0 tasks."""
    s = _snap([_co("sol"), _co("kai")])
    res = run_cycle(s, s, engine=_engine(), cycle_id="c-same")
    assert res["verdict"] == "NO_MATERIAL_CHANGE" and res["auto_executed"] == 0
    assert res["owner_queued"] == 0 and res["material_changes"] == 0
    assert res["results"] == []


def t_repo_inspect_closed_loop_live():
    """§13: a REPO_INSPECT task for a local-git company runs through the REAL default executor
    (resolver → holding.repo → live LocalGitProvider) → real commit evidence → COMPLETE, 0 writes."""
    from app.services.holding.task_resolver import build_holding_executor
    task = PlanTask("repo:kai", "kai", "inspect repo", "repository changed", "repo:kai",
                    task_type=HoldingTaskType.REPO_INSPECT.value, autonomy=int(AutonomyClass.A0_OBSERVE),
                    assigned_to=Assignee.KAI.value)
    eng = HoldingAutonomousWorkEngine(execute=build_holding_executor(),   # real default providers
                                      resolver=make_engine_resolver(TaskCapabilityResolver(), cycle_id="c"))
    r = eng.run_task(task)
    assert r.outcome == EXECUTED and r.verified and r.capability_id == "holding.repo"


def t_repo_inspect_external_company_blocks():
    """A company whose repo is NOT the certified local monorepo → BLOCKED_CAPABILITY (no silent mirror)."""
    from app.services.holding.task_resolver import build_holding_executor
    task = PlanTask("repo:nurtelle", "nurtelle", "inspect repo", "x", "repo:nurtelle",
                    task_type=HoldingTaskType.REPO_INSPECT.value, autonomy=int(AutonomyClass.A0_OBSERVE),
                    assigned_to=Assignee.KAI.value)
    eng = HoldingAutonomousWorkEngine(execute=build_holding_executor(),
                                      resolver=make_engine_resolver(TaskCapabilityResolver()))
    assert eng.run_task(task).outcome == BLOCKED_CAPABILITY


def t_run_internal_test_closed_loop_live():
    """§33: an A1 RUN_INTERNAL_TEST task runs a real allowlisted suite through the engine → real
    pass/fail evidence → COMPLETE. Test failure would be COMPLETED+FAILED, not an infra error (§32)."""
    from app.services.holding.task_resolver import build_holding_executor
    task = PlanTask("test:kai", "kai", "verify regression", "suspected regression", "test:kai",
                    task_type=HoldingTaskType.RUN_INTERNAL_TEST.value,
                    autonomy=int(AutonomyClass.A1_INTERNAL_SAFE), assigned_to=Assignee.KAI.value)
    eng = HoldingAutonomousWorkEngine(execute=build_holding_executor(),
                                      resolver=make_engine_resolver(TaskCapabilityResolver()))
    r = eng.run_task(task)
    assert r.outcome == EXECUTED and r.verified and r.capability_id == "holding.internal_test"


def t_unknown_task_type_blocks_in_loop():
    """A plan task with a non-mapped type never executes — fail-closed BLOCKED_CAPABILITY."""
    t = PlanTask("x:sol", "sol", "do a thing", "r", "x:sol", task_type="ARBITRARY",
                 autonomy=int(AutonomyClass.A0_OBSERVE), assigned_to=Assignee.KAI.value)
    r = _engine().run_task(t)
    assert r.outcome == BLOCKED_CAPABILITY


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
