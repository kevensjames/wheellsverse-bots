"""Insider channel scheduler — promo + paid content delivery.

Fires four cron jobs on the AI Stock Alerts Club channel:

  • Weekly promo repost   — Mon 10am ET (NARAI_PROMO_CRON)
  • Morning briefing      — Mon-Fri 7am ET (NARAI_BRIEFING_INSIDER_CRON)
  • Midday signals        — Mon-Fri 12pm ET (NARAI_SIGNALS_CRON)
  • Weekly portfolio review — Sun 6pm ET (NARAI_WEEKLY_REVIEW_CRON)

Each job:
  - Skips silently if TELEGRAM_BOT_TOKEN or channel id is unset.
  - Catches its own exceptions so one failure doesn't take the others down.
  - Posts via direct Bot API (httpx) — no Bot() instance needed.

Disable any subset:
  NARAI_PROMO_ENABLED=false
  NARAI_BRIEFING_INSIDER_ENABLED=false
  NARAI_SIGNALS_ENABLED=false
  NARAI_WEEKLY_REVIEW_ENABLED=false
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("narai.scheduler.promo")

_scheduler: Optional[AsyncIOScheduler] = None

_INSIDER_POST_TEXT = (
    "<b>Daily AI-powered stock + crypto signals</b>\n\n"
    "📈 Morning market briefing (7am EST)\n"
    "🤖 AI-generated entry/exit signals\n"
    "📊 Weekly portfolio review\n"
    "💬 Private Telegram community\n"
    "🔥 Swing trade ideas (RSI, MACD, momentum)\n\n"
    "<i>Cancel any time. No contracts. Pure alpha.</i>"
)

_INSIDER_BUTTON_URL = os.environ.get(
    "INSIDER_LANDING_URL", "https://app.wheellsverse.com/insider"
)


def _channel_id() -> str:
    return os.environ.get(
        "NARAI_PROMO_CHANNEL_ID",
        os.environ.get("TELEGRAM_PRIVATE_CHANNEL_ID", ""),
    )


async def _post_to_channel(text: str, *, button: dict | None = None) -> bool:
    """Send an HTML-formatted message to the insider channel. Returns True on success."""
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed — post skipped")
        return False

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    channel = _channel_id()
    if not token or not channel:
        logger.info("token or channel unset — post skipped")
        return False

    payload: dict = {
        "chat_id": channel,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if button:
        payload["reply_markup"] = json.dumps({"inline_keyboard": [[button]]})

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, data=payload)
        ok = r.status_code == 200 and r.json().get("ok") is True
        if ok:
            mid = r.json().get("result", {}).get("message_id")
            logger.info(f"posted: chan={channel} msg_id={mid} chars={len(text)}")
        else:
            logger.warning(
                f"post failed: status={r.status_code} body={r.text[:200]}"
            )
        return ok
    except Exception as e:
        logger.exception(f"post raised: {e}")
        return False


async def _send_insider_promo() -> None:
    """Weekly promo repost — full sales pitch with subscribe button."""
    button = {"text": "Join Insider — $19/mo", "url": _INSIDER_BUTTON_URL}
    await _post_to_channel(_INSIDER_POST_TEXT, button=button)


async def _send_morning_briefing() -> None:
    """Daily morning briefing — watchlist + AI signals. Runs in thread because
    yfinance + forecaster do blocking IO and CPU work.
    """
    try:
        import asyncio
        from narai.integrations.subscriber_content import morning_briefing
        text = await asyncio.to_thread(morning_briefing)
        await _post_to_channel(text)
    except Exception as e:
        logger.exception(f"morning briefing failed: {e}")


async def _send_daily_signals() -> None:
    """Midday signal scan — bullish / bearish setups."""
    try:
        import asyncio
        from narai.integrations.subscriber_content import daily_signals
        text = await asyncio.to_thread(daily_signals)
        await _post_to_channel(text)
    except Exception as e:
        logger.exception(f"daily signals failed: {e}")


async def _send_weekly_review() -> None:
    """Sunday weekly portfolio review."""
    try:
        import asyncio
        from narai.integrations.subscriber_content import weekly_review
        text = await asyncio.to_thread(weekly_review)
        await _post_to_channel(text)
    except Exception as e:
        logger.exception(f"weekly review failed: {e}")


def _add_job(scheduler: AsyncIOScheduler, env_enabled: str, env_cron: str,
             default_cron: str, callback, job_id: str, tz: str) -> None:
    """Add a cron job if its enabled-flag is on. Falls back to default_cron
    if the env-supplied expression is invalid.
    """
    if os.environ.get(env_enabled, "true").lower() in {"false", "0", "no"}:
        logger.info(f"{env_enabled}=false — {job_id} skipped")
        return

    cron_expr = os.environ.get(env_cron, default_cron)
    try:
        trigger = CronTrigger.from_crontab(cron_expr, timezone=tz)
    except Exception as e:
        logger.warning(f"{env_cron}='{cron_expr}' invalid ({e}) — using default '{default_cron}'")
        trigger = CronTrigger.from_crontab(default_cron, timezone=tz)

    scheduler.add_job(
        callback, trigger=trigger, id=job_id,
        replace_existing=True, misfire_grace_time=60 * 60,
    )
    logger.info(f"job '{job_id}' scheduled: cron='{cron_expr}' tz='{tz}'")


def start_promo_scheduler() -> None:
    """Idempotent — safe to call multiple times. No-op if Telegram unset."""
    global _scheduler
    if _scheduler is not None:
        return

    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        logger.info("TELEGRAM_BOT_TOKEN unset — insider scheduler skipped")
        return

    if not _channel_id():
        logger.info("channel id unset — insider scheduler skipped")
        return

    tz = os.environ.get("NARAI_INSIDER_TZ", "America/New_York")
    _scheduler = AsyncIOScheduler(timezone=tz)

    _add_job(_scheduler, "NARAI_PROMO_ENABLED",
             "NARAI_PROMO_CRON", "0 10 * * 1",
             _send_insider_promo, "insider_promo_repost", tz)

    _add_job(_scheduler, "NARAI_BRIEFING_INSIDER_ENABLED",
             "NARAI_BRIEFING_INSIDER_CRON", "0 7 * * 1-5",
             _send_morning_briefing, "insider_morning_briefing", tz)

    _add_job(_scheduler, "NARAI_SIGNALS_ENABLED",
             "NARAI_SIGNALS_CRON", "0 12 * * 1-5",
             _send_daily_signals, "insider_midday_signals", tz)

    _add_job(_scheduler, "NARAI_WEEKLY_REVIEW_ENABLED",
             "NARAI_WEEKLY_REVIEW_CRON", "0 18 * * 0",
             _send_weekly_review, "insider_weekly_review", tz)

    _scheduler.start()
    logger.info(f"insider scheduler started: tz={tz}, jobs={len(_scheduler.get_jobs())}")
