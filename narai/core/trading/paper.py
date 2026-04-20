"""Paper trading ledger — simulated broker persisted to JSON.

Keeps account equity, open positions, and trade history. No real money.
Marks to market from yfinance on demand.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from narai.core.trading.risk import RiskManager, RiskLimits


ROOT = Path(__file__).parent.parent.parent
_DEFAULT_LEDGER = str(ROOT / "data" / "paper_ledger.json")
_lock = threading.Lock()


# ── Records ───────────────────────────────────────────────────────────────────

@dataclass
class Position:
    symbol: str
    shares: int
    entry_price: float
    entry_time: str
    stop_price: Optional[float] = None


@dataclass
class Trade:
    symbol: str
    shares: int
    entry_price: float
    exit_price: float
    entry_time: str
    exit_time: str
    pnl: float
    return_pct: float
    reason: str  # "signal" | "stop" | "manual" | "risk_halt"


@dataclass
class Ledger:
    starting_equity: float = 10_000.0
    cash: float = 10_000.0
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[Trade] = field(default_factory=list)
    peak_equity: float = 10_000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "starting_equity": self.starting_equity,
            "cash": self.cash,
            "peak_equity": self.peak_equity,
            "positions": {s: asdict(p) for s, p in self.positions.items()},
            "trades": [asdict(t) for t in self.trades],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Ledger":
        return cls(
            starting_equity=d.get("starting_equity", 10_000.0),
            cash=d.get("cash", 10_000.0),
            peak_equity=d.get("peak_equity", d.get("cash", 10_000.0)),
            positions={s: Position(**p) for s, p in d.get("positions", {}).items()},
            trades=[Trade(**t) for t in d.get("trades", [])],
        )


# ── Broker ────────────────────────────────────────────────────────────────────

class PaperBroker:
    """Single-account paper trading broker."""

    def __init__(self, ledger_path: Optional[str] = None, starting_equity: float = 10_000.0):
        self._path = ledger_path or os.getenv("NARAI_PAPER_LEDGER", _DEFAULT_LEDGER)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._ledger = self._load(starting_equity)
        self._risk = RiskManager(starting_equity=self._ledger.starting_equity,
                                 current_equity=self._total_equity())

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self, starting_equity: float) -> Ledger:
        p = Path(self._path)
        if p.exists():
            try:
                return Ledger.from_dict(json.loads(p.read_text()))
            except Exception:
                pass
        return Ledger(starting_equity=starting_equity, cash=starting_equity, peak_equity=starting_equity)

    def _save(self) -> None:
        with _lock:
            Path(self._path).write_text(json.dumps(self._ledger.to_dict(), indent=2))

    # ── Pricing ───────────────────────────────────────────────────────────────

    def _price(self, symbol: str) -> float:
        import yfinance as yf
        info = yf.Ticker(symbol).fast_info
        px = getattr(info, "last_price", None)
        if px is None:
            hist = yf.Ticker(symbol).history(period="1d")
            if hist.empty:
                raise ValueError(f"No price for {symbol}")
            px = float(hist["Close"].iloc[-1])
        return float(px)

    def _total_equity(self) -> float:
        total = self._ledger.cash
        for sym, pos in self._ledger.positions.items():
            try:
                total += pos.shares * self._price(sym)
            except Exception:
                total += pos.shares * pos.entry_price  # fallback
        return total

    # ── Public API ────────────────────────────────────────────────────────────

    def buy(self, symbol: str, shares: int, stop_price: Optional[float] = None) -> dict[str, Any]:
        if shares <= 0:
            return {"ok": False, "error": "shares must be > 0"}
        if symbol in self._ledger.positions:
            return {"ok": False, "error": "position already open — close first"}
        price = self._price(symbol)
        cost = price * shares
        if cost > self._ledger.cash:
            return {"ok": False, "error": f"insufficient cash: need ${cost:.2f}, have ${self._ledger.cash:.2f}"}

        # Risk check
        if stop_price:
            ok, allowed_shares, reason = self._risk.allow_trade(entry=price, stop=stop_price)
            if not ok:
                return {"ok": False, "error": f"risk_rejected:{reason}"}
            shares = min(shares, allowed_shares)
            cost = price * shares

        now = datetime.now(timezone.utc).isoformat()
        self._ledger.cash -= cost
        self._ledger.positions[symbol] = Position(
            symbol=symbol, shares=shares, entry_price=price,
            entry_time=now, stop_price=stop_price,
        )
        self._risk.on_fill()
        self._save()
        return {"ok": True, "symbol": symbol, "shares": shares, "price": price, "cost": round(cost, 2)}

    def sell(self, symbol: str, reason: str = "manual") -> dict[str, Any]:
        if symbol not in self._ledger.positions:
            return {"ok": False, "error": "no open position"}
        pos = self._ledger.positions[symbol]
        price = self._price(symbol)
        proceeds = price * pos.shares
        pnl = proceeds - (pos.entry_price * pos.shares)
        ret_pct = (price / pos.entry_price - 1) * 100

        now = datetime.now(timezone.utc).isoformat()
        self._ledger.cash += proceeds
        self._ledger.trades.append(Trade(
            symbol=symbol, shares=pos.shares,
            entry_price=pos.entry_price, exit_price=price,
            entry_time=pos.entry_time, exit_time=now,
            pnl=round(pnl, 2), return_pct=round(ret_pct, 3),
            reason=reason,
        ))
        del self._ledger.positions[symbol]
        self._risk.on_close(pnl)
        self._ledger.peak_equity = max(self._ledger.peak_equity, self._total_equity())
        self._save()
        return {"ok": True, "symbol": symbol, "price": price, "pnl": round(pnl, 2), "return_pct": round(ret_pct, 3)}

    def check_stops(self) -> list[dict[str, Any]]:
        """Close any position whose current price hit its stop."""
        triggered = []
        for sym in list(self._ledger.positions.keys()):
            pos = self._ledger.positions[sym]
            if pos.stop_price is None:
                continue
            try:
                cur = self._price(sym)
                if cur <= pos.stop_price:
                    result = self.sell(sym, reason="stop")
                    triggered.append({"symbol": sym, "stop": pos.stop_price, "price": cur, **result})
            except Exception:
                continue
        return triggered

    def status(self) -> dict[str, Any]:
        total = self._total_equity()
        open_pnl = 0.0
        positions = []
        for sym, pos in self._ledger.positions.items():
            try:
                cur = self._price(sym)
            except Exception:
                cur = pos.entry_price
            unr = (cur - pos.entry_price) * pos.shares
            open_pnl += unr
            positions.append({
                "symbol": sym,
                "shares": pos.shares,
                "entry": pos.entry_price,
                "current": round(cur, 4),
                "unrealized_pnl": round(unr, 2),
                "return_pct": round((cur / pos.entry_price - 1) * 100, 3),
                "stop": pos.stop_price,
            })

        realized = sum(t.pnl for t in self._ledger.trades)
        wins = sum(1 for t in self._ledger.trades if t.pnl > 0)
        n = len(self._ledger.trades)

        return {
            "equity": round(total, 2),
            "cash": round(self._ledger.cash, 2),
            "starting_equity": self._ledger.starting_equity,
            "peak_equity": round(self._ledger.peak_equity, 2),
            "total_return_pct": round((total / self._ledger.starting_equity - 1) * 100, 2),
            "unrealized_pnl": round(open_pnl, 2),
            "realized_pnl": round(realized, 2),
            "open_positions": positions,
            "n_trades": n,
            "win_rate_pct": round(wins / n * 100, 2) if n else 0.0,
        }

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        return [asdict(t) for t in self._ledger.trades[-limit:]]

    def reset(self, starting_equity: float = 10_000.0) -> None:
        self._ledger = Ledger(starting_equity=starting_equity, cash=starting_equity, peak_equity=starting_equity)
        self._save()
