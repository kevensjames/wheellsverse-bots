"""Append-only audit log for KAI governance.

Format: JSON Lines at data/governance/audit.jsonl. One record per line.
Writes take an exclusive fcntl.flock(LOCK_EX) so concurrent writers (request
threads + the background scheduler threads) cannot interleave. Records
routinely exceed PIPE_BUF (4096 bytes) once inputs/outputs are redacted in,
so the previous "append is atomic under PIPE_BUF" assumption was false and
unlocked appends could corrupt lines under concurrency (audit CORR-F3).

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

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl  # POSIX advisory file locking; absent on Windows
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# Repo root resolution mirrors the Supreme pattern (5 parents up from this file).
_REPO_ROOT = Path(__file__).resolve().parents[4]

AUDIT_LOG_PATH = Path(
    os.environ.get(
        "KAI_AUDIT_LOG_PATH",
        str(_REPO_ROOT / "data" / "governance" / "audit.jsonl"),
    )
)
AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def record_action(
    *,
    action: str,
    scope: str,
    actor: str,
    destructive: bool,
    approved: bool,
    inputs: dict[str, Any] | None = None,
    outputs: dict[str, Any] | None = None,
    success: bool,
    error: str | None = None,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    """Append one record. Returns the record so callers can reference it
    (e.g., embed its id in an HTTP response).

    Never raises — audit-log failures must not break the action they're
    auditing. A failed write is logged at WARNING and the in-memory record
    is still returned so the response shape is consistent.
    """
    record = {
        "id": uuid.uuid4().hex,
        "ts": datetime.now(timezone.utc).isoformat(),
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
    }
    try:
        line = json.dumps(record, default=str) + "\n"
        with AUDIT_LOG_PATH.open("a") as fp:
            if fcntl is not None:
                fcntl.flock(fp.fileno(), fcntl.LOCK_EX)
            try:
                fp.write(line)
                fp.flush()
            finally:
                if fcntl is not None:
                    fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        logger.warning("audit_log: write failed for %s: %s", action, e)
    return record


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
