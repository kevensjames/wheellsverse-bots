"""Phase E.1: tests for the SQLite-backed index in
:class:`infra.brain.learning.repair_outcome_memory.RepairOutcomeStore`.

The index is a derived view; JSONL stays the source of truth. These
tests verify:

  * Round-trip: every JSONL write lands as exactly one indexed row.
  * Indexed and unindexed query paths return the same RepairOutcomes
    (parity).
  * ``rebuild_index`` recovers from a wiped/corrupted SQLite file by
    replaying JSONL.
  * SQLite write failures degrade gracefully — the JSONL line is
    committed, the index is dropped for the rest of the process, and
    a warning is logged.
  * Schema is keys-only (no patch text, no PII columns).
  * Updates upsert (one row per patch_hash, latest-state semantics).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from infra.brain.learning.repair_outcome_memory import (
    EVENT_OUTCOME_INDEX_DROPPED,
    EVENT_OUTCOME_INDEX_REBUILT,
    STATE_APPLIED,
    STATE_MERGED,
    STATE_REGRESSED,
    STATE_REVERTED,
    RepairOutcome,
    RepairOutcomeStore,
)


# ── Helpers ─────────────────────────────────────────────────────────────


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


def _indexed(tmp_path: Path) -> RepairOutcomeStore:
    return RepairOutcomeStore(
        path=tmp_path / "outcomes.jsonl",
        sqlite_index_path=tmp_path / "outcomes.sqlite",
    )


def _scan(tmp_path: Path, jsonl_name: str = "outcomes.jsonl") -> RepairOutcomeStore:
    return RepairOutcomeStore(path=tmp_path / jsonl_name)


# ── Initialisation ──────────────────────────────────────────────────────


def test_initialisation_creates_sqlite_file_with_schema(tmp_path):
    store = _indexed(tmp_path)
    sqlite_path = tmp_path / "outcomes.sqlite"
    assert sqlite_path.exists()
    # Inspect schema directly via a separate connection.
    with sqlite3.connect(str(sqlite_path)) as conn:
        cols = [
            r[1] for r in conn.execute(
                "PRAGMA table_info(outcomes)"
            ).fetchall()
        ]
    # Keys-only schema — exactly the 5 columns from the spec.
    assert cols == [
        "patch_hash",
        "failure_signature",
        "outcome_state",
        "applied_at",
        "regression_detected_at",
    ]
    store.close()


def test_initialisation_with_invalid_path_falls_back_silently(
    tmp_path, caplog,
):
    """A path that can't be created (parent is a file, not a dir) must
    not crash construction — the index drops, JSONL keeps working."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    sqlite_path = blocker / "outcomes.sqlite"
    with caplog.at_level(logging.WARNING):
        store = RepairOutcomeStore(
            path=tmp_path / "outcomes.jsonl",
            sqlite_index_path=sqlite_path,
        )
    assert store._sqlite_index is None
    assert any("sqlite index init failed" in r.message for r in caplog.records)


# ── Round-trip ──────────────────────────────────────────────────────────


def test_record_outcome_writes_to_index(tmp_path):
    store = _indexed(tmp_path)
    store.record_outcome(_outcome())
    sqlite_path = tmp_path / "outcomes.sqlite"
    with sqlite3.connect(str(sqlite_path)) as conn:
        rows = conn.execute("SELECT patch_hash, failure_signature, outcome_state FROM outcomes").fetchall()
    assert rows == [("patch_def", "sig_abc", STATE_APPLIED)]
    store.close()


