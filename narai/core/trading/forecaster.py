"""Price forecaster — technical indicators + momentum/mean-reversion signals.
No heavy ML deps. yfinance for OHLCV; pandas for math.

Future: plug LSTM/transformer models behind the same `forecast()` API.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Optional

import numpy as np
import pandas as pd


# ── Indicators ────────────────────────────────────────────────────────────────

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(window=n, min_periods=1).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _rsi(s: pd.Series, n: int = 14) -> pd.Series:
    delta = s.diff()
    gain = delta.clip(lower=0).rolling(n, min_periods=1).mean()
    loss = (-delta.clip(upper=0)).rolling(n, min_periods=1).mean()
    rs = gain / loss.replace(0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(50)


def _macd(s: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    macd = _ema(s, 12) - _ema(s, 26)
    signal = _ema(macd, 9)
    return macd, signal, macd - signal


def _bollinger(s: pd.Series, n: int = 20, k: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    mid = _sma(s, n)
    std = s.rolling(n, min_periods=1).std()
    return mid, mid + k * std, mid - k * std


def indicators(df: pd.DataFrame, close_col: str = "Close") -> pd.DataFrame:
    """Attach SMA/EMA/RSI/MACD/Bollinger to an OHLCV DataFrame."""
    out = df.copy()
    c = out[close_col]
    out["sma_20"] = _sma(c, 20)
    out["sma_50"] = _sma(c, 50)
    out["ema_20"] = _ema(c, 20)
    out["rsi_14"] = _rsi(c, 14)
    macd, sig, hist = _macd(c)
    out["macd"] = macd
    out["macd_signal"] = sig
    out["macd_hist"] = hist
    mid, up, lo = _bollinger(c, 20)
    out["bb_mid"], out["bb_up"], out["bb_lo"] = mid, up, lo
    return out


# ── Price fetch ───────────────────────────────────────────────────────────────

def _fetch_ohlcv(symbol: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    import yfinance as yf
    df = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No price data for {symbol}")
    return df


# ── Forecast ──────────────────────────────────────────────────────────────────

@dataclass
class Forecast:
    symbol: str
    last_close: float
    prediction: float
    direction: str           # "up" | "down" | "flat"
    confidence: float        # 0..1
    horizon_days: int
    signals: dict[str, Any]  # breakdown of signal contributions

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _signal_contributions(row: pd.Series) -> dict[str, float]:
    """Return each indicator's vote on direction: +1 bullish, -1 bearish, 0 neutral."""
    s: dict[str, float] = {}
    # MA crossover
    s["sma_20_vs_50"] = 1.0 if row["sma_20"] > row["sma_50"] else -1.0
    # RSI
    rsi = row["rsi_14"]
    s["rsi"] = -1.0 if rsi > 70 else 1.0 if rsi < 30 else 0.0
    # MACD
    s["macd"] = 1.0 if row["macd_hist"] > 0 else -1.0
    # Bollinger
    c = row["Close"]
    if c > row["bb_up"]:
        s["bollinger"] = -0.5   # overbought
    elif c < row["bb_lo"]:
        s["bollinger"] = 0.5    # oversold → mean-revert bullish
    else:
        s["bollinger"] = 0.0
    return s


def forecast(
    symbol: str,
    horizon_days: int = 5,
    period: str = "6mo",
    sentiment: Optional[float] = None,
) -> Forecast:
    """Return a directional forecast for `symbol`.

    `sentiment` is an optional external score in [-1,1] that adds weight.
    """
    df = _fetch_ohlcv(symbol, period=period)
    df = indicators(df)
    last = df.iloc[-1]

    votes = _signal_contributions(last)
    if sentiment is not None:
        votes["sentiment"] = max(-1.0, min(1.0, sentiment))

    score = sum(votes.values())
    max_score = len(votes)  # each vote ∈ [-1,1]
    norm = score / max_score  # [-1,1]

    # Confidence = |normalized score|; direction from sign
    direction = "up" if norm > 0.15 else "down" if norm < -0.15 else "flat"

    # Naive expected move: ATR-scaled
    atr = (df["Close"].pct_change().abs().rolling(14).mean().iloc[-1] or 0.01)
    pct_move = norm * atr * horizon_days
    prediction = float(last["Close"] * (1 + pct_move))

    return Forecast(
        symbol=symbol,
        last_close=float(last["Close"]),
        prediction=round(prediction, 4),
        direction=direction,
        confidence=round(abs(norm), 3),
        horizon_days=horizon_days,
        signals=votes,
    )
