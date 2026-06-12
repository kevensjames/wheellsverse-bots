#!/usr/bin/env python3
"""Self-heal profile.tier mirror against actual Stripe subscription state.

What it does
------------
Resets profiles.tier → 'free' for any profile whose tier is in
('pro','max','ultra') but who does NOT have an active or trialing
subscription. Catches webhook-missed cancellations, refunded-but-not-
canceled subs, and any future drift.

Why
---
profile.tier is a denormalized mirror of "what tier should this user
be billed as RIGHT NOW" — it's the single column the rate-limit and
API-gate code reads. Subscription rows are the source of truth, but
under failure modes (webhook missed, browser_check 403 like 2026-06-03)
the mirror can lag. This is a backstop.

Schedule
--------
LaunchAgent runs nightly at 04:00 local. If it ever fixes more than 0
rows, it logs a WARNING and fires a Telegram alert — that's a signal
to investigate whether the webhook path is dropping events.

Safe to re-run anytime. Idempotent. Read-only on weeks when nothing
needs healing.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Make the backend importable
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "backend"))

# Load env (backend/.env wins on collision — matches start_nai.sh ordering)
for env_path in (ROOT / ".env", ROOT / "backend" / ".env"):
    if not env_path.exists():
        continue
    for line in env_path.read_text().splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ[k] = v.strip().strip('"').strip("'")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s tier_heal: %(message)s",
)
logger = logging.getLogger("tier_heal")


def main() -> int:
    from sqlalchemy import text

    from app.database import SessionLocal

    sql = text("""
        UPDATE profiles
        SET tier = 'free'
        WHERE tier IN ('pro','max','ultra')
          AND id NOT IN (
              SELECT user_id FROM subscriptions
              WHERE status IN ('active','trialing')
          )
        RETURNING id, email, tier
    """)
    db = SessionLocal()
    try:
        result = db.execute(sql)
        rows = result.fetchall()
        db.commit()
    finally:
        db.close()

    n = len(rows)
    if n == 0:
        logger.info("nothing to heal — profile.tier matches Stripe state")
        return 0

    logger.warning("HEALED %d orphan tier rows (drift from Stripe):", n)
    for r in rows:
        logger.warning("  %s  %s", r[1], r[0])

    # Alert operator — drift > 0 is a webhook-pipeline signal
    try:
        from app.services import observability
        details = "\n".join(f"• {r[1]}" for r in rows[:10])
        observability.notify(
            f"⚠️ <b>Tier-mirror drift</b>\n"
            f"Healed {n} orphan profile.tier row{'s' if n != 1 else ''}:\n"
            f"{details}\n"
            f"<i>Check whether webhooks are dropping customer.subscription.deleted events.</i>"
        )
    except Exception as e:
        logger.warning("could not send TG alert: %s", e)

    return 0


if __name__ == "__main__":
    sys.exit(main())
