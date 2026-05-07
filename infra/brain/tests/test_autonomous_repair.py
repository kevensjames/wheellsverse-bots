"""Tests for the CI autonomous repair layer.

Focus: every safety guard + the dry-run path. The expensive paths (real
``pytest`` reruns, real ``git apply``) are exercised via ``monkeypatch``
so the suite stays fast and deterministic.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from infra.brain.debug import ci_autonomous_repair as repair
from infra.brain.debug.ci_autonomous_repair import (
    ApplyOutcome,
    PatchValidation,
    RepairAttempt,
    RerunOutcome,
    StabilityReport,
    apply_patch_safely,
    attempt_repair,
    build_pr_bundle,
    confirm_stability,
    rerun_test,
    validate_patch,
)


# ── validate_patch: shape + safety ─────────────────────────────────────────


def test_validate_patch_rejects_empty_input():
    v = validate_patch("")
    assert isinstance(v, PatchValidation)
    assert v.applicable is False
    assert v.reason == "empty_patch"
    assert v.files_referenced == ()


def test_validate_patch_detects_placeholder_paths():
    """Most suggest_fix() patches reference placeholder paths like
    ``<your_tool_module>.py``. These MUST be rejected before any apply."""
    illustrative = (
        "--- a/<your_tool_module>.py\n"
        "+++ b/<your_tool_module>.py\n"
        "@@ async def _run(input):\n"
        "-    return None\n"
        "+    return {}\n"
    )
    v = validate_patch(illustrative)
    assert v.applicable is False
    assert v.has_placeholders is True
    assert v.reason == "patch_has_placeholders"


def test_validate_patch_flags_missing_files():
    """A patch referencing files that don't exist is not applicable."""
    fake = (
        "--- a/totally_nonexistent_file_xyz.py\n"
        "+++ b/totally_nonexistent_file_xyz.py\n"
        "@@ def f():\n"
        "-    return 1\n"
        "+    return 2\n"
    )
    v = validate_patch(fake)
    assert v.applicable is False
    assert "totally_nonexistent_file_xyz.py" in v.files_missing
    assert v.reason == "files_missing"


def test_validate_patch_against_real_repo_paths_runs_git_check(monkeypatch):
    """When the patch touches real files, validate_patch runs
    ``git apply --check``. We stub the git call to make the test
    deterministic."""
    # An entry that references a real file in the repo (interface.py).
    real_patch = (
        "--- a/infra/brain/interface.py\n"
        "+++ b/infra/brain/interface.py\n"
        "@@ class BrainClient:\n"
        "-    pass\n"
        "+    pass  # touched\n"
    )
    captured = {}

    def fake_git(args, **kw):
        captured["args"] = args
        captured["input"] = kw.get("input_bytes")
        return (0, "")

    monkeypatch.setattr(repair, "_git", fake_git)
    v = validate_patch(real_patch)
    assert captured["args"][0] == "apply"
    assert "--check" in captured["args"]
    assert v.applicable is True
    assert v.has_placeholders is False
    assert v.files_missing == ()


def test_validate_patch_propagates_git_check_rejection(monkeypatch, tmp_path):
    """When ``git apply --check`` rejects a patch that targets real files,
    validate_patch must surface the rejection (not crash on repo discovery)."""
    target = tmp_path / "infra" / "brain" / "interface.py"
    target.parent.mkdir(parents=True)
    target.write_text("class BrainClient:\n    pass\n")

    real_patch = (
        "--- a/infra/brain/interface.py\n"
        "+++ b/infra/brain/interface.py\n"
        "@@ class BrainClient:\n"
        "-    pass\n"
        "+    pass\n"
    )
    # Pass repo_root explicitly so we never hit the _git-based discovery.
    monkeypatch.setattr(
        repair, "_git",
        lambda args, **kw: (1, "error: patch failed to apply"),
    )
    v = validate_patch(real_patch, repo_root=tmp_path)
    assert v.applicable is False
    assert v.reason == "git_apply_check_rejected"
    assert "patch failed" in v.git_check_output


# ── apply_patch_safely: every guard fires before any disk write ────────────


def _force_clean_repo(monkeypatch):
    """Pretend the working tree is clean and we're on a feature branch."""
    monkeypatch.setattr(repair, "_repo_root",     lambda: Path("/tmp/fake-repo"))
    monkeypatch.setattr(repair, "_current_branch", lambda: "feature/test")
    monkeypatch.setattr(repair, "_working_tree_is_clean", lambda: True)
    monkeypatch.setattr(
        repair, "validate_patch",
        lambda *a, **kw: PatchValidation(
            applicable=True, files_referenced=("x.py",),
            files_missing=(), has_placeholders=False,
            git_check_output="",
        ),
    )


