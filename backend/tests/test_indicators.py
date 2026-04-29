import math

import numpy as np
import pandas as pd
import pytest

from app.ml.indicators import compute_all, compute_macd, compute_rsi, compute_sma


def _ohlcv(rows: int = 300) -> pd.DataFrame:
    start = pd.Timestamp("2025-01-01", tz="UTC")
    idx = [start + pd.Timedelta(days=i) for i in range(rows)]
    # sinusoidal + uptrend so RSI/MACD actually move
    price = np.array([100 + i * 0.1 + math.sin(i / 10) * 5 for i in range(rows)])
    return pd.DataFrame(
        {
            "timestamp": idx,
            "open": price,
            "high": price * 1.01,
            "low": price * 0.99,
            "close": price * (1 + np.sin(np.arange(rows) / 7) * 0.002),
            "volume": 1_000_000,
        }
    )


def test_compute_rsi_range():
    df = compute_rsi(_ohlcv(300), period=14)
    rsi = df["rsi"].dropna()
    assert len(rsi) > 0
    assert rsi.min() >= 0.0
    assert rsi.max() <= 100.0


def test_compute_macd_columns():
    df = compute_macd(_ohlcv(300))
    for col in ("macd", "macd_signal", "macd_hist"):
        assert col in df.columns
    # hist should be macd - signal
    tail = df.dropna(subset=["macd", "macd_signal", "macd_hist"]).tail(20)
    assert np.allclose((tail["macd"] - tail["macd_signal"]).values, tail["macd_hist"].values, atol=1e-9)


def test_compute_sma_periods():
    df = compute_sma(_ohlcv(300), periods=[10, 30])
    assert "sma_10" in df.columns
    assert "sma_30" in df.columns
    # sma_10 finishes warmup before sma_30
    assert df["sma_10"].notna().sum() > df["sma_30"].notna().sum()


def test_compute_all_no_mutation():
    df_in = _ohlcv(300)
    snapshot_cols = list(df_in.columns)
    _ = compute_all(df_in, asset_type="stock")
    assert list(df_in.columns) == snapshot_cols


def test_warmup_nans():
    # First N rows of RSI/SMA must be NaN until enough data accumulates.
    df = compute_all(_ohlcv(300), asset_type="stock")
    assert pd.isna(df["rsi"].iloc[0])
    assert pd.isna(df["sma_200"].iloc[50])  # well before 200-row warmup
    # After warmup, indicators must be populated.
    assert df["rsi"].iloc[-1] == df["rsi"].iloc[-1]  # not NaN
    assert df["sma_200"].iloc[-1] == df["sma_200"].iloc[-1]
