"""Trading module tests — unit tests for pure logic, no network."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from narai.core.trading.backtest import backtest_custom, _run_vectorized
from narai.core.trading.forecaster import indicators, _signal_contributions
from narai.core.trading.risk import (
    RiskManager,
    RiskLimits,
    atr_stop,
    kelly_fraction,
    position_size,
    trailing_stop,
)
from narai.core.trading.sentiment import _score_text


# ── Indicators ────────────────────────────────────────────────────────────────

def _fake_ohlcv(n: int = 100, trend: float = 0.001) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    noise = rng.normal(0, 1, n).cumsum()
    close = 100 * (1 + trend * np.arange(n)) + noise
    return pd.DataFrame({"Close": close, "Open": close, "High": close + 1, "Low": close - 1, "Volume": 1000})


def test_indicators_attach():
    df = _fake_ohlcv(200)
    out = indicators(df)
    for col in ["sma_20", "sma_50", "ema_20", "rsi_14", "macd", "macd_signal", "macd_hist", "bb_up", "bb_lo"]:
        assert col in out.columns
    assert len(out) == len(df)


def test_signal_contributions_in_range():
    df = indicators(_fake_ohlcv(200, trend=0.005))
    votes = _signal_contributions(df.iloc[-1])
    assert set(votes.keys()) == {"sma_20_vs_50", "rsi", "macd", "bollinger"}
    for v in votes.values():
        assert -1.0 <= v <= 1.0


# ── Position sizing & risk ────────────────────────────────────────────────────

def test_position_size_basic():
    # $10k, entry $100, stop $95, risk 1% = $100 risk / $5 per share = 20 shares
    assert position_size(10_000, 100, 95, risk_pct=0.01, max_position_pct=1.0) == 20


def test_position_size_capped_by_max_position():
    # Would want 100 shares by risk, but max 20% of 10k = $2000 / $100 = 20 shares cap
    shares = position_size(10_000, 100, 99, risk_pct=0.01, max_position_pct=0.20)
    assert shares == 20


def test_position_size_zero_on_bad_input():
    assert position_size(10_000, 100, 100) == 0  # stop == entry
    assert position_size(10_000, 0, 10) == 0


def test_kelly_fraction_clamped():
    # Very favorable odds → clamped to 0.25
    assert kelly_fraction(0.9, 10.0, 1.0) == 0.25
    # Neutral → 0
    assert kelly_fraction(0.5, 1.0, 1.0) == 0.0
    # Bad odds → 0
    assert kelly_fraction(0.1, 1.0, 1.0) == 0.0


def test_risk_manager_allows_first_trade():
    rm = RiskManager(starting_equity=10_000)
    ok, shares, reason = rm.allow_trade(entry=100, stop=95)
    assert ok and shares > 0 and reason == "ok"


def test_risk_manager_halts_on_drawdown():
    rm = RiskManager(starting_equity=10_000, limits=RiskLimits(max_drawdown_pct=0.10))
    rm.on_fill()
    rm.on_close(pnl=-1500)  # 15 % loss from peak
    ok, _, reason = rm.allow_trade(entry=100, stop=95)
    assert not ok
    assert "max_drawdown" in reason


def test_risk_manager_halts_on_daily_loss():
    rm = RiskManager(starting_equity=10_000, limits=RiskLimits(max_daily_loss_pct=0.03))
    rm.on_fill()
    rm.on_close(pnl=-400)  # 4 % day
    ok, _, reason = rm.allow_trade(entry=100, stop=95)
    assert not ok
    assert "daily_loss" in reason


def test_risk_manager_halts_on_max_positions():
    rm = RiskManager(starting_equity=10_000, limits=RiskLimits(max_concurrent_positions=2))
    rm.on_fill(); rm.on_fill()
    ok, _, reason = rm.allow_trade(entry=100, stop=95)
    assert not ok and reason == "halted:max_positions"


def test_atr_stop_directions():
    assert atr_stop(100, atr=2, multiplier=2, long=True) == 96
    assert atr_stop(100, atr=2, multiplier=2, long=False) == 104


def test_trailing_stop():
    assert trailing_stop(110, highest_since_entry=120, trail_pct=0.05) == 114.0


# ── Backtest ──────────────────────────────────────────────────────────────────

def test_vectorized_backtest_shapes():
    df = _fake_ohlcv(100)
    signal = pd.Series(1, index=df.index)  # always long
    equity, bar_returns, trades = _run_vectorized(df, signal, 10_000)
    assert len(equity) == len(df)
    assert len(bar_returns) == len(df)
    # Always long with no exit → no closed trades
    assert isinstance(trades, list)


def test_backtest_custom_with_always_long():
    df = _fake_ohlcv(200, trend=0.002)

    def always_long(d: pd.DataFrame) -> pd.Series:
        return pd.Series(1, index=d.index)

    # Patch yfinance fetch
    from narai.core.trading import backtest as bt_mod
    orig = bt_mod._fetch
    bt_mod._fetch = lambda s, p: df
    try:
        r = backtest_custom("FAKE", always_long, period="1y", initial_capital=10_000)
    finally:
        bt_mod._fetch = orig

    assert r.symbol == "FAKE"
    assert r.initial_capital == 10_000
    assert r.final_equity > 0
    assert r.strategy == "custom"


# ── Sentiment lexicon ─────────────────────────────────────────────────────────

def test_sentiment_bullish():
    w, h = _score_text("TSLA surges to new ATH on strong partnership news, bullish outlook")
    assert w > 0 and h >= 3


def test_sentiment_bearish():
    w, h = _score_text("Major crash, plunge, and bankruptcy fears in the crypto market")
    assert w < 0 and h >= 3


def test_sentiment_negation():
    # "not bullish" should flip the weight
    w_pos, _ = _score_text("market is bullish today")
    w_neg, _ = _score_text("market is not bullish today")
    assert w_pos > 0 > w_neg


def test_sentiment_no_match():
    w, h = _score_text("weather is nice")
    assert w == 0 and h == 0


# ── Paper broker (no network) ─────────────────────────────────────────────────

def test_paper_broker_buy_sell_roundtrip(tmp_path, monkeypatch):
    ledger = tmp_path / "ledger.json"
    monkeypatch.setenv("NARAI_PAPER_LEDGER", str(ledger))

    from narai.core.trading import paper as paper_mod
    from narai.core.trading.paper import PaperBroker

    # Stub price
    monkeypatch.setattr(PaperBroker, "_price", lambda self, sym: 100.0)

    b = PaperBroker(starting_equity=10_000)
    r = b.buy("FAKE", 10)
    assert r["ok"] and r["shares"] == 10

    r = b.sell("FAKE")
    assert r["ok"] and r["pnl"] == 0.0

    s = b.status()
    assert s["n_trades"] == 1
    assert s["cash"] == 10_000.0


def test_paper_broker_insufficient_cash(tmp_path, monkeypatch):
    monkeypatch.setenv("NARAI_PAPER_LEDGER", str(tmp_path / "ledger.json"))
    from narai.core.trading.paper import PaperBroker

    monkeypatch.setattr(PaperBroker, "_price", lambda self, sym: 1000.0)
    b = PaperBroker(starting_equity=1_000)
    r = b.buy("FAKE", 10)  # costs 10k, have 1k
    assert not r["ok"]
    assert "insufficient cash" in r["error"]


def test_paper_broker_stop_triggered(tmp_path, monkeypatch):
    monkeypatch.setenv("NARAI_PAPER_LEDGER", str(tmp_path / "ledger.json"))
    from narai.core.trading.paper import PaperBroker

    prices = {"FAKE": 100.0}
    monkeypatch.setattr(PaperBroker, "_price", lambda self, sym: prices[sym])
    b = PaperBroker(starting_equity=10_000)
    b.buy("FAKE", 10, stop_price=95.0)

    # Drop price under stop
    prices["FAKE"] = 90.0
    triggered = b.check_stops()
    assert len(triggered) == 1
    assert triggered[0]["symbol"] == "FAKE"
    assert "FAKE" not in b.status()["open_positions"] or b.status()["n_trades"] == 1
