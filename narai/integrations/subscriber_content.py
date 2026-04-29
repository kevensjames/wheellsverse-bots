"""Subscriber-facing content for the AI Stock Alerts Club channel.

Three deliverables, matching what's promised on /insider:

  • morning_briefing()  — fired 7am ET weekdays. Watchlist snapshot + top signals.
  • daily_signals()     — fired noon ET weekdays. Notable entry/exit ideas.
  • weekly_review()     — fired Sunday 6pm ET. Last week + look ahead.

Each function:
  - Returns an HTML-formatted string ready for Telegram sendMessage.
  - Catches per-ticker failures so a bad symbol doesn't kill the whole post.
  - Reads the watchlist from NARAI_INSIDER_WATCHLIST env (comma-separated).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Iterable

logger = logging.getLogger("narai.subscriber_content")

DEFAULT_WATCHLIST = ("SPY", "QQQ", "AAPL", "NVDA", "TSLA", "MSFT", "AMZN")
DEFAULT_CRYPTO = ("BTC-USD", "ETH-USD")
SIGNAL_CONFIDENCE_THRESHOLD = 0.30  # only show signals with |confidence| >= this


def _watchlist() -> tuple[str, ...]:
    raw = os.environ.get("NARAI_INSIDER_WATCHLIST", "").strip()
    if not raw:
        return DEFAULT_WATCHLIST
    return tuple(s.strip().upper() for s in raw.split(",") if s.strip())


def _crypto_list() -> tuple[str, ...]:
    raw = os.environ.get("NARAI_INSIDER_CRYPTO", "").strip()
    if not raw:
        return DEFAULT_CRYPTO
    return tuple(s.strip().upper() for s in raw.split(",") if s.strip())


def _arrow(direction: str) -> str:
    return {"up": "🟢", "down": "🔴", "flat": "⚪"}.get(direction, "⚪")


def _fmt_pct(value: float) -> str:
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}%"


def _safe_forecast(symbol: str):
    """Wrap forecast() so a single bad ticker doesn't break the whole post."""
    try:
        from narai.core.trading.forecaster import forecast
        return forecast(symbol, horizon_days=5)
    except Exception as e:
        logger.warning(f"forecast failed for {symbol}: {e}")
        return None


def _safe_quote(symbol: str) -> dict | None:
    """Last close + 1d change. Returns dict or None on failure."""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        hist = t.history(period="5d", interval="1d")
        if hist.empty or len(hist) < 2:
            return None
        last = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2])
        change_pct = ((last - prev) / prev) * 100 if prev else 0.0
        return {"symbol": symbol, "last": last, "change_pct": change_pct}
    except Exception as e:
        logger.warning(f"quote failed for {symbol}: {e}")
        return None


def _disclaimer() -> str:
    return (
        "<i>Educational content only — not investment advice. "
        "Markets are risky. Always do your own research.</i>"
    )


# ── Morning briefing ─────────────────────────────────────────────────────────


def morning_briefing(now: datetime | None = None) -> str:
    """7am ET weekday briefing. Watchlist quotes + crypto + top signals."""
    now = now or datetime.now(timezone.utc)
    date_str = now.strftime("%a %b %d, %Y").upper()

    sections: list[str] = [
        f"<b>📈 Morning Briefing — {date_str}</b>\n",
    ]

    # Equities watchlist
    quotes = [_safe_quote(s) for s in _watchlist()]
    quotes = [q for q in quotes if q]
    if quotes:
        sections.append("<b>Watchlist</b>")
        for q in quotes:
            sections.append(
                f"  {q['symbol']:<6} ${q['last']:,.2f}  {_fmt_pct(q['change_pct'])}"
            )
        sections.append("")

    # Crypto
    crypto = [_safe_quote(s) for s in _crypto_list()]
    crypto = [q for q in crypto if q]
    if crypto:
        sections.append("<b>Crypto</b>")
        for q in crypto:
            sections.append(
                f"  {q['symbol']:<8} ${q['last']:,.2f}  {_fmt_pct(q['change_pct'])}"
            )
        sections.append("")

    # Top forecasts
    forecasts = [_safe_forecast(s) for s in _watchlist()]
    forecasts = [f for f in forecasts if f]
    forecasts.sort(key=lambda f: abs(f.confidence), reverse=True)
    top = [f for f in forecasts if f.confidence >= SIGNAL_CONFIDENCE_THRESHOLD][:5]
    if top:
        sections.append("<b>AI signals (top 5)</b>")
        for f in top:
            sections.append(
                f"  {_arrow(f.direction)} {f.symbol} → {f.direction} "
                f"({int(f.confidence*100)}% conf, 5d target ${f.prediction:,.2f})"
            )
        sections.append("")

    sections.append(_disclaimer())
    return "\n".join(sections)


