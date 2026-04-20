"""Trading API routes — forecaster, sentiment, backtest, paper trading."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from narai.api.auth import require_auth
from narai.core.trading import (
    backtest_sma_crossover,
    forecast,
    sentiment_score,
    PaperBroker,
)

rt = APIRouter(tags=["trading"])

_broker: Optional[PaperBroker] = None


def _get_broker() -> PaperBroker:
    global _broker
    if _broker is None:
        _broker = PaperBroker()
    return _broker


# ── Forecast ──────────────────────────────────────────────────────────────────

class ForecastRequest(BaseModel):
    symbol: str
    horizon_days: int = 5
    period: str = "6mo"
    use_sentiment: bool = True


@rt.post("/trading/forecast")
async def trading_forecast(req: ForecastRequest, _=Depends(require_auth)) -> dict:
    try:
        sent = None
        if req.use_sentiment:
            try:
                s = sentiment_score(req.symbol)
                sent = s.score
            except Exception:
                sent = None
        f = forecast(req.symbol, horizon_days=req.horizon_days, period=req.period, sentiment=sent)
        return {"ok": True, "forecast": f.to_dict(), "sentiment_used": sent}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Sentiment ─────────────────────────────────────────────────────────────────

class SentimentRequest(BaseModel):
    symbol: str
    query: Optional[str] = None


@rt.post("/trading/sentiment")
async def trading_sentiment(req: SentimentRequest, _=Depends(require_auth)) -> dict:
    try:
        s = sentiment_score(req.symbol, query=req.query)
        return {"ok": True, "sentiment": s.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Backtest ──────────────────────────────────────────────────────────────────

class BacktestRequest(BaseModel):
    symbol: str
    period: str = "2y"
    fast: int = 20
    slow: int = 50
    initial_capital: float = 10_000
    fee_bps: float = 5.0


@rt.post("/trading/backtest")
async def trading_backtest(req: BacktestRequest, _=Depends(require_auth)) -> dict:
    try:
        result = backtest_sma_crossover(
            symbol=req.symbol,
            period=req.period,
            fast=req.fast,
            slow=req.slow,
            initial_capital=req.initial_capital,
            fee_bps=req.fee_bps,
        )
        return {"ok": True, "result": result.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── Paper trading ─────────────────────────────────────────────────────────────

class BuyRequest(BaseModel):
    symbol: str
    shares: int
    stop_price: Optional[float] = None


class SellRequest(BaseModel):
    symbol: str
    reason: str = "manual"


@rt.post("/trading/paper/buy")
async def paper_buy(req: BuyRequest, _=Depends(require_auth)) -> dict:
    r = _get_broker().buy(req.symbol, req.shares, stop_price=req.stop_price)
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r.get("error", "buy failed"))
    return r


@rt.post("/trading/paper/sell")
async def paper_sell(req: SellRequest, _=Depends(require_auth)) -> dict:
    r = _get_broker().sell(req.symbol, reason=req.reason)
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r.get("error", "sell failed"))
    return r


@rt.get("/trading/paper/status")
async def paper_status(_=Depends(require_auth)) -> dict:
    return {"ok": True, "status": _get_broker().status()}


@rt.get("/trading/paper/history")
async def paper_history(limit: int = 50, _=Depends(require_auth)) -> dict:
    return {"ok": True, "trades": _get_broker().history(limit=limit)}


@rt.post("/trading/paper/check_stops")
async def paper_check_stops(_=Depends(require_auth)) -> dict:
    return {"ok": True, "triggered": _get_broker().check_stops()}


@rt.post("/trading/paper/reset")
async def paper_reset(starting_equity: float = 10_000.0, _=Depends(require_auth)) -> dict:
    _get_broker().reset(starting_equity=starting_equity)
    return {"ok": True, "reset": True, "starting_equity": starting_equity}
