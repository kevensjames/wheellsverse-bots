"""Shared SQLite helpers for KAI's subsystem sidecar stores (PERF-F4).

Every services/*/storage.py opened a fresh connection AND re-ran
`executescript(_SCHEMA)` on every single call. The schema is idempotent
(CREATE TABLE IF NOT EXISTS ...), so re-parsing + re-executing it per call is
pure waste — some of these stores are read on every chat turn.

`ensure_schema()` runs the schema exactly once per DB path (thread-safe),
mirroring the `_INITIALIZED` pattern relationship/storage.py already used. A
one-line swap in each store's `_conn()`:

    c.executescript(_SCHEMA)         # before — every call
    ensure_schema(c, str(DB_PATH), _SCHEMA)   # after — once per path
"""
from __future__ import annotations

import sqlite3
import threading

_init_lock = threading.Lock()
_initialized: set[str] = set()


def ensure_schema(conn: sqlite3.Connection, db_path: str, schema: str) -> None:
    """Execute `schema` once per `db_path`. Idempotent + thread-safe."""
    if db_path in _initialized:
        return
    with _init_lock:
        if db_path not in _initialized:   # double-checked under the lock
            conn.executescript(schema)
            _initialized.add(db_path)


def reset_for_tests() -> None:
    """Forget initialized paths (so a test using a fresh temp DB re-creates it)."""
    with _init_lock:
        _initialized.clear()
