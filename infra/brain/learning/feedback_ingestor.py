"""Post-merge feedback ingestor — Phase F of the audit follow-up.

Wires the outcome ledger to two real signal sources:

  1. GitHub ``pull_request_review`` events → the reviewer outcome label
     (approve / changes-requested / commented). Approve + merged means
     the patch was accepted. Changes-requested is the strongest
     negative signal short of a revert.
  2. GitHub ``push`` events on ``main`` → post-merge regression
     detection. A revert commit referencing an autopilot SHA is the
     loudest possible "this fix was wrong" signal. A push that carries
     an out-of-band CI-failure signature matching a previously merged
     outcome's signature is the second-loudest.

The audit identified the missing reviewer signal as **the single
biggest learning unlock**. This module is what closes that loop.

Design constraints (per Phase F spec):

  * **Pure functional.** No HTTP, no GitHub SDK calls, no clock reads
    that aren't guarded behind ``datetime.now``. Inputs are dicts;
    side effects are confined to the supplied
    :class:`RepairOutcomeStore`.
  * **Two entry points only**: :func:`ingest_pr_review` and
    :func:`ingest_push_event`. Anything else is the caller's job.
  * **No new identifiers.** Matching is via existing outcome fields
    only — ``pr_number`` for review events, ``commit_sha`` (or
    ``failure_signature``) for push events.
  * **Idempotent.** Replaying the same payload produces zero new
    JSONL lines once the steady state is reached. This matters
    because GitHub Actions can re-deliver webhooks and the runtime
    can't track "what's been processed".
  * **Never raises.** Malformed payloads return an
    :class:`IngestionResult` with explanatory ``notes`` — failure
    flows must not corrupt or interrupt the ledger.

Phase F ships the ingestor + CLI + workflow. Consumption (e.g. policy
adjustment based on reviewer outcome) is Phase G+.
"""
from __future__ import annotations

import dataclasses
import logging
import re
from datetime import datetime, timezone
from typing import Any, Optional

from .repair_outcome_memory import (
    RepairOutcome,
    RepairOutcomeStore,
    STATE_APPLIED,
    STATE_MERGED,
    STATE_REGRESSED,
    STATE_REJECTED_BY_REVIEW,
    STATE_REVERTED,
    TRANSITIONS,
)


_log = logging.getLogger("infra.brain.learning.feedback_ingestor")


# ── Telemetry events ────────────────────────────────────────────────────


EVENT_FEEDBACK_INGESTED:   str = "feedback_ingested"
EVENT_FEEDBACK_NO_MATCH:   str = "feedback_no_match"
EVENT_FEEDBACK_MALFORMED:  str = "feedback_malformed"


# ── Constants ───────────────────────────────────────────────────────────


#: GitHub branch ref prefix we honor. ``push`` events on any other ref
#: are treated as no-ops — the ingestor only acts on changes that hit
#: the production-equivalent branch.
MAIN_REF: str = "refs/heads/main"

#: GitHub ``pull_request_review`` review.state values that map to a
#: state transition. ``commented`` is logged but does NOT mutate state.
REVIEW_STATE_APPROVED:           str = "approved"
REVIEW_STATE_CHANGES_REQUESTED:  str = "changes_requested"
REVIEW_STATE_COMMENTED:          str = "commented"


# ── Result type ─────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class IngestionResult:
    """Describes what an ingestion call did, regardless of success.

    Fields
    ------
    event_type:
        Verbatim copy of the event kind we processed:
        ``pull_request_review`` or ``push``.
    matched_patch_hash:
        ``patch_hash`` of the outcome we matched, or ``None`` when no
        ledger entry corresponds to the inbound event.
    state_transition:
        ``(from_state, to_state)`` when we changed the outcome's
        state, ``None`` otherwise. Idempotent ingestions
        (state already at target) leave this ``None``.
    notes:
        Short human-readable explanation. Always populated, especially
        useful when ``state_transition is None`` — explains *why* we
        did or did not transition.
    """

    event_type: str
    matched_patch_hash: Optional[str] = None
    state_transition: Optional[tuple[str, str]] = None
    notes: str = ""


