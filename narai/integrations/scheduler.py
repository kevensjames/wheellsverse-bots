"""
Daily briefing scheduler.

Registered on FastAPI startup. Reads NARAI_BRIEFING_CRON (default 7am ET on
weekdays). Skips firing if Telegram isn't configured — assemble + Telegram
delivery is one atomic unit; no point computing if nobody is listening.

Use APScheduler's AsyncIOScheduler so the cron runs inside the same event
loop as the FastAPI app — no thread juggling, no async/sync gluework.
"""
from __future__ import annotations

import logging
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from narai.integrations.briefing import assemble_briefing, deliver_via_telegram

logger = logging.getLogger("narai.scheduler")

_scheduler: AsyncIOScheduler | None = None


async def _fire_briefing() -> None:
    """Cron callback: build briefing and deliver it. Errors caught so a
    failed run doesn't take the whole scheduler down for tomorrow."""
    try:
        text = assemble_briefing()
        delivered = await deliver_via_telegram(text)
        logger.info(
            f"daily briefing fired: delivered={delivered} "
            f"chars={len(text)}"
        )
    except Exception as e:
        logger.exception(f"briefing fire failed: {e}")


def start_briefing_scheduler() -> None:
    """Idempotent — safe to call multiple times. Skips if Telegram unset."""
    global _scheduler
    if _scheduler is not None:
        return

    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        logger.info("TELEGRAM_BOT_TOKEN unset — briefing scheduler skipped")
        return

    # Default: 7am US/Eastern on weekdays. Override with NARAI_BRIEFING_CRON
    # using standard 5-field cron syntax: "minute hour dom month dow".
    cron_expr = os.environ.get("NARAI_BRIEFING_CRON", "0 7 * * 1-5")
    timezone = os.environ.get("NARAI_BRIEFING_TZ", "America/New_York")

    try:
        trigger = CronTrigger.from_crontab(cron_expr, timezone=timezone)
    except Exception as e:
        logger.warning(
            f"NARAI_BRIEFING_CRON='{cron_expr}' invalid ({e}) — using default 7am ET weekdays"
        )
        trigger = CronTrigger.from_crontab("0 7 * * 1-5", timezone=timezone)

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(_fire_briefing, trigger=trigger, id="daily_briefing")
    _scheduler.start()
    logger.info(f"briefing scheduler started: cron='{cron_expr}' tz={timezone}")


def stop_briefing_scheduler() -> None:
    """For tests and graceful shutdown."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
