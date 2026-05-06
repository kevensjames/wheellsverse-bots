"""Phase F.1: tests for the post-merge feedback ingestor.

Coverage targets the eight bullets from the spec:

  * approved + merged → state transitions to ``merged`` (only when
    payload also indicates merge).
  * changes_requested → ``rejected_by_review``; merge state irrelevant.
  * commented → no transition; ``IngestionResult.notes`` populated.
  * PR review with no matching ``pr_number`` in store → no-op.
  * Push with revert commit referencing a known SHA → ``regressed``,
    ``regression_detected_at`` set.
  * Push with fresh CI failure signature on a ``merged`` outcome →
    ``regression_detected_at`` set.
  * Push on a non-``main`` branch is a no-op.
  * Idempotency: re-ingesting the same payload twice produces no
    second state change AND no second JSONL line.
  * Malformed payload → :class:`IngestionResult` with explanatory
    notes; never raises.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from infra.brain.learning.feedback_ingestor import (
    EVENT_FEEDBACK_INGESTED,
    EVENT_FEEDBACK_MALFORMED,
    EVENT_FEEDBACK_NO_MATCH,
    IngestionResult,
    MAIN_REF,
    ingest_pr_review,
    ingest_push_event,
)
from infra.brain.learning.repair_outcome_memory import (
    RepairOutcome,
    RepairOutcomeStore,
    STATE_APPLIED,
    STATE_MERGED,
    STATE_REGRESSED,
    STATE_REJECTED_BY_REVIEW,
    STATE_REVERTED,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


def _store(tmp_path: Path) -> RepairOutcomeStore:
    return RepairOutcomeStore(path=tmp_path / "outcomes.jsonl")


def _outcome(
    *,
    sig: str = "sig_default",
    patch: str = "patch_default",
    state: str = STATE_APPLIED,
    pr_number: int | None = None,
    commit_sha: str | None = None,
    applied_at: str = "2026-05-05T22:00:00+00:00",
    observed_at: str = "2026-05-05T22:00:00+00:00",
) -> RepairOutcome:
    return RepairOutcome(
        failure_signature=sig,
        patch_hash=patch,
        applied_at=applied_at,
        outcome_state=state,
        outcome_observed_at=observed_at,
        pr_number=pr_number,
        commit_sha=commit_sha,
    )


def _pr_review_payload(
    *,
    state: str,
    pr_number: int,
    merged: bool,
) -> dict:
    return {
        "review": {"state": state},
        "pull_request": {"number": pr_number, "merged": merged},
    }


def _push_payload(
    *,
    ref: str = MAIN_REF,
    commits: list[dict] | None = None,
    head_commit: dict | None = None,
    ci_failure_signature: str | None = None,
) -> dict:
    out: dict = {"ref": ref, "commits": commits or []}
    if head_commit is not None:
        out["head_commit"] = head_commit
    if ci_failure_signature is not None:
        out["ci_failure_signature"] = ci_failure_signature
    return out


# ── Pull-request review path ────────────────────────────────────────────


def test_approved_and_merged_transitions_to_merged(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(
        patch="p1", state=STATE_APPLIED, pr_number=42,
    ))
    result = ingest_pr_review(
        _pr_review_payload(state="approved", pr_number=42, merged=True),
        store=store,
    )
    assert result.matched_patch_hash == "p1"
    assert result.state_transition == (STATE_APPLIED, STATE_MERGED)
    # Verify the store actually transitioned.
    latest = store._latest_for_patch("p1")
    assert latest is not None and latest.outcome_state == STATE_MERGED


def test_approved_but_not_merged_does_not_transition(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(patch="p1", state=STATE_APPLIED, pr_number=42))
    result = ingest_pr_review(
        _pr_review_payload(state="approved", pr_number=42, merged=False),
        store=store,
    )
    assert result.matched_patch_hash == "p1"
    assert result.state_transition is None
    assert "approved but pull_request.merged=False" in result.notes
    assert store._latest_for_patch("p1").outcome_state == STATE_APPLIED


def test_changes_requested_transitions_regardless_of_merge_state(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(patch="p1", state=STATE_APPLIED, pr_number=42))
    # ``merged=False`` deliberately — changes_requested doesn't depend on it.
    result = ingest_pr_review(
        _pr_review_payload(
            state="changes_requested", pr_number=42, merged=False,
        ),
        store=store,
    )
    assert result.state_transition == (STATE_APPLIED, STATE_REJECTED_BY_REVIEW)
    assert store._latest_for_patch("p1").outcome_state == STATE_REJECTED_BY_REVIEW


def test_commented_no_transition_with_explanatory_notes(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(patch="p1", state=STATE_APPLIED, pr_number=42))
    result = ingest_pr_review(
        _pr_review_payload(state="commented", pr_number=42, merged=False),
        store=store,
    )
    assert result.matched_patch_hash == "p1"
    assert result.state_transition is None
    assert "commented" in result.notes
    assert store._latest_for_patch("p1").outcome_state == STATE_APPLIED


def test_pr_review_with_no_matching_outcome_is_noop(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(patch="p1", state=STATE_APPLIED, pr_number=42))
    result = ingest_pr_review(
        _pr_review_payload(state="approved", pr_number=999, merged=True),
        store=store,
    )
    assert result.matched_patch_hash is None
    assert result.state_transition is None
    assert "no outcome with pr_number=999" in result.notes


def test_pr_review_picks_latest_record_when_multiple(tmp_path):
    """If multiple JSONL entries share a pr_number (e.g. patch was
    re-applied), the ingestor uses the most recently written record."""
    store = _store(tmp_path)
    store.record_outcome(_outcome(patch="p_old", state=STATE_APPLIED, pr_number=42))
    store.record_outcome(_outcome(patch="p_new", state=STATE_APPLIED, pr_number=42))
    result = ingest_pr_review(
        _pr_review_payload(state="changes_requested", pr_number=42, merged=False),
        store=store,
    )
    assert result.matched_patch_hash == "p_new"


# ── Push event path: revert detection ──────────────────────────────────


def test_push_revert_marks_regressed(tmp_path):
    store = _store(tmp_path)
    sha = "abc123def456789012345678901234567890aaaa"
    store.record_outcome(_outcome(
        patch="p1", state=STATE_MERGED, commit_sha=sha,
    ))
    result = ingest_push_event(
        _push_payload(commits=[{
            "id": "rev99",
            "message": (
                'Revert "feat: bad change"\n\n'
                f'This reverts commit {sha}.\n'
            ),
        }]),
        store=store,
    )
    assert result.state_transition == (STATE_MERGED, STATE_REGRESSED)
    latest = store._latest_for_patch("p1")
    assert latest.outcome_state == STATE_REGRESSED
    assert latest.regression_detected_at is not None


def test_push_revert_with_short_sha_matches_full_sha(tmp_path):
    """``This reverts commit <short>`` should match an outcome whose
    ``commit_sha`` is the full SHA — GitHub revert messages often use
    abbreviated identifiers."""
    store = _store(tmp_path)
    full_sha = "abc123def456789012345678901234567890aaaa"
    store.record_outcome(_outcome(
        patch="p1", state=STATE_MERGED, commit_sha=full_sha,
    ))
    result = ingest_push_event(
        _push_payload(commits=[{
            "id": "rev1",
            "message": "Revert\n\nThis reverts commit abc123def456.\n",
        }]),
        store=store,
    )
    assert result.state_transition == (STATE_MERGED, STATE_REGRESSED)


def test_push_revert_with_no_matching_sha_is_noop(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(
        patch="p1", state=STATE_MERGED,
        commit_sha="abc123def456789012345678901234567890aaaa",
    ))
    result = ingest_push_event(
        _push_payload(commits=[{
            "id": "rev1",
            "message": (
                'Revert "x"\n\n'
                "This reverts commit fffffffffffffffffffffffffffffffffffffff0.\n"
            ),
        }]),
        store=store,
    )
    assert result.matched_patch_hash is None
    assert result.state_transition is None


def test_push_revert_in_head_commit_is_detected(tmp_path):
    """The revert message can be in ``head_commit`` rather than the
    ``commits`` array — GitHub does this for fast-forward pushes."""
    store = _store(tmp_path)
    sha = "abc123def456789012345678901234567890aaaa"
    store.record_outcome(_outcome(
        patch="p1", state=STATE_MERGED, commit_sha=sha,
    ))
    result = ingest_push_event(
        _push_payload(
            commits=[],
            head_commit={
                "id": "rev1",
                "message": f'Revert "x"\n\nThis reverts commit {sha}.\n',
            },
        ),
        store=store,
    )
    assert result.state_transition == (STATE_MERGED, STATE_REGRESSED)


# ── Push event path: CI-failure-signature detection ────────────────────


def test_push_with_ci_failure_signature_marks_merged_regressed(tmp_path):
    store = _store(tmp_path)
    store.record_outcome(_outcome(
        sig="hot_sig", patch="p1", state=STATE_MERGED,
    ))
    result = ingest_push_event(
        _push_payload(ci_failure_signature="hot_sig"),
        store=store,
    )
    assert result.state_transition == (STATE_MERGED, STATE_REGRESSED)
    latest = store._latest_for_patch("p1")
    assert latest.regression_detected_at is not None


def test_push_with_ci_failure_signature_does_not_match_applied_outcome(tmp_path):
    """Only ``merged`` outcomes are eligible for CI-failure regression
    marking. An ``applied`` outcome is still in flight, so a CI failure
    isn't a regression — it's the original failure."""
    store = _store(tmp_path)
    store.record_outcome(_outcome(
        sig="hot_sig", patch="p1", state=STATE_APPLIED,
    ))
    result = ingest_push_event(
        _push_payload(ci_failure_signature="hot_sig"),
        store=store,
    )
    assert result.matched_patch_hash is None
    assert result.state_transition is None


def test_push_with_unmatched_ci_failure_signature_is_noop(tmp_path):
    store = _store(tmp_path)
    result = ingest_push_event(
        _push_payload(ci_failure_signature="unknown_sig"),
        store=store,
    )
    assert result.matched_patch_hash is None
    assert result.state_transition is None


# ── Push event path: branch filtering ──────────────────────────────────


def test_push_on_non_main_branch_is_noop(tmp_path):
    store = _store(tmp_path)
    sha = "abc123def456789012345678901234567890aaaa"
    store.record_outcome(_outcome(
        patch="p1", state=STATE_MERGED, commit_sha=sha,
    ))
    # Same revert message but ref points at a feature branch.
    result = ingest_push_event(
        _push_payload(
            ref="refs/heads/develop",
            commits=[{
                "id": "rev1",
                "message": f"Revert\n\nThis reverts commit {sha}.\n",
            }],
        ),
        store=store,
    )
    assert result.matched_patch_hash is None
    assert "is not 'refs/heads/main'" in result.notes
    # And the outcome stays merged.
    assert store._latest_for_patch("p1").outcome_state == STATE_MERGED


# ── Idempotency ────────────────────────────────────────────────────────


def test_idempotent_replay_pr_review_changes_requested(tmp_path):
    """Replaying the same review twice produces zero second JSONL line."""
    store = _store(tmp_path)
    store.record_outcome(_outcome(patch="p1", state=STATE_APPLIED, pr_number=42))
    payload = _pr_review_payload(
        state="changes_requested", pr_number=42, merged=False,
    )

    r1 = ingest_pr_review(payload, store=store)
    assert r1.state_transition == (STATE_APPLIED, STATE_REJECTED_BY_REVIEW)
    line_count_after_first = len(
        (tmp_path / "outcomes.jsonl").read_text().splitlines()
    )

    r2 = ingest_pr_review(payload, store=store)
    assert r2.state_transition is None
    assert "idempotent" in r2.notes
    line_count_after_second = len(
        (tmp_path / "outcomes.jsonl").read_text().splitlines()
    )
    assert line_count_after_first == line_count_after_second


def test_idempotent_replay_revert(tmp_path):
    store = _store(tmp_path)
    sha = "abc123def456789012345678901234567890aaaa"
    store.record_outcome(_outcome(
        patch="p1", state=STATE_MERGED, commit_sha=sha,
    ))
    payload = _push_payload(commits=[{
        "id": "rev1",
        "message": f"Revert\n\nThis reverts commit {sha}.\n",
    }])
    r1 = ingest_push_event(payload, store=store)
    assert r1.state_transition == (STATE_MERGED, STATE_REGRESSED)
    line_count_after_first = len(
        (tmp_path / "outcomes.jsonl").read_text().splitlines()
    )
    r2 = ingest_push_event(payload, store=store)
    assert r2.state_transition is None
    assert "idempotent" in r2.notes
    assert line_count_after_first == len(
        (tmp_path / "outcomes.jsonl").read_text().splitlines()
    )


# ── State-machine refusals ─────────────────────────────────────────────


def test_pr_review_on_terminal_outcome_does_not_transition(tmp_path):
    """An outcome already in a terminal state (e.g. reverted) cannot
    accept further state mutations from review events. The ingestor
    surfaces the refusal in ``notes`` rather than raising."""
    store = _store(tmp_path)
    store.record_outcome(_outcome(patch="p1", state=STATE_REVERTED, pr_number=42))
    result = ingest_pr_review(
        _pr_review_payload(
            state="changes_requested", pr_number=42, merged=False,
        ),
        store=store,
    )
    assert result.state_transition is None
    assert "state machine refuses" in result.notes
    assert store._latest_for_patch("p1").outcome_state == STATE_REVERTED


# ── Malformed payloads ─────────────────────────────────────────────────


def test_malformed_pr_review_non_dict_returns_no_op_result(tmp_path):
    store = _store(tmp_path)
    result = ingest_pr_review("not a dict", store=store)  # type: ignore[arg-type]
    assert result.matched_patch_hash is None
    assert result.state_transition is None
    assert "not a dict" in result.notes


def test_malformed_pr_review_missing_review_key(tmp_path):
    """A payload without a ``review`` key falls through to the empty-state
    branch ({} → ''.lower() not in valid set), and surfaces the reason
    via the notes field. The exact wording is "unknown review.state ''"
    — informative without claiming the literal word "missing"."""
    store = _store(tmp_path)
    result = ingest_pr_review(
        {"pull_request": {"number": 1, "merged": False}},
        store=store,
    )
    assert result.matched_patch_hash is None
    assert result.state_transition is None
    assert "unknown review.state" in result.notes


def test_malformed_pr_review_unknown_review_state(tmp_path):
    store = _store(tmp_path)
    result = ingest_pr_review(
        {
            "review": {"state": "love_struck"},
            "pull_request": {"number": 1, "merged": False},
        },
        store=store,
    )
    assert "unknown review.state" in result.notes


def test_malformed_pr_review_pr_number_not_int(tmp_path):
    store = _store(tmp_path)
    result = ingest_pr_review(
        {
            "review": {"state": "approved"},
            "pull_request": {"number": "42", "merged": True},
        },
        store=store,
    )
    assert "not an int" in result.notes


def test_malformed_push_non_dict(tmp_path):
    store = _store(tmp_path)
    result = ingest_push_event(["not", "a", "dict"], store=store)  # type: ignore[arg-type]
    assert result.matched_patch_hash is None
    assert "not a dict" in result.notes


def test_push_with_no_relevant_signal_is_silent_noop(tmp_path):
    """A push that's neither a revert nor a CI failure produces a
    well-formed IngestionResult, not a malformed one."""
    store = _store(tmp_path)
    result = ingest_push_event(
        _push_payload(commits=[{
            "id": "abcd1234",
            "message": "feat: add cool thing\n",
        }]),
        store=store,
    )
    assert result.matched_patch_hash is None
    assert result.state_transition is None
    # Not malformed — just nothing actionable in this push.
    assert "no revert or ci-failure-signature match" in result.notes


# ── Telemetry ──────────────────────────────────────────────────────────


def test_telemetry_emits_ingested_on_transition(tmp_path):
    from infra.brain.telemetry.collector import _current_telemetry

    store = _store(tmp_path)
    store.record_outcome(_outcome(patch="p1", state=STATE_APPLIED, pr_number=42))

    fake = MagicMock()
    fake.emit = MagicMock()
    token = _current_telemetry.set(fake)
    try:
        ingest_pr_review(
            _pr_review_payload(state="approved", pr_number=42, merged=True),
            store=store,
        )
    finally:
        _current_telemetry.reset(token)

    ingested = [
        c for c in fake.emit.call_args_list
        if c.args and c.args[0] == EVENT_FEEDBACK_INGESTED
    ]
    assert len(ingested) >= 1
    transitioning = [
        c for c in ingested if c.kwargs.get("transitioned") is True
    ]
    assert len(transitioning) == 1


def test_telemetry_emits_no_match_when_pr_number_unknown(tmp_path):
    from infra.brain.telemetry.collector import _current_telemetry

    store = _store(tmp_path)
    fake = MagicMock()
    fake.emit = MagicMock()
    token = _current_telemetry.set(fake)
    try:
        ingest_pr_review(
            _pr_review_payload(state="approved", pr_number=12345, merged=True),
            store=store,
        )
    finally:
        _current_telemetry.reset(token)

    no_match = [
        c for c in fake.emit.call_args_list
        if c.args and c.args[0] == EVENT_FEEDBACK_NO_MATCH
    ]
    assert len(no_match) == 1


def test_telemetry_emits_malformed_event(tmp_path):
    from infra.brain.telemetry.collector import _current_telemetry

    store = _store(tmp_path)
    fake = MagicMock()
    fake.emit = MagicMock()
    token = _current_telemetry.set(fake)
    try:
        ingest_pr_review("garbage", store=store)  # type: ignore[arg-type]
    finally:
        _current_telemetry.reset(token)

    malformed = [
        c for c in fake.emit.call_args_list
        if c.args and c.args[0] == EVENT_FEEDBACK_MALFORMED
    ]
    assert len(malformed) == 1
