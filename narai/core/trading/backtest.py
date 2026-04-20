"""Backtest engine — vectorized pandas. Returns equity curve + metrics.

Built-in strategies: SMA crossover. Custom strategies: pass a signal function
that maps a DataFrame with indicators → {-1, 0, 1} series.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable

import numpy as np
import pandas as pd

from narai.core.trading.forecaster import indicators as _indicators


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    start: str
    end: str
    initial_capital: float
    final_equity: float
    total_return_pct: float
    sharpe: float
    max_drawdown_pct: float
    win_rate_pct: float
    n_trades: int
    equity_curve: list[dict[str, Any]]  # [{date, equity}]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _metrics(
    equity: pd.Series,
    returns: pd.Series,
    trade_returns: list[float],
    initial: float,
) -> dict[str, float]:
    final = float(equity.iloc[-1])
    total_ret = (final / initial - 1) * 100

    # Sharpe (daily → annualized, risk-free rate = 0 for simplicity)
    if returns.std() > 0:
        sharpe = float((returns.mean() / returns.std()) * np.sqrt(252))
    else:
        sharpe = 0.0

    # Max drawdown
    peak = equity.cummax()
    dd = (equity - peak) / peak
    max_dd = float(dd.min()) * 100

    # Win rate
    if trade_returns:
        wins = sum(1 for r in trade_returns if r > 0)
        win_rate = wins / len(trade_returns) * 100
    else:
        win_rate = 0.0

    return {
        "final_equity": round(final, 2),
        "total_return_pct": round(total_ret, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(max_dd, 2),
        "win_rate_pct": round(win_rate, 2),
    }


def _run_vectorized(
    df: pd.DataFrame,
    signal: pd.Series,
    initial_capital: float,
    fee_bps: float = 5.0,
) -> tuple[pd.Series, pd.Series, list[float]]:
    """Long-only vectorized backtest.

    `signal` ∈ {-1, 0, 1}: position to hold at each bar's close (applied next bar).
    Returns (equity, bar_returns, per_trade_returns).
    """
    close = df["Close"]
    # Enter at next bar's close (shift signal forward)
    pos = signal.shift(1).fillna(0).clip(lower=0)  # long-only
    bar_returns = close.pct_change().fillna(0) * pos

    # Transaction costs on entry/exit
    fee = fee_bps / 1e4
    trades = pos.diff().abs().fillna(pos.iloc[0])
    costs = trades * fee
    bar_returns = bar_returns - costs

    equity = initial_capital * (1 + bar_returns).cumprod()

    # Compute per-trade returns (close → close while pos == 1)
    per_trade: list[float] = []
    in_trade = False
    entry = 0.0
    for i, p in enumerate(pos):
        if p > 0 and not in_trade:
            entry = float(close.iloc[i])
            in_trade = True
        elif p == 0 and in_trade:
            exit_px = float(close.iloc[i])
            per_trade.append((exit_px / entry - 1) - 2 * fee)
            in_trade = False
    return equity, bar_returns, per_trade


# ── Built-in strategies ───────────────────────────────────────────────────────

def _sma_crossover_signal(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.Series:
    """Long when fast SMA > slow SMA."""
    c = df["Close"]
    fast_ma = c.rolling(fast, min_periods=1).mean()
    slow_ma = c.rolling(slow, min_periods=1).mean()
    return (fast_ma > slow_ma).astype(int)


# ── Public API ────────────────────────────────────────────────────────────────

def _fetch(symbol: str, period: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.Ticker(symbol).history(period=period, auto_adjust=True)
    if df.empty:
        raise ValueError(f"No data for {symbol}")
    return df


def backtest_sma_crossover(
    symbol: str,
    period: str = "2y",
    fast: int = 20,
    slow: int = 50,
    initial_capital: float = 10_000,
    fee_bps: float = 5.0,
) -> BacktestResult:
    df = _fetch(symbol, period)
    signal = _sma_crossover_signal(df, fast=fast, slow=slow)
    equity, bar_ret, per_trade = _run_vectorized(df, signal, initial_capital, fee_bps)
    m = _metrics(equity, bar_ret, per_trade, initial_capital)

    step = max(1, len(equity) // 200)
    curve = [
        {"date": d.date().isoformat() if hasattr(d, "date") else str(d), "equity": round(float(v), 2)}
        for d, v in zip(equity.index[::step], equity.iloc[::step])
    ]

    return BacktestResult(
        symbol=symbol,
        strategy=f"SMA({fast}/{slow}) crossover",
        start=df.index[0].date().isoformat() if hasattr(df.index[0], "date") else str(df.index[0]),
        end=df.index[-1].date().isoformat() if hasattr(df.index[-1], "date") else str(df.index[-1]),
        initial_capital=initial_capital,
        final_equity=m["final_equity"],
        total_return_pct=m["total_return_pct"],
        sharpe=m["sharpe"],
        max_drawdown_pct=m["max_drawdown_pct"],
        win_rate_pct=m["win_rate_pct"],
        n_trades=len(per_trade),
        equity_curve=curve,
    )


def backtest_custom(
    symbol: str,
    signal_fn: Callable[[pd.DataFrame], pd.Series],
    period: str = "2y",
    initial_capital: float = 10_000,
    fee_bps: float = 5.0,
) -> BacktestResult:
    """Custom backtest: `signal_fn(df_with_indicators)` → signal Series ∈ {-1, 0, 1}."""
    df = _fetch(symbol, period)
    df_i = _indicators(df)
    signal = signal_fn(df_i).astype(int).clip(-1, 1)
    equity, bar_ret, per_trade = _run_vectorized(df, signal, initial_capital, fee_bps)
    m = _metrics(equity, bar_ret, per_trade, initial_capital)

    step = max(1, len(equity) // 200)
    curve = [
        {"date": d.date().isoformat() if hasattr(d, "date") else str(d), "equity": round(float(v), 2)}
        for d, v in zip(equity.index[::step], equity.iloc[::step])
    ]

    return BacktestResult(
        symbol=symbol,
        strategy="custom",
        start=df.index[0].date().isoformat() if hasattr(df.index[0], "date") else str(df.index[0]),
        end=df.index[-1].date().isoformat() if hasattr(df.index[-1], "date") else str(df.index[-1]),
        initial_capital=initial_capital,
        final_equity=m["final_equity"],
        total_return_pct=m["total_return_pct"],
        sharpe=m["sharpe"],
        max_drawdown_pct=m["max_drawdown_pct"],
        win_rate_pct=m["win_rate_pct"],
        n_trades=len(per_trade),
        equity_curve=curve,
    )
