"""Rule-based BUY/SELL/HOLD predictor. Vote-based across three indicators
(RSI, MACD histogram crossover, SMA golden/death cross). Pure function —
no DB, no network.

Expected input: a DataFrame already enriched with indicator columns by
`app.ml.indicators.compute_all(df, asset_type)`. Rows with NaN indicator
values (warmup) must be dropped before calling predict().
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from pydantic import BaseModel

from app.config import settings
from app.ml.constants import SIGNAL_BUY, SIGNAL_HOLD, SIGNAL_SELL, Signal
from app.ml.predictor_config import get_config


class PredictionOutput(BaseModel):
    signal: Signal
    confidence: float
    target_price: float | None = None
    stop_loss: float | None = None
    features_snapshot: dict[str, Any] = {}
    horizon_hours: int


# ---------- crossover helpers ----------

def _crossed_above_zero(series: pd.Series, lookback: int) -> bool:
    """True if the most recent value is > 0 AND at least one value in the
    previous `lookback` bars was <= 0 (i.e., it actually crossed)."""
    if len(series) < lookback + 1:
        return False
    latest = series.iloc[-1]
    if not (latest > 0):
        return False
    window = series.iloc[-(lookback + 1):-1]
    return bool((window <= 0).any())


def _crossed_below_zero(series: pd.Series, lookback: int) -> bool:
    if len(series) < lookback + 1:
        return False
    latest = series.iloc[-1]
    if not (latest < 0):
        return False
    window = series.iloc[-(lookback + 1):-1]
    return bool((window >= 0).any())


def _golden_cross(fast: pd.Series, slow: pd.Series, lookback: int) -> bool:
    if len(fast) < lookback + 1 or len(slow) < lookback + 1:
        return False
    if not (fast.iloc[-1] > slow.iloc[-1]):
        return False
    diff = fast.iloc[-(lookback + 1):-1].values - slow.iloc[-(lookback + 1):-1].values
    return bool((diff <= 0).any())


def _death_cross(fast: pd.Series, slow: pd.Series, lookback: int) -> bool:
    if len(fast) < lookback + 1 or len(slow) < lookback + 1:
        return False
    if not (fast.iloc[-1] < slow.iloc[-1]):
        return False
    diff = fast.iloc[-(lookback + 1):-1].values - slow.iloc[-(lookback + 1):-1].values
    return bool((diff >= 0).any())


# ---------- individual votes ----------

def _rsi_vote(rsi_latest: float, oversold: float, overbought: float) -> float:
    if math.isnan(rsi_latest):
        return 0.0
    if rsi_latest < oversold:
        return 1.0
    if rsi_latest > overbought:
        return -1.0
    return 0.0


def _macd_vote(hist: pd.Series, lookback: int = 3) -> float:
    if _crossed_above_zero(hist, lookback):
        return 1.0
    if _crossed_below_zero(hist, lookback):
        return -1.0
    return 0.0


def _sma_vote(fast: pd.Series, slow: pd.Series, lookback: int = 5) -> float:
    if _golden_cross(fast, slow, lookback):
        return 1.0
    if _death_cross(fast, slow, lookback):
        return -1.0
    # fallback: trend-following bias (no crossover, but one is above/below the other)
    if len(fast) == 0 or len(slow) == 0:
        return 0.0
    fast_latest, slow_latest = fast.iloc[-1], slow.iloc[-1]
    if math.isnan(fast_latest) or math.isnan(slow_latest):
        return 0.0
    return 0.5 if fast_latest > slow_latest else -0.5


# ---------- JSON-safe snapshot helpers ----------

def _py(v: Any) -> Any:
    """Coerce numpy scalars to native Python so json.dumps doesn't choke."""
    if v is None:
        return None
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if math.isnan(f) else f
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, float):
        return None if math.isnan(v) else v
    return v


# ---------- main entry point ----------

def predict(df: pd.DataFrame, asset_type: str) -> PredictionOutput:
    cfg = get_config(asset_type)
    horizon = cfg["horizon_hours"]
    min_rows = settings.MIN_PRICE_HISTORY_ROWS

    if df is None or len(df) < min_rows:
        return PredictionOutput(
            signal=SIGNAL_HOLD,
            confidence=0.0,
            features_snapshot={
                "reason": "insufficient_data",
                "rows": int(len(df)) if df is not None else 0,
                "required": min_rows,
                "asset_type": asset_type,
            },
            horizon_hours=horizon,
        )

    sma_fast_col = f"sma_{cfg['sma_fast']}"
    sma_slow_col = f"sma_{cfg['sma_slow']}"

    rsi = df["rsi"]
    macd_hist = df["macd_hist"]
    sma_fast = df[sma_fast_col]
    sma_slow = df[sma_slow_col]

    rsi_vote = _rsi_vote(rsi.iloc[-1], cfg["rsi_oversold"], cfg["rsi_overbought"])
    macd_vote = _macd_vote(macd_hist, lookback=3)
    sma_vote = _sma_vote(sma_fast, sma_slow, lookback=5)

    total_score = rsi_vote + macd_vote + sma_vote

    if total_score >= 1.5:
        signal: Signal = SIGNAL_BUY
    elif total_score <= -1.5:
        signal = SIGNAL_SELL
    else:
        signal = SIGNAL_HOLD

    confidence = round(min(abs(total_score) / 3.0 * 100, 100.0), 2)

    close = float(df["close"].iloc[-1])
    if signal == SIGNAL_BUY:
        target_price: float | None = round(close * 1.03, 6)
        stop_loss: float | None = round(close * 0.98, 6)
    elif signal == SIGNAL_SELL:
        target_price = round(close * 0.97, 6)
        stop_loss = round(close * 1.02, 6)
    else:
        target_price = None
        stop_loss = None

    features_snapshot: dict[str, Any] = {
        "asset_type": asset_type,
        "model_version": settings.MODEL_VERSION,
        "config": {k: _py(v) for k, v in cfg.items()},
        "close": close,
        "rsi": _py(rsi.iloc[-1]),
        "macd": _py(df["macd"].iloc[-1]) if "macd" in df.columns else None,
        "macd_signal": _py(df["macd_signal"].iloc[-1]) if "macd_signal" in df.columns else None,
        "macd_hist": _py(macd_hist.iloc[-1]),
        sma_fast_col: _py(sma_fast.iloc[-1]),
        sma_slow_col: _py(sma_slow.iloc[-1]),
        "votes": {
            "rsi": rsi_vote,
            "macd": macd_vote,
            "sma": sma_vote,
            "total_score": total_score,
        },
    }

    return PredictionOutput(
        signal=signal,
        confidence=confidence,
        target_price=target_price,
        stop_loss=stop_loss,
        features_snapshot=features_snapshot,
        horizon_hours=horizon,
    )
