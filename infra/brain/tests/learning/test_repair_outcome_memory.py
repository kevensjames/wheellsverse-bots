"""Tests for :mod:`infra.brain.learning.repair_outcome_memory` (Phase D).

Coverage:

  * RepairOutcome round-trip (write → read → equal).
  * record_outcome rejects bad inputs.
  * update_outcome only mutates the matching patch_hash.
  * State machine: invalid transitions raise ValueError.
  * query_by_signature: most-recent-first, respects ``limit``.
  * get_stability_score: None for unseen, mean for seen, ignores
    entries with ``stability_score is None``.
  * get_recurrence_count: counts only matching ``failure_signature``.
  * mark_regressed: terminal transition + sets timestamp.
  * Concurrent record_outcome from multiple threads — no torn lines.
  * JSONL corruption tolerance: malformed lines skipped + logged.
  * Telemetry: events emit through the active collector when one is
    bound; module is silent when none is bound.
  * sqlite_index_path is reserved (raises NotImplementedError).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from infra.brain.learning import repair_outcome_memory as rom
from infra.brain.learning.repair_outcome_memory import (
    DEFAULT_OUTCOMES_PATH,
    EVENT_OUTCOME_RECORDED,
    EVENT_OUTCOME_STATE_CHANGED,
    OUTCOME_STATES,
    STATE_APPLIED,
    STATE_MERGED,
    STATE_REGRESSED,
    STATE_REJECTED_BY_REVIEW,
    STATE_REJECTED_BY_VALIDATION,
    STATE_REVERTED,
    TRANSITIONS,
    RepairOutcome,
    RepairOutcomeStore,
    compute_failure_signature,
    patch_signature,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _store(tmp_path: Path) -> RepairOutcomeStore:
    return RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")


def _outcome(
    *,
    sig: str = "sig_abc",
    patch: str = "patch_def",
    state: str = STATE_APPLIED,
    applied_at: str = "2026-05-05T22:00:00+00:00",
    observed_at: str = "2026-05-05T22:00:00+00:00",
    **extra,
) -> RepairOutcome:
    return RepairOutcome(
        failure_signature=sig,
        patch_hash=patch,
        applied_at=applied_at,
        outcome_state=state,
        outcome_observed_at=observed_at,
        **extra,
    )


# ── Vocabulary + state machine ─────────────────────────────────────────


def test_outcome_states_size_and_contents():
    assert OUTCOME_STATES == frozenset({
        STATE_APPLIED,
        STATE_REJECTED_BY_VALIDATION,
        STATE_REJECTED_BY_REVIEW,
        STATE_MERGED,
        STATE_REVERTED,
        STATE_REGRESSED,
    })


def test_terminal_states_have_no_outbound_transitions():
    for terminal in (
        STATE_REJECTED_BY_VALIDATION, STATE_REJECTED_BY_REVIEW,
        STATE_REVERTED, STATE_REGRESSED,
    ):
        assert TRANSITIONS[terminal] == frozenset()


def test_applied_can_transition_to_all_post_apply_states():
    allowed = TRANSITIONS[STATE_APPLIED]
    assert STATE_MERGED in allowed
    assert STATE_REVERTED in allowed
    assert STATE_REGRESSED in allowed
    assert STATE_REJECTED_BY_REVIEW in allowed


def test_merged_can_only_transition_to_reverted_or_regressed():
    assert TRANSITIONS[STATE_MERGED] == frozenset({
        STATE_REVERTED, STATE_REGRESSED,
    })


# ── Hash re-exports ────────────────────────────────────────────────────


def test_hash_helpers_are_re_exported():
    sig = compute_failure_signature("test::x", stage="planner")
    assert isinstance(sig, str) and len(sig) == 16
    h = patch_signature("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n")
    assert isinstance(h, str) and len(h) == 16


# ── RepairOutcome round-trip ───────────────────────────────────────────


def test_repair_outcome_to_dict_round_trip():
    o = _outcome(commit_sha="abc123", pr_number=42, stability_score=0.9)
    d = o.to_dict()
    o2 = RepairOutcome.from_dict(d)
    assert o == o2


def test_repair_outcome_from_dict_tolerates_extra_keys():
    d = _outcome().to_dict()
    d["future_field"] = "ignored"
    # Should not raise — forward-compat.
    o = RepairOutcome.from_dict(d)
    assert o.failure_signature == "sig_abc"


def test_repair_outcome_from_dict_rejects_non_dict():
    with pytest.raises(TypeError):
        RepairOutcome.from_dict([1, 2, 3])  # type: ignore[arg-type]


def test_repair_outcome_is_frozen():
    o = _outcome()
    with pytest.raises(dataclasses_FrozenInstanceError := Exception):
        o.outcome_state = STATE_MERGED  # type: ignore[misc]


# ── record_outcome basic round-trip ────────────────────────────────────


def test_record_outcome_creates_file_and_writes_line(tmp_path):
    store = _store(tmp_path)
    o = _outcome()
    store.record_outcome(o)
    assert store.path.exists()
    lines = store.path.read_text().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["failure_signature"] == "sig_abc"
    assert parsed["patch_hash"] == "patch_def"
    assert parsed["outcome_state"] == STATE_APPLIED


def test_record_outcome_round_trip_via_query(tmp_path):
    store = _store(tmp_path)
    o = _outcome(stability_score=0.75, pr_number=7)
    store.record_outcome(o)
    found = store.query_by_signature("sig_abc")
    assert len(found) == 1
    assert found[0] == o


def test_record_outcome_rejects_non_dataclass_input(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(TypeError, match="RepairOutcome"):
        store.record_outcome({"failure_signature": "x"})  # type: ignore[arg-type]


def test_record_outcome_rejects_unknown_state(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="unknown outcome state"):
        store.record_outcome(_outcome(state="not_a_state"))


def test_record_outcome_creates_parent_dirs(tmp_path):
    nested = tmp_path / "deeply" / "nested" / "outcomes.jsonl"
    store = RepairOutcomeStore(path=nested)
    store.record_outcome(_outcome())
    assert nested.exists()
    assert nested.parent.is_dir()


# ── update_outcome ─────────────────────────────────────────────────────


def test_update_outcome_returns_false_for_unknown_patch(tmp_path):
    store = _store(tmp_path)
    assert store.update_outcome("nonexistent") is False


def test_update_outcome_appends_new_line_for_matching_patch(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(patch="patch_a", state=STATE_APPLIED))
    assert store.update_outcome("patch_a", outcome_state=STATE_MERGED) is True
    lines = store.path.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[1])["outcome_state"] == STATE_MERGED


def test_update_outcome_only_affects_matching_patch_hash(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(patch="patch_a", sig="sig_1"))
    store.record_outcome(_outcome(patch="patch_b", sig="sig_2"))
    store.update_outcome("patch_a", outcome_state=STATE_MERGED)

    a_history = [
        e for e in store._iter_records() if e.patch_hash == "patch_a"
    ]
    b_history = [
        e for e in store._iter_records() if e.patch_hash == "patch_b"
    ]
    # patch_a got 2 entries (record + update); patch_b stays at 1.
    assert len(a_history) == 2
    assert len(b_history) == 1
    assert b_history[0].outcome_state == STATE_APPLIED  # unchanged


def test_update_outcome_refreshes_outcome_observed_at(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(observed_at="2026-01-01T00:00:00+00:00"))
    store.update_outcome("patch_def", outcome_state=STATE_MERGED)
    latest = store._latest_for_patch("patch_def")
    assert latest is not None
    assert latest.outcome_observed_at != "2026-01-01T00:00:00+00:00"


def test_update_outcome_honors_caller_supplied_observed_at(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome())
    store.update_outcome(
        "patch_def",
        outcome_state=STATE_MERGED,
        outcome_observed_at="2099-12-31T23:59:59+00:00",
    )
    latest = store._latest_for_patch("patch_def")
    assert latest.outcome_observed_at == "2099-12-31T23:59:59+00:00"


def test_update_outcome_rejects_unknown_field(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome())
    with pytest.raises(ValueError, match="unknown field"):
        store.update_outcome("patch_def", made_up_field="oops")


# ── State-machine validation ───────────────────────────────────────────


def test_invalid_transition_merged_to_applied_raises(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(state=STATE_MERGED))
    with pytest.raises(ValueError, match="invalid state transition"):
        store.update_outcome("patch_def", outcome_state=STATE_APPLIED)


def test_invalid_transition_from_terminal_state(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(state=STATE_REVERTED))
    with pytest.raises(ValueError, match=r"terminal"):
        store.update_outcome("patch_def", outcome_state=STATE_MERGED)


def test_valid_transition_applied_to_merged(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(state=STATE_APPLIED))
    assert store.update_outcome("patch_def", outcome_state=STATE_MERGED) is True


def test_update_to_unknown_state_raises(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(state=STATE_APPLIED))
    with pytest.raises(ValueError, match="unknown outcome state"):
        store.update_outcome("patch_def", outcome_state="bogus")


def test_no_state_change_does_not_validate_transition(tmp_path):
    """Updating a non-state field on a terminal entry must NOT trip
    the transition validator."""
    store = _store(tmp_path)
    store.record_outcome(_outcome(state=STATE_REVERTED))
    # No outcome_state field → no transition check.
    assert store.update_outcome("patch_def", commit_sha="zzz") is True


# ── query_by_signature ─────────────────────────────────────────────────


def test_query_returns_most_recent_first(tmp_path):
    store = _store(tmp_path)
    for i in range(3):
        store.record_outcome(_outcome(
            sig="sig_q",
            patch=f"patch_{i}",
            observed_at=f"2026-05-0{i+1}T00:00:00+00:00",
        ))
    found = store.query_by_signature("sig_q")
    assert len(found) == 3
    # Most recently written = last in file = first in result list.
    assert found[0].patch_hash == "patch_2"
    assert found[2].patch_hash == "patch_0"


def test_query_respects_limit(tmp_path):
    store = _store(tmp_path)
    for i in range(5):
        store.record_outcome(_outcome(sig="sig_q", patch=f"p{i}"))
    assert len(store.query_by_signature("sig_q", limit=2)) == 2


def test_query_filters_to_matching_signature(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(sig="sig_a"))
    store.record_outcome(_outcome(sig="sig_b", patch="other"))
    result = store.query_by_signature("sig_a")
    assert len(result) == 1
    assert result[0].failure_signature == "sig_a"


def test_query_empty_when_no_matches(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(sig="other"))
    assert store.query_by_signature("nope") == []


def test_query_handles_missing_file(tmp_path):
    store = _store(tmp_path)
    # No record_outcome called → file doesn't exist.
    assert store.query_by_signature("anything") == []


def test_query_zero_limit_returns_empty(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome())
    assert store.query_by_signature("sig_abc", limit=0) == []


# ── get_stability_score ────────────────────────────────────────────────


def test_stability_score_none_for_unseen_signature(tmp_path):
    store = _store(tmp_path)
    assert store.get_stability_score("never_recorded") is None


def test_stability_score_none_when_all_entries_have_none(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(sig="s"))  # stability_score=None
    assert store.get_stability_score("s") is None


def test_stability_score_mean_across_matching_entries(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(sig="s", patch="p1", stability_score=1.0))
    store.record_outcome(_outcome(sig="s", patch="p2", stability_score=0.5))
    store.record_outcome(_outcome(sig="s", patch="p3", stability_score=0.0))
    assert store.get_stability_score("s") == pytest.approx(0.5)


def test_stability_score_ignores_other_signatures(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(sig="s", stability_score=1.0))
    store.record_outcome(_outcome(sig="other", patch="p2", stability_score=0.0))
    assert store.get_stability_score("s") == pytest.approx(1.0)


# ── get_recurrence_count ───────────────────────────────────────────────


def test_recurrence_zero_for_unseen(tmp_path):
    assert _store(tmp_path).get_recurrence_count("nope") == 0


def test_recurrence_counts_every_matching_entry(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(sig="hot", patch="p1"))
    store.record_outcome(_outcome(sig="hot", patch="p2"))
    store.record_outcome(_outcome(sig="cool", patch="p3"))
    # update on p1 = another entry, also counted (per docstring).
    store.update_outcome("p1", outcome_state=STATE_MERGED)
    assert store.get_recurrence_count("hot") == 3
    assert store.get_recurrence_count("cool") == 1


# ── mark_regressed ─────────────────────────────────────────────────────


def test_mark_regressed_transitions_state(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(state=STATE_MERGED))
    ts = datetime(2026, 5, 5, 23, 0, 0, tzinfo=timezone.utc)
    assert store.mark_regressed("patch_def", ts) is True
    latest = store._latest_for_patch("patch_def")
    assert latest.outcome_state == STATE_REGRESSED
    assert latest.regression_detected_at == ts.isoformat()


def test_mark_regressed_returns_false_for_unknown(tmp_path):
    store = _store(tmp_path)
    ts = datetime(2026, 5, 5, tzinfo=timezone.utc)
    assert store.mark_regressed("missing", ts) is False


def test_mark_regressed_rejects_non_datetime(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome())
    with pytest.raises(TypeError, match="datetime"):
        store.mark_regressed("patch_def", "2026-05-05")  # type: ignore[arg-type]


def test_mark_regressed_handles_naive_datetime_as_utc(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(state=STATE_APPLIED))
    naive = datetime(2026, 5, 5, 23, 0, 0)
    assert store.mark_regressed("patch_def", naive) is True
    latest = store._latest_for_patch("patch_def")
    assert latest.regression_detected_at.endswith("+00:00")


def test_mark_regressed_invalid_from_terminal_state(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(state=STATE_REVERTED))
    ts = datetime(2026, 5, 5, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        store.mark_regressed("patch_def", ts)


# ── Concurrency ────────────────────────────────────────────────────────


def test_concurrent_record_outcome_no_torn_lines(tmp_path):
    """100 records from 10 threads → exactly 100 valid JSONL lines."""
    store = _store(tmp_path)
    n_threads = 10
    per_thread = 10

    def worker(t_id: int):
        for i in range(per_thread):
            store.record_outcome(_outcome(
                sig=f"sig_{t_id}",
                patch=f"patch_{t_id}_{i}",
                observed_at=f"2026-05-05T22:{i:02d}:00+00:00",
            ))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = store.path.read_text().splitlines()
    assert len(lines) == n_threads * per_thread
    # Every line must round-trip.
    for line in lines:
        d = json.loads(line)
        assert "patch_hash" in d
        assert "outcome_state" in d


# ── JSONL corruption tolerance ─────────────────────────────────────────


def test_malformed_lines_are_skipped_with_warning(tmp_path, caplog):
    store = _store(tmp_path)
    store.record_outcome(_outcome(sig="good_sig"))
    # Append garbage + a partial JSON line.
    with store.path.open("a") as f:
        f.write("this is not json\n")
        f.write('{"failure_signature": "broken", incomplete\n')
        f.write(json.dumps(_outcome(sig="good_sig").to_dict()) + "\n")

    import logging
    with caplog.at_level(logging.WARNING):
        result = store.query_by_signature("good_sig")
    # Only the two valid entries are returned.
    assert len(result) == 2
    # Two warnings logged — one per malformed line.
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) >= 2


def test_record_with_unrecognised_field_in_jsonl_is_dropped(tmp_path, caplog):
    """If someone hand-writes a line with an unknown ``outcome_state``,
    :class:`RepairOutcome.from_dict` is forgiving — but a missing
    *required* field will trigger a warning + skip."""
    store = _store(tmp_path)
    # Hand-write a record with no ``patch_hash`` (required field).
    bad = {"failure_signature": "x", "outcome_state": STATE_APPLIED}
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps(bad) + "\n")

    import logging
    with caplog.at_level(logging.WARNING):
        result = store.query_by_signature("x")
    assert result == []
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) >= 1


# ── Telemetry ──────────────────────────────────────────────────────────


def test_telemetry_emits_recorded_event_when_collector_active(tmp_path):
    """Bind a fake collector via the ContextVar and confirm the
    recorded event flows through it."""
    from infra.brain.telemetry.collector import _current_telemetry

    fake = MagicMock()
    fake.emit = MagicMock()
    token = _current_telemetry.set(fake)
    try:
        store = _store(tmp_path)
        store.record_outcome(_outcome())
    finally:
        _current_telemetry.reset(token)

    fake.emit.assert_any_call(
        EVENT_OUTCOME_RECORDED,
        failure_signature="sig_abc",
        patch_hash="patch_def",
        outcome_state=STATE_APPLIED,
    )


def test_telemetry_emits_state_changed_only_on_actual_transition(tmp_path):
    from infra.brain.telemetry.collector import _current_telemetry

    fake = MagicMock()
    fake.emit = MagicMock()

    store = _store(tmp_path)
    store.record_outcome(_outcome(state=STATE_APPLIED))

    token = _current_telemetry.set(fake)
    try:
        # Update with no state change → should NOT emit state_changed.
        store.update_outcome("patch_def", commit_sha="zzz")
        # Now actually transition.
        store.update_outcome("patch_def", outcome_state=STATE_MERGED)
    finally:
        _current_telemetry.reset(token)

    state_change_calls = [
        c for c in fake.emit.call_args_list
        if c.args and c.args[0] == EVENT_OUTCOME_STATE_CHANGED
    ]
    assert len(state_change_calls) == 1
    kwargs = state_change_calls[0].kwargs
    assert kwargs["from_state"] == STATE_APPLIED
    assert kwargs["to_state"] == STATE_MERGED


def test_module_silent_when_no_collector_bound(tmp_path):
    """No collector active → record_outcome must succeed silently."""
    store = _store(tmp_path)
    # Just confirm no exception escapes.
    store.record_outcome(_outcome())
    assert store.path.exists()


# ── sqlite_index_path is reserved ─────────────────────────────────────


def test_sqlite_index_path_is_reserved(tmp_path):
    with pytest.raises(NotImplementedError, match="Phase E"):
        RepairOutcomeStore(
            path=tmp_path / "x.jsonl",
            sqlite_index_path=tmp_path / "x.sqlite",
        )


def test_sqlite_index_path_none_works(tmp_path):
    # The default (None) must keep working.
    s = RepairOutcomeStore(path=tmp_path / "x.jsonl", sqlite_index_path=None)
    s.record_outcome(_outcome())
    assert (tmp_path / "x.jsonl").exists()


# ── Default path constant is sane ─────────────────────────────────────


def test_default_outcomes_path_is_state_relative():
    assert DEFAULT_OUTCOMES_PATH == "state/repair_outcomes.jsonl"
