"""
Daily briefing assembler.

Each section is wrapped in a defensive try/except so a missing data source
(no Google OAuth yet, the board's database down, paper broker not initialized)
degrades that section to a graceful "—" line instead of breaking the whole
briefing. The cron firing this should never crash on missing data.

Sections (in order):
  1. Header — date, owner greeting
  2. Revenue — yesterday's revenue line from the daily numbers board
     (core.board.day: net, attributed revenue by channel, fees), for the New
     York calendar day, the same line as the board's 07:00 message
  3. Trading — paper broker P&L + active positions + open SELL signals
  4. Calendar — today's events from Google Calendar
  5. Inbox — top priority emails (Phase 2.1; stub for now)
  6. Crypto — BTC/ETH from yfinance (already a dep) + 24h change
  7. KPIs — yesterday vs the day before, both New York days: /go clicks
     (core.click_tracker.clicks_on) and net revenue (the board's day view).
     A number that cannot be read prints "—", never 0.

Sections 2 and 7 are the board's lines, the owner's numbers: board=False
leaves both out (the HTTP routes pass it unless the request also passes the
app's owner check, narai/api/routes/briefing.py). The 07:00 cron keeps them.

Public API:
    assemble_briefing(now: datetime | None = None, *, board: bool = True) -> str   # plain text
    deliver_via_telegram(text: str) -> bool                                         # send + log
"""
from __future__ import annotations

import html
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("narai.briefing")

ROOT = Path(__file__).resolve().parents[2]


# ── Section: Revenue ─────────────────────────────────────────────────────────

def _revenue_section(now: datetime) -> str:
    """Yesterday's revenue, New York day, from the board's day view: the same
    line as its morning message ('💰 Revenue: $10.00 net · attributed $29.99
    (meta) · fees $3.17'), or why there is no number ('not connected', never
    $0). The text is escaped for Telegram HTML."""
    try:
        from core.board import day as board_day
        view = board_day.day_view(board_day.yesterday_ny(now))
        return "💰 " + html.escape(board_day.summary_line(view), quote=False)
    except Exception as e:
        logger.warning(f"revenue_section failed: {e}")
        return "💰 Revenue: —"


# ── Section: Trading ─────────────────────────────────────────────────────────

def _trading_section() -> str:
    """Two-line trading update: equity headline + a positions/trades detail.
    The detail line names the top open position (or last closed trade) so
    the briefing shows momentum, not just totals."""
    try:
        from narai.core.trading.paper import PaperBroker
        broker = PaperBroker()
        s = broker.status()
        equity = s.get("equity", 0.0)
        cash = s.get("cash", 0.0)
        starting = s.get("starting_equity", 10_000.0)
        positions = s.get("open_positions", [])
        pnl = equity - starting
        sign = "+" if pnl >= 0 else ""
        ret_pct = s.get("total_return_pct", 0.0)
        head = (
            f"📈 Trading: ${equity:,.0f} equity ({sign}${pnl:,.0f} / {sign}{ret_pct:.1f}%) · "
            f"{len(positions)} open · cash ${cash:,.0f}"
        )

        # Detail line: top open by unrealized P&L, or fall back to last
        # closed trade. Returns "" when no positions and no trades yet so
        # the briefing stays compact instead of padding with empty headers.
        detail = ""
        if positions:
            top = max(positions, key=lambda p: p.get("unrealized_pnl", 0))
            up = top.get("unrealized_pnl", 0)
            up_sign = "+" if up >= 0 else ""
            detail = (
                f"   ↳ top open: {top.get('symbol', '?')} "
                f"x{top.get('shares', 0)} @ ${top.get('entry', 0):.2f} → "
                f"${top.get('current', 0):.2f} ({up_sign}${up:.0f})"
            )
        else:
            history = broker.history(limit=1)
            if history:
                last = history[0]
                lp = last.get("pnl", 0)
                lp_sign = "+" if lp >= 0 else ""
                detail = (
                    f"   ↳ last close: {last.get('symbol', '?')} "
                    f"({lp_sign}${lp:.0f}) — {last.get('reason', 'closed')}"
                )
        return head + (("\n" + detail) if detail else "")
    except Exception as e:
        logger.warning(f"trading_section failed: {e}")
        return "📈 Trading: —"


