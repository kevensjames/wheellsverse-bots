"""Per-asset-class tuning knobs for the rule-based predictor.

Changing a value here is a full A/B lever — no code changes needed.
Stock thresholds are conservative (wider bands, longer SMAs). Crypto is
tighter and faster because price moves are larger.
"""
from __future__ import annotations


PREDICTOR_CONFIG: dict[str, dict] = {
    "stock": {
        "rsi_period": 14,
        "rsi_oversold": 30,
        "rsi_overbought": 70,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "sma_fast": 50,
        "sma_slow": 200,
        "horizon_hours": 24,
    },
    "crypto": {
        "rsi_period": 14,
        "rsi_oversold": 25,
        "rsi_overbought": 75,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "sma_fast": 20,
        "sma_slow": 50,
        "horizon_hours": 24,
    },
}


DEFAULT_ASSET_TYPE = "stock"


def get_config(asset_type: str) -> dict:
    return PREDICTOR_CONFIG.get(asset_type, PREDICTOR_CONFIG[DEFAULT_ASSET_TYPE])