def test_record_outcome_writes_jsonl_first(tmp_path):
    """JSONL line must be persisted even if SQLite later fails."""
    store = _indexed(tmp_path)
    store.record_outcome(_outcome())
    lines = (tmp_path / "outcomes.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["patch_hash"] == "patch_def"
    store.close()


def test_update_outcome_upserts_one_row_per_patch(tmp_path):
    """Update is an upsert — the index keeps a single row per patch_hash
    reflecting the LATEST state, while JSONL accumulates all events."""
    store = _indexed(tmp_path)
    store.record_outcome(_outcome(state=STATE_APPLIED))
    store.update_outcome("patch_def", outcome_state=STATE_MERGED)
    store.update_outcome("patch_def", outcome_state=STATE_REGRESSED)

    sqlite_path = tmp_path / "outcomes.sqlite"
    with sqlite3.connect(str(sqlite_path)) as conn:
        rows = conn.execute(
            "SELECT patch_hash, outcome_state FROM outcomes "
            "WHERE patch_hash=?", ("patch_def",),
        ).fetchall()
    # Exactly one indexed row, latest state.
    assert rows == [("patch_def", STATE_REGRESSED)]
    # And JSONL has all 3 lines (record + 2 updates).
    lines = (tmp_path / "outcomes.jsonl").read_text().splitlines()
    assert len(lines) == 3
    store.close()


def test_mark_regressed_updates_index_regression_field(tmp_path):
    store = _indexed(tmp_path)
    store.record_outcome(_outcome(state=STATE_MERGED))
    ts = datetime(2026, 5, 5, 23, 0, 0, tzinfo=timezone.utc)
    assert store.mark_regressed("patch_def", ts) is True

    sqlite_path = tmp_path / "outcomes.sqlite"
    with sqlite3.connect(str(sqlite_path)) as conn:
        row = conn.execute(
            "SELECT outcome_state, regression_detected_at FROM outcomes "
            "WHERE patch_hash=?", ("patch_def",),
        ).fetchone()
    assert row == (STATE_REGRESSED, ts.isoformat())
    store.close()


# ── Indexed vs scan parity ──────────────────────────────────────────────


@pytest.mark.parametrize("path_kind", ["indexed", "scan"])
def test_query_by_signature_parity(tmp_path, path_kind):
    """Both indexed and scan paths must return the same RepairOutcome
    list for the same JSONL state. Parametrize so a regression in
    either path surfaces clearly."""
    if path_kind == "indexed":
        store = _indexed(tmp_path)
    else:
        store = _scan(tmp_path)
    for i in range(3):
        store.record_outcome(_outcome(
            sig="sig_q",
            patch=f"patch_{i}",
            applied_at=f"2026-05-0{i+1}T00:00:00+00:00",
            observed_at=f"2026-05-0{i+1}T00:00:00+00:00",
        ))
    store.record_outcome(_outcome(sig="other", patch="other_p"))
    found = store.query_by_signature("sig_q")
    assert {r.patch_hash for r in found} == {"patch_0", "patch_1", "patch_2"}
    # Most-recent-first: patch_2 (applied 2026-05-03) must come first.
    assert found[0].patch_hash == "patch_2"
    if path_kind == "indexed":
        store.close()


@pytest.mark.parametrize("path_kind", ["indexed", "scan"])
def test_get_recurrence_count_parity(tmp_path, path_kind):
    """Phase E correctness fix: BOTH paths return the count of distinct
    patch_hashes, not the number of JSONL appends. State-machine
    updates on the same patch don't inflate."""
    if path_kind == "indexed":
        store = _indexed(tmp_path)
    else:
        store = _scan(tmp_path)
    store.record_outcome(_outcome(sig="hot", patch="p1"))
    store.record_outcome(_outcome(sig="hot", patch="p2"))
    store.record_outcome(_outcome(sig="cool", patch="p3"))
    store.update_outcome("p1", outcome_state=STATE_MERGED)
    store.update_outcome("p1", outcome_state=STATE_REGRESSED)
    assert store.get_recurrence_count("hot") == 2
    assert store.get_recurrence_count("cool") == 1
    if path_kind == "indexed":
        store.close()


def test_query_by_signature_indexed_returns_latest_per_patch(tmp_path):
    """When the same patch is updated multiple times, the indexed query
    surfaces the LATEST entry (not earlier history) for that patch."""
    store = _indexed(tmp_path)
    store.record_outcome(_outcome(sig="s", patch="p", state=STATE_APPLIED))
    store.update_outcome("p", outcome_state=STATE_MERGED)
    found = store.query_by_signature("s")
    assert len(found) == 1
    assert found[0].outcome_state == STATE_MERGED
    store.close()


# ── rebuild_index ───────────────────────────────────────────────────────


def test_rebuild_index_recovers_from_wiped_sqlite(tmp_path):
    """If the SQLite file is wiped behind the store's back, rebuild_index
    drops + repopulates from JSONL."""
    store = _indexed(tmp_path)
    store.record_outcome(_outcome(sig="s1", patch="p1"))
    store.record_outcome(_outcome(sig="s1", patch="p2"))
    store.record_outcome(_outcome(sig="s2", patch="p3"))
    store.close()

    # Simulate corruption: wipe the SQLite file entirely.
    sqlite_path = tmp_path / "outcomes.sqlite"
    sqlite_path.unlink()

    # Reopen and rebuild.
    store2 = _indexed(tmp_path)
    n = store2.rebuild_index()
    assert n == 3  # 3 distinct patches in JSONL

    with sqlite3.connect(str(sqlite_path)) as conn:
        rows = conn.execute(
            "SELECT patch_hash, failure_signature FROM outcomes "
            "ORDER BY patch_hash"
        ).fetchall()
    assert rows == [("p1", "s1"), ("p2", "s1"), ("p3", "s2")]
    store2.close()


def test_rebuild_index_preserves_latest_state_per_patch(tmp_path):
    """A patch with multiple lifecycle entries in JSONL collapses to its
    LATEST state in the rebuilt index."""
    store = _indexed(tmp_path)
    store.record_outcome(_outcome(sig="s", patch="p", state=STATE_APPLIED))
    store.update_outcome("p", outcome_state=STATE_MERGED)
    store.update_outcome("p", outcome_state=STATE_REVERTED)
    store.close()

    # Wipe and rebuild from a fresh store.
    (tmp_path / "outcomes.sqlite").unlink()
    store2 = _indexed(tmp_path)
    store2.rebuild_index()

    with sqlite3.connect(str(tmp_path / "outcomes.sqlite")) as conn:
        row = conn.execute(
            "SELECT outcome_state FROM outcomes WHERE patch_hash='p'"
        ).fetchone()
    assert row == (STATE_REVERTED,)
    store2.close()


def test_rebuild_index_returns_zero_when_no_index(tmp_path):
    """rebuild_index is a no-op when the store has no SQLite index."""
    store = _scan(tmp_path)
    store.record_outcome(_outcome())
    assert store.rebuild_index() == 0


def test_rebuild_index_emits_telemetry_event(tmp_path):
    from infra.brain.telemetry.collector import _current_telemetry
    from unittest.mock import MagicMock

    store = _indexed(tmp_path)
    store.record_outcome(_outcome(sig="s", patch="p"))

    fake = MagicMock()
    fake.emit = MagicMock()
    token = _current_telemetry.set(fake)
    try:
        store.rebuild_index()
    finally:
        _current_telemetry.reset(token)

    rebuilt_calls = [
        c for c in fake.emit.call_args_list
        if c.args and c.args[0] == EVENT_OUTCOME_INDEX_REBUILT
    ]
    assert len(rebuilt_calls) == 1
    assert rebuilt_calls[0].kwargs == {"rows": 1}
    store.close()


# ── Graceful degradation on SQLite write failure ────────────────────────


def test_record_outcome_continues_when_sqlite_upsert_fails(
    tmp_path, caplog,
):
    """If the SQLite upsert raises, JSONL still commits, the index is
    dropped for the rest of the process, and a warning is logged."""
    store = _indexed(tmp_path)
    # Replace the index's upsert with one that always raises.
    boom = sqlite3.OperationalError("disk full")
    with patch.object(
        store._sqlite_index, "upsert", side_effect=boom,
    ):
        with caplog.at_level(logging.WARNING):
            store.record_outcome(_outcome(sig="s", patch="p"))

    # Index handle is gone.
    assert store._sqlite_index is None
    # JSONL is committed.
    lines = (tmp_path / "outcomes.jsonl").read_text().splitlines()
    assert len(lines) == 1
    # Warning got logged.
    assert any("sqlite upsert failed" in r.message for r in caplog.records)


def test_index_drop_emits_telemetry_event(tmp_path):
    from infra.brain.telemetry.collector import _current_telemetry
    from unittest.mock import MagicMock

    store = _indexed(tmp_path)
    fake = MagicMock()
    fake.emit = MagicMock()
    token = _current_telemetry.set(fake)
    try:
        with patch.object(
            store._sqlite_index, "upsert",
            side_effect=sqlite3.OperationalError("boom"),
        ):
            store.record_outcome(_outcome())
    finally:
        _current_telemetry.reset(token)

    drop_calls = [
        c for c in fake.emit.call_args_list
        if c.args and c.args[0] == EVENT_OUTCOME_INDEX_DROPPED
    ]
    assert len(drop_calls) == 1


def test_query_falls_back_to_scan_after_index_drop(tmp_path):
    """After an upsert failure drops the index, queries seamlessly use
    the JSONL-scan path. Same answers, slower path."""
    store = _indexed(tmp_path)
    # Seed JSONL via the indexed path.
    store.record_outcome(_outcome(sig="s", patch="p1"))
    # Now break the index's query method.
    with patch.object(
        store._sqlite_index, "query_patch_hashes_by_signature",
        side_effect=sqlite3.OperationalError("query failed"),
    ):
        result = store.query_by_signature("s")
    assert len(result) == 1
    assert result[0].patch_hash == "p1"
    # Index dropped after the failed read.
    assert store._sqlite_index is None


# ── Concurrency ─────────────────────────────────────────────────────────


def test_indexed_concurrent_writes_no_torn_lines(tmp_path):
    """100 records from 10 threads → 100 JSONL lines AND 100 distinct
    indexed rows (each thread used a unique patch_hash)."""
    store = _indexed(tmp_path)
    n_threads = 10
    per_thread = 10

    def worker(t_id: int):
        for i in range(per_thread):
            store.record_outcome(_outcome(
                sig=f"sig_{t_id}",
                patch=f"patch_{t_id}_{i}",
            ))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = (tmp_path / "outcomes.jsonl").read_text().splitlines()
    assert len(lines) == 100

    with sqlite3.connect(str(tmp_path / "outcomes.sqlite")) as conn:
        count = conn.execute("SELECT COUNT(*) FROM outcomes").fetchone()[0]
    assert count == 100
    store.close()


# ── close() is idempotent ───────────────────────────────────────────────


def test_close_is_idempotent_and_safe_when_no_index(tmp_path):
    # No-index store
    s1 = _scan(tmp_path)
    s1.close()
    s1.close()  # no error

    # Indexed store
    s2 = _indexed(tmp_path)
    s2.close()
    s2.close()  # no error
