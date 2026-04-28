"""
Daily briefing assembler.

Each section is wrapped in a defensive try/except so a missing data source
(no Google OAuth yet, empty click_tracker, paper broker not initialized)
degrades that section to a graceful "—" line instead of breaking the whole
briefing. The cron firing this should never crash on missing data.

Sections (in order):
  1. Header — date, owner greeting
  2. Revenue — yesterday's affiliate clicks + conversions ($)
  3. Trading — paper broker P&L + active positions + open SELL signals
  4. Calendar — today's events from Google Calendar
  5. Inbox — top priority emails (Phase 2.1; stub for now)
  6. Crypto — BTC/ETH from yfinance (already a dep) + 24h change
  7. KPIs — yesterday vs day-before deltas (clicks, revenue)

Public API:
    assemble_briefing(now: datetime | None = None) -> str   # plain text
    deliver_via_telegram(text: str) -> bool                  # send + log
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("narai.briefing")

ROOT = Path(__file__).resolve().parents[2]


# ── Section: Revenue ─────────────────────────────────────────────────────────

def _revenue_section(yesterday: datetime) -> str:
    try:
        from core.click_tracker import get_stats
        stats = get_stats()
        total_clicks = stats.get("total_clicks", 0)
        revenue = stats.get("total_revenue_usd", 0.0)
        by_partner = stats.get("by_partner", {})
        # All-time top partner — yesterday filtering would need timestamps; we
        # surface lifetime numbers and let the user see momentum from KPI delta.
        top_partner = max(by_partner.items(), key=lambda kv: kv[1])[0] if by_partner else "—"
        return (
            f"💰 Revenue (lifetime): ${revenue:.2f} · "
            f"{total_clicks} clicks · top: {top_partner}"
        )
    except Exception as e:
        logger.warning(f"revenue_section failed: {e}")
        return "💰 Revenue: —"


# ── Section: Trading ─────────────────────────────────────────────────────────

def _trading_section() -> str:
    try:
        from narai.core.trading.paper import PaperBroker
        broker = PaperBroker()
        s = broker.status()
        # status() returns: equity, cash, starting_equity, open_positions, ...
        equity = s.get("equity", 0.0)
        cash = s.get("cash", 0.0)
        starting = s.get("starting_equity", 10_000.0)
        positions = s.get("open_positions", [])
        open_count = len(positions)
        pnl = equity - starting
        sign = "+" if pnl >= 0 else ""
        ret_pct = s.get("total_return_pct", 0.0)
        return (
            f"📈 Trading: ${equity:,.0f} equity ({sign}${pnl:,.0f} / {sign}{ret_pct:.1f}%) · "
            f"{open_count} open · cash ${cash:,.0f}"
        )
    except Exception as e:
        logger.warning(f"trading_section failed: {e}")
        return "📈 Trading: —"


# ── Section: Calendar ────────────────────────────────────────────────────────

def _calendar_section(now: datetime) -> str:
    try:
        from narai_godmode.adapters.google import get_service, GoogleReauthRequired
        try:
            service = get_service("calendar")
        except GoogleReauthRequired:
            return "📅 Calendar: reconnect Google in /admin → NarAI Godmode"
        # Fetch events from now → end of day, owner's primary calendar.
        end_of_day = now.replace(hour=23, minute=59, second=59).astimezone(timezone.utc)
        events_result = service.events().list(
            calendarId="primary",
            timeMin=now.astimezone(timezone.utc).isoformat(),
            timeMax=end_of_day.isoformat(),
            maxResults=5,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        events = events_result.get("items", [])
        if not events:
            return "📅 Calendar: clear day"
        first = events[0]
        first_title = (first.get("summary") or "(no title)")[:50]
        first_start = first.get("start", {}).get("dateTime", "")
        # Truncate ISO to HH:MM if present
        first_time = first_start[11:16] if len(first_start) > 16 else "all-day"
        return f"📅 Calendar: {len(events)} event(s) · next: {first_title} at {first_time}"
    except Exception as e:
        logger.warning(f"calendar_section failed: {e}")
        return "📅 Calendar: —"


# ── Section: Inbox (stub for now) ────────────────────────────────────────────

def _inbox_section() -> str:
    """Stub — will be expanded once Gmail priority classifier ships."""
    return "📨 Inbox: priority filter not yet wired"


# ── Section: Crypto ──────────────────────────────────────────────────────────

def _crypto_section() -> str:
    try:
        import yfinance as yf
        out = []
        for ticker_sym, label in [("BTC-USD", "BTC"), ("ETH-USD", "ETH")]:
            t = yf.Ticker(ticker_sym)
            hist = t.history(period="2d", interval="1d")
            if hist.empty or len(hist) < 1:
                continue
            last = float(hist["Close"].iloc[-1])
            prev = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else last
            pct = ((last - prev) / prev * 100) if prev else 0.0
            sign = "+" if pct >= 0 else ""
            out.append(f"{label} ${last:,.0f} ({sign}{pct:.1f}%)")
        if not out:
            return "🪙 Crypto: —"
        return "🪙 Crypto: " + " · ".join(out)
    except Exception as e:
        logger.warning(f"crypto_section failed: {e}")
        return "🪙 Crypto: —"


# ── Section: KPI delta (placeholder) ─────────────────────────────────────────

def _kpi_section() -> str:
    """Day-over-day delta placeholder. Click_tracker doesn't currently slice
    by day, so this is a stub until we add date-bucketed totals."""
    return "✅ KPIs: tracking enabled"


# ── Assembler ────────────────────────────────────────────────────────────────

def assemble_briefing(now: datetime | None = None) -> str:
    """Build the morning briefing as plain text (Telegram HTML-safe).

    Each section is best-effort. A failing data source produces a "—" line,
    never a raised exception. The full briefing should be safe to deliver
    regardless of which integrations are configured.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    date_str = now.strftime("%A, %B %-d, %Y")

    lines = [
        f"🌅 <b>Good morning, J.K.</b>",
        f"<i>{date_str}</i>",
        "",
        _revenue_section(yesterday),
        _trading_section(),
        _calendar_section(now),
        _inbox_section(),
        _crypto_section(),
        _kpi_section(),
        "",
        "→ Reply with a question or command.",
    ]
    return "\n".join(lines)


# ── Delivery ─────────────────────────────────────────────────────────────────

async def deliver_via_telegram(text: str) -> bool:
    """Send the briefing to OWNER_CHAT_ID. Returns True on success.
    Silently logs and returns False if Telegram isn't configured."""
    chat_id = int(os.environ.get("TELEGRAM_CHAT_ID", "0"))
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not chat_id or not token:
        logger.warning("Telegram not configured — briefing not delivered")
        return False
    try:
        from telegram import Bot
        from telegram.constants import ParseMode
        bot = Bot(token)
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
        logger.info(f"Briefing delivered to chat_id={chat_id} ({len(text)} chars)")
        return True
    except Exception as e:
        logger.error(f"Telegram delivery failed: {e}")
        return False
