"""Tests for the extended self-improving repair-memory layer.

Covers the additions on top of ``test_repair_memory.py``:

  * ``derive_failure_category`` — classifies stage/reason into the
    five canonical categories.
  * ``classify_fix_pattern``    — heuristic patch-intent classifier.
  * Category-aware similarity   — entries from the same category match
    even when their failure_signature differs.
  * Regression penalty          — same patch went pass → fail.
  * ``flakiness`` and ``match_count`` fields in the safety-score dict.
  * ``[CI-REPAIR-DECISION]`` audit log line.
  * Auto-derivation of optional fields in ``record_attempt``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from infra.brain.debug import ci_autonomous_repair as repair
from infra.brain.debug.ci_autonomous_repair import (
    ApplyOutcome,
    PatchValidation,
    apply_patch_safely,
)
from infra.brain.learning import (
    CATEGORY_EXECUTOR_TOOL,
    CATEGORY_PLANNER,
    CATEGORY_TELEMETRY,
    CATEGORY_UNKNOWN,
    CATEGORY_VALIDATION,
    DEFAULT_THRESHOLD,
    FIX_GUARDRAIL,
    FIX_NULL_SAFETY,
    FIX_PARSING,
    FIX_RETRY,
    FIX_TIMEOUT,
    FIX_UNCLASSIFIED,
    FIX_VALIDATION,
    RepairMemory,
    classify_fix_pattern,
    derive_failure_category,
)


# ── derive_failure_category ────────────────────────────────────────────────


@pytest.mark.parametrize("stage,reason,expected", [
    ("planner",   "planner_did_not_start",   CATEGORY_PLANNER),
    ("planner",   "any",                     CATEGORY_PLANNER),
    ("",          "planning_failed",         CATEGORY_PLANNER),
    ("telemetry", "duplicate_brackets",      CATEGORY_TELEMETRY),
    ("",          "telemetry_event_missing", CATEGORY_TELEMETRY),
    ("tool",      "tool_runtime_error",      CATEGORY_EXECUTOR_TOOL),
    ("executor",  "step_error",              CATEGORY_EXECUTOR_TOOL),
    ("",          "tool_permission_denied",  CATEGORY_EXECUTOR_TOOL),
    # "invalid_plan" lives in the planner bucket — it's a planner-domain
    # failure even though it sounds like a validation error. Validation
    # routing requires a more specific signal (error_type or reason
    # without "plan"/"telemetry"/"tool").
    ("",          "invalid_plan",            CATEGORY_PLANNER),
    ("",          "schema_violation",        CATEGORY_VALIDATION),
    ("",          "unrecognised",            CATEGORY_UNKNOWN),
    ("",          "",                        CATEGORY_UNKNOWN),
])
def test_derive_failure_category_covers_all_buckets(stage, reason, expected):
    assert derive_failure_category(stage=stage, reason=reason) == expected


def test_derive_failure_category_uses_error_type_for_validation():
    assert derive_failure_category(error_type="ValueError") == CATEGORY_VALIDATION
    assert derive_failure_category(error_type="TypeError") == CATEGORY_VALIDATION


def test_derive_failure_category_is_deterministic():
    a = derive_failure_category(stage="tool", reason="x", error_type="RuntimeError")
    b = derive_failure_category(stage="tool", reason="x", error_type="RuntimeError")
    assert a == b


# ── classify_fix_pattern ───────────────────────────────────────────────────


def _diff(added_lines: list[str]) -> str:
    """Build a minimal patch where the given lines are additions."""
    return "--- a/x.py\n+++ b/x.py\n@@\n" + "\n".join(
        f"+{ln}" for ln in added_lines
    ) + "\n"


def test_classify_fix_pattern_timeout():
    p = _diff(["asyncio.wait_for(coro, timeout=5)"])
    assert classify_fix_pattern(p) == FIX_TIMEOUT


def test_classify_fix_pattern_retry():
    p = _diff(["for _ in range(max_attempts):  retry"])
    assert classify_fix_pattern(p) == FIX_RETRY


def test_classify_fix_pattern_null_safety():
    p = _diff(["if value is None: return"])
    assert classify_fix_pattern(p) == FIX_NULL_SAFETY


def test_classify_fix_pattern_parsing():
    p = _diff(["data = json.loads(text)"])
    assert classify_fix_pattern(p) == FIX_PARSING


def test_classify_fix_pattern_validation():
    p = _diff(["if not isinstance(x, dict):  raise ValueError"])
    assert classify_fix_pattern(p) == FIX_VALIDATION


def test_classify_fix_pattern_guardrail():
    p = _diff(["try:", "    do_thing()", "except Exception:"])
    assert classify_fix_pattern(p) == FIX_GUARDRAIL


def test_classify_fix_pattern_unclassified_for_random_diff():
    p = _diff(["some_var = some_var + 1"])
    assert classify_fix_pattern(p) == FIX_UNCLASSIFIED


def test_classify_fix_pattern_ignores_removed_lines():
    """Only added (+) lines drive the classification; removed (-) lines must
    not pollute the signal even when they contain matching keywords."""
    p = (
        "--- a/x.py\n+++ b/x.py\n@@\n"
        "-import json\n"      # removed: contains 'json' but should be ignored
        "+x = 1\n"            # added: nothing matches → unclassified
    )
    assert classify_fix_pattern(p) == FIX_UNCLASSIFIED


def test_classify_fix_pattern_empty_input():
    assert classify_fix_pattern("") == FIX_UNCLASSIFIED
    assert classify_fix_pattern(None) == FIX_UNCLASSIFIED  # type: ignore[arg-type]


# ── compute_safety_score: new fields (flakiness, match_count) ──────────────


def _record(mem, **overrides):
    """Append a fully-populated entry, override fields ad-hoc."""
    entry = {
        "test_id": "t::case",
        "failure_signature": "sig_x",
        "failure_category": CATEGORY_EXECUTOR_TOOL,
        "fix_pattern": FIX_GUARDRAIL,
        "patch_diff": "p",
        "applied": True,
        "result": "passed",
        "stability_score": 1.0,
        "confidence_at_time": 0.9,
        "timestamp": "2026-05-05T00:00:00+00:00",
    }
    entry.update(overrides)
    mem.record_attempt(entry)


def test_safety_score_returns_flakiness_as_float(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    for _ in range(2):
        _record(mem, result="passed")
    for _ in range(2):
        _record(mem, result="flaky")
    s = mem.compute_safety_score("sig_x", patch_diff="p")
    assert "flakiness" in s
    assert isinstance(s["flakiness"], float)
    assert s["flakiness"] == pytest.approx(0.5)  # 2 flaky / 4 applied


def test_safety_score_returns_match_count_field(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    for _ in range(4):
        _record(mem, result="passed")
    s = mem.compute_safety_score("sig_x", patch_diff="p")
    assert s["match_count"] == 4
    # Backwards-compat alias is preserved
    assert s["similar_cases"] == 4


def test_safety_score_cold_start_has_zero_flakiness(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    s = mem.compute_safety_score("never_seen", patch_diff="p")
    assert s["flakiness"] == 0.0
    assert s["match_count"] == 0


# ── Category-aware similarity ─────────────────────────────────────────────


def test_query_similar_failures_includes_category_matches(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    # Different signatures, same category.
    _record(mem, failure_signature="sig_a", failure_category=CATEGORY_PLANNER)
    _record(mem, failure_signature="sig_b", failure_category=CATEGORY_PLANNER)
    _record(mem, failure_signature="sig_c", failure_category=CATEGORY_TELEMETRY)

    by_sig_only = mem.query_similar_failures("sig_a")
    by_sig_or_cat = mem.query_similar_failures(
        "sig_a", failure_category=CATEGORY_PLANNER,
    )
    assert len(by_sig_only) == 1
    # Two entries match the planner category; one entry also matches the sig.
    assert len(by_sig_or_cat) == 2
    assert all(r["failure_category"] == CATEGORY_PLANNER for r in by_sig_or_cat)


def test_query_similar_failures_dedups_signature_and_category_overlap(tmp_path):
    """An entry that matches BOTH sig and category must not be counted twice."""
    mem = RepairMemory(tmp_path / "mem.jsonl")
    _record(mem, failure_signature="sig_x", failure_category=CATEGORY_PLANNER)
    rows = mem.query_similar_failures("sig_x", failure_category=CATEGORY_PLANNER)
    assert len(rows) == 1


def test_safety_score_uses_category_matches_when_signature_is_unique(tmp_path):
    """A first-time signature should still get a learned score from the
    category bucket — that's the whole point of category-based similarity."""
    mem = RepairMemory(tmp_path / "mem.jsonl", min_cases_for_gate=3)
    # Seed three FAILED attempts in the same category but different sigs.
    for i in range(3):
        _record(mem, failure_signature=f"sig_{i}",
                failure_category=CATEGORY_PLANNER, result="failed")
    # New signature, never seen before, but same category.
    s = mem.compute_safety_score(
        "brand_new_sig", patch_diff="p",
        failure_category=CATEGORY_PLANNER,
    )
    assert s["match_count"] == 3
    assert s["score"] < DEFAULT_THRESHOLD


