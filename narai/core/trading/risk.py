"""Risk manager — position sizing, stop loss, max drawdown circuit breaker.

Stateful per-account. Caller instantiates RiskManager with account equity,
asks `allow_trade(...)` before placing orders, and calls `on_fill/on_close`
to update state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── Position sizing ───────────────────────────────────────────────────────────

def position_size(
    equity: float,
    entry_price: float,
    stop_price: float,
    risk_pct: float = 0.01,
    max_position_pct: float = 0.20,
) -> int:
    """Fixed-fractional sizing: risk `risk_pct` of equity per trade.

    Returns integer share count.
    """
    if entry_price <= 0 or stop_price <= 0 or entry_price == stop_price:
        return 0
    risk_per_share = abs(entry_price - stop_price)
    shares_by_risk = int((equity * risk_pct) / risk_per_share)
    shares_by_cap = int((equity * max_position_pct) / entry_price)
    return max(0, min(shares_by_risk, shares_by_cap))


def kelly_fraction(win_rate: float, avg_win: float, avg_loss: float) -> float:
    """Kelly criterion optimal fraction. Clamped to [0, 0.25] for safety."""
    if avg_loss <= 0:
        return 0.0
    b = avg_win / avg_loss
    q = 1 - win_rate
    f = win_rate - (q / b) if b > 0 else 0.0
    return max(0.0, min(0.25, f))


# ── Risk manager ──────────────────────────────────────────────────────────────

@dataclass
class RiskLimits:
    max_position_pct: float = 0.20     # 20 % of equity per trade
    risk_pct: float = 0.01              # 1 % risk per trade
    max_daily_loss_pct: float = 0.05    # halt trading after -5 % day
    max_drawdown_pct: float = 0.20      # halt after -20 % peak drawdown
    max_concurrent_positions: int = 10


@dataclass
class RiskManager:
    starting_equity: float
    limits: RiskLimits = field(default_factory=RiskLimits)
    current_equity: float = 0.0
    peak_equity: float = 0.0
    day_start_equity: float = 0.0
    open_positions: int = 0
    halted_reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.current_equity == 0.0:
            self.current_equity = self.starting_equity
        self.peak_equity = max(self.peak_equity, self.current_equity)
        self.day_start_equity = self.current_equity

    # ── Circuit breakers ──────────────────────────────────────────────────────

    def _check_limits(self) -> None:
        # Max drawdown from peak
        dd = (self.peak_equity - self.current_equity) / self.peak_equity if self.peak_equity else 0
        if dd >= self.limits.max_drawdown_pct:
            self.halted_reason = f"max_drawdown ({dd:.1%})"
            return
        # Daily loss
        if self.day_start_equity:
            day_loss = (self.day_start_equity - self.current_equity) / self.day_start_equity
            if day_loss >= self.limits.max_daily_loss_pct:
                self.halted_reason = f"daily_loss ({day_loss:.1%})"
                return
        # Position cap
        if self.open_positions >= self.limits.max_concurrent_positions:
            self.halted_reason = "max_positions"
            return
        self.halted_reason = None

    # ── Public API ────────────────────────────────────────────────────────────

    def allow_trade(self, entry: float, stop: float) -> tuple[bool, int, str]:
        """Pre-trade check. Returns (allowed, shares, reason)."""
        self._check_limits()
        if self.halted_reason:
            return False, 0, f"halted:{self.halted_reason}"

        shares = position_size(
            equity=self.current_equity,
            entry_price=entry,
            stop_price=stop,
            risk_pct=self.limits.risk_pct,
            max_position_pct=self.limits.max_position_pct,
        )
        if shares == 0:
            return False, 0, "zero_size"
        return True, shares, "ok"

    def on_fill(self) -> None:
        self.open_positions += 1

    def on_close(self, pnl: float) -> None:
        self.open_positions = max(0, self.open_positions - 1)
        self.current_equity += pnl
        self.peak_equity = max(self.peak_equity, self.current_equity)

    def new_day(self) -> None:
        self.day_start_equity = self.current_equity

    def status(self) -> dict[str, object]:
        self._check_limits()
        return {
            "equity": round(self.current_equity, 2),
            "peak_equity": round(self.peak_equity, 2),
            "drawdown_pct": round((self.peak_equity - self.current_equity) / self.peak_equity * 100, 2) if self.peak_equity else 0,
            "open_positions": self.open_positions,
            "halted": self.halted_reason is not None,
            "halted_reason": self.halted_reason,
        }


# ── Stop loss helpers ─────────────────────────────────────────────────────────

def atr_stop(entry: float, atr: float, multiplier: float = 2.0, long: bool = True) -> float:
    """ATR-based stop loss distance."""
    if long:
        return entry - multiplier * atr
    return entry + multiplier * atr


def trailing_stop(current_price: float, highest_since_entry: float, trail_pct: float = 0.05) -> float:
    """Trailing stop that ratchets up."""
    return highest_since_entry * (1 - trail_pct)
