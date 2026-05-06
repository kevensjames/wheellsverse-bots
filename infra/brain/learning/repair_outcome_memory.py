"""Repair-outcome memory — the learning kernel for the autonomous CI repair pipeline.

Phase D of the audit follow-up roadmap. Where :mod:`infra.brain.learning.repair_memory`
is a *pre-apply* heuristic gate (decides whether to apply a candidate
patch), this module is a *post-apply* outcome ledger. Every patch the
pipeline applies — regardless of whether it merges, gets reverted, or
regresses later — leaves a record here keyed by ``(failure_signature,
patch_hash)``. Future repair decisions can read this ledger to:

  * weight candidate patches by their historical merge-and-stay-green rate,
  * detect signatures that have repeatedly regressed and escalate them
    to human review,
  * surface "this fix worked once but was reverted" signals that the
    pre-apply gate alone cannot see.

This module ships the **kernel only**. The wiring that has
:func:`infra.brain.debug.ci_autonomous_repair.attempt_repair` and
:class:`infra.brain.debug.repair_generator.RepairGenerator` consult it
is intentionally a separate, reviewable patch (Phase E or later).

Storage
-------

Append-only JSONL at :data:`DEFAULT_OUTCOMES_PATH` (default
``state/repair_outcomes.jsonl``). Mirrors the disk shape of
:mod:`repair_memory` so operators have one mental model for both
ledgers — inspect with ``cat`` / ``jq``, diff in version control,
crash-safe (partial trailing writes are dropped on the next read).

Each line is a :class:`RepairOutcome` round-tripped through
:meth:`RepairOutcome.to_dict` / :meth:`RepairOutcome.from_dict`.

State machine
-------------

Outcomes evolve through a small explicit state machine. The diagram::

    ┌──────────────────┐
    │  rejected_by_    │   terminal — patch never reached the tree
    │  validation       │
    └──────────────────┘

    ┌──────────────────┐
    │     applied      │ ─── merged ─── reverted | regressed (terminal)
    │                  │ ─── reverted (terminal)
    │                  │ ─── regressed (terminal)
    │                  │ ─── rejected_by_review (terminal)
    └──────────────────┘

    ┌──────────────────┐
    │     merged       │ ─── reverted | regressed (terminal)
    └──────────────────┘

    rejected_by_review / reverted / regressed are all terminal.

Concurrency
-----------

All operations on a single :class:`RepairOutcomeStore` instance are
thread-safe (one re-entrant lock around the file). **Cross-process
writes are NOT safe** — POSIX append atomicity is roughly 4 KB and a
serialised :class:`RepairOutcome` can exceed that when patches are
large. Production deployments that fan repair work across multiple
processes should either (a) funnel writes through a single owner, or
(b) gate this module behind the SQLite index option (see
``sqlite_index_path`` constructor arg) — Phase E will fill in the
SQLite implementation, the API + flag are present here so callers
don't need to change.

Public API
----------

    >>> store = RepairOutcomeStore()
    >>> store.record_outcome(RepairOutcome(
    ...     failure_signature="abc123",
    ...     patch_hash="def456",
    ...     applied_at="2026-05-05T22:00:00+00:00",
    ...     outcome_state=STATE_APPLIED,
    ...     outcome_observed_at="2026-05-05T22:00:00+00:00",
    ... ))
    >>> store.update_outcome("def456", outcome_state=STATE_MERGED, pr_number=42)
    True
    >>> store.get_recurrence_count("abc123")
    1
"""
from __future__ import annotations

import dataclasses
import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Re-export the existing hash helpers — callers should not invent their
# own. This keeps signature stability across the two ledgers.
from .repair_memory import compute_failure_signature, patch_signature


_log = logging.getLogger("infra.brain.learning.repair_outcome_memory")


# ── Tunables / constants ────────────────────────────────────────────────


DEFAULT_OUTCOMES_PATH: str = "state/repair_outcomes.jsonl"
"""On-disk JSONL log location. Append-only, line-delimited."""

DEFAULT_QUERY_LIMIT: int = 10


# ── Outcome state vocabulary + state machine ───────────────────────────


STATE_APPLIED:                str = "applied"
STATE_REJECTED_BY_VALIDATION: str = "rejected_by_validation"
STATE_REJECTED_BY_REVIEW:     str = "rejected_by_review"
STATE_MERGED:                 str = "merged"
STATE_REVERTED:               str = "reverted"
STATE_REGRESSED:              str = "regressed"


OUTCOME_STATES: frozenset[str] = frozenset({
    STATE_APPLIED,
    STATE_REJECTED_BY_VALIDATION,
    STATE_REJECTED_BY_REVIEW,
    STATE_MERGED,
    STATE_REVERTED,
    STATE_REGRESSED,
})


