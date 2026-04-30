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


# ── Discord delivery ─────────────────────────────────────────────────────────


async def _post_to_discord(channel_id: str, content: str) -> bool:
    """Send a message to a Discord channel via the Bot API. <2000 chars per msg."""
    try:
        import httpx
    except ImportError:
        logger.warning("httpx not installed — discord post skipped")
        return False

    token = os.environ.get("DISCORD_BOT_TOKEN", "")
    if not token or not channel_id:
        return False

    headers = {
        "Authorization": f"Bot {token}",
        "User-Agent": "WheellsVerse (https://app.wheellsverse.com, 1.0)",
    }
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"

    # Discord caps content at 2000 chars. Split if longer.
    chunks = [content[i:i + 1900] for i in range(0, len(content), 1900)] or [content]
    ok_all = True
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            for chunk in chunks:
                r = await client.post(url, json={"content": chunk}, headers=headers)
                if r.status_code not in (200, 201):
                    logger.warning(
                        f"discord post failed: status={r.status_code} body={r.text[:200]}"
                    )
                    ok_all = False
                    break
        if ok_all:
            logger.info(f"discord posted: chan={channel_id} chars={len(content)}")
        return ok_all
    except Exception as e:
        logger.exception(f"discord post raised: {e}")
        return False


def _discord_status_channel() -> str:
    return os.environ.get(
        "DISCORD_STATUS_CHANNEL_ID",
        os.environ.get("DISCORD_GENERAL_CHANNEL_ID", ""),
    )


def _discord_content_channel() -> str:
    return os.environ.get(
        "DISCORD_CONTENT_CHANNEL_ID",
        os.environ.get("DISCORD_GENERAL_CHANNEL_ID", ""),
    )


def _strip_html(text: str) -> str:
    """Discord doesn't parse Telegram HTML. Strip the tags so signals look clean."""
    import re
    text = re.sub(r"<b>(.*?)</b>", r"**\1**", text)
    text = re.sub(r"<i>(.*?)</i>", r"_\1_", text)
    text = re.sub(r"<code>(.*?)</code>", r"`\1`", text)
    text = re.sub(r"<[^>]+>", "", text)  # drop anything else
    return text


async def _send_discord_morning_briefing() -> None:
    """Mirror the TG morning briefing into the Discord content channel."""
    try:
        import asyncio
        from narai.integrations.subscriber_content import morning_briefing
        text = _strip_html(await asyncio.to_thread(morning_briefing))
        chan = _discord_content_channel()
        if chan:
            await _post_to_discord(chan, text)
    except Exception as e:
        logger.exception(f"discord morning briefing failed: {e}")


async def _send_discord_daily_signals() -> None:
    try:
        import asyncio
        from narai.integrations.subscriber_content import daily_signals
        text = _strip_html(await asyncio.to_thread(daily_signals))
        chan = _discord_content_channel()
        if chan:
            await _post_to_discord(chan, text)
    except Exception as e:
        logger.exception(f"discord daily signals failed: {e}")


async def _send_discord_weekly_review() -> None:
    try:
        import asyncio
        from narai.integrations.subscriber_content import weekly_review
        text = _strip_html(await asyncio.to_thread(weekly_review))
        chan = _discord_content_channel()
        if chan:
            await _post_to_discord(chan, text)
    except Exception as e:
        logger.exception(f"discord weekly review failed: {e}")


async def _send_discord_fleet_status() -> None:
    """Bot-fleet status digest: which bots are running, today's revenue, etc.
    Best-effort — any subsystem that's missing degrades to a "—" line.
    """
    chan = _discord_status_channel()
    if not chan:
        return
    lines: list[str] = ["**🤖 WheellsVerse Bot Fleet — hourly status**", ""]

    try:
        from core.bot_manager import list_bots
        running = list_bots()
        running_count = sum(1 for b in running if b.get("status") == "running")
        lines.append(f"  Bots:     {running_count}/{len(running)} running")
    except Exception as e:
        lines.append("  Bots:     — (manager unavailable)")
        logger.warning(f"fleet status: bots failed: {e}")

    try:
        from core.click_tracker import get_stats
        stats = get_stats()
        lines.append(
            f"  Affiliate: ${stats.get('total_revenue_usd', 0.0):.2f} · "
            f"{stats.get('total_clicks', 0)} clicks (lifetime)"
        )
    except Exception as e:
        lines.append("  Affiliate: —")
        logger.warning(f"fleet status: clicks failed: {e}")

    try:
        from narai.integrations import telegram_subscription as ts
        active_tg = len(ts.list_active_subscribers())
        lines.append(f"  TG subs:  {active_tg} active")
    except Exception:
        pass

    try:
        from narai.integrations import discord_subscription as ds
        active_dc = len(ds.list_active_subscribers())
        lines.append(f"  Discord:  {active_dc} active")
    except Exception:
        pass

    from datetime import datetime
    lines.append("")
    lines.append(f"_as of {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_")

    await _post_to_discord(chan, "\n".join(lines))


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

    # Discord-side jobs (only register if a Discord channel is configured)
    if os.environ.get("DISCORD_BOT_TOKEN"):
        if _discord_content_channel():
            _add_job(_scheduler, "NARAI_DISCORD_BRIEFING_ENABLED",
                     "NARAI_DISCORD_BRIEFING_CRON", "5 7 * * 1-5",
                     _send_discord_morning_briefing, "discord_morning_briefing", tz)
            _add_job(_scheduler, "NARAI_DISCORD_SIGNALS_ENABLED",
                     "NARAI_DISCORD_SIGNALS_CRON", "5 12 * * 1-5",
                     _send_discord_daily_signals, "discord_midday_signals", tz)
            _add_job(_scheduler, "NARAI_DISCORD_WEEKLY_ENABLED",
                     "NARAI_DISCORD_WEEKLY_CRON", "5 18 * * 0",
                     _send_discord_weekly_review, "discord_weekly_review", tz)
        else:
            logger.info("Discord content channel unset — content jobs skipped")

        if _discord_status_channel():
            _add_job(_scheduler, "NARAI_DISCORD_STATUS_ENABLED",
                     "NARAI_DISCORD_STATUS_CRON", "0 * * * *",  # hourly
                     _send_discord_fleet_status, "discord_fleet_status", tz)
        else:
            logger.info("Discord status channel unset — fleet status job skipped")

    _scheduler.start()
    logger.info(f"insider scheduler started: tz={tz}, jobs={len(_scheduler.get_jobs())}")
