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

from narai.integrations.briefing import (
    assemble_briefing,
    deliver_via_telegram,
    log_briefing_to_memory,
)

logger = logging.getLogger("narai.scheduler")

_scheduler: AsyncIOScheduler | None = None


async def _fire_briefing() -> None:
    """Cron callback: build briefing, deliver it, log it to memory.
    Errors caught so a failed run doesn't take the whole scheduler down
    for tomorrow."""
    try:
        text = assemble_briefing()
        delivered = await deliver_via_telegram(text)
        log_briefing_to_memory(text)  # side effect, never blocks delivery
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

    # Morning: 7am US/Eastern on weekdays (NARAI_BRIEFING_CRON).
    # Evening: 6pm US/Eastern on weekdays (NARAI_RECAP_CRON). Set the env var
    # to "" or "off" to disable the evening run while keeping the morning one.
    morning_expr = os.environ.get("NARAI_BRIEFING_CRON", "0 7 * * 1-5")
    evening_expr = os.environ.get("NARAI_RECAP_CRON", "0 18 * * 1-5")
    timezone = os.environ.get("NARAI_BRIEFING_TZ", "America/New_York")

    def _safe_trigger(expr: str, fallback: str):
        try:
            return CronTrigger.from_crontab(expr, timezone=timezone)
        except Exception as e:
            logger.warning(f"cron '{expr}' invalid ({e}) — using fallback '{fallback}'")
            return CronTrigger.from_crontab(fallback, timezone=timezone)

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _fire_briefing,
        trigger=_safe_trigger(morning_expr, "0 7 * * 1-5"),
        id="daily_briefing_morning",
    )
    if evening_expr and evening_expr.lower() != "off":
        _scheduler.add_job(
            _fire_briefing,
            trigger=_safe_trigger(evening_expr, "0 18 * * 1-5"),
            id="daily_briefing_evening",
        )
    _scheduler.start()
    logger.info(
        f"briefing scheduler started: morning='{morning_expr}' "
        f"evening='{evening_expr}' tz={timezone}"
    )


def stop_briefing_scheduler() -> None:
    """For tests and graceful shutdown."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