#: Allowed transitions: current → set of next states. Anything not listed
#: is rejected by :func:`_validate_transition`. Terminal states map to
#: empty frozensets — they admit no outbound transitions.
TRANSITIONS: dict[str, frozenset[str]] = {
    STATE_APPLIED: frozenset({
        STATE_MERGED,
        STATE_REVERTED,
        STATE_REGRESSED,
        STATE_REJECTED_BY_REVIEW,
    }),
    STATE_MERGED: frozenset({
        STATE_REVERTED,
        STATE_REGRESSED,
    }),
    # Terminal states.
    STATE_REJECTED_BY_VALIDATION: frozenset(),
    STATE_REJECTED_BY_REVIEW:     frozenset(),
    STATE_REVERTED:               frozenset(),
    STATE_REGRESSED:              frozenset(),
}


# Telemetry event types — bare strings, consumed by the existing
# :class:`infra.brain.telemetry.collector.TelemetryCollector`. Not added
# to ``events.KNOWN_EVENT_TYPES`` because that file's docstring explicitly
# permits custom strings ("any custom string for plug-in events; stable
# strings are encouraged but not enforced").
EVENT_OUTCOME_RECORDED:      str = "repair_outcome_recorded"
EVENT_OUTCOME_STATE_CHANGED: str = "repair_outcome_state_changed"


# ── RepairOutcome dataclass ─────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class RepairOutcome:
    """Frozen record of a single repair attempt's lifecycle so far.

    Fields
    ------
    failure_signature:
        16-hex-char hash from
        :func:`infra.brain.learning.repair_memory.compute_failure_signature`.
        Buckets equivalent failures across signatures.
    patch_hash:
        16-hex-char hash from
        :func:`infra.brain.learning.repair_memory.patch_signature`.
        Identifies a unique patch instance — supersedes the patch_diff
        body in queries and indexes.
    applied_at:
        UTC ISO 8601 timestamp of when the patch first landed in the
        working tree (or, for ``rejected_by_validation``, when the apply
        was attempted and refused).
    outcome_state:
        Current state — one of :data:`OUTCOME_STATES`. The state machine
        in :data:`TRANSITIONS` constrains :meth:`update_outcome`.
    outcome_observed_at:
        UTC ISO 8601 timestamp of the most recent state transition.
        On the initial :meth:`record_outcome` this is typically equal
        to ``applied_at``.
    commit_sha:
        Git SHA the patch landed on. ``None`` for pre-apply rejection.
    pr_number:
        GitHub PR number if a PR was opened. ``None`` otherwise.
    recurrence_count:
        Snapshot of how many times the same ``failure_signature`` had
        been seen at the moment this entry was created. Use
        :meth:`RepairOutcomeStore.get_recurrence_count` for the live count.
    stability_score:
        Rolling fraction of stability reruns that passed (0..1). ``None``
        until the first rerun completes.
    regression_detected_at:
        UTC ISO 8601 timestamp when a post-merge regression on this
        signature was first observed. ``None`` while no regression
        signal has fired.
    """

    failure_signature: str
    patch_hash: str
    applied_at: str
    outcome_state: str
    outcome_observed_at: str
    commit_sha: Optional[str] = None
    pr_number: Optional[int] = None
    recurrence_count: int = 0
    stability_score: Optional[float] = None
    regression_detected_at: Optional[str] = None

    def to_dict(self) -> dict:
        """JSON-friendly representation. Round-trips losslessly through
        :meth:`from_dict`."""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "RepairOutcome":
        """Construct from a parsed JSON object. Tolerates extra keys
        (forward-compat: future fields just get dropped here)."""
        if not isinstance(data, dict):
            raise TypeError(
                f"from_dict expected dict, got {type(data).__name__}"
            )
        valid_fields = {f.name for f in dataclasses.fields(cls)}
        kwargs = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**kwargs)


# ── Validation helpers ─────────────────────────────────────────────────


def _validate_transition(current: str, target: str) -> None:
    """Raise :class:`ValueError` if ``current → target`` is not allowed."""
    if target not in OUTCOME_STATES:
        raise ValueError(
            f"unknown outcome state: {target!r} "
            f"(expected one of {sorted(OUTCOME_STATES)})"
        )
    allowed = TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise ValueError(
            f"invalid state transition {current!r} → {target!r} "
            f"(allowed from {current!r}: "
            f"{sorted(allowed) if allowed else '∅ (terminal)'})"
        )


def _now_iso() -> str:
    """Current UTC time as ISO 8601, matching repair_memory's format."""
    return datetime.now(timezone.utc).isoformat()