# ── Daily signals (midday) ───────────────────────────────────────────────────


def daily_signals() -> str:
    """Concise entry/exit ideas based on current forecast strength."""
    forecasts = [_safe_forecast(s) for s in _watchlist()]
    forecasts = [f for f in forecasts if f]

    bullish = [f for f in forecasts
               if f.direction == "up" and f.confidence >= SIGNAL_CONFIDENCE_THRESHOLD]
    bearish = [f for f in forecasts
               if f.direction == "down" and f.confidence >= SIGNAL_CONFIDENCE_THRESHOLD]

    bullish.sort(key=lambda f: f.confidence, reverse=True)
    bearish.sort(key=lambda f: f.confidence, reverse=True)

    sections: list[str] = ["<b>🤖 Midday signal scan</b>\n"]

    if bullish:
        sections.append("<b>Bullish (consider entry)</b>")
        for f in bullish[:3]:
            sections.append(
                f"  🟢 {f.symbol} @ ${f.last_close:,.2f} → "
                f"5d target ${f.prediction:,.2f} ({int(f.confidence*100)}% conf)"
            )
        sections.append("")
    if bearish:
        sections.append("<b>Bearish (consider exit / hedge)</b>")
        for f in bearish[:3]:
            sections.append(
                f"  🔴 {f.symbol} @ ${f.last_close:,.2f} → "
                f"5d target ${f.prediction:,.2f} ({int(f.confidence*100)}% conf)"
            )
        sections.append("")

    if not bullish and not bearish:
        sections.append("No high-confidence setups today. Patience.\n")

    sections.append(_disclaimer())
    return "\n".join(sections)


# ── Weekly review ────────────────────────────────────────────────────────────


def weekly_review(now: datetime | None = None) -> str:
    """Sunday 6pm ET. Recap last week's watchlist performance + look ahead."""
    now = now or datetime.now(timezone.utc)
    week_str = now.strftime("Week of %b %d").upper()

    sections: list[str] = [
        f"<b>📊 {week_str} — Portfolio Review</b>\n",
    ]

    # 5-day performance per watchlist ticker
    try:
        import yfinance as yf
        rows: list[tuple[str, float]] = []
        for sym in _watchlist():
            try:
                hist = yf.Ticker(sym).history(period="7d", interval="1d")
                if len(hist) >= 2:
                    rows.append((sym, ((hist["Close"].iloc[-1] / hist["Close"].iloc[0]) - 1) * 100))
            except Exception as e:
                logger.warning(f"weekly: {sym} fetch failed: {e}")
        rows.sort(key=lambda r: r[1], reverse=True)

        if rows:
            sections.append("<b>5-day performance</b>")
            for sym, pct in rows:
                emoji = "🟢" if pct > 0 else "🔴" if pct < 0 else "⚪"
                sections.append(f"  {emoji} {sym:<6} {_fmt_pct(pct)}")
            sections.append("")
    except Exception as e:
        logger.warning(f"weekly: yfinance failed: {e}")

    # Forward look: top 3 highest-confidence forecasts
    forecasts = [_safe_forecast(s) for s in _watchlist()]
    forecasts = [f for f in forecasts if f]
    forecasts.sort(key=lambda f: abs(f.confidence), reverse=True)
    top = forecasts[:3]
    if top:
        sections.append("<b>Highest-conviction setups for the week ahead</b>")
        for f in top:
            sections.append(
                f"  {_arrow(f.direction)} {f.symbol} → {f.direction} "
                f"({int(f.confidence*100)}% conf, 5d target ${f.prediction:,.2f})"
            )
        sections.append("")

    sections.append("Stay disciplined. See you Monday at 7am ET.\n")
    sections.append(_disclaimer())
    return "\n".join(sections)
