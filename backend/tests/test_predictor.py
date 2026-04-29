"""Unit tests for the pure predictor. Construct indicator-enriched DataFrames
directly so we can force specific vote outcomes without simulating real
price dynamics."""
from __future__ import annotations

import json

import pandas as pd
import pytest

from app.ml.predictor import predict
from app.ml.predictor_config import PREDICTOR_CONFIG


def _empty_like(rows: int) -> pd.DataFrame:
    start = pd.Timestamp("2025-01-01", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": [start + pd.Timedelta(days=i) for i in range(rows)],
            "open": [100.0] * rows,
            "high": [101.0] * rows,
            "low": [99.0] * rows,
            "close": [100.0] * rows,
            "volume": [1_000_000] * rows,
            "macd": [0.0] * rows,
            "macd_signal": [0.0] * rows,
        }
    )


def _strong_buy_df(asset_type: str = "stock", rows: int = 210) -> pd.DataFrame:
    """RSI oversold + MACD histogram crossed above zero + golden cross."""
    cfg = PREDICTOR_CONFIG[asset_type]
    df = _empty_like(rows)
    df["rsi"] = [50.0] * rows
    df.loc[df.index[-1], "rsi"] = cfg["rsi_oversold"] - 5  # oversold
    df["macd_hist"] = [-0.5] * rows
    df.loc[df.index[-1], "macd_hist"] = 0.5  # crossed above zero just now
    fast_col = f"sma_{cfg['sma_fast']}"
    slow_col = f"sma_{cfg['sma_slow']}"
    # Fast was BELOW slow for most of history; final 2 rows flip it above.
    df[fast_col] = [95.0] * rows
    df[slow_col] = [100.0] * rows
    df.loc[df.index[-2:], fast_col] = 105.0
    return df


def _strong_sell_df(asset_type: str = "stock", rows: int = 210) -> pd.DataFrame:
    cfg = PREDICTOR_CONFIG[asset_type]
    df = _empty_like(rows)
    df["rsi"] = [50.0] * rows
    df.loc[df.index[-1], "rsi"] = cfg["rsi_overbought"] + 5
    df["macd_hist"] = [0.5] * rows
    df.loc[df.index[-1], "macd_hist"] = -0.5  # crossed below zero
    fast_col = f"sma_{cfg['sma_fast']}"
    slow_col = f"sma_{cfg['sma_slow']}"
    df[fast_col] = [105.0] * rows
    df[slow_col] = [100.0] * rows
    df.loc[df.index[-2:], fast_col] = 95.0  # death cross
    return df


def _conflicting_df() -> pd.DataFrame:
    """RSI oversold (+1), MACD crossed DOWN (-1), no SMA cross, fast < slow (-0.5)
    → total = -0.5 → HOLD (abs < 1.5)."""
    df = _empty_like(210)
    df["rsi"] = [50.0] * 210
    df.loc[df.index[-1], "rsi"] = 25.0  # oversold
    df["macd_hist"] = [0.5] * 210
    df.loc[df.index[-1], "macd_hist"] = -0.5  # crossed below
    df["sma_50"] = [95.0] * 210
    df["sma_200"] = [100.0] * 210
    return df


def test_predict_insufficient_data():
    df = _empty_like(10)  # way below MIN_PRICE_HISTORY_ROWS
    df["rsi"] = 50.0
    df["macd_hist"] = 0.0
    df["sma_50"] = 100.0
    df["sma_200"] = 100.0
    out = predict(df, "stock")
    assert out.signal == "HOLD"
    assert out.confidence == 0.0
    assert out.features_snapshot.get("reason") == "insufficient_data"


def test_predict_strong_buy():
    out = predict(_strong_buy_df("stock"), "stock")
    assert out.signal == "BUY"
    assert out.confidence > 50.0
    assert out.target_price is not None
    assert out.stop_loss is not None
    # 3% up target, 2% down stop
    close = 100.0
    assert abs(out.target_price - close * 1.03) < 1e-6
    assert abs(out.stop_loss - close * 0.98) < 1e-6


def test_predict_strong_sell():
    out = predict(_strong_sell_df("stock"), "stock")
    assert out.signal == "SELL"
    assert out.confidence > 50.0
    assert out.target_price is not None and out.target_price < 100.0


def test_predict_conflicting_signals():
    out = predict(_conflicting_df(), "stock")
    assert out.signal == "HOLD"
    assert out.target_price is None
    assert out.stop_loss is None


def test_predict_stock_vs_crypto_config():
    """Same vote inputs; different asset_type uses different SMA column names.
    Build a crypto-shaped df and confirm it runs without KeyError."""
    out_stock = predict(_strong_buy_df("stock"), "stock")
    out_crypto = predict(_strong_buy_df("crypto"), "crypto")
    assert out_stock.signal == "BUY"
    assert out_crypto.signal == "BUY"
    # Snapshot must carry the right SMA columns for each asset type.
    assert "sma_50" in out_stock.features_snapshot
    assert "sma_200" in out_stock.features_snapshot
    assert "sma_20" in out_crypto.features_snapshot
    assert "sma_50" in out_crypto.features_snapshot


def test_features_snapshot_json_serializable():
    out = predict(_strong_buy_df("stock"), "stock")
    # Must round-trip through json.dumps without TypeError on numpy scalars.
    s = json.dumps(out.features_snapshot)
    assert isinstance(s, str) and len(s) > 0
