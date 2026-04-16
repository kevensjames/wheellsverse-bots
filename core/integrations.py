#!/usr/bin/env python3
"""
core/integrations.py
─────────────────────────────────────────────────────────────────────────────
Real Data Integration Hub.

Provides live data feeds to bots via a single `IntegrationsHub` singleton:
  • News        — NewsAPI (key optional) + RSS fallback
  • Crypto      — CoinGecko (free, no key required)
  • Stocks      — Yahoo Finance via yfinance (no key required)
  • Trends      — Google Trends via pytrends (no key required)
  • Twitter     — trending topics via Tweepy (TWITTER_BEARER_TOKEN)
  • Reddit      — hot posts summary via PRAW or public JSON (no key required)

All methods return clean Python dicts/lists — never raise, instead return
{error: "..."} so bots can check and degrade gracefully.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("integrations")

# ─── Simple TTL cache ─────────────────────────────────────────────────────────

_cache: Dict[str, Dict] = {}


def _cached(key: str, ttl_seconds: int, fetch_fn):
    """Return cached result or call fetch_fn() if stale/missing."""
    now = time.time()
    if key in _cache:
        entry = _cache[key]
        if now - entry["ts"] < ttl_seconds:
            return entry["data"]
    try:
        data = fetch_fn()
        _cache[key] = {"ts": now, "data": data}
        return data
    except Exception as e:
        logger.warning(f"Integration fetch failed [{key}]: {e}")
        if key in _cache:
            return _cache[key]["data"]  # return stale on error
        return {"error": str(e)}


# ─── News ──────────────────────────────────────────────────────────────────────

def _fetch_news_newsapi(query: str = "AI automation business", page_size: int = 10) -> List[Dict]:
    """Fetch via NewsAPI.org (requires NEWS_API_KEY env var)."""
    key = os.getenv("NEWS_API_KEY", "")
    if not key:
        raise ValueError("NEWS_API_KEY not set")
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": query,
        "pageSize": page_size,
        "sortBy": "publishedAt",
        "language": "en",
        "apiKey": key,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    articles = resp.json().get("articles", [])
    return [
        {
            "title": a.get("title", ""),
            "source": a.get("source", {}).get("name", ""),
            "description": a.get("description", ""),
            "url": a.get("url", ""),
            "published": a.get("publishedAt", ""),
        }
        for a in articles
    ]


def _fetch_news_rss(topic: str = "artificial intelligence") -> List[Dict]:
    """Fallback: parse Google News RSS (no key needed)."""
    safe_topic = topic.replace(" ", "+")
    url = f"https://news.google.com/rss/search?q={safe_topic}&hl=en-US&gl=US&ceid=US:en"
    resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()

    # Minimal XML parse without lxml dependency
    import xml.etree.ElementTree as ET
    root = ET.fromstring(resp.text)
    channel = root.find("channel")
    items = []
    for item in (channel.findall("item") if channel else [])[:15]:
        items.append({
            "title": (item.findtext("title") or "").strip(),
            "source": "Google News",
            "description": (item.findtext("description") or "").strip()[:200],
            "url": item.findtext("link") or "",
            "published": item.findtext("pubDate") or "",
        })
    return items


# ─── Crypto ────────────────────────────────────────────────────────────────────

def _fetch_crypto(coins: List[str] = None) -> List[Dict]:
    """CoinGecko public API — no key required."""
    ids = ",".join(coins or ["bitcoin", "ethereum", "solana", "bnb", "xrp"])
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ids,
        "vs_currencies": "usd",
        "include_24hr_change": "true",
        "include_market_cap": "true",
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return [
        {
            "coin": coin,
            "price_usd": info.get("usd", 0),
            "change_24h": info.get("usd_24h_change", 0),
            "market_cap": info.get("usd_market_cap", 0),
        }
        for coin, info in data.items()
    ]


def _fetch_crypto_trending() -> List[Dict]:
    """CoinGecko trending coins (last 24h searches)."""
    url = "https://api.coingecko.com/api/v3/search/trending"
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    coins = resp.json().get("coins", [])
    return [
        {
            "name": c["item"]["name"],
            "symbol": c["item"]["symbol"],
            "rank": c["item"].get("market_cap_rank", 0),
            "score": c["item"].get("score", 0),
        }
        for c in coins[:10]
    ]


# ─── Stocks ────────────────────────────────────────────────────────────────────

def _fetch_stocks(tickers: List[str] = None) -> List[Dict]:
    """Yahoo Finance quotes via yfinance (no API key needed)."""
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance not installed — run: pip install yfinance")

    symbols = tickers or ["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMZN", "TSLA"]
    results = []
    for sym in symbols:
        try:
            t = yf.Ticker(sym)
            info = t.fast_info
            results.append({
                "ticker": sym,
                "price": round(float(getattr(info, "last_price", 0) or 0), 2),
                "change_pct": round(float(
                    ((getattr(info, "last_price", 0) - getattr(info, "previous_close", 0)) /
                     max(getattr(info, "previous_close", 1), 0.01)) * 100
                ), 2),
                "volume": int(getattr(info, "three_month_average_volume", 0) or 0),
                "market_cap": int(getattr(info, "market_cap", 0) or 0),
            })
        except Exception as e:
            results.append({"ticker": sym, "error": str(e)})
    return results


# ─── Trends ────────────────────────────────────────────────────────────────────

def _fetch_google_trends(keywords: List[str] = None) -> Dict:
    """Google Trends via pytrends (no key needed)."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        raise ImportError("pytrends not installed — run: pip install pytrends")

    kw = keywords or ["AI automation", "side hustle", "passive income", "ChatGPT", "make money online"]
    pt = TrendReq(hl="en-US", tz=360, timeout=(10, 25))
    pt.build_payload(kw[:5], timeframe="now 7-d", geo="US")
    interest = pt.interest_over_time()
    related = {}
    try:
        related_raw = pt.related_queries()
        for k in kw[:5]:
            top_df = related_raw.get(k, {}).get("top")
            if top_df is not None and not top_df.empty:
                related[k] = top_df["query"].tolist()[:5]
    except Exception:
        pass

    trending_now = []
    try:
        trending_now = pt.trending_searches(pn="united_states")["0"].tolist()[:20]
    except Exception:
        pass

    return {
        "keywords": kw,
        "interest_summary": {
            col: int(interest[col].mean()) if not interest.empty and col in interest else 0
            for col in kw[:5]
        },
        "related_queries": related,
        "trending_now": trending_now,
    }


