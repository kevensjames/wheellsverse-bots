"""Append-only audit log for KAI governance.

Format: JSON Lines at data/governance/audit.jsonl. One record per line.
Append is atomic on POSIX for writes under PIPE_BUF (4096 bytes), which
our records comfortably fit. No locking needed for single-daemon writes.

Why JSONL instead of a Postgres table:
  - Zero migration / schema management for v1
  - Append-only is the right shape for an audit log (no UPDATE/DELETE)
  - grep-friendly during incidents
  - Easy backup/rotate via cron + logrotate
  - Upgrade path: a future commit can backfill rows into a `audit_actions`
    table without changing the writer surface — readers swap, writers
    don't.

If the file grows unbounded, add a rotator. Until KAI sees real volume
this is fine.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Genesis link for the hash chain.
_GENESIS = "0" * 64


class AuditWriteError(RuntimeError):
    """A fail-closed audit record could not be persisted. The caller MUST NOT
    proceed with the destructive action it was about to perform."""

# Repo root resolution mirrors the Supreme pattern (5 parents up from this file).
_REPO_ROOT = Path(__file__).resolve().parents[4]

AUDIT_LOG_PATH = Path(
    os.environ.get(
        "KAI_AUDIT_LOG_PATH",
        str(_REPO_ROOT / "data" / "governance" / "audit.jsonl"),
    )
)
AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _canonical(record: dict[str, Any]) -> str:
    """Deterministic serialization for hashing (key order fixed, no spaces)."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), default=str)


def _last_hash() -> str:
    """Hash of the newest record, or genesis when the log is empty/absent.

    ponytail: re-reads the file per write (O(n)); the log is low-volume and
    list_actions already does a full read. Cache it if writes get hot — but a
    cache needs invalidation when AUDIT_LOG_PATH is repointed.
    """
    try:
        if not AUDIT_LOG_PATH.exists():
            return _GENESIS
        last = None
        with AUDIT_LOG_PATH.open() as fp:
            for line in fp:
                if line.strip():
                    last = line
        if last:
            return json.loads(last).get("hash") or _GENESIS
    except Exception:  # unreadable/corrupt tail — start a fresh link
        pass
    return _GENESIS


def record_action(
    *,
    action: str,
    scope: str,
    actor: str,
    destructive: bool,
    approved: bool,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    success: bool | None,
    error: str | None = None,
    duration_ms: int | None = None,
    event: str = "outcome",
    fail_closed: bool = False,
) -> dict[str, Any]:
    """Append one hash-chained record. Returns the record so callers can
    reference it (e.g., embed its id in an HTTP response).

    Each record carries ``prev_hash`` (the previous record's hash) and its own
    ``hash`` over its content, so an edit, reorder, or middle-deletion breaks
    the chain and is detectable via ``verify_chain``.

    Write semantics:
      - default (``fail_closed=False``): never raises. A failed write is logged
        at WARNING — routine telemetry must not break the product.
      - ``fail_closed=True``: raises AuditWriteError. Used for the pre-action
        INTENT record of a destructive action, so an action we cannot durably
        record never happens.
    """
    prev = _last_hash()
    record = {
        "id": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "action": action,
        "scope": scope,
        "actor": actor,
        "destructive": destructive,
        "approved": approved,
        "success": success,
        "error": error,
        "duration_ms": duration_ms,
        "inputs": _redact(inputs or {}),
        "outputs": _truncate(outputs or {}),
        "prev_hash": prev,
    }
    record["hash"] = hashlib.sha256((prev + _canonical(record)).encode("utf-8")).hexdigest()
    try:
        with AUDIT_LOG_PATH.open("a") as fp:
            fp.write(json.dumps(record, default=str) + "\n")
            fp.flush()
            os.fsync(fp.fileno())   # durable before we act on it
    except Exception as e:
        if fail_closed:
            raise AuditWriteError(
                f"could not persist audit record for {action!r}: {e}"
            ) from e
        logger.warning("audit_log: write failed for %s: %s", action, e)
    return record


def verify_chain() -> dict[str, Any]:
    """Walk the log and confirm every record hashes to its content and links to
    its predecessor.

    Detects: content edits, reordering, and deletion from the middle.
    Does NOT detect: truncation of the TAIL — an append-only file with no
    external anchor cannot prove records once existed. Anchor the head hash
    off-host (or notarize periodically) if that matters.
    """
    if not AUDIT_LOG_PATH.exists():
        return {"ok": True, "records": 0, "broken_at": None, "reason": None}
    prev, n = _GENESIS, 0
    try:
        with AUDIT_LOG_PATH.open() as fp:
            for lineno, line in enumerate(fp, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    return {"ok": False, "records": n, "broken_at": lineno,
                            "reason": "unparseable record"}
                n += 1
                if rec.get("prev_hash") != prev:
                    return {"ok": False, "records": n, "broken_at": lineno,
                            "reason": "prev_hash does not match preceding record"}
                body = {k: v for k, v in rec.items() if k != "hash"}
                expect = hashlib.sha256(
                    (prev + _canonical(body)).encode("utf-8")
                ).hexdigest()
                if rec.get("hash") != expect:
                    return {"ok": False, "records": n, "broken_at": lineno,
                            "reason": "content hash mismatch (record was edited)"}
                prev = rec["hash"]
    except Exception as e:
        return {"ok": False, "records": n, "broken_at": None, "reason": f"read failed: {e}"}
    return {"ok": True, "records": n, "broken_at": None, "reason": None}


# ─── inputs/outputs hygiene ─────────────────────────────────────────

_SECRET_KEY_PATTERNS = (
    "password", "secret", "token", "api_key", "apikey", "auth",
    "x-admin-token", "cookie", "bearer",
)
_MAX_VALUE_LEN = 500


def _redact(value: Any) -> Any:
    """Recursive scrub — any dict at any depth has its secret-keyed values
    replaced with '<redacted>'. Walks lists/tuples too so nested
    structures (e.g. _args: [{password: ...}]) are reached."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if any(p in str(k).lower() for p in _SECRET_KEY_PATTERNS):
                out[k] = "<redacted>"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [_redact(x) for x in value]
    return _truncate_value(value)


def _truncate(d: dict[str, Any]) -> dict[str, Any]:
    return {k: _redact(v) for k, v in d.items()}


def _truncate_value(v: Any) -> Any:
    s = str(v) if not isinstance(v, (dict, list, type(None), bool, int, float)) else v
    if isinstance(s, str) and len(s) > _MAX_VALUE_LEN:
        return s[:_MAX_VALUE_LEN] + f"… ({len(s)} chars)"
    return s


# ─── read side ──────────────────────────────────────────────────────


def list_actions(
    *, limit: int = 100, scope: str | None = None, actor: str | None = None
) -> list[dict[str, Any]]:
    """Newest-first slice of the audit log. Filters in Python because the
    log is small enough that grep/parse fits comfortably in memory. If
    this becomes hot, move to Postgres.
    """
    if not AUDIT_LOG_PATH.exists():
        return []
    limit = max(1, min(int(limit), 1000))
    rows: list[dict[str, Any]] = []
    try:
        with AUDIT_LOG_PATH.open() as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if scope is not None and rec.get("scope") != scope:
                    continue
                if actor is not None and rec.get("actor") != actor:
                    continue
                rows.append(rec)
    except Exception as e:
        logger.warning("audit_log: read failed: %s", e)
        return []
    rows.reverse()  # newest first
    return rows[:limit]
