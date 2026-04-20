"""Sentiment engine — free sources: Reddit JSON, RSS news feeds.

No paid APIs. Keyword-based lexicon scoring (VADER-lite).
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, asdict
from typing import Any

import feedparser
import requests


_HEADERS = {"User-Agent": "NarAI/1.0 (wheellsverse.com)"}
_CACHE: dict[str, tuple[float, Any]] = {}
_CACHE_TTL = 300  # 5 min


# ── Minimal finance lexicon ───────────────────────────────────────────────────
# Keyword → weight in [-1, 1]. Not a replacement for VADER but good enough for a
# first-pass directional score; can be swapped for a trained model later.

_LEXICON = {
    # Positive
    "surge": 0.7, "rally": 0.7, "bullish": 0.9, "breakout": 0.6, "soars": 0.8,
    "gains": 0.5, "upgrade": 0.6, "beat": 0.5, "outperform": 0.7, "pump": 0.5,
    "moon": 0.8, "ath": 0.8, "rally": 0.7, "buy": 0.3, "strong": 0.3,
    "partnership": 0.4, "record": 0.4, "profit": 0.4, "growth": 0.4,
    # Negative
    "crash": -0.9, "plunge": -0.8, "bearish": -0.9, "dump": -0.7, "sell-off": -0.7,
    "downgrade": -0.6, "miss": -0.5, "underperform": -0.7, "recession": -0.7,
    "bankruptcy": -0.9, "fraud": -0.9, "hack": -0.7, "lawsuit": -0.5,
    "bear": -0.4, "fall": -0.3, "decline": -0.4, "loss": -0.4, "weak": -0.3,
    "resistance": -0.2, "sell": -0.3, "fear": -0.5, "panic": -0.7,
}

_NEGATORS = {"not", "no", "never", "nor", "without", "barely", "hardly"}
_WORD_RE = re.compile(r"[a-zA-Z']+")


def _score_text(text: str) -> tuple[float, int]:
    """Return (sum_weight, matched_count). Applies simple negation flip."""
    words = [w.lower() for w in _WORD_RE.findall(text)]
    total = 0.0
    hits = 0
    for i, w in enumerate(words):
        if w in _LEXICON:
            weight = _LEXICON[w]
            # Negation: if any of the 3 prior tokens is a negator, flip
            prev = words[max(0, i - 3):i]
            if any(p in _NEGATORS for p in prev):
                weight = -weight
            total += weight
            hits += 1
    return total, hits


# ── Sources ───────────────────────────────────────────────────────────────────

_REDDIT_SUBS = ["wallstreetbets", "stocks", "cryptocurrency", "investing"]

_RSS_FEEDS = [
    "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US",
    "https://www.google.com/alerts/feeds/09999999999999999/{symbol}",  # placeholder — user-specific
]

_COINDESK_RSS = "https://www.coindesk.com/arc/outboundfeeds/rss/"


def _fetch_reddit(query: str, limit: int = 25) -> list[str]:
    """Scrape Reddit search JSON — public endpoint, rate-limited to ~60/min."""
    texts: list[str] = []
    for sub in _REDDIT_SUBS:
        url = f"https://www.reddit.com/r/{sub}/search.json"
        params = {"q": query, "restrict_sr": "on", "sort": "new", "t": "week", "limit": limit}
        try:
            r = requests.get(url, params=params, headers=_HEADERS, timeout=8)
            if r.status_code != 200:
                continue
            for item in r.json().get("data", {}).get("children", []):
                d = item.get("data", {})
                texts.append(f"{d.get('title', '')} {d.get('selftext', '')}")
        except Exception:
            continue
    return texts


def _fetch_news_rss(symbol: str) -> list[str]:
    """Yahoo Finance RSS — keyed by ticker."""
    texts: list[str] = []
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
    try:
        feed = feedparser.parse(url)
        for entry in feed.entries[:25]:
            texts.append(f"{entry.get('title', '')} {entry.get('summary', '')}")
    except Exception:
        pass
    # Crypto: also CoinDesk
    if any(k in symbol.upper() for k in ("BTC", "ETH", "CRYPTO")):
        try:
            feed = feedparser.parse(_COINDESK_RSS)
            for entry in feed.entries[:15]:
                texts.append(f"{entry.get('title', '')} {entry.get('summary', '')}")
        except Exception:
            pass
    return texts


# ── Public API ────────────────────────────────────────────────────────────────

@dataclass
class SentimentResult:
    symbol: str
    score: float          # [-1, 1]
    confidence: float     # based on sample size
    n_posts: int
    n_news: int
    label: str            # "bullish" | "bearish" | "neutral"
    sample: list[str]     # top 3 matching excerpts

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def sentiment_score(symbol: str, query: str | None = None) -> SentimentResult:
    """Aggregate sentiment for a ticker from Reddit + Yahoo news RSS."""
    cache_key = f"sentiment:{symbol}"
    if cache_key in _CACHE:
        ts, val = _CACHE[cache_key]
        if time.time() - ts < _CACHE_TTL:
            return val

    q = query or symbol
    reddit_texts = _fetch_reddit(q)
    news_texts = _fetch_news_rss(symbol)
    all_texts = reddit_texts + news_texts

    total_weight = 0.0
    total_hits = 0
    samples: list[tuple[float, str]] = []
    for t in all_texts:
        w, h = _score_text(t)
        if h > 0:
            total_weight += w
            total_hits += h
            samples.append((w, t[:200]))

    # Normalize: average per match, clamp to [-1,1]
    raw = (total_weight / total_hits) if total_hits else 0.0
    score = max(-1.0, min(1.0, raw))

    # Confidence grows with sample size (asymptote at 1.0)
    n = len(all_texts)
    confidence = round(1 - (1 / (1 + n / 20)), 3)

    label = "bullish" if score > 0.1 else "bearish" if score < -0.1 else "neutral"

    # Top 3 samples by absolute score
    samples.sort(key=lambda x: abs(x[0]), reverse=True)
    top_excerpts = [s[1] for s in samples[:3]]

    result = SentimentResult(
        symbol=symbol,
        score=round(score, 3),
        confidence=confidence,
        n_posts=len(reddit_texts),
        n_news=len(news_texts),
        label=label,
        sample=top_excerpts,
    )
    _CACHE[cache_key] = (time.time(), result)
    return result