def test_apply_refuses_dirty_working_tree(monkeypatch):
    monkeypatch.setattr(repair, "_repo_root",     lambda: Path("/tmp/fake-repo"))
    monkeypatch.setattr(repair, "_current_branch", lambda: "feature/test")
    monkeypatch.setattr(repair, "_working_tree_is_clean", lambda: False)
    out = apply_patch_safely("--- a/x.py\n+++ b/x.py\n", fix_confidence=1.0)
    assert out.applied is False
    assert out.reason == "working_tree_dirty"


def test_apply_refuses_protected_branch(monkeypatch):
    monkeypatch.setattr(repair, "_repo_root",     lambda: Path("/tmp/fake-repo"))
    monkeypatch.setattr(repair, "_current_branch", lambda: "main")
    monkeypatch.setattr(repair, "_working_tree_is_clean", lambda: True)
    out = apply_patch_safely("p", fix_confidence=1.0)
    assert out.applied is False
    assert "protected_branch" in out.reason


def test_apply_refuses_low_confidence(monkeypatch):
    _force_clean_repo(monkeypatch)
    out = apply_patch_safely("p", fix_confidence=0.4)
    assert out.applied is False
    assert "confidence_below_threshold" in out.reason


def test_apply_refuses_when_validation_rejects_patch(monkeypatch):
    _force_clean_repo(monkeypatch)
    monkeypatch.setattr(
        repair, "validate_patch",
        lambda *a, **kw: PatchValidation(
            applicable=False, files_referenced=(),
            files_missing=(), has_placeholders=True,
            git_check_output="",
            reason="patch_has_placeholders",
        ),
    )
    out = apply_patch_safely("p", fix_confidence=0.95)
    assert out.applied is False
    assert "patch_not_applicable" in out.reason


def test_apply_runs_git_apply_when_all_guards_pass(monkeypatch):
    _force_clean_repo(monkeypatch)
    calls = []

    def fake_git(args, **kw):
        calls.append(list(args))
        return (0, "applied")

    monkeypatch.setattr(repair, "_git", fake_git)
    out = apply_patch_safely("p", fix_confidence=0.95)
    assert out.applied is True
    assert out.reason == "applied"
    assert any(a[0] == "apply" for a in calls)


# ── confirm_stability: bail on first failure, classify stability ───────────


def _outcome(passed: bool, rc: int = 0) -> RerunOutcome:
    return RerunOutcome(
        test_node_id="x::y", passed=passed,
        duration_ms=1.0, return_code=rc, output_tail="",
    )


def test_confirm_stability_all_pass(monkeypatch):
    monkeypatch.setattr(repair, "rerun_test", lambda *a, **kw: _outcome(True))
    rep = confirm_stability("x::y", repeats=3)
    assert isinstance(rep, StabilityReport)
    assert len(rep.runs) == 3
    assert rep.all_passed is True
    assert rep.stable is True


def test_confirm_stability_bails_on_first_failure(monkeypatch):
    seq = iter([_outcome(False, rc=1)])
    monkeypatch.setattr(repair, "rerun_test", lambda *a, **kw: next(seq))
    rep = confirm_stability("x::y", repeats=5)
    assert len(rep.runs) == 1
    assert rep.all_passed is False
    assert rep.stable is True  # one consistent failure is "stable" too


def test_confirm_stability_rejects_invalid_repeats():
    with pytest.raises(ValueError):
        confirm_stability("x::y", repeats=0)


# ── attempt_repair: dry-run never mutates the tree ────────────────────────


def test_attempt_repair_dry_run_never_applies(monkeypatch, tmp_path):
    """The default path (``apply_patch=False``) MUST NOT call git apply."""
    monkeypatch.setattr(repair, "rerun_test", lambda *a, **kw: _outcome(False, 1))

    git_calls = []
    def fake_git(args, **kw):
        git_calls.append(list(args))
        return (0, "")
    monkeypatch.setattr(repair, "_git", fake_git)

    monkeypatch.setattr(repair, "_repo_root", lambda: tmp_path)
    # Patch references a placeholder → not applicable anyway, but the
    # dry-run path should never even attempt the apply.
    fix = {
        "stage": "tool", "fix_type": "config",
        "patch": (
            "--- a/<your_tool_module>.py\n"
            "+++ b/<your_tool_module>.py\n"
            "@@ async def _run(input):\n-    pass\n+    pass\n"
        ),
        "confidence": 0.9, "risk_level": "low",
        "root_cause": "x", "explanation": "x",
    }
    analysis = {"stage": "tool", "reason": "tool_runtime_error",
                "summary": "x", "event_trace": [], "recommendation": "x"}

    attempt = attempt_repair(
        "infra/brain/tests/test_x.py::test_y",
        analysis, fix,
        apply_patch=False, bundle_dir=tmp_path / "bundles",
    )
    assert isinstance(attempt, RepairAttempt)
    assert attempt.patch_applied is False
    assert attempt.post_repair is None
    assert "dry_run=True" in attempt.decision
    # No git apply / git checkout was attempted
    assert all(args[0] != "apply"   for args in git_calls)
    assert all(args[0] != "checkout" for args in git_calls)
    assert attempt.bundle_path is not None
    assert Path(attempt.bundle_path).is_dir()