def _fetch_reddit_hot(subreddit: str = "entrepreneur", limit: int = 10) -> List[Dict]:
    """Reddit hot posts via public JSON API (no key needed)."""
    url = f"https://www.reddit.com/r/{subreddit}/hot.json"
    headers = {"User-Agent": "WheellsVerse/2.0 (data aggregator)"}
    resp = requests.get(url, params={"limit": limit}, headers=headers, timeout=10)
    resp.raise_for_status()
    posts = resp.json().get("data", {}).get("children", [])
    return [
        {
            "title": p["data"]["title"],
            "score": p["data"]["score"],
            "comments": p["data"]["num_comments"],
            "url": "https://reddit.com" + p["data"]["permalink"],
            "flair": p["data"].get("link_flair_text", ""),
        }
        for p in posts
    ]


# ─── Market Summary ────────────────────────────────────────────────────────────

def _fetch_fear_greed() -> Dict:
    """Crypto Fear & Greed Index — no key required."""
    url = "https://api.alternative.me/fng/"
    resp = requests.get(url, timeout=8)
    resp.raise_for_status()
    d = resp.json().get("data", [{}])[0]
    return {
        "value": int(d.get("value", 50)),
        "label": d.get("value_classification", "Neutral"),
        "timestamp": d.get("timestamp", ""),
    }


# ─── IntegrationsHub ──────────────────────────────────────────────────────────

