"""Tests for the adaptive layer + multi-fix generation.

Covers the additions on top of ``test_repair_memory.py`` and
``test_repair_learning.py``:

  * Dynamic threshold raises / lowers based on the recent window.
  * RISK_PROFILES penalty pulls scores down per-category.
  * Per-fix-pattern reputation bonus / penalty.
  * Anti-loop detection blocks even at cold start.
  * compute_final_score returns the full adaptive breakdown.
  * should_block_adaptive: loop > cold start > final-score gate.
  * current_mode() classifies the threshold position.
  * intelligence_summary + print_intelligence_summary line format.
  * suggest_multiple_fixes returns ≥ 2 candidates with type tags.
  * rank_fixes orders by adaptive score.
  * select_best_fix picks the top-ranked entry.
  * The new multi-line ``[CI-REPAIR-DECISION]`` audit format.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from infra.brain.debug import ci_autonomous_repair as repair
from infra.brain.debug.ci_autonomous_repair import (
    PatchValidation,
    apply_patch_safely,
)
from infra.brain.debug.ci_auto_fix import (
    rank_fixes,
    select_best_fix,
    suggest_fix,
    suggest_multiple_fixes,
)
from infra.brain.learning import (
    CATEGORY_EXECUTOR_TOOL,
    CATEGORY_PLANNER,
    CATEGORY_TELEMETRY,
    CATEGORY_UNKNOWN,
    DEFAULT_THRESHOLD,
    FIX_GUARDRAIL,
    FIX_VALIDATION,
    LOOP_PENALTY,
    LOOP_THRESHOLD,
    LOOP_WINDOW,
    REPUTATION_BONUS,
    REPUTATION_PENALTY,
    RISK_PROFILES,
    THRESHOLD_LOWER,
    THRESHOLD_RAISE,
    RepairMemory,
)


def _entry(**overrides) -> dict:
    base = {
        "test_id": "t::case",
        "failure_signature": "sig",
        "failure_category": CATEGORY_EXECUTOR_TOOL,
        "fix_pattern": FIX_GUARDRAIL,
        "patch_diff": "p",
        "applied": True,
        "result": "passed",
        "stability_score": 1.0,
        "confidence_at_time": 0.9,
        "timestamp": "2026-05-05T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _seed(mem: RepairMemory, n: int, **overrides) -> None:
    for _ in range(n):
        mem.record_attempt(_entry(**overrides))


# ════════════════════════════════════════════════════════════════════════════
#  1. Dynamic threshold
# ════════════════════════════════════════════════════════════════════════════


def test_dynamic_threshold_default_when_no_history(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    assert mem.compute_dynamic_threshold() == DEFAULT_THRESHOLD


def test_dynamic_threshold_raises_when_recent_failures_dominate(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    # 6 of 10 recent attempts failed → fail_rate ≥ 0.5 → raise threshold
    _seed(mem, 4, result="passed")
    _seed(mem, 6, result="failed")
    expected = DEFAULT_THRESHOLD + THRESHOLD_RAISE
    assert mem.compute_dynamic_threshold() == pytest.approx(expected)


def test_dynamic_threshold_lowers_when_history_is_clean(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    # 10 of 10 passed → fail_rate = 0 → lower threshold
    _seed(mem, 10, result="passed")
    expected = DEFAULT_THRESHOLD - THRESHOLD_LOWER
    assert mem.compute_dynamic_threshold() == pytest.approx(expected)


def test_dynamic_threshold_uses_last_10_only(tmp_path):
    """Even with hundreds of historical failures, only the last 10 matter."""
    mem = RepairMemory(tmp_path / "mem.jsonl")
    _seed(mem, 100, result="failed")        # ancient history: bad
    _seed(mem, 10,  result="passed")         # recent: clean
    expected = DEFAULT_THRESHOLD - THRESHOLD_LOWER
    assert mem.compute_dynamic_threshold() == pytest.approx(expected)


# ════════════════════════════════════════════════════════════════════════════
#  2. Risk profiles
# ════════════════════════════════════════════════════════════════════════════


def test_risk_profiles_present_for_every_category():
    for cat in (
        "planner_error", "executor_tool_error", "telemetry_failure",
        "validation_failure", "unknown_runtime_error",
    ):
        assert cat in RISK_PROFILES
        assert 0.0 <= RISK_PROFILES[cat] <= 1.0


def test_final_score_applies_category_risk_penalty(tmp_path):
    """A high success rate is dragged down by the category's risk prior."""
    mem = RepairMemory(tmp_path / "mem.jsonl")
    # 5 passes — clean record. Spread their signatures so loop doesn't fire.
    for i in range(5):
        mem.record_attempt(_entry(failure_signature=f"sig_{i}",
                                  failure_category=CATEGORY_TELEMETRY,
                                  result="passed"))
    # Telemetry has the smallest risk penalty (0.1).
    s_tel = mem.compute_final_score(
        "sig_0", patch_diff="p", failure_category=CATEGORY_TELEMETRY,
    )
    s_unk = mem.compute_final_score(
        "sig_0", patch_diff="p", failure_category=CATEGORY_UNKNOWN,
    )
    # Same data, different category → different score
    assert s_tel["risk_profile_penalty"] == RISK_PROFILES[CATEGORY_TELEMETRY]
    assert s_unk["risk_profile_penalty"] == RISK_PROFILES[CATEGORY_UNKNOWN]
    assert s_tel["final_score"] > s_unk["final_score"]


