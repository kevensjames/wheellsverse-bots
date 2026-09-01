"""Tests for the limited A2 framework (Part D, §34-41, §36 self-code flow).
Run: python3 backend/app/services/holding/test_a2_framework.py"""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.capability.coding import WorkerResult  # noqa: E402
from app.services.holding.a2_framework import (  # noqa: E402
    A2Framework, A2GrantRegistry, A2Grant, A2State, A2ActionType, touches_authority)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _task(action_type=A2ActionType.EDIT_CODE_IN_WORKTREE.value, company="kai", env="development"):
    return SimpleNamespace(a2_action_type=action_type, company_id=company, capability="coding",
                           environment=env, task_id="fix-123", base_sha="abc", base_dir="/tmp/kai-a2")


def _worker_ok(files=None):
    def w(task, wt):
        return WorkerResult(task="fix", worker="coder-1", starting_sha="abc",
                            files_changed=files or ["app/services/holding/plan.py"],
                            diff_summary="fixed off-by-one", tests_run=7, tests_passed=7, tests_failed=0,
                            artifacts=["diff.patch"])
    return w


def _tests_pass(wt):
    return {"tests_run": 7, "tests_passed": 7, "tests_failed": 0}


def _reg(*grants):
    return A2GrantRegistry(list(grants))


_GRANT = A2Grant(A2ActionType.EDIT_CODE_IN_WORKTREE.value, "coding", "kai", "development")


def t_no_grant_needs_certification():
    """§34: default-empty registry → nothing is A2-eligible."""
    fw = A2Framework(_reg(), worker_fn=_worker_ok(), test_fn=_tests_pass)
    assert fw.prepare(_task()).state == A2State.NEEDS_CERTIFICATION.value


def t_forbidden_action_owner_required():
    """§38/§41: merge/deploy are never A2."""
    fw = A2Framework(_reg(_GRANT), worker_fn=_worker_ok(), test_fn=_tests_pass)
    for bad in ("MERGE", "DEPLOY", "PUSH_PRODUCTION", "MONEY", "ROTATE_SECRET"):
        assert fw.prepare(_task(action_type=bad)).state == A2State.OWNER_REQUIRED.value, bad


def t_production_env_owner_required():
    fw = A2Framework(_reg(_GRANT), worker_fn=_worker_ok(), test_fn=_tests_pass)
    assert fw.prepare(_task(env="production")).state == A2State.OWNER_REQUIRED.value


def t_unknown_action_blocked():
    fw = A2Framework(_reg(_GRANT), worker_fn=_worker_ok(), test_fn=_tests_pass)
    assert fw.prepare(_task(action_type="REWRITE_EVERYTHING")).state == A2State.BLOCKED.value


def t_granted_flow_ready_for_review_never_merges():
    """§36/§39/§41: granted change → isolated worktree → worker → tests → independent review →
    READY_FOR_REVIEW; never merged or deployed."""
    fw = A2Framework(_reg(_GRANT), worker_fn=_worker_ok(), test_fn=_tests_pass)
    r = fw.prepare(_task())
    assert r.state == A2State.READY_FOR_REVIEW.value and r.ready_for_review
    assert r.reviewed and r.certified and r.reviewer == "kai-independent-reviewer"
    assert r.merged is False and r.deployed is False        # the core A2 invariant
    assert r.branch.startswith("kai/") and r.worktree


def t_authority_immutable_owner_required():
    """§40: a diff touching approval gates / risk / kill switch / auth / money / audit is OWNER_REQUIRED."""
    for f in ("app/config.py", "app/services/capability/risk.py", "core/kai_bridge.py",
              "app/services/holding/a2_framework.py", "billing/stripe.py"):
        fw = A2Framework(_reg(_GRANT), worker_fn=_worker_ok(files=[f]), test_fn=_tests_pass)
        r = fw.prepare(_task())
        assert r.state == A2State.OWNER_REQUIRED.value, f
        assert r.merged is False
    assert touches_authority(["app/services/holding/plan.py"]) == []   # ordinary code is fine


def t_no_self_approval():
    """§40: the implementing worker can NEVER certify its own result."""
    fw = A2Framework(_reg(_GRANT), worker_fn=_worker_ok(), test_fn=_tests_pass, reviewer="coder-1")
    r = fw.prepare(_task())      # reviewer == worker
    assert r.state == A2State.BLOCKED.value and not r.certified


def t_failing_tests_block():
    def failing(wt): return {"tests_run": 5, "tests_passed": 3, "tests_failed": 2}
    fw = A2Framework(_reg(_GRANT), worker_fn=_worker_ok(), test_fn=failing)
    r = fw.prepare(_task())
    assert r.state == A2State.BLOCKED.value and not r.certified and r.merged is False


def t_registry_rejects_bad_grants():
    try:
        A2Grant("MERGE", "coding", "kai", "development"); reg = A2GrantRegistry(); reg.grant(A2Grant("MERGE", "coding", "kai", "development")); assert False
    except ValueError:
        pass
    try:
        A2GrantRegistry([A2Grant(A2ActionType.EDIT_CODE_IN_WORKTREE.value, "coding", "kai", "production")]); assert False
    except ValueError:
        pass


def t_worktree_only_when_no_worker():
    """Framework can prepare the isolated worktree even before a coding worker is wired."""
    fw = A2Framework(_reg(_GRANT), worker_fn=None)
    r = fw.prepare(_task())
    assert r.state == A2State.WORKTREE.value and r.worktree and not r.ready_for_review


def t_engine_a2_routing():
    """Engine hook: without a framework an A2 task NEEDS_CERTIFICATION; with a grant it reaches
    A2_READY_FOR_REVIEW (owner reviews) — the engine never merges."""
    from app.services.holding.autonomous_work import (
        HoldingAutonomousWorkEngine, NEEDS_CERTIFICATION, A2_READY_FOR_REVIEW)
    from app.services.holding.plan import PlanTask, AutonomyClass, Assignee
    t = PlanTask("fix-1", "kai", "fix bug", "regression", "fix-1",
                 autonomy=int(AutonomyClass.A2_REVERSIBLE_INTERNAL_WRITE), assigned_to=Assignee.KAI.value)
    t.a2_action_type = A2ActionType.EDIT_CODE_IN_WORKTREE.value
    t.capability, t.environment, t.base_sha, t.base_dir = "coding", "development", "abc", "/tmp/kai-a2"
    # no framework wired → needs certification
    eng0 = HoldingAutonomousWorkEngine(execute=lambda *a, **k: None, resolver=lambda x: None)
    assert eng0.run_task(t).outcome == NEEDS_CERTIFICATION
    # framework + grant → prepared, owner-reviewed, never merged
    fw = A2Framework(_reg(_GRANT), worker_fn=_worker_ok(), test_fn=_tests_pass)
    eng = HoldingAutonomousWorkEngine(execute=lambda *a, **k: None, resolver=lambda x: None, a2_framework=fw)
    r = eng.run_task(t)
    assert r.outcome == A2_READY_FOR_REVIEW and r.task_status == "BLOCKED"   # not COMPLETE — owner merges


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
