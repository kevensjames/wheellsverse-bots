"""Pure indicator functions. Each takes an OHLCV DataFrame sorted by timestamp
ascending and returns a *copy* with indicator columns added. No mutation.

Uses the `ta` library (pure Python) instead of TA-Lib — no C compile step,
works in Docker without grief.
"""
from __future__ import annotations

from typing import Iterable

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import MACD, SMAIndicator

from app.ml.predictor_config import PREDICTOR_CONFIG, get_config


def compute_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    out = df.copy()
    out["rsi"] = RSIIndicator(close=out["close"], window=period, fillna=False).rsi()
    return out


def compute_macd(
    df: pd.DataFrame,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    out = df.copy()
    macd = MACD(
        close=out["close"],
        window_slow=slow,
        window_fast=fast,
        window_sign=signal,
        fillna=False,
    )
    out["macd"] = macd.macd()
    out["macd_signal"] = macd.macd_signal()
    out["macd_hist"] = macd.macd_diff()
    return out


def compute_sma(df: pd.DataFrame, periods: Iterable[int] = (50, 200)) -> pd.DataFrame:
    out = df.copy()
    for p in periods:
        out[f"sma_{p}"] = SMAIndicator(close=out["close"], window=p, fillna=False).sma_indicator()
    return out


def compute_all(df: pd.DataFrame, asset_type: str = "stock") -> pd.DataFrame:
    """Apply RSI + MACD + SMA (fast & slow) with asset-class-specific parameters."""
    cfg = get_config(asset_type)
    out = compute_rsi(df, period=cfg["rsi_period"])
    out = compute_macd(
        out,
        fast=cfg["macd_fast"],
        slow=cfg["macd_slow"],
        signal=cfg["macd_signal"],
    )
    out = compute_sma(out, periods=[cfg["sma_fast"], cfg["sma_slow"]])
    return out


__all__ = [
    "compute_rsi",
    "compute_macd",
    "compute_sma",
    "compute_all",
    "PREDICTOR_CONFIG",
]
