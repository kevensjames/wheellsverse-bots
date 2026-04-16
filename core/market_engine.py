#!/usr/bin/env python3
"""
core/market_engine.py
─────────────────────────────────────────────────────────────────────────────
Real-time market data.
Stocks: yfinance (already in requirements)
Crypto: CoinGecko free API (no key needed)
Responses cached 60 seconds in memory.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import time
from typing import Dict, List

import requests

logger = logging.getLogger("market_engine")

_CACHE: Dict[str, tuple] = {}   # key → (data, timestamp)
_CACHE_TTL = 60                  # seconds


def _cached(key: str, fn):
    if key in _CACHE:
        data, ts = _CACHE[key]
        if time.time() - ts < _CACHE_TTL:
            return data
    data = fn()
    _CACHE[key] = (data, time.time())
    return data


def get_stocks(symbols: List[str]) -> List[Dict]:
    """Fetch stock quotes using yfinance."""
    def _fetch():
        try:
            import yfinance as yf
            result = []
            tickers = yf.Tickers(" ".join(symbols))
            for sym in symbols:
                try:
                    t = tickers.tickers.get(sym)
                    info = t.fast_info if t else {}
                    result.append({
                        "symbol": sym,
                        "price": getattr(info, "last_price", None),
                        "change_pct": getattr(info, "percent_change", None),
                        "market_cap": getattr(info, "market_cap", None),
                        "volume": getattr(info, "three_month_average_volume", None),
                        "currency": getattr(info, "currency", "USD"),
                    })
                except Exception as e:
                    result.append({"symbol": sym, "error": str(e)})
            return result
        except Exception as e:
            logger.warning(f"[market] yfinance error: {e}")
            return [{"symbol": s, "error": str(e)} for s in symbols]

    key = "stocks:" + ",".join(sorted(symbols))
    return _cached(key, _fetch)


def get_crypto(coins: List[str]) -> List[Dict]:
    """Fetch crypto prices from CoinGecko (free, no API key)."""
    def _fetch():
        try:
            ids = ",".join(coins)
            url = "https://api.coingecko.com/api/v3/simple/price"
            resp = requests.get(url, params={
                "ids": ids,
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_market_cap": "true",
                "include_24hr_vol": "true",
            }, timeout=10)
            data = resp.json()
            result = []
            for coin in coins:
                d = data.get(coin, {})
                result.append({
                    "coin": coin,
                    "price_usd": d.get("usd"),
                    "change_24h": d.get("usd_24h_change"),
                    "market_cap": d.get("usd_market_cap"),
                    "volume_24h": d.get("usd_24h_vol"),
                })
            return result
        except Exception as e:
            logger.warning(f"[market] CoinGecko error: {e}")
            return [{"coin": c, "error": str(e)} for c in coins]

    key = "crypto:" + ",".join(sorted(coins))
    return _cached(key, _fetch)


def get_market_summary() -> Dict:
    """Snapshot of major indices + top crypto."""
    def _fetch():
        stocks = get_stocks(["SPY", "QQQ", "AAPL", "TSLA", "NVDA"])
        crypto = get_crypto(["bitcoin", "ethereum", "solana"])
        return {"stocks": stocks, "crypto": crypto, "fetched_at": time.time()}

    return _cached("market_summary", _fetch)


def get_trending_coins(limit: int = 10) -> List[Dict]:
    """Get trending coins from CoinGecko."""
    def _fetch():
        try:
            resp = requests.get("https://api.coingecko.com/api/v3/search/trending", timeout=10)
            data = resp.json()
            coins = data.get("coins", [])[:limit]
            return [
                {
                    "name": c["item"]["name"],
                    "symbol": c["item"]["symbol"],
                    "rank": c["item"].get("market_cap_rank"),
                    "price_btc": c["item"].get("price_btc"),
                }
                for c in coins
            ]
        except Exception as e:
            return [{"error": str(e)}]
    return _cached("trending", _fetch)
