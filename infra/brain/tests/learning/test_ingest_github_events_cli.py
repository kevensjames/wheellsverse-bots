"""Phase F.2: tests for the ``scripts/feedback/ingest_github_events.py`` CLI.

The CLI is a thin seam over :mod:`infra.brain.learning.feedback_ingestor`;
those tests cover the ingestor semantics. These tests cover the CLI's
contract:

  * Stdin path with a valid ``pull_request_review`` payload → exit 0,
    store updated.
  * File path argument with a valid ``push`` payload → exit 0, store
    updated.
  * Invalid JSON on stdin → exit 1, error to stderr, store untouched.
  * Missing payload file → exit 1.
  * Payload root is not an object → exit 1.
  * Payload with no detectable event type → exit 1; ``--event-type``
    override unblocks ingestion.
  * IngestionResult is printed to stdout as one JSON line.
  * Ledger path resolves: --ledger > $BRAIN_OUTCOME_LEDGER > default.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from infra.brain.learning.repair_outcome_memory import (
    RepairOutcome,
    RepairOutcomeStore,
    STATE_APPLIED,
    STATE_MERGED,
)


# ── Helpers ─────────────────────────────────────────────────────────────


def _seed_store(ledger_path: Path, *, pr_number: int = 42) -> str:
    """Drop one outcome into a fresh JSONL store and return the
    patch_hash so tests can assert against it."""
    store = RepairOutcomeStore(path=ledger_path)
    outcome = RepairOutcome(
        failure_signature="sig_test",
        patch_hash="patch_xyz",
        applied_at="2026-05-05T22:00:00+00:00",
        outcome_state=STATE_APPLIED,
        outcome_observed_at="2026-05-05T22:00:00+00:00",
        pr_number=pr_number,
    )
    store.record_outcome(outcome)
    return outcome.patch_hash


def _run_cli(
    argv: list[str],
    *,
    stdin: str = "",
    capsys,
    monkeypatch,
) -> tuple[int, str, str]:
    """Invoke ``main()`` directly with the given argv + stdin. Returns
    ``(exit_code, stdout, stderr)``."""
    # Re-import inside the helper so each test gets a fresh module
    # state — argparse caches nothing across calls but importing here
    # keeps the test surface explicit.
    from scripts.feedback.ingest_github_events import main as cli_main

    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    code = cli_main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# Make the script importable as a module for the tests. The script lives
# at ``scripts/feedback/ingest_github_events.py``; we add the parent
# scripts directory to sys.path on first import so ``from
# scripts.feedback.ingest_github_events`` works without forcing an
# __init__.py in scripts/.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ── Stdin path ──────────────────────────────────────────────────────────


def test_stdin_pr_review_triggers_state_transition(
    tmp_path, capsys, monkeypatch,
):
    ledger = tmp_path / "outcomes.jsonl"
    monkeypatch.setenv("BRAIN_OUTCOME_LEDGER", str(ledger))
    _seed_store(ledger)

    payload = {
        "review": {"state": "approved"},
        "pull_request": {"number": 42, "merged": True},
    }
    code, out, err = _run_cli(
        argv=[],
        stdin=json.dumps(payload),
        capsys=capsys,
        monkeypatch=monkeypatch,
    )
    assert code == 0, err
    parsed = json.loads(out.strip())
    assert parsed["event_type"] == "pull_request_review"
    assert parsed["matched_patch_hash"] == "patch_xyz"
    # state_transition is a tuple in the dataclass; asdict converts to list.
    assert parsed["state_transition"] == [STATE_APPLIED, STATE_MERGED]

    # Verify the store actually updated.
    store2 = RepairOutcomeStore(path=ledger)
    latest = store2._latest_for_patch("patch_xyz")
    assert latest.outcome_state == STATE_MERGED


# ── File path argument ─────────────────────────────────────────────────


def test_file_path_with_push_payload_runs(
    tmp_path, capsys, monkeypatch,
):
    ledger = tmp_path / "outcomes.jsonl"
    monkeypatch.setenv("BRAIN_OUTCOME_LEDGER", str(ledger))

    # Seed a merged outcome with a known SHA so the push-revert path
    # actually transitions.
    sha = "abc123def456789012345678901234567890aaaa"
    store = RepairOutcomeStore(path=ledger)
    store.record_outcome(RepairOutcome(
        failure_signature="sig",
        patch_hash="p1",
        applied_at="2026-05-05T22:00:00+00:00",
        outcome_state=STATE_MERGED,
        outcome_observed_at="2026-05-05T22:00:00+00:00",
        commit_sha=sha,
    ))

    payload = {
        "ref": "refs/heads/main",
        "commits": [{
            "id": "rev_a",
            "message": f'Revert "feat"\n\nThis reverts commit {sha}.\n',
        }],
    }
    payload_path = tmp_path / "event.json"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    code, out, err = _run_cli(
        argv=[str(payload_path)],
        capsys=capsys,
        monkeypatch=monkeypatch,
    )
    assert code == 0, err
    parsed = json.loads(out.strip())
    assert parsed["event_type"] == "push"
    assert parsed["matched_patch_hash"] == "p1"
    assert parsed["state_transition"][1] == "regressed"


# ── Failure modes ──────────────────────────────────────────────────────


def test_invalid_json_on_stdin_exit_1_with_stderr(
    tmp_path, capsys, monkeypatch,
):
    ledger = tmp_path / "outcomes.jsonl"
    monkeypatch.setenv("BRAIN_OUTCOME_LEDGER", str(ledger))
    code, out, err = _run_cli(
        argv=[],
        stdin="this is not json {{{",
        capsys=capsys,
        monkeypatch=monkeypatch,
    )
    assert code == 1
    assert out == ""
    assert "not valid JSON" in err
    # Ledger never created.
    assert not ledger.exists()


def test_missing_file_path_exit_1(tmp_path, capsys, monkeypatch):
    ledger = tmp_path / "outcomes.jsonl"
    monkeypatch.setenv("BRAIN_OUTCOME_LEDGER", str(ledger))
    code, out, err = _run_cli(
        argv=[str(tmp_path / "does_not_exist.json")],
        capsys=capsys,
        monkeypatch=monkeypatch,
    )
    assert code == 1
    assert "not found" in err.lower()


def test_payload_root_not_object_exit_1(tmp_path, capsys, monkeypatch):
    ledger = tmp_path / "outcomes.jsonl"
    monkeypatch.setenv("BRAIN_OUTCOME_LEDGER", str(ledger))
    code, out, err = _run_cli(
        argv=[],
        stdin=json.dumps([1, 2, 3]),  # JSON array, not object
        capsys=capsys,
        monkeypatch=monkeypatch,
    )
    assert code == 1
    assert "must be a JSON object" in err


def test_unknown_event_shape_exit_1(tmp_path, capsys, monkeypatch):
    ledger = tmp_path / "outcomes.jsonl"
    monkeypatch.setenv("BRAIN_OUTCOME_LEDGER", str(ledger))
    code, out, err = _run_cli(
        argv=[],
        stdin=json.dumps({"action": "opened"}),  # neither review nor push
        capsys=capsys,
        monkeypatch=monkeypatch,
    )
    assert code == 1
    assert "could not determine event type" in err


def test_event_type_override_unblocks_unknown_shape(
    tmp_path, capsys, monkeypatch,
):
    """Even if the payload doesn't have the keys the shape detector
    looks for, ``--event-type`` lets the caller force dispatch.
    Result is a no-op (no actionable signal) but the CLI exits 0
    because dispatch happened cleanly."""
    ledger = tmp_path / "outcomes.jsonl"
    monkeypatch.setenv("BRAIN_OUTCOME_LEDGER", str(ledger))
    payload = {"some_field": "value"}
    code, out, err = _run_cli(
        argv=["--event-type", "push"],
        stdin=json.dumps(payload),
        capsys=capsys,
        monkeypatch=monkeypatch,
    )
    assert code == 0
    parsed = json.loads(out.strip())
    assert parsed["event_type"] == "push"
    assert parsed["matched_patch_hash"] is None


# ── Ledger-path resolution ─────────────────────────────────────────────


def test_ledger_arg_overrides_env_var(tmp_path, capsys, monkeypatch):
    arg_ledger = tmp_path / "from_arg.jsonl"
    env_ledger = tmp_path / "from_env.jsonl"
    monkeypatch.setenv("BRAIN_OUTCOME_LEDGER", str(env_ledger))

    # Seed BOTH to make the routing observable.
    _seed_store(arg_ledger, pr_number=100)
    _seed_store(env_ledger, pr_number=200)

    # PR number 100 only exists in the arg ledger, so the ingestor
    # should hit a match if --ledger is honored.
    payload = {
        "review": {"state": "changes_requested"},
        "pull_request": {"number": 100, "merged": False},
    }
    code, out, err = _run_cli(
        argv=["--ledger", str(arg_ledger)],
        stdin=json.dumps(payload),
        capsys=capsys,
        monkeypatch=monkeypatch,
    )
    assert code == 0, err
    parsed = json.loads(out.strip())
    assert parsed["matched_patch_hash"] == "patch_xyz"


def test_env_var_used_when_arg_omitted(tmp_path, capsys, monkeypatch):
    env_ledger = tmp_path / "via_env.jsonl"
    monkeypatch.setenv("BRAIN_OUTCOME_LEDGER", str(env_ledger))
    _seed_store(env_ledger, pr_number=77)

    payload = {
        "review": {"state": "changes_requested"},
        "pull_request": {"number": 77, "merged": False},
    }
    code, out, err = _run_cli(
        argv=[],
        stdin=json.dumps(payload),
        capsys=capsys,
        monkeypatch=monkeypatch,
    )
    assert code == 0, err
    parsed = json.loads(out.strip())
    assert parsed["matched_patch_hash"] == "patch_xyz"
