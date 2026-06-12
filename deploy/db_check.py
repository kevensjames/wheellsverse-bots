#!/usr/bin/env python3
"""db_check.py — SQLAlchemy-based DB checks for verify_stage.sh

Replaces the psql CLI dependency. Uses the SAME connection path the app uses,
so the verifier tests what production actually does — not a separate CLI tool.

Usage:
    python deploy/db_check.py connect
    python deploy/db_check.py extension vector
    python deploy/db_check.py table memories
    python deploy/db_check.py column memories embedding
    python deploy/db_check.py index memories ix_memories_embedding

Exit codes:
    0  = check passed
    1  = check failed (not found / mismatch)
    2  = usage error
    3  = connection error (env missing or DB unreachable)

Reads DATABASE_URL or DIRECT_DATABASE_URL from environment.
Prefers DIRECT_DATABASE_URL (direct:5432) for DDL-level introspection,
since the Supabase pooler can behave differently for system-catalog queries.
"""
from __future__ import annotations

import os
import sys


def _get_url() -> str:
    url = os.environ.get("DIRECT_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: neither DIRECT_DATABASE_URL nor DATABASE_URL set", file=sys.stderr)
        sys.exit(3)
    # Reject the classic stale-localhost trap explicitly
    if "localhost/wheellsverse_dev" in url or "127.0.0.1/wheellsverse_dev" in url:
        print(
            "ERROR: DATABASE_URL points at stale local dev DB "
            "(localhost/wheellsverse_dev). Point it at Supabase.",
            file=sys.stderr,
        )
        sys.exit(3)
    return url


def _engine(url: str):
    try:
        from sqlalchemy import create_engine
    except ImportError:
        print("ERROR: sqlalchemy not installed in this venv", file=sys.stderr)
        sys.exit(3)
    # Normalize postgres:// → postgresql:// (SQLAlchemy requirement)
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url, future=True, pool_pre_ping=True)


def check_connect(url: str) -> int:
    from sqlalchemy import text
    try:
        eng = _engine(url)
        with eng.connect() as conn:
            row = conn.execute(text("SELECT current_database(), version()")).first()
        print(f"OK connected: db={row[0]}")
        print(f"   {row[1][:60]}")
        return 0
    except Exception as e:
        print(f"FAIL connection: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


def check_extension(url: str, name: str) -> int:
    from sqlalchemy import text
    try:
        eng = _engine(url)
        with eng.connect() as conn:
            row = conn.execute(
                text("SELECT extversion FROM pg_extension WHERE extname = :n"),
                {"n": name},
            ).first()
        if row:
            print(f"OK extension {name} v{row[0]}")
            return 0
        print(f"FAIL extension {name} not installed")
        return 1
    except Exception as e:
        print(f"FAIL extension check: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


def check_table(url: str, table: str) -> int:
    from sqlalchemy import text
    try:
        eng = _engine(url)
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = :t AND table_schema = 'public'"
                ),
                {"t": table},
            ).first()
        if row:
            print(f"OK table public.{table} exists")
            return 0
        print(f"FAIL table public.{table} not found")
        return 1
    except Exception as e:
        print(f"FAIL table check: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


def check_column(url: str, table: str, column: str) -> int:
    from sqlalchemy import text
    try:
        eng = _engine(url)
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_name = :t AND column_name = :c "
                    "AND table_schema = 'public'"
                ),
                {"t": table, "c": column},
            ).first()
        if row:
            print(f"OK column {table}.{column} exists (type={row[0]})")
            return 0
        print(f"FAIL column {table}.{column} not found")
        return 1
    except Exception as e:
        print(f"FAIL column check: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


def check_index(url: str, table: str, index: str) -> int:
    from sqlalchemy import text
    try:
        eng = _engine(url)
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM pg_indexes "
                    "WHERE tablename = :t AND indexname = :i "
                    "AND schemaname = 'public'"
                ),
                {"t": table, "i": index},
            ).first()
        if row:
            print(f"OK index {index} on {table} exists")
            return 0
        print(f"FAIL index {index} on {table} not found")
        return 1
    except Exception as e:
        print(f"FAIL index check: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    cmd = argv[1]
    url = _get_url()

    if cmd == "connect":
        return check_connect(url)
    if cmd == "extension" and len(argv) == 3:
        return check_extension(url, argv[2])
    if cmd == "table" and len(argv) == 3:
        return check_table(url, argv[2])
    if cmd == "column" and len(argv) == 4:
        return check_column(url, argv[2], argv[3])
    if cmd == "index" and len(argv) == 4:
        return check_index(url, argv[2], argv[3])

    print(f"ERROR: bad usage: {' '.join(argv[1:])}", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
