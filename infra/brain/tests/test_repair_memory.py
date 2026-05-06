"""Tests for the self-improving repair-memory layer.

Layered into three groups:

  1. Pure helpers — failure-signature derivation, patch normalisation.
  2. RepairMemory class — persistence, querying, scoring, gate logic.
  3. Integration — apply_patch_safely + attempt_repair with the memory
     hook attached, asserting cold-start safety, the audit log line,
     and the feedback loop.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch as mock_patch

import pytest

from infra.brain.learning import (
    DEFAULT_THRESHOLD,
    MIN_CASES_FOR_GATE,
    VALID_RESULTS,
    RepairMemory,
    SafetyScore,
    compute_failure_signature,
    normalize_patch,
    patch_signature,
)
from infra.brain.debug.ci_autonomous_repair import (
    ApplyOutcome,
    PatchValidation,
    apply_patch_safely,
)
from infra.brain.debug import ci_autonomous_repair as repair


# ── Helpers ────────────────────────────────────────────────────────────────


def _entry(**overrides) -> dict:
    """Build a fully-populated record_attempt entry, override fields ad-hoc."""
    base = {
        "test_id": "t::case",
        "failure_signature": "abc123",
        "patch_diff": "--- a/x.py\n+++ b/x.py\n@@\n-1\n+2\n",
        "applied": True,
        "result": "passed",
        "stability_score": 1.0,
        "confidence_at_time": 0.9,
        "timestamp": "2026-05-05T00:00:00+00:00",
    }
    base.update(overrides)
    return base


# ════════════════════════════════════════════════════════════════════════════
#  1. Pure helpers
# ════════════════════════════════════════════════════════════════════════════


def test_failure_signature_is_deterministic_and_stable():
    a = compute_failure_signature("t::x", stage="tool", reason="x")
    b = compute_failure_signature("t::x", stage="tool", reason="x")
    assert a == b
    assert isinstance(a, str) and len(a) == 16  # 16 hex chars


def test_failure_signature_distinguishes_tests():
    sig_a = compute_failure_signature("t::a", stage="tool", reason="x")
    sig_b = compute_failure_signature("t::b", stage="tool", reason="x")
    assert sig_a != sig_b


def test_failure_signature_normalises_messages():
    """Paths, line numbers, and hex addresses must not perturb the signature."""
    sig_1 = compute_failure_signature(
        "t::x", error_message="error at /Users/me/proj/foo.py:42: 0xABCDEF",
    )
    sig_2 = compute_failure_signature(
        "t::x", error_message="error at /home/other/foo.py:99: 0xDEADBEEF",
    )
    assert sig_1 == sig_2


def test_normalize_patch_strips_line_numbers():
    p = "--- a/x.py\n+++ b/x.py\n@@ -42,3 +99,5 @@\n-old\n+new\n"
    n = normalize_patch(p)
    assert "@@ -X +Y @@" in n
    # Different line numbers, same logical patch → same hash
    p2 = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"
    assert patch_signature(p) == patch_signature(p2)


def test_normalize_patch_handles_empty_input():
    assert normalize_patch("") == ""
    assert patch_signature("") != patch_signature("nonempty")  # they differ


# ════════════════════════════════════════════════════════════════════════════
#  2. RepairMemory class
# ════════════════════════════════════════════════════════════════════════════


def test_record_attempt_validates_required_fields(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    with pytest.raises(ValueError, match="missing required fields"):
        mem.record_attempt({"test_id": "t::x"})  # almost everything missing


def test_record_attempt_validates_result_value(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    with pytest.raises(ValueError, match="result must be one of"):
        mem.record_attempt(_entry(result="exploded"))


def test_record_attempt_rejects_non_dict(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    with pytest.raises(TypeError):
        mem.record_attempt(["not", "a", "dict"])  # type: ignore[arg-type]


def test_record_attempt_appends_jsonl_creates_parent(tmp_path):
    p = tmp_path / "deep" / "nested" / "mem.jsonl"
    mem = RepairMemory(p)
    mem.record_attempt(_entry(failure_signature="aaa"))
    mem.record_attempt(_entry(failure_signature="bbb"))
    lines = p.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["failure_signature"] == "aaa"
    assert json.loads(lines[1])["failure_signature"] == "bbb"


def test_record_attempt_writes_summary_sidecar(tmp_path):
    """The summary JSON next to the JSONL is the dashboard fast path."""
    p = tmp_path / "mem.jsonl"
    mem = RepairMemory(p)
    mem.record_attempt(_entry(failure_signature="sig1", result="passed"))
    mem.record_attempt(_entry(failure_signature="sig1", result="failed"))
    summary = json.loads((tmp_path / "mem.summary.json").read_text())
    assert summary["total_attempts"] == 2
    assert summary["by_signature"]["sig1"]["passed"] == 1
    assert summary["by_signature"]["sig1"]["failed"] == 1


def test_query_similar_failures_returns_matches_only(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    mem.record_attempt(_entry(failure_signature="hit"))
    mem.record_attempt(_entry(failure_signature="miss"))
    mem.record_attempt(_entry(failure_signature="hit", result="failed"))
    rows = mem.query_similar_failures("hit")
    assert len(rows) == 2
    assert all(r["failure_signature"] == "hit" for r in rows)


def test_query_similar_failures_empty_when_file_absent(tmp_path):
    mem = RepairMemory(tmp_path / "absent.jsonl")
    assert mem.query_similar_failures("anything") == []


def test_query_tolerates_partial_write_at_tail(tmp_path):
    """JSONL is naturally crash-safe — the half-line at EOF must not crash queries."""
    p = tmp_path / "mem.jsonl"
    mem = RepairMemory(p)
    mem.record_attempt(_entry(failure_signature="sig"))
    # Append a torn line (simulates a crash mid-write).
    with p.open("a") as f:
        f.write('{"failure_signature": "sig", "incomplete_')
    rows = mem.query_similar_failures("sig")
    assert len(rows) == 1   # only the well-formed line is returned


# ── compute_safety_score: the heuristic itself ──────────────────────────────


def test_score_cold_start_returns_optimistic_with_flag(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    s = mem.compute_safety_score("never_seen", patch_diff="x")
    assert s["score"] == 1.0
    assert s["similar_cases"] == 0
    assert "no_prior_data" in s["risk_flags"]


def test_score_high_when_all_prior_passed(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    for _ in range(5):
        mem.record_attempt(_entry(failure_signature="sig", result="passed"))
    s = mem.compute_safety_score("sig", patch_diff="x")
    assert s["success_rate"] == 1.0
    assert s["score"] >= DEFAULT_THRESHOLD
    assert s["similar_cases"] == 5


def test_score_low_when_all_prior_failed(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    for _ in range(5):
        mem.record_attempt(_entry(failure_signature="sig", result="failed"))
    s = mem.compute_safety_score("sig", patch_diff="x")
    assert s["success_rate"] == 0.0
    assert s["score"] < DEFAULT_THRESHOLD


def test_score_flaky_history_drives_score_below_threshold(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    # 3 passed, 3 flaky → flakiness penalty kicks in
    for _ in range(3):
        mem.record_attempt(_entry(failure_signature="sig", result="passed"))
    for _ in range(3):
        mem.record_attempt(_entry(failure_signature="sig", result="flaky"))
    s = mem.compute_safety_score("sig", patch_diff="x")
    assert "flaky_history" in s["risk_flags"]
    assert s["score"] < s["success_rate"]   # penalty was applied


def test_score_mixed_outcomes_penalised(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    for _ in range(2):
        mem.record_attempt(_entry(failure_signature="sig", result="passed"))
    for _ in range(2):
        mem.record_attempt(_entry(failure_signature="sig", result="failed"))
    s = mem.compute_safety_score("sig", patch_diff="x")
    assert "mixed_outcomes" in s["risk_flags"]


def test_score_identical_patch_succeeded_before_bonus(tmp_path):
    """Same diff that worked before earns an extra bonus on top of success rate."""
    mem = RepairMemory(tmp_path / "mem.jsonl")
    diff = "--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"
    mem.record_attempt(_entry(failure_signature="sig", patch_diff=diff,
                              result="passed"))
    mem.record_attempt(_entry(failure_signature="sig", patch_diff=diff,
                              result="passed"))
    s = mem.compute_safety_score("sig", patch_diff=diff)
    assert "identical_patch_succeeded_before" in s["risk_flags"]


def test_score_never_applied_returns_optimistic(tmp_path):
    """Recording attempts that never applied (planner aborted, etc.)
    must not poison the score for future attempts."""
    mem = RepairMemory(tmp_path / "mem.jsonl")
    for _ in range(3):
        mem.record_attempt(_entry(
            failure_signature="sig", applied=False, result="failed",
            stability_score=0.0,
        ))
    s = mem.compute_safety_score("sig", patch_diff="x")
    assert s["score"] == 1.0
    assert "never_applied" in s["risk_flags"]


# ── should_block: the gate decision ────────────────────────────────────────


def test_should_block_cold_start_never_blocks(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    blocked, breakdown = mem.should_block("never_seen", patch_diff="x")
    assert blocked is False
    assert breakdown["similar_cases"] == 0


def test_should_block_below_min_cases_never_blocks(tmp_path):
    """Even a 100% failed history under the min-cases bar never blocks."""
    mem = RepairMemory(tmp_path / "mem.jsonl", min_cases_for_gate=5)
    for _ in range(2):
        mem.record_attempt(_entry(failure_signature="sig", result="failed"))
    blocked, breakdown = mem.should_block("sig", patch_diff="x")
    assert blocked is False
    assert breakdown["similar_cases"] == 2


def test_should_block_blocks_when_threshold_violated(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl", min_cases_for_gate=3)
    for _ in range(5):
        mem.record_attempt(_entry(failure_signature="sig", result="failed"))
    blocked, breakdown = mem.should_block(
        "sig", patch_diff="x", threshold=0.65,
    )
    assert blocked is True
    assert breakdown["score"] < 0.65


def test_should_block_allows_when_above_threshold(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl", min_cases_for_gate=3)
    for _ in range(5):
        mem.record_attempt(_entry(failure_signature="sig", result="passed"))
    blocked, breakdown = mem.should_block("sig", patch_diff="x")
    assert blocked is False
    assert breakdown["score"] >= DEFAULT_THRESHOLD


# ════════════════════════════════════════════════════════════════════════════
#  3. Integration with the existing apply / attempt pipeline
# ════════════════════════════════════════════════════════════════════════════


def _force_clean_repo(monkeypatch):
    monkeypatch.setattr(repair, "_repo_root",     lambda: Path("/tmp/fake-repo"))
    monkeypatch.setattr(repair, "_current_branch", lambda: "feature/x")
    monkeypatch.setattr(repair, "_working_tree_is_clean", lambda: True)
    monkeypatch.setattr(
        repair, "validate_patch",
        lambda *a, **kw: PatchValidation(
            applicable=True, files_referenced=("x.py",),
            files_missing=(), has_placeholders=False,
            git_check_output="",
        ),
    )


def test_apply_without_memory_is_unchanged(monkeypatch):
    """Pre-learning callers (no repair_memory= passed) see identical behaviour."""
    _force_clean_repo(monkeypatch)
    monkeypatch.setattr(repair, "_git", lambda *a, **kw: (0, "applied"))
    out = apply_patch_safely("p", fix_confidence=0.95)
    assert out.applied is True


def test_apply_with_memory_cold_start_does_not_block(monkeypatch, tmp_path, capsys):
    """A fresh, empty memory layer NEVER blocks an apply."""
    _force_clean_repo(monkeypatch)
    monkeypatch.setattr(repair, "_git", lambda *a, **kw: (0, "applied"))
    mem = RepairMemory(tmp_path / "mem.jsonl")
    out = apply_patch_safely(
        "p", fix_confidence=0.95,
        repair_memory=mem, failure_signature="sig",
    )
    assert out.applied is True
    # And the [CI-REPAIR-GUARD] line was emitted regardless
    captured = capsys.readouterr().out
    assert "[CI-REPAIR-GUARD]" in captured
    assert "decision: allowed" in captured


def test_apply_with_memory_blocks_when_history_is_bad(monkeypatch, tmp_path, capsys):
    _force_clean_repo(monkeypatch)
    monkeypatch.setattr(repair, "_git", lambda *a, **kw: (0, "applied"))
    mem = RepairMemory(tmp_path / "mem.jsonl", min_cases_for_gate=3)
    # Seed an unambiguously-bad history for the signature.
    for _ in range(5):
        mem.record_attempt(_entry(failure_signature="bad_sig", result="failed"))

    out = apply_patch_safely(
        "p", fix_confidence=0.95,
        repair_memory=mem, failure_signature="bad_sig",
        safety_threshold=0.65,
    )
    assert out.applied is False
    assert out.reason.startswith("repair_memory_blocked:")
    captured = capsys.readouterr().out
    assert "[CI-REPAIR-GUARD]" in captured
    assert "decision: blocked" in captured


def test_apply_with_memory_allows_when_history_is_good(monkeypatch, tmp_path):
    _force_clean_repo(monkeypatch)
    monkeypatch.setattr(repair, "_git", lambda *a, **kw: (0, "applied"))
    mem = RepairMemory(tmp_path / "mem.jsonl", min_cases_for_gate=3)
    # Seed 5 prior passes for good_sig, then 6 other-signature entries so
    # the loop-detection window (last 5) doesn't pull good_sig in and
    # falsely flag a loop.
    for _ in range(5):
        mem.record_attempt(_entry(failure_signature="good_sig", result="passed"))
    for _ in range(6):
        mem.record_attempt(_entry(failure_signature="other_sig", result="passed"))
    out = apply_patch_safely(
        "p", fix_confidence=0.95,
        repair_memory=mem, failure_signature="good_sig",
    )
    assert out.applied is True


def test_apply_swallows_memory_errors(monkeypatch, tmp_path, capsys):
    """A broken memory layer must NOT crash the apply pipeline.
    Defensive: if memory raises, we proceed with the apply."""
    _force_clean_repo(monkeypatch)
    monkeypatch.setattr(repair, "_git", lambda *a, **kw: (0, "applied"))

    class _ExplodingMemory:
        min_cases_for_gate = 3
        def should_block(self, *a, **kw):
            raise RuntimeError("memory boom")

    out = apply_patch_safely(
        "p", fix_confidence=0.95,
        repair_memory=_ExplodingMemory(), failure_signature="sig",
    )
    assert out.applied is True
    captured = capsys.readouterr().out
    assert "[CI-REPAIR-GUARD]" in captured
    # The flag mentions the memory error
    assert "memory_error:RuntimeError" in captured


def test_attempt_repair_records_outcome_to_memory(monkeypatch, tmp_path):
    """After a repair attempt, the memory must contain a corresponding entry."""
    monkeypatch.setattr(
        repair, "rerun_test",
        lambda *a, **kw: repair.RerunOutcome(
            test_node_id="x::y", passed=False, duration_ms=1.0,
            return_code=1, output_tail="",
        ),
    )
    mem_path = tmp_path / "mem.jsonl"
    mem = RepairMemory(mem_path)

    fix = {"stage": "tool", "fix_type": "config",
           "patch": "--- a/<x>\n+++ b/<x>\n@@\n", "confidence": 0.95,
           "risk_level": "low", "root_cause": "", "explanation": ""}
    analysis = {"stage": "tool", "reason": "tool_runtime_error",
                "summary": "x", "event_trace": [], "recommendation": "x"}

    repair.attempt_repair(
        "infra/brain/tests/test_x.py::test_y",
        analysis, fix,
        apply_patch=False,    # dry run — placeholders make the patch unapplicable anyway
        repair_memory=mem,
    )

    # The memory got one entry, and it carries the fields the spec promises.
    rows = [json.loads(line) for line in mem_path.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    rec = rows[0]
    for required in RepairMemory.REQUIRED_FIELDS:
        assert required in rec, f"missing required field {required!r}"
    assert rec["test_id"] == "infra/brain/tests/test_x.py::test_y"
    assert rec["applied"] is False
    assert rec["result"] in VALID_RESULTS


def test_attempt_repair_records_passed_when_stable(monkeypatch, tmp_path):
    """A truly successful repair (apply + stable runs) records ``result='passed'``."""
    monkeypatch.setattr(
        repair, "rerun_test",
        lambda *a, **kw: repair.RerunOutcome(
            test_node_id="x::y", passed=False, duration_ms=1.0,
            return_code=1, output_tail="",
        ),
    )
    monkeypatch.setattr(
        repair, "validate_patch",
        lambda *a, **kw: PatchValidation(
            applicable=True, files_referenced=("infra/brain/x.py",),
            files_missing=(), has_placeholders=False, git_check_output="",
        ),
    )
    monkeypatch.setattr(
        repair, "apply_patch_safely",
        lambda *a, **kw: ApplyOutcome(
            applied=True, reason="applied", git_output="",
            branch="feature/x", pre_apply_clean=True,
        ),
    )

    def _passing_outcome():
        return repair.RerunOutcome(
            test_node_id="x::y", passed=True, duration_ms=1.0,
            return_code=0, output_tail="",
        )

    monkeypatch.setattr(
        repair, "confirm_stability",
        lambda *a, **kw: repair.StabilityReport(
            test_node_id="x::y",
            runs=(_passing_outcome(), _passing_outcome(), _passing_outcome()),
        ),
    )
    monkeypatch.setattr(repair, "_git", lambda *a, **kw: (0, ""))

    mem = RepairMemory(tmp_path / "mem.jsonl")
    fix = {"stage": "tool", "patch": "p", "confidence": 0.95,
           "risk_level": "low", "fix_type": "config",
           "root_cause": "", "explanation": ""}
    analysis = {"stage": "tool", "reason": "tool_runtime_error",
                "summary": "", "event_trace": [], "recommendation": ""}
    repair.attempt_repair(
        "x::y", analysis, fix,
        apply_patch=True, repair_memory=mem,
    )
    rows = [json.loads(line) for line in
            (tmp_path / "mem.jsonl").read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["applied"] is True
    assert rows[0]["result"] == "passed"
    assert rows[0]["stability_score"] == 1.0


# ── End-to-end: feedback loop tightens future decisions ───────────────────


def test_feedback_loop_eventually_blocks_repeatedly_failing_repairs(tmp_path, monkeypatch):
    """After enough recorded failures for a signature, a NEW apply attempt
    against the same signature must be blocked by the memory gate."""
    _force_clean_repo(monkeypatch)
    monkeypatch.setattr(repair, "_git", lambda *a, **kw: (0, "applied"))

    mem = RepairMemory(tmp_path / "mem.jsonl", min_cases_for_gate=3)

    # Simulate three prior failed attempts for the same signature.
    for _ in range(3):
        mem.record_attempt(_entry(failure_signature="trouble", result="failed"))

    # The fourth apply MUST now be blocked by the gate.
    out = apply_patch_safely(
        "p", fix_confidence=0.95,
        repair_memory=mem, failure_signature="trouble",
    )
    assert out.applied is False
    assert out.reason.startswith("repair_memory_blocked:")
