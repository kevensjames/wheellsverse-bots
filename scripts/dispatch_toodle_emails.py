#!/usr/bin/env python3
"""
scripts/dispatch_toodle_emails.py
─────────────────────────────────────────────────────────────────────────────
Cron-friendly entrypoint for the Toodle SMTP dispatcher (Path B).

Usage:
  /Users/jhonwheeler/wheellsverse_venv/bin/python scripts/dispatch_toodle_emails.py
  /Users/jhonwheeler/wheellsverse_venv/bin/python scripts/dispatch_toodle_emails.py --dry-run
  /Users/jhonwheeler/wheellsverse_venv/bin/python scripts/dispatch_toodle_emails.py --limit 10

Crontab (every 15 minutes):
  */15 * * * * cd /Volumes/Wheellsverse/wheellsverse-bots && \\
      /Users/jhonwheeler/wheellsverse_venv/bin/python \\
      scripts/dispatch_toodle_emails.py >> data/toodle_dispatch.log 2>&1

Exit codes:
  0 = run completed (sent or no-op)
  1 = run completed with at least one SMTP failure
  2 = setup error (env, DB)
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("dispatch")


def main() -> int:
    p = argparse.ArgumentParser(description="Dispatch due Toodle nurture emails via SMTP.")
    p.add_argument("--dry-run", action="store_true",
                   help="Mark rows as 'dry_run' without sending. Useful for verifying queue state.")
    p.add_argument("--limit", type=int, default=60,
                   help="Max rows to process this run (default 60; hard ceiling enforced).")
    args = p.parse_args()

    # Trigger model registration before init_db so the new table is created
    try:
        from core.toodle_dispatcher import process_due, is_smtp_configured
        from narai.api.routes.toodle import ToodleEmailQueue  # noqa: F401
        from narai.core.db import SessionLocal, init_db
    except Exception as e:
        log.error("import error: %s", e)
        return 2

    async def _run() -> int:
        await init_db()
        if not args.dry_run and not is_smtp_configured():
            log.error("EMAIL_USER / EMAIL_PASSWORD not set — refusing to send. "
                      "Use --dry-run to inspect queue, or set credentials in .env.")
            return 2
        result = await process_due(SessionLocal, limit=args.limit, dry_run=args.dry_run)
        log.info("done: sent=%s failed=%s skipped_dry=%s remaining_due=%s",
                 result["sent"], result["failed"], result["skipped_dry"], result["remaining_due"])
        for err in result.get("errors", []):
            log.error("  • %s", err)
        return 1 if result["failed"] else 0

    return asyncio.run(_run())


if __name__ == "__main__":
    sys.exit(main())
