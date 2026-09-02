"""Tests for the SelfImprovementEngine (Part B, §18,§25,§26,§33,§34,§38-42).
Run: python3 backend/app/services/holding/test_self_improvement.py"""
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # backend/ on path

from app.services.capability.coding import WorkerResult  # noqa: E402
from app.services.holding.a2_framework import A2Framework, A2GrantRegistry, A2ActionType  # noqa: E402
from app.services.holding.deployment_status import MATCH, DEPLOYMENT_BEHIND  # noqa: E402
from app.services.holding.self_improvement import (  # noqa: E402
    SelfImprovementEngine, SelfImprovementCandidate, ImprovementStatus, self_improvement_grant_v1,
    DIAG_SOURCE_DEFECT, DIAG_DEPLOYMENT_STALE, DIAG_CONFIG, MAX_FILES_CHANGED)

_p = 0


def test(name, fn):
    global _p
    try:
        fn(); print("  ok  " + name); _p += 1
    except AssertionError as e:
        print("  FAIL " + name + "\n       " + str(e)); sys.exit(1)


def _cand(outcome="CORRECTNESS"):
    return SelfImprovementCandidate(improvement_id="imp-1", subsystem="holding.reports",
                                    problem_type="LOGIC", problem="off-by-one in status transform",
                                    desired_outcome=outcome, company_id="kai",
                                    evidence_refs=["test:holding_x::t_fail"], created_at="2026-09-01")


def _worker(files_claim=None):
    def w(task, wt):
        return WorkerResult(task="fix", worker="coder-1", starting_sha="abc",
                            files_changed=files_claim or ["app/services/holding/reports.py"],
                            diff_summary="fix off-by-one", tests_run=8, tests_passed=8, tests_failed=0)
    return w


def _engine(*, diff_files, tests_pass=True, reviewer="kai-independent-reviewer"):
    reg = A2GrantRegistry([self_improvement_grant_v1("kai")])
    tfn = (lambda wt: {"tests_run": 8, "tests_passed": 8, "tests_failed": 0}) if tests_pass \
        else (lambda wt: {"tests_run": 8, "tests_passed": 6, "tests_failed": 2})
    fw = A2Framework(reg, worker_fn=_worker(), test_fn=tfn, diff_fn=lambda w, s: list(diff_files),
                     reviewer=reviewer)
    return SelfImprovementEngine(a2_framework=fw)


def _task():
    return SimpleNamespace(a2_action_type=A2ActionType.EDIT_CODE_IN_WORKTREE.value, company_id="kai",
                           capability="coding", environment="development", task_id="imp-1",
                           base_sha="abc", base_dir="/tmp/kai-a2")


def t_value_gate_rejects_cosmetic():
    """§18: no measurable value outcome → REJECTED."""
    eng = _engine(diff_files=["app/services/holding/reports.py"])
    c = eng.confirm(_cand(outcome="LOOKS_NICER"), test_before_fails=True)
    assert c.status == ImprovementStatus.REJECTED.value


def t_deployment_stale_no_code_fix():
    """§41 CRITICAL: source may already be fixed, deployment behind → BLOCKED/DEPLOYMENT_STALE, no fix."""
    eng = _engine(diff_files=["app/services/holding/reports.py"])
    c = eng.confirm(_cand(), deployment_comparison=DEPLOYMENT_BEHIND, test_before_fails=True)
    assert c.status == ImprovementStatus.BLOCKED.value and c.diagnosis == DIAG_DEPLOYMENT_STALE
    out = eng.prepare(c, _task())
    assert out["prepared"] is None      # never prepared a second fix


def t_config_only_owner():
    """§42: production config issue → OWNER_REQUIRED, no autonomous config write."""
    eng = _engine(diff_files=["app/config.py"])
    c = eng.confirm(_cand(), deployment_comparison=MATCH, test_before_fails=True, is_config_issue=True)
    assert c.status == ImprovementStatus.OWNER_REQUIRED.value and c.diagnosis == DIAG_CONFIG


