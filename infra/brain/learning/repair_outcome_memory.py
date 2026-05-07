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
import sqlite3
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
EVENT_OUTCOME_INDEX_DROPPED: str = "repair_outcome_index_dropped"
EVENT_OUTCOME_INDEX_REBUILT: str = "repair_outcome_index_rebuilt"


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
    # Phase G addition (2026-05-06): tool names this outcome touched,
    # used by ``PolicyEvolver`` for per-tool restriction decisions.
    # Default empty tuple so existing fixtures, JSONL lines, and
    # callers all stay byte-compatible — Phase D's ``from_dict``
    # already filters on declared fields. Outcomes that don't tag
    # the tools they used contribute zero to per-tool evolver stats.
    touched_tools: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        """JSON-friendly representation. Round-trips losslessly through
        :meth:`from_dict`. ``touched_tools`` is serialised as a JSON
        array (tuples don't survive json.dumps directly)."""
        d = dataclasses.asdict(self)
        d["touched_tools"] = list(self.touched_tools)
        return d

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
        # touched_tools may arrive as a list (from JSON) — coerce to tuple
        # so the dataclass stays hashable + frozen-correct.
        if "touched_tools" in kwargs and isinstance(kwargs["touched_tools"], list):
            kwargs["touched_tools"] = tuple(kwargs["touched_tools"])
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


# ── SQLite index (Phase E.1) ────────────────────────────────────────────


_SQLITE_SCHEMA: str = """
CREATE TABLE IF NOT EXISTS outcomes (
    patch_hash TEXT PRIMARY KEY,
    failure_signature TEXT NOT NULL,
    outcome_state TEXT NOT NULL,
    applied_at TEXT NOT NULL,
    regression_detected_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outcomes_signature
    ON outcomes(failure_signature);
CREATE INDEX IF NOT EXISTS idx_outcomes_state
    ON outcomes(outcome_state);
"""


