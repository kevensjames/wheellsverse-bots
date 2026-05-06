#!/usr/bin/env python3
"""scripts/feedback/ingest_github_events.py — CLI seam for the
:mod:`infra.brain.learning.feedback_ingestor` module.

Reads a single GitHub webhook payload as JSON (from a file path or
stdin), dispatches to the right ingestor, and writes the
:class:`IngestionResult` to stdout as one JSON line. Designed to be
invoked from a GitHub Actions workflow (see
``.github/workflows/brain-feedback-ingest.yml``).

Contract (intentionally minimal):

  * **Input** — one JSON object per invocation. Either:
      - first positional arg = path to a JSON file, OR
      - no arg → read from stdin.
  * **Output** — JSON-encoded :class:`IngestionResult` dict on stdout.
    Includes ``event_type``, ``matched_patch_hash``,
    ``state_transition``, and ``notes``.
  * **Exit codes**:
      - ``0`` — payload parsed + ingestor dispatched (whether or not
        the ingestor produced a state transition; the result tells
        you which).
      - ``1`` — payload could not be parsed as JSON, or no event-type
        could be inferred. Stderr carries a short diagnostic.
  * **No GitHub API calls.** Payload-in, side-effects-on-store-out.

Event-type detection is shape-based (no requirement that the caller
tag the payload):

  * ``review`` key → ``pull_request_review``
  * ``commits`` key → ``push``
  * ``--event-type`` flag overrides shape detection.

Ledger location is read from ``--ledger`` (or ``BRAIN_OUTCOME_LEDGER``
env var). Defaults to :data:`infra.brain.learning.repair_outcome_memory.DEFAULT_OUTCOMES_PATH`.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from pathlib import Path
from typing import Optional


def _detect_event_type(payload: dict, override: Optional[str]) -> Optional[str]:
    """Return ``"pull_request_review"`` | ``"push"`` | ``None``."""
    if override:
        return override
    if not isinstance(payload, dict):
        return None
    if "review" in payload and "pull_request" in payload:
        return "pull_request_review"
    # ``push`` events always have at least ``ref`` + ``commits``.
    if "ref" in payload and "commits" in payload:
        return "push"
    return None


def _read_payload(path: Optional[str]) -> dict:
    """Load JSON from ``path`` (when set) or stdin. Caller catches
    exceptions; this function does not pretty-print."""
    if path:
        text = Path(path).read_text(encoding="utf-8")
    else:
        text = sys.stdin.read()
    return json.loads(text)


def _resolve_ledger_path(arg_path: Optional[str]) -> Path:
    """Precedence: --ledger > $BRAIN_OUTCOME_LEDGER > module default."""
    if arg_path:
        return Path(arg_path)
    env = os.environ.get("BRAIN_OUTCOME_LEDGER")
    if env:
        return Path(env)
    # Lazy import so ``--help`` works without the brain package being
    # importable (e.g. partial deploys).
    from infra.brain.learning.repair_outcome_memory import (
        DEFAULT_OUTCOMES_PATH,
    )
    return Path(DEFAULT_OUTCOMES_PATH)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Ingest a GitHub webhook payload into the Brain outcome "
            "ledger. Reads JSON from stdin or a file path."
        ),
    )
    parser.add_argument(
        "payload_path",
        nargs="?",
        default=None,
        help="Path to a JSON file. Reads stdin when omitted.",
    )
    parser.add_argument(
        "--event-type",
        choices=["pull_request_review", "push"],
        default=None,
        help=(
            "Override shape-based event detection. Useful when the "
            "calling workflow knows the event type up front."
        ),
    )
    parser.add_argument(
        "--ledger",
        default=None,
        help=(
            "Path to the JSONL outcome ledger. Defaults to "
            "$BRAIN_OUTCOME_LEDGER, then the module default."
        ),
    )
    parser.add_argument(
        "--sqlite-index",
        default=None,
        help=(
            "Optional SQLite index path (Phase E.1). When omitted, the "
            "store runs JSONL-only."
        ),
    )
    args = parser.parse_args(argv)

    # 1. Read + parse payload.
    try:
        payload = _read_payload(args.payload_path)
    except FileNotFoundError as e:
        print(f"error: payload file not found: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"error: payload is not valid JSON: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # pragma: no cover — defensive
        print(f"error: could not read payload: {e}", file=sys.stderr)
        return 1

    if not isinstance(payload, dict):
        print(
            "error: payload root must be a JSON object",
            file=sys.stderr,
        )
        return 1

    # 2. Determine event type.
    event_type = _detect_event_type(payload, args.event_type)
    if event_type is None:
        print(
            "error: could not determine event type — payload has no "
            "'review'/'pull_request' or 'ref'/'commits' keys; pass "
            "--event-type to override",
            file=sys.stderr,
        )
        return 1

    # 3. Build the store + dispatch.
    from infra.brain.learning.feedback_ingestor import (
        ingest_pr_review,
        ingest_push_event,
    )
    from infra.brain.learning.repair_outcome_memory import (
        RepairOutcomeStore,
    )

    ledger_path = _resolve_ledger_path(args.ledger)
    store = RepairOutcomeStore(
        path=ledger_path,
        sqlite_index_path=Path(args.sqlite_index) if args.sqlite_index else None,
    )
    try:
        if event_type == "pull_request_review":
            result = ingest_pr_review(payload, store=store)
        else:
            result = ingest_push_event(payload, store=store)
    finally:
        store.close()

    # 4. Print the result as one JSON line.
    out = dataclasses.asdict(result)
    # state_transition is a tuple — JSON has no tuples, asdict converts
    # to a list, which is what we want. Confirm by running the test.
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