def _emit(event_type: str, **md: Any) -> None:
    """Forward a telemetry event to the active collector, if any.

    Resolves the collector via the ContextVar bridge in
    :mod:`infra.brain.telemetry.collector`. No-op when no client has an
    ``activate()`` scope open — this lets the module run in tests + admin
    scripts without a brain client wired up. The ``record(event)`` call
    inside the collector is itself a no-op when telemetry is disabled.
    """
    try:
        from ..telemetry import get_current_telemetry
    except Exception:  # pragma: no cover — telemetry import failure shouldn't crash recording
        return
    collector = get_current_telemetry()
    if collector is None:
        return
    try:
        collector.emit(event_type, **md)
    except Exception:  # pragma: no cover — telemetry MUST NOT break recording
        _log.debug("telemetry emit failed for %s", event_type, exc_info=True)


# ── Store ──────────────────────────────────────────────────────────────


class RepairOutcomeStore:
    """JSONL-backed ledger of repair-outcome lifecycle records.

    Operations are thread-safe inside a single instance via a re-entrant
    lock. Cross-process write atomicity is documented as a known
    limitation — see the module docstring.

    The ``sqlite_index_path`` argument is reserved for Phase E. Passing
    a non-None value today raises :class:`NotImplementedError` rather
    than silently doing nothing; callers must opt in deliberately.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        sqlite_index_path: Optional[Path] = None,
    ) -> None:
        self.path = Path(path) if path else Path(DEFAULT_OUTCOMES_PATH)
        if sqlite_index_path is not None:
            # Reserved for Phase E. The flag exists here so the public
            # API stays stable across the rollout — callers passing the
            # arg today get a precise error, not a silent no-op.
            raise NotImplementedError(
                "sqlite_index_path is reserved for Phase E; pass None today."
            )
        self._sqlite_index_path: Optional[Path] = None
        self._lock = threading.RLock()

    # ── Recording ──────────────────────────────────────────────────

    def record_outcome(self, entry: RepairOutcome) -> None:
        """Append a fresh outcome record to the JSONL log.

        ``entry.outcome_state`` must be in :data:`OUTCOME_STATES`. No
        state-machine validation is performed here — :meth:`update_outcome`
        is where transitions are gated. The first record for a given
        ``patch_hash`` is the *initial* state and may be any valid state
        (e.g. a patch can be born ``rejected_by_validation`` if the
        upstream gauntlet refused it).
        """
        if not isinstance(entry, RepairOutcome):
            raise TypeError(
                f"entry must be a RepairOutcome, got {type(entry).__name__}"
            )
        if entry.outcome_state not in OUTCOME_STATES:
            raise ValueError(
                f"unknown outcome state: {entry.outcome_state!r}"
            )

        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(
                entry.to_dict(), default=str, ensure_ascii=False,
            ) + "\n"
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)

        _emit(
            EVENT_OUTCOME_RECORDED,
            failure_signature=entry.failure_signature,
            patch_hash=entry.patch_hash,
            outcome_state=entry.outcome_state,
        )

    # ── Updating (state transitions) ───────────────────────────────

    def update_outcome(self, patch_hash: str, **fields: Any) -> bool:
        """Append a new entry that updates the latest record for
        ``patch_hash``.

        Behavior:

          * Looks up the latest existing entry by ``patch_hash``.
            Returns ``False`` if no entry exists.
          * If ``outcome_state`` is in ``fields``, validates the
            transition against :data:`TRANSITIONS` — raises
            :class:`ValueError` for an illegal step.
          * Builds a new :class:`RepairOutcome` by merging the existing
            entry with ``fields`` (dataclasses.replace semantics).
          * Sets ``outcome_observed_at`` to ``fields["outcome_observed_at"]``
            if the caller passed it, otherwise to "now".
          * Appends the new record. Returns ``True``.

        Concurrency: holds the lock across read + append so the
        latest-entry view is consistent. Other processes may still
        race (see module docstring).
        """
        with self._lock:
            latest = self._latest_for_patch(patch_hash)
            if latest is None:
                return False

            target_state = fields.get("outcome_state", latest.outcome_state)
            if target_state != latest.outcome_state:
                _validate_transition(latest.outcome_state, target_state)

            # Merge: caller-provided fields win. Always refresh
            # outcome_observed_at unless the caller pinned it.
            updates = dict(fields)
            updates.setdefault("outcome_observed_at", _now_iso())

            try:
                new_entry = dataclasses.replace(latest, **updates)
            except TypeError as e:
                raise ValueError(f"unknown field in update: {e}") from e

            line = json.dumps(
                new_entry.to_dict(), default=str, ensure_ascii=False,
            ) + "\n"
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)

        if target_state != latest.outcome_state:
            _emit(
                EVENT_OUTCOME_STATE_CHANGED,
                failure_signature=new_entry.failure_signature,
                patch_hash=patch_hash,
                from_state=latest.outcome_state,
                to_state=target_state,
            )
        return True

    def mark_regressed(
        self, patch_hash: str, observed_at: datetime,
    ) -> bool:
        """Convenience wrapper around :meth:`update_outcome`.

        Transitions the latest entry for ``patch_hash`` to
        :data:`STATE_REGRESSED` and stamps ``regression_detected_at``.
        Returns ``False`` if the entry doesn't exist; raises
        :class:`ValueError` if the current state doesn't permit the
        transition (only ``applied`` and ``merged`` do).
        """
        if not isinstance(observed_at, datetime):
            raise TypeError(
                f"observed_at must be datetime, got {type(observed_at).__name__}"
            )
        if observed_at.tzinfo is None:
            # Treat naive datetimes as UTC — mirror the rest of the repo's
            # ISO-with-tzinfo convention without surprising callers that
            # pass utcnow().
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        iso = observed_at.isoformat()
        return self.update_outcome(
            patch_hash,
            outcome_state=STATE_REGRESSED,
            regression_detected_at=iso,
            outcome_observed_at=iso,
        )

    # ── Reading ────────────────────────────────────────────────────

    def query_by_signature(
        self, signature: str, limit: int = DEFAULT_QUERY_LIMIT,
    ) -> list[RepairOutcome]:
        """Return up to ``limit`` outcomes matching ``signature``,
        most-recent-first by file order (later in the JSONL = newer)."""
        if limit < 1:
            return []
        out: list[RepairOutcome] = []
        for entry in self._iter_records():
            if entry.failure_signature == signature:
                out.append(entry)
        # Most-recent-first: reverse the file-order list, then truncate.
        out.reverse()
        return out[:limit]

    def get_stability_score(self, signature: str) -> Optional[float]:
        """Mean ``stability_score`` across entries with ``signature``.

        Returns ``None`` if no entry for that signature has a
        non-``None`` ``stability_score`` (cold start). Empty file →
        also ``None``.
        """
        scores: list[float] = []
        for entry in self._iter_records():
            if entry.failure_signature != signature:
                continue
            if entry.stability_score is None:
                continue
            try:
                scores.append(float(entry.stability_score))
            except (TypeError, ValueError):
                continue
        if not scores:
            return None
        return sum(scores) / len(scores)

    def get_recurrence_count(self, signature: str) -> int:
        """Total entries (across all patch_hashes) with ``signature``.

        Counts every ledger record — a single patch updated five times
        contributes 5. That matches the "how many times this signature
        was seen since the entry was created" semantics in the
        :class:`RepairOutcome.recurrence_count` snapshot field.
        """
        return sum(
            1 for entry in self._iter_records()
            if entry.failure_signature == signature
        )

    # ── Internals ──────────────────────────────────────────────────

    def _iter_records(self):
        """Yield every well-formed record from the JSONL log.

        Malformed lines are skipped with a logged warning (per the
        module's "JSONL corruption tolerance" contract). The file may
        not exist yet; in that case we yield nothing.
        """
        if not self.path.exists():
            return
        with self._lock:
            with self.path.open("r", encoding="utf-8") as f:
                for lineno, raw in enumerate(f, start=1):
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError as e:
                        _log.warning(
                            "skipping malformed JSONL line %s:%d (%s)",
                            self.path, lineno, e,
                        )
                        continue
                    try:
                        yield RepairOutcome.from_dict(obj)
                    except (TypeError, ValueError) as e:
                        _log.warning(
                            "skipping invalid outcome record at %s:%d (%s)",
                            self.path, lineno, e,
                        )
                        continue

    def _latest_for_patch(self, patch_hash: str) -> Optional[RepairOutcome]:
        """Return the most recently written record for ``patch_hash``,
        or ``None``. Caller must hold the lock when correctness against
        concurrent writes matters."""
        latest: Optional[RepairOutcome] = None
        for entry in self._iter_records():
            if entry.patch_hash == patch_hash:
                latest = entry
        return latest


__all__ = [
    # Class + dataclass
    "RepairOutcomeStore",
    "RepairOutcome",
    # State vocabulary
    "STATE_APPLIED", "STATE_REJECTED_BY_VALIDATION",
    "STATE_REJECTED_BY_REVIEW", "STATE_MERGED",
    "STATE_REVERTED", "STATE_REGRESSED",
    "OUTCOME_STATES", "TRANSITIONS",
    # Hash helpers re-exported for caller convenience
    "compute_failure_signature", "patch_signature",
    # Telemetry event types
    "EVENT_OUTCOME_RECORDED", "EVENT_OUTCOME_STATE_CHANGED",
    # Tunables
    "DEFAULT_OUTCOMES_PATH", "DEFAULT_QUERY_LIMIT",
]