def t_no_improvement_insufficient_evidence():
    """§40: no reproducing test → BLOCKED_EVIDENCE, KAI does not modify code."""
    eng = _engine(diff_files=["app/services/holding/reports.py"])
    c = eng.confirm(_cand(), deployment_comparison=MATCH, test_before_fails=False)
    assert c.status == ImprovementStatus.BLOCKED_EVIDENCE.value


def t_full_e2e_ready_for_review():
    """§38: defect → CONFIRMED → isolated worktree → worker → git-diff gate → tests → independent
    review → READY_FOR_REVIEW; never merged/deployed."""
    eng = _engine(diff_files=["app/services/holding/reports.py"])
    c = eng.confirm(_cand(outcome="RELIABILITY"), deployment_comparison=MATCH, test_before_fails=True)
    assert c.status == ImprovementStatus.CONFIRMED.value and c.diagnosis == DIAG_SOURCE_DEFECT
    out = eng.prepare(c, _task())
    assert out["status"] == ImprovementStatus.READY_FOR_REVIEW.value
    prep = out["prepared"]
    assert prep["ready_for_review"] and prep["merged"] is False and prep["deployed"] is False
    assert "review_package" in out and out["review_package"]["owner_action"].startswith("REVIEW")


def t_bad_fix_fails():
    """§39: worker's fix fails tests → not certified → FAILED (no escalation, no retry)."""
    eng = _engine(diff_files=["app/services/holding/reports.py"], tests_pass=False)
    c = eng.confirm(_cand(), deployment_comparison=MATCH, test_before_fails=True)
    out = eng.prepare(c, _task())
    assert out["status"] == ImprovementStatus.FAILED.value


def t_self_authority_attack_denied():
    """§34: worker's diff touches an authority surface → A2 gate → OWNER_REQUIRED, never prepared-clean."""
    for f in ("app/config.py", "app/services/holding/a2_framework.py",
              "app/services/capability/risk.py", "app/rbac.py"):
        eng = _engine(diff_files=[f])
        c = eng.confirm(_cand(), deployment_comparison=MATCH, test_before_fails=True)
        out = eng.prepare(c, _task())
        assert out["status"] == ImprovementStatus.OWNER_REQUIRED.value, f


def t_dependency_change_owner_required():
    """§26: a dependency/build-file change → OWNER_REQUIRED."""
    for f in ("requirements.txt", "backend/requirements-staging.txt", "pyproject.toml", "Dockerfile.staging"):
        eng = _engine(diff_files=["app/services/holding/reports.py", f])
        c = eng.confirm(_cand(), deployment_comparison=MATCH, test_before_fails=True)
        out = eng.prepare(c, _task())
        assert out["status"] == ImprovementStatus.OWNER_REQUIRED.value and out["diagnosis"] == "DEPENDENCY_CHANGE", f


def t_diff_too_large_owner_required():
    """§25: too many files → OWNER_REQUIRED."""
    eng = _engine(diff_files=[f"app/services/holding/f{i}.py" for i in range(MAX_FILES_CHANGED + 1)])
    c = eng.confirm(_cand(), deployment_comparison=MATCH, test_before_fails=True)
    out = eng.prepare(c, _task())
    assert out["status"] == ImprovementStatus.OWNER_REQUIRED.value and out["diagnosis"] == "DIFF_TOO_LARGE"


def t_test_cheating_owner_required():
    """§33: a CORRECTNESS fix that changes ONLY a test file (no source) → OWNER_REQUIRED (suspicious)."""
    eng = _engine(diff_files=["app/services/holding/test_reports.py"])
    c = eng.confirm(_cand(outcome="CORRECTNESS"), deployment_comparison=MATCH, test_before_fails=True)
    out = eng.prepare(c, _task())
    assert out["status"] == ImprovementStatus.OWNER_REQUIRED.value and out["diagnosis"] == "POSSIBLE_TEST_CHEATING"


def run():
    for _n, _f in list(globals().items()):
        if _n.startswith("t_"):
            test(_n[2:], _f)
    print("\n%d passed" % _p)


if __name__ == "__main__":
    run()