class _SqliteIndex:
    """Optional secondary index over the JSONL store.

    JSONL is the source of truth (durability + auditability); this index
    is a derived view, regenerable from JSONL via
    :meth:`RepairOutcomeStore.rebuild_index`. Schema is keys-only — no
    patch bodies, no PII (per the audit boundary):

        outcomes(
            patch_hash TEXT PRIMARY KEY,
            failure_signature TEXT INDEXED,
            outcome_state TEXT INDEXED,
            applied_at TEXT,
            regression_detected_at TEXT
        )

    One row per patch_hash — the index tracks the *latest* state for each
    distinct patch. This is deliberate: the index answers "how many
    distinct patches has this signature spawned?" with O(log N) instead
    of full-file scan.

    Concurrency:
      * Same-process: serialised behind ``RepairOutcomeStore``'s
        :class:`threading.RLock`. The index uses ``BEGIN IMMEDIATE`` so
        SQLite gives us write-write serialisation across threads of
        the same process even when the lock is dropped briefly.
      * Cross-process: NOT safe. Same hazard as JSONL appends — operators
        running multiple workers should funnel writes through one owner.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # ``isolation_level=None`` puts SQLite in autocommit mode so
            # we control transactions explicitly via ``BEGIN IMMEDIATE``.
            conn = sqlite3.connect(
                str(self.path),
                isolation_level=None,
                check_same_thread=False,
                timeout=10.0,
            )
            conn.executescript(_SQLITE_SCHEMA)
            self._conn = conn
        return self._conn

    def upsert(self, entry: "RepairOutcome") -> None:
        """Insert-or-update a single outcome row."""
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                INSERT INTO outcomes (
                    patch_hash, failure_signature, outcome_state,
                    applied_at, regression_detected_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(patch_hash) DO UPDATE SET
                    failure_signature      = excluded.failure_signature,
                    outcome_state          = excluded.outcome_state,
                    applied_at             = excluded.applied_at,
                    regression_detected_at = excluded.regression_detected_at
                """,
                (
                    entry.patch_hash,
                    entry.failure_signature,
                    entry.outcome_state,
                    entry.applied_at,
                    entry.regression_detected_at,
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def query_patch_hashes_by_signature(
        self, signature: str, limit: int,
    ) -> list[str]:
        """Return up to ``limit`` patch_hashes for ``signature``,
        most-recently-applied first."""
        if limit < 1:
            return []
        conn = self._connect()
        cursor = conn.execute(
            "SELECT patch_hash FROM outcomes "
            "WHERE failure_signature = ? "
            "ORDER BY applied_at DESC, patch_hash DESC "
            "LIMIT ?",
            (signature, limit),
        )
        return [row[0] for row in cursor.fetchall()]

    def count_by_signature(self, signature: str) -> int:
        """Distinct-patch count for ``signature``."""
        conn = self._connect()
        cursor = conn.execute(
            "SELECT COUNT(*) FROM outcomes WHERE failure_signature = ?",
            (signature,),
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def truncate(self) -> None:
        """Remove every row. Used by :meth:`RepairOutcomeStore.rebuild_index`."""
        conn = self._connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM outcomes")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:  # pragma: no cover
                pass
            self._conn = None


# ── Store ──────────────────────────────────────────────────────────────


class RepairOutcomeStore:
    """JSONL-backed ledger of repair-outcome lifecycle records.

    Operations are thread-safe inside a single instance via a re-entrant
    lock. Cross-process write atomicity is documented as a known
    limitation — see the module docstring.

    Optional secondary index (Phase E.1): pass ``sqlite_index_path`` to
    enable a SQLite-backed index over the JSONL log. The index is a
    derived view (regenerable via :meth:`rebuild_index`) — JSONL stays
    the source of truth. SQLite-write failures degrade gracefully: the
    index is dropped for the rest of the process and queries fall back
    to JSONL scan. Default ``None`` keeps the original Phase D behavior.
    """

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        sqlite_index_path: Optional[Path] = None,
    ) -> None:
        self.path = Path(path) if path else Path(DEFAULT_OUTCOMES_PATH)
        self._sqlite_index: Optional[_SqliteIndex] = None
        if sqlite_index_path is not None:
            try:
                idx = _SqliteIndex(Path(sqlite_index_path))
                # Eagerly touch the connection so a borked path fails fast
                # at construction rather than on the first write.
                idx._connect()
                self._sqlite_index = idx
            except Exception as e:
                _log.warning(
                    "sqlite index init failed for %s: %s — falling back "
                    "to JSONL only", sqlite_index_path, e,
                )
                self._sqlite_index = None
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
            # Phase E.1: best-effort secondary index. JSONL is the source
            # of truth — if SQLite stumbles we drop the index for this
            # process and continue.
            self._index_upsert_or_drop(entry)

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
            # Phase E.1: keep the index aligned. Same best-effort policy
            # as record_outcome — JSONL stays the source of truth.
            self._index_upsert_or_drop(new_entry)

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
        most-recent-first by file order (later in the JSONL = newer).

        When the SQLite index is enabled, the candidate ``patch_hash``
        set is fetched from the index first (O(log N) on the signature
        column) and the JSONL scan filters to only those rows. JSONL is
        still the materialisation source so ``stability_score``,
        ``commit_sha`` and other non-indexed fields round-trip correctly.
        """
        if limit < 1:
            return []
        if self._sqlite_index is not None:
            try:
                wanted = self._sqlite_index.query_patch_hashes_by_signature(
                    signature, limit,
                )
                if not wanted:
                    return []
                wanted_set = set(wanted)
                # Walk JSONL once, keep the latest record per matching
                # patch_hash so multi-update entries collapse correctly.
                latest_per: dict[str, RepairOutcome] = {}
                for entry in self._iter_records():
                    if entry.patch_hash in wanted_set:
                        latest_per[entry.patch_hash] = entry
                # Return in the SQLite ordering (most-recent-applied first).
                return [latest_per[h] for h in wanted if h in latest_per]
            except Exception as e:
                _log.warning(
                    "sqlite query_by_signature failed; dropping index "
                    "and falling back to scan: %s", e,
                )
                self._drop_index()
        # Unindexed path — full JSONL scan.
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
        """Distinct-patch count for ``signature``.

        Phase E correctness fix: previously this counted every JSONL
        line with a matching signature, which over-counted lifecycle
        updates (a single patch transitioned applied→merged contributed
        2 to the count). The semantic intent — and the docstring on
        :class:`RepairOutcome.recurrence_count` — is "how many times
        this signature has been *seen*", which means *distinct patches
        attempted*. State-machine updates on the same patch are not
        new sightings.

        Both indexed and unindexed paths return the same answer.
        """
        if self._sqlite_index is not None:
            try:
                return self._sqlite_index.count_by_signature(signature)
            except Exception as e:
                _log.warning(
                    "sqlite count_by_signature failed; dropping index "
                    "and falling back to scan: %s", e,
                )
                self._drop_index()
        seen: set[str] = set()
        for entry in self._iter_records():
            if entry.failure_signature == signature:
                seen.add(entry.patch_hash)
        return len(seen)

    # ── Index maintenance (Phase E.1) ───────────────────────────────

    def rebuild_index(self) -> int:
        """Drop and replay the SQLite index from JSONL. No-op when no
        index is configured. Returns the number of rows reloaded.

        Use after a process detects the SQLite file is corrupt, after a
        failed write that dropped the in-memory handle, or as a
        scheduled cron job for long-running deployments.
        """
        if self._sqlite_index is None:
            return 0
        with self._lock:
            try:
                self._sqlite_index.truncate()
            except Exception as e:
                _log.warning(
                    "sqlite truncate failed during rebuild; dropping "
                    "index: %s", e,
                )
                self._drop_index()
                return 0
            # Walk JSONL, take the LATEST entry per patch_hash (the index
            # is one-row-per-patch by design) and upsert.
            latest_per: dict[str, RepairOutcome] = {}
            for entry in self._iter_records():
                latest_per[entry.patch_hash] = entry
            count = 0
            for entry in latest_per.values():
                try:
                    self._sqlite_index.upsert(entry)
                except Exception as e:
                    _log.warning(
                        "sqlite upsert failed mid-rebuild for %s: %s — "
                        "dropping index", entry.patch_hash, e,
                    )
                    self._drop_index()
                    return count
                count += 1
        _emit(EVENT_OUTCOME_INDEX_REBUILT, rows=count)
        return count

    def close(self) -> None:
        """Release the SQLite handle. Safe to call repeatedly. No-op
        when no index is configured."""
        with self._lock:
            if self._sqlite_index is not None:
                self._sqlite_index.close()

    def _index_upsert_or_drop(self, entry: RepairOutcome) -> None:
        """Best-effort SQLite upsert. Caller holds ``self._lock``.
        On any failure: drop the in-memory handle, log a warning, and
        continue — JSONL is the source of truth."""
        if self._sqlite_index is None:
            return
        try:
            self._sqlite_index.upsert(entry)
        except Exception as e:
            _log.warning(
                "sqlite upsert failed for patch_hash=%s: %s — dropping "
                "index for the rest of this process",
                entry.patch_hash, e,
            )
            self._drop_index()

    def _drop_index(self) -> None:
        """Internal: nullify the index handle and emit a telemetry
        beacon. Caller holds ``self._lock``."""
        if self._sqlite_index is None:
            return
        try:
            self._sqlite_index.close()
        except Exception:  # pragma: no cover
            pass
        self._sqlite_index = None
        _emit(EVENT_OUTCOME_INDEX_DROPPED)

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
    "EVENT_OUTCOME_INDEX_DROPPED", "EVENT_OUTCOME_INDEX_REBUILT",
    # Tunables
    "DEFAULT_OUTCOMES_PATH", "DEFAULT_QUERY_LIMIT",
]
