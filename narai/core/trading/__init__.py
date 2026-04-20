"""NarAI Trading Core — forecaster, sentiment, backtest, risk, paper trading."""
from narai.core.trading.forecaster import forecast, indicators
from narai.core.trading.sentiment import sentiment_score
from narai.core.trading.backtest import backtest_sma_crossover, backtest_custom
from narai.core.trading.risk import RiskManager, position_size
from narai.core.trading.paper import PaperBroker

__all__ = [
    "forecast",
    "indicators",
    "sentiment_score",
    "backtest_sma_crossover",
    "backtest_custom",
    "RiskManager",
    "position_size",
    "PaperBroker",
]