# ── Regression penalty: same patch went pass → fail ────────────────────────


def test_regression_penalty_applied_when_patch_pass_then_fail(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    diff = _diff(["x = 1"])
    # Earlier — same patch passed
    _record(mem, patch_diff=diff, result="passed",
            timestamp="2026-01-01T00:00:00+00:00")
    # Later — same patch failed  → regression
    _record(mem, patch_diff=diff, result="failed",
            timestamp="2026-02-01T00:00:00+00:00")

    s = mem.compute_safety_score("sig_x", patch_diff=diff)
    assert "regression_seen" in s["risk_flags"]
    # The regression penalty knocks the score below what success_rate alone
    # would suggest.
    assert s["score"] < s["success_rate"]


def test_no_regression_penalty_for_consistently_passing_patch(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    diff = _diff(["y = 2"])
    for ts in ("2026-01-01T00:00:00+00:00",
               "2026-02-01T00:00:00+00:00",
               "2026-03-01T00:00:00+00:00"):
        _record(mem, patch_diff=diff, result="passed", timestamp=ts)

    s = mem.compute_safety_score("sig_x", patch_diff=diff)
    assert "regression_seen" not in s["risk_flags"]


def test_no_regression_penalty_for_consistently_failing_patch(tmp_path):
    """A patch that ALWAYS failed is bad, but it's not a regression — it
    never worked in the first place."""
    mem = RepairMemory(tmp_path / "mem.jsonl")
    diff = _diff(["z = 3"])
    for ts in ("2026-01-01T00:00:00+00:00",
               "2026-02-01T00:00:00+00:00"):
        _record(mem, patch_diff=diff, result="failed", timestamp=ts)
    s = mem.compute_safety_score("sig_x", patch_diff=diff)
    assert "regression_seen" not in s["risk_flags"]


def test_flaky_after_pass_counts_as_regression(tmp_path):
    """A pass followed by flaky outcomes is a regression — flaky is not
    a stable fix."""
    mem = RepairMemory(tmp_path / "mem.jsonl")
    diff = _diff(["a = 4"])
    _record(mem, patch_diff=diff, result="passed",
            timestamp="2026-01-01T00:00:00+00:00")
    _record(mem, patch_diff=diff, result="flaky",
            timestamp="2026-02-01T00:00:00+00:00")
    s = mem.compute_safety_score("sig_x", patch_diff=diff)
    assert "regression_seen" in s["risk_flags"]


# ── Auto-derivation of optional fields ─────────────────────────────────────


def test_record_attempt_auto_derives_failure_category(tmp_path):
    """Old fixtures that don't supply failure_category must still work —
    the missing column is filled with the unknown bucket."""
    mem = RepairMemory(tmp_path / "mem.jsonl")
    legacy = {
        "test_id": "t::x",
        "failure_signature": "sig",
        "patch_diff": "p",
        "applied": True,
        "result": "passed",
        "stability_score": 1.0,
        "confidence_at_time": 0.9,
        "timestamp": "2026-05-05T00:00:00+00:00",
    }
    mem.record_attempt(legacy)
    written = json.loads((tmp_path / "mem.jsonl").read_text().strip())
    assert written["failure_category"] == CATEGORY_UNKNOWN
    # fix_pattern auto-classified
    assert written["fix_pattern"] in {
        FIX_VALIDATION, FIX_NULL_SAFETY, FIX_TIMEOUT, FIX_PARSING,
        FIX_RETRY, FIX_GUARDRAIL, FIX_UNCLASSIFIED,
    }


def test_record_attempt_classifies_fix_pattern_from_patch(tmp_path):
    mem = RepairMemory(tmp_path / "mem.jsonl")
    p = _diff(["asyncio.wait_for(coro, timeout=5)"])
    mem.record_attempt({
        "test_id": "t::x",
        "failure_signature": "sig",
        "patch_diff": p,
        "applied": True,
        "result": "passed",
        "stability_score": 1.0,
        "confidence_at_time": 0.9,
        "timestamp": "2026-05-05T00:00:00+00:00",
    })
    written = json.loads((tmp_path / "mem.jsonl").read_text().strip())
    assert written["fix_pattern"] == FIX_TIMEOUT


# ── New audit-log format ───────────────────────────────────────────────────


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


def test_audit_log_emits_new_decision_format(monkeypatch, tmp_path, capsys):
    _force_clean_repo(monkeypatch)
    monkeypatch.setattr(repair, "_git", lambda *a, **kw: (0, "applied"))
    mem = RepairMemory(tmp_path / "mem.jsonl")
    apply_patch_safely(
        "p", fix_confidence=0.95,
        repair_memory=mem, failure_signature="sig", failure_category=CATEGORY_EXECUTOR_TOOL,
    )
    out = capsys.readouterr().out
    # Both formats are present (legacy kept for backwards compat).
    assert "[CI-REPAIR-GUARD]" in out
    assert "[CI-REPAIR-DECISION]" in out
    # New format carries the richer breakdown
    assert "score:" in out
    assert "success_rate:" in out
    assert "flakiness:" in out
    assert "match_count:" in out
    assert "failure_category:" in out
    assert "reason:" in out


def test_audit_log_blocks_with_reason_explanation(monkeypatch, tmp_path, capsys):
    """A blocking decision must explain the WHY in human-readable terms."""
    _force_clean_repo(monkeypatch)
    monkeypatch.setattr(repair, "_git", lambda *a, **kw: (0, "applied"))
    mem = RepairMemory(tmp_path / "mem.jsonl", min_cases_for_gate=3)
    # Seed three flaky outcomes for the same signature.
    for _ in range(3):
        _record(mem, failure_signature="bad_sig", result="flaky")
    out = apply_patch_safely(
        "p", fix_confidence=0.95,
        repair_memory=mem, failure_signature="bad_sig",
        failure_category=CATEGORY_EXECUTOR_TOOL,
    )
    assert out.applied is False
    captured = capsys.readouterr().out
    assert "[CI-REPAIR-DECISION]" in captured
    assert "decision: blocked" in captured
    # The reason mentions the flaky-history signal
    assert "flaky" in captured.lower()


# ── Integration: attempt_repair records category + fix_pattern ────────────


def test_attempt_repair_records_failure_category_and_fix_pattern(monkeypatch, tmp_path):
    monkeypatch.setattr(
        repair, "rerun_test",
        lambda *a, **kw: repair.RerunOutcome(
            test_node_id="x::y", passed=False, duration_ms=1.0,
            return_code=1, output_tail="",
        ),
    )
    mem_path = tmp_path / "mem.jsonl"
    mem = RepairMemory(mem_path)

    fix = {
        "stage": "tool", "fix_type": "config",
        "patch": _diff(["if x is None: return"]),
        "confidence": 0.95, "risk_level": "low",
        "root_cause": "", "explanation": "",
    }
    analysis = {
        "stage": "tool", "reason": "tool_runtime_error",
        "summary": "x", "event_trace": [], "recommendation": "x",
    }
    repair.attempt_repair(
        "infra/brain/tests/test_x.py::test_y",
        analysis, fix,
        apply_patch=False,
        repair_memory=mem,
    )
    rows = [json.loads(line) for line in mem_path.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    rec = rows[0]
    assert rec["failure_category"] == CATEGORY_EXECUTOR_TOOL
    assert rec["fix_pattern"] == FIX_NULL_SAFETY


# ── End-to-end: the gate widens through the category bucket ──────────────


def test_category_history_eventually_blocks_unfamiliar_signature(monkeypatch, tmp_path, capsys):
    """A brand-new failure signature can be blocked when its CATEGORY has
    accumulated enough evidence of bad outcomes — the entire point of
    category-based similarity widening."""
    _force_clean_repo(monkeypatch)
    monkeypatch.setattr(repair, "_git", lambda *a, **kw: (0, "applied"))
    mem = RepairMemory(tmp_path / "mem.jsonl", min_cases_for_gate=3)
    # Seed three failed attempts in the planner category, each with a
    # different signature.
    for i in range(3):
        _record(mem, failure_signature=f"sig_{i}",
                failure_category=CATEGORY_PLANNER, result="failed")
    # NEW signature in the same category — should be blocked.
    out = apply_patch_safely(
        "p", fix_confidence=0.95,
        repair_memory=mem, failure_signature="brand_new_sig",
        failure_category=CATEGORY_PLANNER,
    )
    assert out.applied is False
    assert out.reason.startswith("repair_memory_blocked:")