# ── Public API ──────────────────────────────────────────────────────────


def ingest_pr_review(
    payload: dict, *, store: RepairOutcomeStore,
) -> IngestionResult:
    """Process a GitHub ``pull_request_review`` event payload.

    Inputs
    ------
    payload:
        The webhook payload dict. Required-ish keys:
          - ``review.state`` : str — one of ``approved``,
            ``changes_requested``, ``commented``.
          - ``pull_request.number`` : int — the PR identifier we use
            to match the outcome.
          - ``pull_request.merged`` : bool — only ``True`` lets
            ``approved`` map to ``merged``.
        Missing keys produce an :class:`IngestionResult` with a
        descriptive ``notes`` string; this function does not raise.

    Behavior
    --------
    - ``approved`` AND ``merged=True`` → outcome transitions to
      :data:`STATE_MERGED` (only when the source state allows it; if
      the outcome is already merged or terminal, no transition).
    - ``approved`` AND ``merged=False`` → no transition; ``notes``
      reflects "approved but PR not merged in payload".
    - ``changes_requested`` → outcome transitions to
      :data:`STATE_REJECTED_BY_REVIEW`. PR merge state is irrelevant.
    - ``commented`` → no transition; ``notes`` records the comment
      arrived.
    - PR number not found in store → no-op.
    """
    if not isinstance(payload, dict):
        return _malformed("pull_request_review", "payload is not a dict")

    review = payload.get("review") or {}
    pull_request = payload.get("pull_request") or {}
    if not isinstance(review, dict) or not isinstance(pull_request, dict):
        return _malformed(
            "pull_request_review",
            "payload missing 'review' or 'pull_request' dict",
        )

    review_state = (review.get("state") or "").strip().lower()
    pr_number = pull_request.get("number")
    pr_merged = bool(pull_request.get("merged"))

    if review_state not in {
        REVIEW_STATE_APPROVED,
        REVIEW_STATE_CHANGES_REQUESTED,
        REVIEW_STATE_COMMENTED,
    }:
        return _malformed(
            "pull_request_review",
            f"unknown review.state {review_state!r}",
        )
    if not isinstance(pr_number, int):
        return _malformed(
            "pull_request_review",
            "pull_request.number is missing or not an int",
        )

    matched = _find_outcome_by_pr_number(store, pr_number)
    if matched is None:
        _emit(EVENT_FEEDBACK_NO_MATCH, event_type="pull_request_review", pr_number=pr_number)
        return IngestionResult(
            event_type="pull_request_review",
            matched_patch_hash=None,
            state_transition=None,
            notes=f"no outcome with pr_number={pr_number}",
        )

    target_state: Optional[str]
    notes_template: str
    if review_state == REVIEW_STATE_APPROVED:
        if pr_merged:
            target_state = STATE_MERGED
            notes_template = "approved + merged → marking outcome as merged"
        else:
            target_state = None
            notes_template = "approved but pull_request.merged=False; awaiting merge"
    elif review_state == REVIEW_STATE_CHANGES_REQUESTED:
        target_state = STATE_REJECTED_BY_REVIEW
        notes_template = "changes_requested → marking outcome as rejected_by_review"
    else:  # commented
        target_state = None
        notes_template = "review state=commented; no outcome transition"

    return _apply_transition(
        event_type="pull_request_review",
        outcome=matched,
        target_state=target_state,
        store=store,
        notes=notes_template,
    )


