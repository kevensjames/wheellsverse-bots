#!/usr/bin/env python3
"""
scripts/run_supabase_migration.py
─────────────────────────────────────────────────────────────────────────────
Run a SQL migration file against the Supabase Postgres.

Usage:
  python3 scripts/run_supabase_migration.py <sql_file>
  python3 scripts/run_supabase_migration.py supabase_shopify_multitenant.sql

Requires either:
  DATABASE_URL              — full Postgres URL (preferred), or
  SUPABASE_DB_PASSWORD      — just the password; URL is derived from SUPABASE_URL

Both can be in .env, Railway env, or exported in the shell.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import os
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass


def _build_database_url() -> str:
    """Return a full postgres URL. Prefer DATABASE_URL, else build from parts."""
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url

    pw = os.getenv("SUPABASE_DB_PASSWORD", "").strip()
    sb_url = os.getenv("SUPABASE_URL", "").strip()
    if not pw or not sb_url:
        raise SystemExit(
            "Missing credentials. Set either:\n"
            "  DATABASE_URL=postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:6543/postgres\n"
            "or:\n"
            "  SUPABASE_DB_PASSWORD=<your-db-password>  (with SUPABASE_URL already set)"
        )

    # Extract project ref from https://<ref>.supabase.co
    m = re.match(r"https?://([a-z0-9]+)\.supabase\.co", sb_url)
    if not m:
        raise SystemExit(f"Can't parse project ref from SUPABASE_URL={sb_url!r}")
    ref = m.group(1)
    # URL-encode the password to survive special chars like @, /, :, #
    pw_enc = urllib.parse.quote(pw, safe="")
    # Direct connection (port 5432) — works from any Python runtime
    return f"postgresql://postgres:{pw_enc}@db.{ref}.supabase.co:5432/postgres?sslmode=require"


def main() -> None:
    _load_env()
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    sql_path = Path(sys.argv[1])
    if not sql_path.is_absolute():
        sql_path = ROOT / sql_path
    if not sql_path.exists():
        raise SystemExit(f"SQL file not found: {sql_path}")

    sql = sql_path.read_text(encoding="utf-8")
    print(f"Running {sql_path.name} ({len(sql):,} bytes)...")

    try:
        import psycopg2
    except ImportError:
        raise SystemExit(
            "psycopg2 not installed. Run:\n"
            "  pip3 install psycopg2-binary --break-system-packages"
        )

    url = _build_database_url()
    redacted = re.sub(r":[^:@]+@", ":***@", url)
    print(f"Connecting to {redacted}")

    conn = psycopg2.connect(url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        print(f"✓ Migration applied successfully: {sql_path.name}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
