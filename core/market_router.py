#!/usr/bin/env python3
"""
core/market_router.py
─────────────────────────────────────────────────────────────────────────────
Market data API.

GET /api/market/summary          — major indices + top crypto snapshot
GET /api/market/stocks?symbols=  — stock quotes
GET /api/market/crypto?coins=    — crypto prices
GET /api/market/trending         — trending coins
GET/PATCH /api/market/watchlist  — user watchlist (from DB settings)
─────────────────────────────────────────────────────────────────────────────
"""

from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel
from core.market_engine import get_crypto, get_market_summary, get_stocks, get_trending_coins
from core.chat_db import get_setting, update_setting

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/summary")
def market_summary():
    return get_market_summary()


@router.get("/stocks")
def market_stocks(symbols: str = "AAPL,TSLA,NVDA,META,GOOGL"):
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:20]
    return {"stocks": get_stocks(sym_list)}


@router.get("/crypto")
def market_crypto(coins: str = "bitcoin,ethereum,solana,cardano,avalanche-2"):
    coin_list = [c.strip().lower() for c in coins.split(",") if c.strip()][:20]
    return {"crypto": get_crypto(coin_list)}


@router.get("/trending")
def market_trending():
    return {"trending": get_trending_coins(10)}


@router.get("/watchlist")
def market_watchlist():
    stocks_raw = get_setting("watchlist_stocks") or "AAPL,TSLA,NVDA"
    crypto_raw = get_setting("watchlist_crypto") or "bitcoin,ethereum"
    stock_list = [s.strip().upper() for s in stocks_raw.split(",") if s.strip()]
    crypto_list = [c.strip().lower() for c in crypto_raw.split(",") if c.strip()]
    stocks = get_stocks(stock_list) if stock_list else []
    crypto = get_crypto(crypto_list) if crypto_list else []
    return {
        "stocks": stocks,
        "crypto": crypto,
        "watchlist_stocks": stocks_raw,
        "watchlist_crypto": crypto_raw,
    }


class WatchlistUpdate(BaseModel):
    stocks: Optional[str] = None
    crypto: Optional[str] = None


@router.patch("/watchlist")
def market_watchlist_update(req: WatchlistUpdate):
    if req.stocks is not None:
        update_setting("watchlist_stocks", req.stocks)
    if req.crypto is not None:
        update_setting("watchlist_crypto", req.crypto)
    return {"updated": True}