# ════════════════════════════════════════════════════════════════════════════
#  3. Fix-pattern reputation
# ════════════════════════════════════════════════════════════════════════════


def test_reputation_bonus_for_high_success_rate(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    # 5 passed, 0 failed for FIX_VALIDATION → success_rate 1.0 ≥ 0.8 → bonus
    for i in range(5):
        mem.record_attempt(_entry(failure_signature=f"sig_{i}",
                                  fix_pattern=FIX_VALIDATION,
                                  result="passed"))
    assert mem.get_fix_reputation(FIX_VALIDATION) == REPUTATION_BONUS


def test_reputation_penalty_for_low_success_rate(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    # 1 passed, 9 failed for FIX_GUARDRAIL → success_rate 0.1 ≤ 0.4 → penalty
    for i in range(9):
        mem.record_attempt(_entry(failure_signature=f"sig_{i}",
                                  fix_pattern=FIX_GUARDRAIL,
                                  result="failed"))
    mem.record_attempt(_entry(failure_signature="sig_pass",
                              fix_pattern=FIX_GUARDRAIL,
                              result="passed"))
    assert mem.get_fix_reputation(FIX_GUARDRAIL) == -REPUTATION_PENALTY


def test_reputation_neutral_on_thin_data(tmp_path):
    """Below MIN_SAMPLES (3) the reputation is exactly 0.0."""
    mem = RepairMemory(tmp_path / "mem.jsonl")
    mem.record_attempt(_entry(fix_pattern=FIX_VALIDATION, result="passed"))
    assert mem.get_fix_reputation(FIX_VALIDATION) == 0.0


# ════════════════════════════════════════════════════════════════════════════
#  4. Anti-loop detection
# ════════════════════════════════════════════════════════════════════════════


def test_detect_loop_when_signature_repeats(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    # 3 of last 5 share the same signature
    mem.record_attempt(_entry(failure_signature="loop"))
    mem.record_attempt(_entry(failure_signature="loop"))
    mem.record_attempt(_entry(failure_signature="other"))
    mem.record_attempt(_entry(failure_signature="loop"))
    mem.record_attempt(_entry(failure_signature="other"))
    assert mem.detect_loop("loop") is True
    assert mem.detect_loop("other") is False


def test_should_block_adaptive_blocks_loops_even_at_cold_start(monkeypatch, tmp_path):
    """Loop detection must override the cold-start carve-out."""
    mem = RepairMemory(tmp_path / "mem.jsonl", min_cases_for_gate=10)
    # Even though we're below min_cases_for_gate, three same-signature
    # entries in the recent window must block.
    for _ in range(3):
        mem.record_attempt(_entry(failure_signature="trouble"))

    blocked, breakdown = mem.should_block_adaptive(
        "trouble", patch_diff="p",
        failure_category=CATEGORY_EXECUTOR_TOOL,
    )
    assert blocked is True
    assert breakdown["loop_detected"] is True
    assert breakdown["loop_penalty"] == LOOP_PENALTY


# ════════════════════════════════════════════════════════════════════════════
#  5. Final score & confidence recalibration
# ════════════════════════════════════════════════════════════════════════════


def test_final_score_clamped_to_unit_interval(tmp_path):
    """Pathological inputs must still produce 0 ≤ score ≤ 1."""
    mem = RepairMemory(tmp_path / "mem.jsonl")
    # Stuff the memory with all-flaky entries → flakiness penalty + risk
    # penalty + (no loop) sums below zero pre-clamp.
    for i in range(5):
        mem.record_attempt(_entry(failure_signature=f"sig_{i}",
                                  failure_category=CATEGORY_UNKNOWN,
                                  result="flaky"))
    s = mem.compute_final_score(
        "sig_0", patch_diff="p", failure_category=CATEGORY_UNKNOWN,
    )
    assert 0.0 <= s["final_score"] <= 1.0


def test_final_score_recalibrates_confidence(tmp_path):
    """final_confidence = fix_confidence * 0.5 + success_rate * 0.5."""
    mem = RepairMemory(tmp_path / "mem.jsonl")
    for i in range(5):
        mem.record_attempt(_entry(failure_signature=f"sig_{i}", result="passed"))
    s = mem.compute_final_score(
        "sig_0", patch_diff="p",
        failure_category=CATEGORY_EXECUTOR_TOOL,
        fix_confidence=0.6,
    )
    # success_rate should be 1.0 (5/5 passed) → 0.6*0.5 + 1.0*0.5 = 0.8
    assert s["final_confidence"] == pytest.approx(0.8)


def test_final_score_returns_no_calibration_when_confidence_omitted(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    s = mem.compute_final_score("sig", patch_diff="p")
    assert s["final_confidence"] is None


# ════════════════════════════════════════════════════════════════════════════
#  6. System modes
# ════════════════════════════════════════════════════════════════════════════


def test_current_mode_is_balanced_at_cold_start(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    assert mem.current_mode() == "balanced"


def test_current_mode_conservative_when_failures_dominate(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    _seed(mem, 4, result="passed")
    _seed(mem, 6, result="failed")
    assert mem.current_mode() == "conservative"


def test_current_mode_aggressive_when_history_is_clean(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    _seed(mem, 10, result="passed")
    assert mem.current_mode() == "aggressive"


# ════════════════════════════════════════════════════════════════════════════
#  7. Intelligence summary
# ════════════════════════════════════════════════════════════════════════════


def test_intelligence_summary_includes_all_required_fields(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    _seed(mem, 3, result="passed")
    summary = mem.intelligence_summary()
    for key in (
        "total_attempts", "successful_repairs", "blocked_repairs",
        "loop_preventions", "top_fix_pattern", "worst_failure_type",
        "current_threshold", "mode",
    ):
        assert key in summary, f"missing {key!r}"


def test_print_intelligence_summary_contains_required_lines(tmp_path, capsys):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    _seed(mem, 3, result="passed")
    mem.print_intelligence_summary()
    out = capsys.readouterr().out
    # Banner present
    assert "[CI-INTELLIGENCE-SUMMARY]" in out
    # Both canonical and short-alias field names emitted
    for required in (
        "total_attempts:", "attempts:",
        "successful_repairs:", "success:",
        "blocked_repairs:", "blocked:",
        "loop_preventions:", "loops_prevented:",
        "top_fix_pattern:", "top_fix:",
        "worst_failure_type:", "worst_failure:",
        "current_threshold:", "mode:",
    ):
        assert required in out, f"summary missing {required!r}"


# ════════════════════════════════════════════════════════════════════════════
#  8. Multi-fix generation + ranking
# ════════════════════════════════════════════════════════════════════════════


def test_suggest_multiple_fixes_returns_at_least_two_candidates():
    analysis = {"stage": "tool", "reason": "tool_runtime_error",
                "summary": "x", "event_trace": [], "recommendation": "x"}
    fixes = suggest_multiple_fixes(analysis)
    assert isinstance(fixes, list)
    assert len(fixes) >= 2
    # Every candidate carries a type tag matching the learning taxonomy
    for f in fixes:
        assert "type" in f
        assert f["type"] in {
            "validation_fix", "guardrail_fix", "null_safety_fix",
            "timeout_fix", "parsing_fix", "retry_fix", "unclassified_fix",
        }


def test_suggest_multiple_fixes_first_entry_is_primary_suggest_fix():
    analysis = {"stage": "tool", "reason": "tool_runtime_error",
                "summary": "x", "event_trace": [], "recommendation": "x"}
    fixes = suggest_multiple_fixes(analysis)
    primary = fixes[0]
    direct = suggest_fix(analysis)
    # Same stage / fix_type / patch
    assert primary["stage"] == direct["stage"]
    assert primary["fix_type"] == direct["fix_type"]
    assert primary["patch"] == direct["patch"]


def test_suggest_multiple_fixes_dedups_when_primary_equals_fallback():
    """If the primary's type already matches a generic fallback, the
    fallback is dropped — no near-duplicates returned."""
    analysis = {"stage": "tool", "reason": "tool_runtime_error",
                "summary": "x", "event_trace": [], "recommendation": "x"}
    fixes = suggest_multiple_fixes(analysis)
    types = [f.get("type") for f in fixes]
    assert len(types) == len(set(types)), f"duplicate types in: {types}"


def test_rank_fixes_orders_by_adaptive_score(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    # Seed reputation: validation_fix has been passing; guardrail_fix has
    # been failing.
    for i in range(5):
        mem.record_attempt(_entry(failure_signature=f"sig_{i}",
                                  fix_pattern=FIX_VALIDATION, result="passed"))
    for i in range(5, 10):
        mem.record_attempt(_entry(failure_signature=f"sig_{i}",
                                  fix_pattern=FIX_GUARDRAIL, result="failed"))

    fixes = [
        {"patch": "g", "confidence": 0.9, "type": "guardrail_fix"},
        {"patch": "v", "confidence": 0.5, "type": "validation_fix"},
    ]
    ranked = rank_fixes(
        fixes, repair_memory=mem,
        failure_signature="sig_x", failure_category=CATEGORY_EXECUTOR_TOOL,
    )
    # Even though guardrail had higher raw confidence, validation's
    # reputation bonus + guardrail's reputation penalty should flip them.
    assert ranked[0]["type"] == "validation_fix"


def test_rank_fixes_attaches_rank_score_field():
    fixes = [
        {"patch": "p1", "confidence": 0.9, "type": "validation_fix"},
        {"patch": "p2", "confidence": 0.5, "type": "guardrail_fix"},
    ]
    ranked = rank_fixes(fixes)  # no memory → falls back to confidence
    for f in ranked:
        assert "rank_score" in f
    # Ordering by confidence
    assert ranked[0]["confidence"] >= ranked[1]["confidence"]


def test_select_best_fix_returns_top_or_none():
    assert select_best_fix([]) is None
    fixes = [
        {"patch": "a", "confidence": 0.4, "type": "validation_fix"},
        {"patch": "b", "confidence": 0.9, "type": "guardrail_fix"},
    ]
    best = select_best_fix(fixes)
    assert best is not None
    assert best["confidence"] == 0.9


# ════════════════════════════════════════════════════════════════════════════
#  9. Audit log: new multi-line [CI-REPAIR-DECISION] format
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


def test_audit_log_emits_full_multi_line_format(monkeypatch, tmp_path, capsys):
    _force_clean_repo(monkeypatch)
    monkeypatch.setattr(repair, "_git", lambda *a, **kw: (0, "applied"))
    mem = RepairMemory(tmp_path / "mem.jsonl")

    apply_patch_safely(
        "p", fix_confidence=0.95,
        repair_memory=mem,
        failure_signature="sig_x",
        failure_category=CATEGORY_EXECUTOR_TOOL,
    )
    out = capsys.readouterr().out
    # Both formats present (legacy single-line + new multi-line block)
    assert "[CI-REPAIR-GUARD]" in out
    assert "[CI-REPAIR-DECISION]" in out

    # Every required field appears as its own line in the new block
    for line in (
        "decision:",
        "selected_fix:",
        "final_score:",
        "threshold:",
        "failure_category:",
        "fix_pattern:",
        "success_rate:",
        "fix_reputation:",
        "loop_detected:",
        "reason:",
    ):
        assert line in out, f"audit log missing {line!r}"


def test_audit_log_loop_detected_flag_renders_correctly(monkeypatch, tmp_path, capsys):
    _force_clean_repo(monkeypatch)
    monkeypatch.setattr(repair, "_git", lambda *a, **kw: (0, "applied"))
    mem = RepairMemory(tmp_path / "mem.jsonl", min_cases_for_gate=3)
    # Build a loop: same signature 3+ times in last 5
    for _ in range(3):
        mem.record_attempt(_entry(failure_signature="loop_sig", result="failed"))
    out = apply_patch_safely(
        "p", fix_confidence=0.95,
        repair_memory=mem,
        failure_signature="loop_sig",
        failure_category=CATEGORY_EXECUTOR_TOOL,
    )
    captured = capsys.readouterr().out
    assert out.applied is False
    assert "loop_detected: true" in captured
    assert "decision: blocked" in captured
