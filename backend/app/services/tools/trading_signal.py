"""Trading signal tool — RSI/MACD/SMA-vote for a ticker.

v1 calls yfinance + `ta` directly. Same indicator + voting logic the Trading
SaaS Stage 4 ships. Future revision swaps to the trading service's API once
it's live.
"""
from __future__ import annotations

import logging
from typing import Any

import yfinance as yf
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator

from app.services.tools.base import ToolContext, ToolError

logger = logging.getLogger(__name__)


RSI_OVERSOLD = 30
RSI_OVERBOUGHT = 70
SCORE_BUY = 1.5
SCORE_SELL = -1.5


class TradingSignalTool:
    name = "trading_signal"
    description = (
        "Compute a basic technical analysis signal for a stock or crypto ticker. "
        "Returns RSI, MACD, SMA20/50, a vote score in [-3, +3], and a "
        "BUY/SELL/HOLD recommendation. Descriptive only — not financial advice."
    )
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "Ticker symbol (e.g. AAPL, MSFT, BTC-USD).",
            },
            "period": {
                "type": "string",
                "description": "Lookback period for indicators. Default '3mo'.",
                "enum": ["1mo", "3mo", "6mo", "1y"],
            },
        },
        "required": ["ticker"],
    }

    def execute(self, ctx: ToolContext, **kwargs) -> dict[str, Any]:
        ticker = (kwargs.get("ticker") or "").strip().upper()
        if not ticker:
            raise ToolError("ticker required")
        period = kwargs.get("period") or "3mo"

        try:
            data = yf.download(
                ticker,
                period=period,
                interval="1d",
                progress=False,
                auto_adjust=True,
            )
        except Exception as e:
            raise ToolError(f"yfinance failure for {ticker}: {e}")

        if data is None or data.empty:
            raise ToolError(f"no price data for {ticker}")

        close = data["Close"].squeeze()
        if len(close) < 50:
            raise ToolError(f"not enough history for {ticker} ({len(close)} bars)")

        rsi = float(RSIIndicator(close=close, window=14).rsi().iloc[-1])
        macd_obj = MACD(close=close)
        macd_line = float(macd_obj.macd().iloc[-1])
        macd_signal = float(macd_obj.macd_signal().iloc[-1])
        sma20 = float(SMAIndicator(close=close, window=20).sma_indicator().iloc[-1])
        sma50 = float(SMAIndicator(close=close, window=50).sma_indicator().iloc[-1])
        last_price = float(close.iloc[-1])

        votes: list[tuple[str, int, str]] = []

        if rsi < RSI_OVERSOLD:
            votes.append(("rsi", 1, f"RSI {rsi:.1f} < {RSI_OVERSOLD} (oversold → BUY)"))
        elif rsi > RSI_OVERBOUGHT:
            votes.append(("rsi", -1, f"RSI {rsi:.1f} > {RSI_OVERBOUGHT} (overbought → SELL)"))
        else:
            votes.append(("rsi", 0, f"RSI {rsi:.1f} neutral"))

        if macd_line > macd_signal:
            votes.append(("macd", 1, f"MACD {macd_line:.2f} > signal {macd_signal:.2f} (BUY)"))
        elif macd_line < macd_signal:
            votes.append(("macd", -1, f"MACD {macd_line:.2f} < signal {macd_signal:.2f} (SELL)"))
        else:
            votes.append(("macd", 0, "MACD == signal"))

        if sma20 > sma50:
            votes.append(("sma_cross", 1, f"SMA20 {sma20:.2f} > SMA50 {sma50:.2f} (BUY)"))
        elif sma20 < sma50:
            votes.append(("sma_cross", -1, f"SMA20 {sma20:.2f} < SMA50 {sma50:.2f} (SELL)"))
        else:
            votes.append(("sma_cross", 0, "SMA20 == SMA50"))

        score = sum(v[1] for v in votes)
        if score >= SCORE_BUY:
            recommendation = "BUY"
        elif score <= SCORE_SELL:
            recommendation = "SELL"
        else:
            recommendation = "HOLD"

        return {
            "ticker": ticker,
            "last_price": round(last_price, 4),
            "rsi": round(rsi, 2),
            "macd": round(macd_line, 4),
            "macd_signal": round(macd_signal, 4),
            "sma20": round(sma20, 4),
            "sma50": round(sma50, 4),
            "score": score,
            "recommendation": recommendation,
            "votes": [
                {"indicator": v[0], "vote": v[1], "reason": v[2]} for v in votes
            ],
            "disclaimer": "Descriptive technical signal only. Not financial advice.",
        }