def ingest_push_event(
    payload: dict, *, store: RepairOutcomeStore,
) -> IngestionResult:
    """Process a GitHub ``push`` event payload.

    Inputs
    ------
    payload:
        The webhook payload. Honored keys:
          - ``ref`` : str — only ``refs/heads/main`` is acted on.
          - ``commits`` : list[dict] — each with ``id`` (sha) and
            ``message``. The ingestor scans for revert markers
            (``This reverts commit <sha>``) and matches against the
            store's ``commit_sha`` field.
          - ``ci_failure_signature`` : str (optional, NOT a standard
            GitHub field) — supplied by the workflow when CI failed
            on this push. If the signature matches an outcome whose
            current state is ``merged``, the outcome is marked
            regressed.

    Order of detection (a single payload may match multiple signals
    but the FIRST match wins so the result is deterministic):

      1. Revert commit referencing a known SHA.
      2. CI failure signature matching a merged outcome.
    """
    if not isinstance(payload, dict):
        return _malformed("push", "payload is not a dict")

    ref = payload.get("ref")
    if ref != MAIN_REF:
        return IngestionResult(
            event_type="push",
            notes=f"ref={ref!r} is not {MAIN_REF!r}; skipping",
        )

    # 1) Revert detection.
    revert_target = _extract_reverted_sha(payload)
    if revert_target is not None:
        outcome = _find_outcome_by_commit_sha(store, revert_target)
        if outcome is not None:
            return _mark_regressed_via_revert(
                outcome=outcome, store=store, reverted_sha=revert_target,
            )
        _emit(
            EVENT_FEEDBACK_NO_MATCH,
            event_type="push", reverted_sha=revert_target,
        )

    # 2) Fresh-failure-on-merged-signature detection.
    ci_sig = payload.get("ci_failure_signature")
    if isinstance(ci_sig, str) and ci_sig:
        merged = _find_merged_outcome_by_signature(store, ci_sig)
        if merged is not None:
            return _mark_regressed_via_ci(
                outcome=merged, store=store, signature=ci_sig,
            )
        _emit(
            EVENT_FEEDBACK_NO_MATCH,
            event_type="push", failure_signature=ci_sig,
        )

    return IngestionResult(
        event_type="push",
        matched_patch_hash=None,
        state_transition=None,
        notes="no revert or ci-failure-signature match in payload",
    )


# ── Internals ──────────────────────────────────────────────────────────


_REVERT_SHA_RE = re.compile(
    r"This reverts commit ([0-9a-fA-F]{7,40})", re.MULTILINE,
)


def _find_outcome_by_pr_number(
    store: RepairOutcomeStore, pr_number: int,
) -> Optional[RepairOutcome]:
    """Walk the JSONL log and return the latest record matching
    ``pr_number``. Latest = last-written; this is the right view of
    the ledger because lifecycle updates are append-only and the
    final entry is the current state.
    """
    latest: Optional[RepairOutcome] = None
    for entry in store._iter_records():
        if entry.pr_number == pr_number:
            latest = entry
    return latest


def _find_outcome_by_commit_sha(
    store: RepairOutcomeStore, sha: str,
) -> Optional[RepairOutcome]:
    """Find the latest outcome whose ``commit_sha`` matches ``sha``.

    Treats short shas (≥ 7 hex chars) as prefixes — that's the GitHub
    convention for revert messages. We accept either full or
    abbreviated identifiers.
    """
    sha = (sha or "").strip().lower()
    if not sha:
        return None
    latest: Optional[RepairOutcome] = None
    for entry in store._iter_records():
        cs = (entry.commit_sha or "").strip().lower()
        if not cs:
            continue
        if cs == sha or cs.startswith(sha) or sha.startswith(cs):
            latest = entry
    return latest


def _find_merged_outcome_by_signature(
    store: RepairOutcomeStore, signature: str,
) -> Optional[RepairOutcome]:
    """Find the latest outcome with ``failure_signature == signature``
    whose current state is :data:`STATE_MERGED`."""
    latest: Optional[RepairOutcome] = None
    for entry in store._iter_records():
        if entry.failure_signature == signature \
                and entry.outcome_state == STATE_MERGED:
            latest = entry
    return latest


