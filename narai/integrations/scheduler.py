"""
Daily briefing scheduler.

Registered on FastAPI startup. Reads NARAI_BRIEFING_CRON (default 7am ET on
weekdays). Skips firing if Telegram isn't configured — assemble + Telegram
delivery is one atomic unit; no point computing if nobody is listening.

The daily numbers board's jobs (start_board_scheduler, core/board/jobs.py) run
on New York time, the zone of the board's SQL, and start without Telegram too:
the hourly Stripe sync has work to do either way.

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
_board_scheduler: AsyncIOScheduler | None = None

BOARD_TZ = "America/New_York"   # the owner's day in the board's SQL


def _safe_trigger(expr: str, fallback: str, timezone: str):
    """A cron trigger for `expr`, or for `fallback` when `expr` is invalid."""
    try:
        return CronTrigger.from_crontab(expr, timezone=timezone)
    except Exception as e:
        logger.warning(f"cron '{expr}' invalid ({e}) — using fallback '{fallback}'")
        return CronTrigger.from_crontab(fallback, timezone=timezone)


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

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _fire_briefing,
        trigger=_safe_trigger(morning_expr, "0 7 * * 1-5", timezone),
        id="daily_briefing_morning",
    )
    if evening_expr and evening_expr.lower() != "off":
        _scheduler.add_job(
            _fire_briefing,
            trigger=_safe_trigger(evening_expr, "0 18 * * 1-5", timezone),
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


def start_board_scheduler() -> None:
    """The daily numbers board's jobs, on New York time whatever
    NARAI_BRIEFING_TZ says: the Stripe sync every hour at :07, the morning
    report at BOARD_REPORT_CRON (default 07:00), and once now the report's
    catch-up, for a container that started after the report time. Idempotent;
    must be called on the running event loop (FastAPI startup)."""
    global _board_scheduler
    if _board_scheduler is not None:
        return
    from core.board import jobs

    report_expr = os.environ.get("BOARD_REPORT_CRON", "").strip() or "0 7 * * *"
    report_trigger = _safe_trigger(report_expr, "0 7 * * *", BOARD_TZ)
    scheduler = AsyncIOScheduler(timezone=BOARD_TZ, job_defaults={
        "coalesce": True, "max_instances": 1, "misfire_grace_time": 900})
    scheduler.add_job(jobs.sync_stripe, trigger=CronTrigger.from_crontab("7 * * * *", timezone=BOARD_TZ),
                      id="board_sync_hourly")
    scheduler.add_job(jobs.morning_report, trigger=report_trigger, id="board_morning_report")
    scheduler.add_job(jobs.catch_up, args=[report_trigger], id="board_report_catch_up")
    scheduler.start()
    _board_scheduler = scheduler
    logger.info(f"board scheduler started: report='{report_expr}' sync='7 * * * *' tz={BOARD_TZ}")


def stop_board_scheduler() -> None:
    """For tests and graceful shutdown."""
    global _board_scheduler
    if _board_scheduler is not None:
        _board_scheduler.shutdown(wait=False)
        _board_scheduler = None
