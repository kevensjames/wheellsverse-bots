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


# The guard `stripe_customer_id IS NOT NULL` is load-bearing, not defensive noise.
#
# Without it this query demotes COMPED accounts — profiles granted a paid tier that were
# never provisioned through Stripe and therefore correctly have no subscription row. The
# operator's own profile is exactly that: backend/app/routers/admin_chat.py pins it to
# tier='ultra' on every /admin/kai-chat call ("so a stray DB edit can't silently downgrade"),
# while this job demoted it every night at 04:00 and fired a Telegram alert blaming dropped
# `customer.subscription.deleted` webhooks. Two subsystems fighting over one row; no webhook
# was ever involved. Measured 2026-09-11: current query demotes 1 (the comped operator),
# this query demotes 0, and the 2 ex-customers carrying a stripe_customer_id are already free.
#
# Restricting to Stripe-provisioned accounts keeps the real capability — a genuine customer
# who cancels still gets demoted — while making a comped grant un-demotable by construction.
# THE PRECONDITION. This job infers "cancelled" from the ABSENCE of an active/trialing row in
# `subscriptions`. That inference is only valid if something actually WRITES that table — and
# nothing live does: narai/integrations/nai_subscription.py implements the full flow (_apply_tier
# upserts the row) but is imported by nothing except its own test, and the live promoter in
# core/api.py writes profiles.tier only.
#
# So if `subscriptions` holds zero active/trialing rows, every paying customer looks cancelled and
# this job would demote all of them at 04:00 while their Stripe subscriptions are live. An empty
# signal is a DATA-AVAILABILITY FAILURE, not evidence of mass cancellation. Fail closed: demote
# nothing, and say why.
#
# Raised in review on PR #83 (High). The earlier stripe_customer_id guard spares comped accounts;
# it does not make an unwritten table mean what this query assumes it means.
def should_heal(active_subscription_count: int) -> tuple[bool, str]:
    """Run only when the cancellation signal is actually present. Pure; see demo()."""
    if active_subscription_count is None:
        return False, "subscriptions count unreadable — refusing to infer cancellation"
    if active_subscription_count <= 0:
        return False, ("subscriptions holds 0 active/trialing rows — the cancellation signal is "
                       "unusable and every paid profile would look cancelled. Demoting nothing. "
                       "Root cause: no live code writes subscriptions (nai_subscription.py is "
                       "unreferenced); wire it before this job can mean anything.")
    return True, ""


HEAL_SQL = """
        UPDATE profiles
        SET tier = 'free'
        WHERE tier IN ('pro','max','ultra')
          AND stripe_customer_id IS NOT NULL
          AND id NOT IN (
              SELECT user_id FROM subscriptions
              WHERE status IN ('active','trialing')
          )
        RETURNING id, email, tier
"""


def _alert_precondition(why: str, active: int) -> None:
    """Tell the operator the job stood down. Silence would look identical to 'nothing to heal'."""
    try:
        from app.services import observability
        observability.notify(
            "⚠️ <b>Tier-heal stood down</b>\n"
            f"active/trialing subscription rows: {active}\n{why}")
    except Exception as e:                                       # noqa: BLE001
        logger.warning("could not send TG alert: %s", e)


def main() -> int:
    from sqlalchemy import text

    from app.database import SessionLocal

    sql = text(HEAL_SQL)
    db = SessionLocal()
    try:
        try:
            active = db.execute(text(
                "SELECT count(*) FROM subscriptions WHERE status IN ('active','trialing')")).scalar()
        except Exception as e:                                   # noqa: BLE001
            db.rollback()
            logger.error("could not read the subscriptions signal (%s) — demoting nothing", type(e).__name__)
            return 0
        ok, why = should_heal(active)
        if not ok:
            logger.warning("PRECONDITION NOT MET — %s", why)
            _alert_precondition(why, active)
            return 0
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
            f"<i>These accounts were provisioned through Stripe and have no active subscription. "
            f"Check whether customer.subscription.deleted is reaching the webhook — note that "
            f"no server-side demotion is wired at all (nai_subscription.py is unreferenced).</i>"
        )
    except Exception as e:
        logger.warning("could not send TG alert: %s", e)

    return 0


if __name__ == "__main__":
    sys.exit(main())