class IntegrationsHub:
    """
    Single access point for all live data integrations.
    All methods are safe — they never raise, returning {"error": "..."} on failure.
    Results are cached with per-method TTLs.
    """

    # ── News ──────────────────────────────────────────────────────────────────

    def get_news(self, query: str = "AI automation entrepreneurship", limit: int = 10) -> Dict:
        """Return latest news articles. Falls back from NewsAPI → Google News RSS."""
        def _fetch():
            try:
                articles = _fetch_news_newsapi(query, limit)
            except Exception:
                articles = _fetch_news_rss(query)
            return {"articles": articles, "count": len(articles), "query": query,
                    "fetched_at": datetime.now().isoformat()}

        return _cached(f"news:{query[:30]}", 900, _fetch)  # 15 min TTL

    def get_tech_news(self) -> Dict:
        return self.get_news("artificial intelligence machine learning technology")

    def get_business_news(self) -> Dict:
        return self.get_news("entrepreneurship business startup revenue")

    def get_crypto_news(self) -> Dict:
        return self.get_news("cryptocurrency bitcoin blockchain defi")

    # ── Crypto ────────────────────────────────────────────────────────────────

    def get_crypto_prices(self, coins: List[str] = None) -> Dict:
        def _fetch():
            prices = _fetch_crypto(coins)
            trending = {}
            try:
                trending = {"trending": _fetch_crypto_trending()}
            except Exception:
                pass
            return {
                "prices": prices,
                **trending,
                "fetched_at": datetime.now().isoformat(),
            }
        return _cached("crypto:prices", 120, _fetch)  # 2 min TTL

    def get_fear_greed(self) -> Dict:
        return _cached("crypto:fear_greed", 3600, _fetch_fear_greed)  # 1h TTL

    # ── Stocks ────────────────────────────────────────────────────────────────

    def get_stock_prices(self, tickers: List[str] = None) -> Dict:
        def _fetch():
            data = _fetch_stocks(tickers)
            return {"stocks": data, "fetched_at": datetime.now().isoformat()}
        return _cached(f"stocks:{str(tickers)}", 300, _fetch)  # 5 min TTL

    def get_tech_stocks(self) -> Dict:
        return self.get_stock_prices(["AAPL", "MSFT", "GOOGL", "META", "NVDA", "AMZN"])

    def get_ai_stocks(self) -> Dict:
        return self.get_stock_prices(["NVDA", "MSFT", "GOOGL", "IBM", "PLTR", "C3AI"])

    # ── Trends ────────────────────────────────────────────────────────────────

    def get_google_trends(self, keywords: List[str] = None) -> Dict:
        def _fetch():
            return _fetch_google_trends(keywords)
        return _cached(f"trends:{str(keywords)[:30]}", 3600, _fetch)  # 1h TTL

    def get_reddit_hot(self, subreddit: str = "entrepreneur") -> Dict:
        def _fetch():
            posts = _fetch_reddit_hot(subreddit)
            return {"subreddit": subreddit, "posts": posts,
                    "fetched_at": datetime.now().isoformat()}
        return _cached(f"reddit:{subreddit}", 1800, _fetch)  # 30 min TTL

    def get_entrepreneurship_feed(self) -> Dict:
        """Combined feed: entrepreneur + smallbusiness subreddits."""
        def _fetch():
            posts = []
            for sub in ["entrepreneur", "smallbusiness", "startups", "passive_income"]:
                try:
                    posts += _fetch_reddit_hot(sub, 5)
                except Exception:
                    pass
            posts.sort(key=lambda x: x.get("score", 0), reverse=True)
            return {"posts": posts[:20], "fetched_at": datetime.now().isoformat()}
        return _cached("reddit:combined", 1800, _fetch)

    # ── Market Summary ────────────────────────────────────────────────────────

    def get_market_summary(self) -> Dict:
        """
        Aggregated market snapshot:
          • Top crypto prices
          • Fear & Greed index
          • Top tech stock movers
          • Today's top news
        """
        summary: Dict[str, Any] = {"generated_at": datetime.now().isoformat()}

        # Crypto
        try:
            crypto = self.get_crypto_prices()
            summary["crypto"] = crypto.get("prices", [])[:5]
        except Exception as e:
            summary["crypto"] = {"error": str(e)}

        # Fear & Greed
        try:
            summary["fear_greed"] = self.get_fear_greed()
        except Exception as e:
            summary["fear_greed"] = {"error": str(e)}

        # Stocks
        try:
            stocks = self.get_tech_stocks()
            summary["stocks"] = stocks.get("stocks", [])
        except Exception as e:
            summary["stocks"] = {"error": str(e)}

        # News
        try:
            news = self.get_tech_news()
            summary["top_news"] = news.get("articles", [])[:5]
        except Exception as e:
            summary["top_news"] = {"error": str(e)}

        return summary

    def get_content_intelligence(self) -> Dict:
        """
        Intelligence feed for content/marketing bots:
          • Trending topics
          • Reddit entrepreneur posts
          • Business news headlines
        """
        summary: Dict[str, Any] = {"generated_at": datetime.now().isoformat()}

        try:
            summary["reddit"] = self.get_entrepreneurship_feed().get("posts", [])[:10]
        except Exception as e:
            summary["reddit"] = {"error": str(e)}

        try:
            summary["news"] = self.get_business_news().get("articles", [])[:5]
        except Exception as e:
            summary["news"] = {"error": str(e)}

        try:
            trends = self.get_google_trends()
            summary["trending_now"] = trends.get("trending_now", [])[:10]
            summary["keyword_interest"] = trends.get("interest_summary", {})
        except Exception as e:
            summary["google_trends"] = {"error": str(e)}

        return summary

    # ── Cache management ──────────────────────────────────────────────────────

    def clear_cache(self, key_prefix: str = ""):
        global _cache
        if key_prefix:
            _cache = {k: v for k, v in _cache.items() if not k.startswith(key_prefix)}
        else:
            _cache = {}

    def get_cache_status(self) -> Dict:
        now = time.time()
        return {
            key: {
                "age_seconds": int(now - entry["ts"]),
                "size_bytes": len(str(entry["data"])),
            }
            for key, entry in _cache.items()
        }


# ─── Singleton ────────────────────────────────────────────────────────────────

_hub: Optional[IntegrationsHub] = None


def get_integrations() -> IntegrationsHub:
    global _hub
    if _hub is None:
        _hub = IntegrationsHub()
    return _hub