def _extract_reverted_sha(payload: dict) -> Optional[str]:
    """Pull the SHA out of a revert commit message anywhere in the
    push payload. Returns ``None`` when no revert marker is present.
    """
    commits = payload.get("commits")
    if not isinstance(commits, list):
        commits = []
    head_commit = payload.get("head_commit")
    if isinstance(head_commit, dict):
        commits = list(commits) + [head_commit]
    for c in commits:
        if not isinstance(c, dict):
            continue
        msg = c.get("message")
        if not isinstance(msg, str):
            continue
        m = _REVERT_SHA_RE.search(msg)
        if m:
            return m.group(1).lower()
    return None


def _apply_transition(
    *,
    event_type: str,
    outcome: RepairOutcome,
    target_state: Optional[str],
    store: RepairOutcomeStore,
    notes: str,
) -> IngestionResult:
    """Centralised state-transition + idempotency check.

    If ``target_state`` is ``None`` or already equals the outcome's
    current state, we record the no-op and return without writing.
    Otherwise, we attempt the transition; if the state machine refuses
    it (terminal source, unknown target), we capture the refusal in
    ``notes`` and return without writing.
    """
    if target_state is None:
        _emit(
            EVENT_FEEDBACK_INGESTED,
            event_type=event_type,
            patch_hash=outcome.patch_hash,
            transitioned=False,
        )
        return IngestionResult(
            event_type=event_type,
            matched_patch_hash=outcome.patch_hash,
            state_transition=None,
            notes=notes,
        )

    if outcome.outcome_state == target_state:
        _emit(
            EVENT_FEEDBACK_INGESTED,
            event_type=event_type,
            patch_hash=outcome.patch_hash,
            transitioned=False,
        )
        return IngestionResult(
            event_type=event_type,
            matched_patch_hash=outcome.patch_hash,
            state_transition=None,
            notes=(
                f"already in target state {target_state!r}; idempotent no-op"
            ),
        )

    allowed = TRANSITIONS.get(outcome.outcome_state, frozenset())
    if target_state not in allowed:
        return IngestionResult(
            event_type=event_type,
            matched_patch_hash=outcome.patch_hash,
            state_transition=None,
            notes=(
                f"state machine refuses {outcome.outcome_state!r} → "
                f"{target_state!r} (allowed: {sorted(allowed) or 'terminal'})"
            ),
        )

    try:
        store.update_outcome(
            outcome.patch_hash, outcome_state=target_state,
        )
    except Exception as e:
        _log.warning(
            "update_outcome failed for patch_hash=%s: %s",
            outcome.patch_hash, e,
        )
        return IngestionResult(
            event_type=event_type,
            matched_patch_hash=outcome.patch_hash,
            state_transition=None,
            notes=f"store update failed: {e}",
        )

    _emit(
        EVENT_FEEDBACK_INGESTED,
        event_type=event_type,
        patch_hash=outcome.patch_hash,
        from_state=outcome.outcome_state,
        to_state=target_state,
        transitioned=True,
    )
    return IngestionResult(
        event_type=event_type,
        matched_patch_hash=outcome.patch_hash,
        state_transition=(outcome.outcome_state, target_state),
        notes=notes,
    )