def test_attempt_repair_skips_when_test_already_passes(monkeypatch, tmp_path):
    """If the test is already green, no repair is attempted."""
    monkeypatch.setattr(repair, "rerun_test", lambda *a, **kw: _outcome(True))
    monkeypatch.setattr(repair, "_repo_root", lambda: tmp_path)

    fix = {"stage": "tool", "fix_type": "config", "patch": "",
           "confidence": 0.9, "risk_level": "low",
           "root_cause": "", "explanation": ""}
    attempt = attempt_repair(
        "x::y", {"stage": "tool", "reason": "tool_runtime_error"},
        fix, apply_patch=True,
    )
    assert attempt.patch_applied is False
    assert "already passes" in attempt.decision


def test_attempt_repair_reverts_on_unstable_post_repair(monkeypatch):
    """If post-repair runs flake (some pass, some fail) the patch is reverted."""
    monkeypatch.setattr(repair, "rerun_test", lambda *a, **kw: _outcome(False, 1))
    monkeypatch.setattr(
        repair, "validate_patch",
        lambda *a, **kw: PatchValidation(
            applicable=True, files_referenced=("infra/brain/interface.py",),
            files_missing=(), has_placeholders=False,
            git_check_output="",
        ),
    )
    monkeypatch.setattr(
        repair, "apply_patch_safely",
        lambda *a, **kw: ApplyOutcome(
            applied=True, reason="applied", git_output="",
            branch="feature/x", pre_apply_clean=True,
        ),
    )
    # Stability: pass, FAIL, pass — so the bail-on-first-fail short-circuit
    # registers an "unstable" outcome.
    seq = iter([_outcome(False, 1)])
    monkeypatch.setattr(
        repair, "confirm_stability",
        lambda *a, **kw: StabilityReport(
            test_node_id="x::y",
            runs=(_outcome(True), _outcome(False, 1), _outcome(True)),
        ),
    )

    git_calls = []
    monkeypatch.setattr(
        repair, "_git",
        lambda args, **kw: git_calls.append(list(args)) or (0, ""),
    )

    fix = {"stage": "router", "fix_type": "schema", "patch": "p",
           "confidence": 0.95, "risk_level": "low",
           "root_cause": "", "explanation": ""}
    attempt = attempt_repair(
        "x::y", {"stage": "router", "reason": "invalid_plan_from_llm"},
        fix, apply_patch=True,
    )
    # Patch was applied then REVERTED because runs were mixed
    assert attempt.patch_applied is False
    # `git checkout -- .` must be the recovery call
    assert any(args[:2] == ["checkout", "--"] for args in git_calls), (
        f"expected revert via 'git checkout -- .', saw: {git_calls}"
    )
    # Decision narrates what happened
    assert "reverted" in attempt.decision


# ── PR-ready bundle layout ─────────────────────────────────────────────────


def test_build_pr_bundle_writes_full_layout(tmp_path):
    attempt = RepairAttempt(
        test_node_id="infra/brain/tests/test_x.py::test_y",
        analysis={"stage": "tool", "reason": "tool_runtime_error",
                  "summary": "x", "event_trace": [], "recommendation": "x"},
        fix={"stage": "tool", "fix_type": "crash",
             "patch": "--- a/x.py\n+++ b/x.py\n@@\n-1\n+2\n",
             "confidence": 0.7, "risk_level": "low",
             "root_cause": "tool body raised", "explanation": "..."},
        patch_validation=PatchValidation(
            applicable=True, files_referenced=("x.py",),
            files_missing=(), has_placeholders=False,
            git_check_output="",
        ),
        pre_repair=_outcome(False, 1),
        patch_applied=True,
        post_repair=StabilityReport(
            test_node_id="x::y",
            runs=(_outcome(True), _outcome(True), _outcome(True)),
        ),
        decision="stable across 3 runs; left applied",
    )
    out = build_pr_bundle(attempt, tmp_path)
    assert out.is_dir()
    # Every expected file is present
    for name in (
        "PATCH.diff", "ANALYSIS.json", "FIX.json",
        "PRE_REPAIR_LOG.txt", "POST_REPAIR.json",
        "ATTEMPT.json", "PR_DESCRIPTION.md",
    ):
        assert (out / name).is_file(), f"bundle missing {name}"
    # The JSON files round-trip
    json.loads((out / "ANALYSIS.json").read_text())
    json.loads((out / "FIX.json").read_text())
    json.loads((out / "POST_REPAIR.json").read_text())
    # PR description contains the test id + verdict
    pr_md = (out / "PR_DESCRIPTION.md").read_text()
    assert "infra/brain/tests/test_x.py::test_y" in pr_md
    assert "PASS" in pr_md