# ── Section: Calendar ────────────────────────────────────────────────────────

def _calendar_section(now: datetime) -> str:
    try:
        from narai.godmode.adapters.google import get_service, GoogleReauthRequired
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


# ── Section: Inbox ───────────────────────────────────────────────────────────

def _inbox_section() -> str:
    """Top of Gmail's priority inbox: unread + important. Returns count + the
    most-recent subject so the briefing surfaces the *thing* you'd want to
    skim first, not just a tally."""
    try:
        from narai.godmode.adapters.google import get_service, GoogleReauthRequired
        try:
            service = get_service("gmail")
        except GoogleReauthRequired:
            return "📨 Inbox: reconnect Google in /admin → NarAI Godmode"
        # Gmail's "is:important is:unread" matches the priority bucket the
        # web UI shows — same heuristic the user sees when they open Gmail.
        # maxResults=10 keeps us cheap; we only render a count + 1 subject.
        result = service.users().messages().list(
            userId="me",
            q="is:important is:unread",
            maxResults=10,
        ).execute()
        msgs = result.get("messages", [])
        if not msgs:
            return "📨 Inbox: 0 unread priority"
        # Fetch only the first message's headers to grab the subject.
        first = service.users().messages().get(
            userId="me",
            id=msgs[0]["id"],
            format="metadata",
            metadataHeaders=["Subject", "From"],
        ).execute()
        headers = {h["name"]: h["value"] for h in first.get("payload", {}).get("headers", [])}
        subject = (headers.get("Subject") or "(no subject)")[:50]
        from_ = (headers.get("From") or "?").split("<")[0].strip()[:30]
        return f"📨 Inbox: {len(msgs)} unread priority · top: \"{subject}\" — {from_}"
    except Exception as e:
        logger.warning(f"inbox_section failed: {e}")
        return "📨 Inbox: —"


# ── Section: Subscribers (Telegram + Discord member counts) ─────────────────

def _subscribers_section() -> str:
    """One-line read of audience size across the two main channels.
    Each platform fetched independently — a Discord auth issue won't kill
    the Telegram count."""
    parts = []

    # Telegram: prefer the private subscription channel ID if set; fall back
    # to the main TELEGRAM_CHAT_ID (the public/owner chat).
    # Uses sync HTTP directly against Telegram's REST API — avoids the
    # async/sync entanglement we had with python-telegram-bot's Bot class
    # (calling its async methods from a sync function inside an already-
    # running event loop produced 'cannot be called from a running event
    # loop' RuntimeErrors and orphaned coroutines).
    try:
        import requests
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chan = os.environ.get("TELEGRAM_PRIVATE_CHANNEL_ID") or os.environ.get("TELEGRAM_CHAT_ID")
        if token and chan:
            r = requests.get(
                f"https://api.telegram.org/bot{token}/getChatMemberCount",
                params={"chat_id": chan},
                timeout=8,
            )
            if r.ok and r.json().get("ok"):
                parts.append(f"TG {r.json()['result']}")
            else:
                logger.warning(f"telegram member count: HTTP {r.status_code} {r.text[:120]}")
    except Exception as e:
        logger.warning(f"telegram subscribers count failed: {e}")

    # Discord: REST GET on the guild with `with_counts=true` returns
    # approximate_member_count + approximate_presence_count without needing
    # the heavy gateway connection.
    try:
        import requests
        token = os.environ.get("DISCORD_BOT_TOKEN", "")
        guild = os.environ.get("DISCORD_GUILD_ID", "")
        if token and guild:
            r = requests.get(
                f"https://discord.com/api/v10/guilds/{guild}?with_counts=true",
                headers={"Authorization": f"Bot {token}"},
                timeout=8,
            )
            if r.ok:
                data = r.json()
                m = data.get("approximate_member_count", 0)
                online = data.get("approximate_presence_count", 0)
                parts.append(f"Discord {m} ({online} online)")
    except Exception as e:
        logger.warning(f"discord subscribers count failed: {e}")

    if not parts:
        return "👥 Subscribers: —"
    return "👥 Subscribers: " + " · ".join(parts)


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