def _mark_regressed_via_revert(
    *,
    outcome: RepairOutcome,
    store: RepairOutcomeStore,
    reverted_sha: str,
) -> IngestionResult:
    """Specialisation of the transition path for revert detection.

    Uses :meth:`RepairOutcomeStore.mark_regressed` so the
    ``regression_detected_at`` timestamp lands alongside the state
    change in a single atomic update.
    """
    if outcome.outcome_state == STATE_REGRESSED:
        return IngestionResult(
            event_type="push",
            matched_patch_hash=outcome.patch_hash,
            state_transition=None,
            notes=f"already regressed; revert of {reverted_sha} is idempotent no-op",
        )

    allowed = TRANSITIONS.get(outcome.outcome_state, frozenset())
    if STATE_REGRESSED not in allowed:
        return IngestionResult(
            event_type="push",
            matched_patch_hash=outcome.patch_hash,
            state_transition=None,
            notes=(
                f"state machine refuses {outcome.outcome_state!r} → "
                f"regressed (allowed: {sorted(allowed) or 'terminal'})"
            ),
        )

    now = datetime.now(timezone.utc)
    try:
        store.mark_regressed(outcome.patch_hash, now)
    except Exception as e:
        _log.warning(
            "mark_regressed failed for patch_hash=%s: %s",
            outcome.patch_hash, e,
        )
        return IngestionResult(
            event_type="push",
            matched_patch_hash=outcome.patch_hash,
            state_transition=None,
            notes=f"store update failed: {e}",
        )

    _emit(
        EVENT_FEEDBACK_INGESTED,
        event_type="push",
        patch_hash=outcome.patch_hash,
        reverted_sha=reverted_sha,
        from_state=outcome.outcome_state,
        to_state=STATE_REGRESSED,
        transitioned=True,
    )
    return IngestionResult(
        event_type="push",
        matched_patch_hash=outcome.patch_hash,
        state_transition=(outcome.outcome_state, STATE_REGRESSED),
        notes=f"revert of {reverted_sha} → marked regressed",
    )


def _mark_regressed_via_ci(
    *,
    outcome: RepairOutcome,
    store: RepairOutcomeStore,
    signature: str,
) -> IngestionResult:
    """Specialisation for the CI-failure-on-merged-signature path."""
    # Source state is merged by construction; transition to regressed
    # is allowed by the state machine.
    now = datetime.now(timezone.utc)
    try:
        store.mark_regressed(outcome.patch_hash, now)
    except Exception as e:
        _log.warning(
            "mark_regressed failed for patch_hash=%s: %s",
            outcome.patch_hash, e,
        )
        return IngestionResult(
            event_type="push",
            matched_patch_hash=outcome.patch_hash,
            state_transition=None,
            notes=f"store update failed: {e}",
        )

    _emit(
        EVENT_FEEDBACK_INGESTED,
        event_type="push",
        patch_hash=outcome.patch_hash,
        ci_failure_signature=signature,
        from_state=STATE_MERGED,
        to_state=STATE_REGRESSED,
        transitioned=True,
    )
    return IngestionResult(
        event_type="push",
        matched_patch_hash=outcome.patch_hash,
        state_transition=(STATE_MERGED, STATE_REGRESSED),
        notes=f"CI failure signature {signature[:16]} on merged outcome → regressed",
    )


def _malformed(event_type: str, reason: str) -> IngestionResult:
    """Build a no-write result describing a malformed payload."""
    _emit(EVENT_FEEDBACK_MALFORMED, event_type=event_type, reason=reason)
    return IngestionResult(
        event_type=event_type,
        matched_patch_hash=None,
        state_transition=None,
        notes=f"malformed payload: {reason}",
    )


def _emit(kind: str, **md: Any) -> None:
    """Forward a telemetry event to the active collector. No-op when
    none is bound or the import fails. ``kind`` is the telemetry event
    type; we don't name the param ``event_type`` because callers pass
    ``event_type`` as METADATA (which entity the feedback was for) and
    that would collide with the positional arg."""
    try:
        from ..telemetry import get_current_telemetry
    except Exception:  # pragma: no cover
        return
    col = get_current_telemetry()
    if col is None:
        return
    try:
        col.emit(kind, **md)
    except Exception:  # pragma: no cover
        _log.debug("feedback telemetry emit failed", exc_info=True)


__all__ = [
    "IngestionResult",
    "ingest_pr_review",
    "ingest_push_event",
    # Telemetry
    "EVENT_FEEDBACK_INGESTED", "EVENT_FEEDBACK_NO_MATCH",
    "EVENT_FEEDBACK_MALFORMED",
    # Constants
    "MAIN_REF",
    "REVIEW_STATE_APPROVED", "REVIEW_STATE_CHANGES_REQUESTED",
    "REVIEW_STATE_COMMENTED",
]