# ── Section: KPI delta ───────────────────────────────────────────────────────

def _kpi_section(now: datetime) -> str:
    """Yesterday vs the day before, both New York calendar days: /go clicks
    (counted by the database) and net revenue (the board's day view). An
    unknown number prints '—', never 0, and gets no arrow. A partial day's
    revenue (its sync has not read the whole day) reads 'so far' and gets no
    arrow either: a day still being read is no drop."""
    try:
        from core.board import day as board_day
        from core.click_tracker import clicks_on
        yesterday = board_day.yesterday_ny(now)
        day_before = yesterday - timedelta(days=1)
        c_yest, c_prev = clicks_on(yesterday), clicks_on(day_before)
        rev_yest = board_day.day_view(yesterday)["numbers"]["revenue"]
        rev_prev = board_day.day_view(day_before)["numbers"]["revenue"]
        r_yest, r_prev = rev_yest["value"], rev_prev["value"]
        partial = "partial" in (rev_yest.get("state"), rev_prev.get("state"))
        so_far = " so far" if rev_yest.get("state") == "partial" and r_yest is not None else ""

        def _arrow(a, b) -> str:
            if a is None or b is None:
                return ""
            return " ▲" if a > b else (" ▼" if a < b else " →")

        def _n(value) -> str:
            return "—" if value is None else str(value)

        return (
            f"✅ KPIs (yesterday, New York): {_n(c_yest)} clicks{_arrow(c_yest, c_prev)} (prev {_n(c_prev)}) · "
            f"{board_day.money(r_yest)} net revenue{so_far}{'' if partial else _arrow(r_yest, r_prev)} "
            f"(prev {board_day.money(r_prev)})"
        )
    except Exception as e:
        logger.warning(f"kpi_section failed: {e}")
        return "✅ KPIs: —"


# ── Assembler ────────────────────────────────────────────────────────────────

def assemble_briefing(now: datetime | None = None, *, board: bool = True) -> str:
    """Build the morning briefing as plain text (Telegram HTML-safe).

    Each section is best-effort. A failing data source produces a "—" line,
    never a raised exception. The full briefing should be safe to deliver
    regardless of which integrations are configured.

    board=False leaves out the two lines read from the daily numbers board,
    the revenue line and the KPI line, and does not read the board at all:
    they are the owner's numbers. The other sections are the same either way.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    date_str = now.strftime("%A, %B %-d, %Y")

    lines = [
        f"🌅 <b>Good morning, J.K.</b>",
        f"<i>{date_str}</i>",
        "",
        *([_revenue_section(now)] if board else []),    # yesterday, New York day
        _trading_section(),
        _calendar_section(now),
        _inbox_section(),
        _subscribers_section(),
        _crypto_section(),
        *([_kpi_section(now)] if board else []),
        "",
        "→ Reply with a question or command.",
    ]
    return "\n".join(lines)


def assemble_briefing_markdown(now: datetime | None = None, *, board: bool = True) -> str:
    """Plain-text briefing for non-Telegram destinations (Slack, email, SMS).
    Strips the HTML tags assemble_briefing() emits and reflows minor markup.
    `board` as in assemble_briefing()."""
    import re
    html = assemble_briefing(now, board=board)
    # Drop <b>, </b>, <i>, </i> — leaving the contents intact.
    text = re.sub(r"</?[bi]>", "", html)
    return text


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


def log_briefing_to_memory(text: str) -> None:
    """Persist the briefing as a NarAI episode so the next chat call can
    recall 'what happened in today's briefing' without you re-stating it.
    Strips HTML so the embedded text is search-friendly. Errors swallowed —
    memory log is a side effect, never a delivery blocker."""
    try:
        import re
        from infra.brain.interface import BrainClient
        store = BrainClient(user_id="owner", mode="narai").memory.MemoryStore()
        clean = re.sub(r"</?[bi]>", "", text)
        store.log_episode(user_id="owner", content=f"Briefing:\n{clean}")
    except Exception as e:
        logger.warning(f"briefing memory log failed: {e}")
