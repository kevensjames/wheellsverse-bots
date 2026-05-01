"""
core/trending.py — Real-Time Trending Intelligence

NarAI monitors what's trending right now and jumps on opportunities
before they peak. Sources:
  - Twitter/X trending topics via API
  - News headlines via RSS feeds (no key required)
  - Reddit hot posts from finance/crypto subreddits
  - CoinGecko for crypto price movements (free API)
  - Google Trends via pytrends (optional)

Output: a ranked list of trending topics with NarAI-specific angles,
ready to inject into the content pipeline.
"""

from __future__ import annotations
import json
import os
import re
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger(__name__)

DATA_FILE = Path("data/trending.json")
BRAND_NICHE = os.getenv("BRAND_NICHE", "AI tools, crypto, and passive income")

# ─── RSS news sources (no API key required) ───────────────────────────────────

NEWS_FEEDS = {
    "crypto": "https://cointelegraph.com/rss",
    "investing": "https://feeds.finance.yahoo.com/rss/2.0/headline",
    "ai": "https://techcrunch.com/feed/",
    "business": "https://feeds.bloomberg.com/markets/news.rss",
}

# ─── Reddit subreddits to monitor ────────────────────────────────────────────

SUBREDDITS = [
    "CryptoCurrency", "Bitcoin", "investing", "personalfinance",
    "passive_income", "Entrepreneur", "artificial",
]

# ─── Trend record ─────────────────────────────────────────────────────────────


class TrendItem:
    def __init__(self, topic: str, source: str, score: float,
                 headline: str = "", url: str = "", niche: str = "general"):
        self.topic = topic
        self.source = source   # twitter / news / reddit / crypto / google
        self.score = score    # relevance/heat score
        self.headline = headline
        self.url = url
        self.niche = niche
        self.angle = ""       # NarAI's content angle (GPT-generated)
        self.captured_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict:
        return {
            "topic": self.topic, "source": self.source, "score": self.score,
            "headline": self.headline, "url": self.url, "niche": self.niche,
            "angle": self.angle, "captured_at": self.captured_at,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "TrendItem":
        t = cls(d["topic"], d["source"], d["score"],
                d.get("headline", ""), d.get("url", ""), d.get("niche", "general"))
        t.angle = d.get("angle", "")
        t.captured_at = d.get("captured_at", "")
        return t


# ─── Trending Engine ──────────────────────────────────────────────────────────

class TrendingEngine:
    _instance: Optional["TrendingEngine"] = None
    _lock = threading.Lock()

    def __init__(self):
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._trends: List[TrendItem] = []
        self._last_refresh: Optional[datetime] = None
        self._thread: Optional[threading.Thread] = None
        self._load()

    @classmethod
    def get(cls) -> "TrendingEngine":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self):
        if DATA_FILE.exists():
            try:
                raw = json.loads(DATA_FILE.read_text())
                self._trends = [TrendItem.from_dict(t) for t in raw.get("trends", [])]
                last = raw.get("last_refresh")
                if last:
                    self._last_refresh = datetime.fromisoformat(last)
            except Exception as e:
                log.error(f"Trending load error: {e}")

    def _save(self):
        DATA_FILE.write_text(json.dumps({
            "trends": [t.to_dict() for t in self._trends],
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else "",
        }, indent=2))

    # ── Fetch methods ──────────────────────────────────────────────────────────

    def _fetch_news(self) -> List[TrendItem]:
        """Pull headlines from RSS feeds — no API key needed."""
        import requests
        from xml.etree import ElementTree as ET
        items = []
        for niche, url in NEWS_FEEDS.items():
            try:
                r = requests.get(url, timeout=8,
                                 headers={"User-Agent": "WheellsVerse/1.0"})
                root = ET.fromstring(r.content)
                for item in root.findall(".//item")[:5]:
                    title = item.findtext("title", "").strip()
                    link = item.findtext("link", "").strip()
                    if title:
                        items.append(TrendItem(
                            topic=title[:80], source="news",
                            score=50.0, headline=title, url=link, niche=niche,
                        ))
            except Exception as e:
                log.warning(f"RSS {niche} failed: {e}")
        return items

    def _fetch_reddit(self) -> List[TrendItem]:
        """Fetch hot posts from relevant subreddits."""
        import requests
        items = []
        for sub in SUBREDDITS[:4]:  # limit API calls
            try:
                r = requests.get(
                    f"https://www.reddit.com/r/{sub}/hot.json?limit=5",
                    headers={"User-Agent": "WheellsVerse/1.0"},
                    timeout=8,
                )
                data = r.json()
                for post in data.get("data", {}).get("children", []):
                    p = post.get("data", {})
                    score = p.get("score", 0)
                    if score < 100:
                        continue
                    niche = _sub_to_niche(sub)
                    items.append(TrendItem(
                        topic=p.get("title", "")[:80],
                        source="reddit",
                        score=min(100, score / 100),
                        headline=p.get("title", ""),
                        url=f"https://reddit.com{p.get('permalink', '')}",
                        niche=niche,
                    ))
            except Exception as e:
                log.warning(f"Reddit {sub} failed: {e}")
            time.sleep(0.5)
        return items

    def _fetch_crypto_movers(self) -> List[TrendItem]:
        """Top crypto movers from CoinGecko free API."""
        import requests
        items = []
        try:
            r = requests.get(
                "https://api.coingecko.com/api/v3/coins/markets",
                params={"vs_currency": "usd", "order": "percent_change_24h_desc",
                        "per_page": 10, "page": 1,
                        "price_change_percentage": "24h"},
                timeout=10,
            )
            coins = r.json()
            for coin in coins[:5]:
                change = coin.get("price_change_percentage_24h", 0) or 0
                if abs(change) < 5:
                    continue
                direction = "surging" if change > 0 else "crashing"
                topic = f"{coin['name']} ({coin['symbol'].upper()}) is {direction} {change:.1f}% today"
                score = min(100, abs(change) * 2)
                items.append(TrendItem(
                    topic=topic, source="crypto",
                    score=score, headline=topic,
                    niche="crypto",
                ))
        except Exception as e:
            log.warning(f"CoinGecko fetch failed: {e}")
        return items

    def _fetch_twitter_trends(self) -> List[TrendItem]:
        """Twitter trending topics (requires API access)."""
        try:
            import tweepy
            bearer = os.getenv("TWITTER_BEARER_TOKEN", "")
            if not bearer:
                return []
            client = tweepy.Client(bearer_token=bearer, wait_on_rate_limit=False)
            # Twitter API v2 doesn't expose trends directly in free tier
            # Use search for niche-specific trending
            items = []
            for query in ["#crypto", "#AI", "#passiveincome"]:
                try:
                    resp = client.search_recent_tweets(
                        query=f"{query} -is:retweet lang:en",
                        max_results=10,
                        tweet_fields=["public_metrics"],
                    )
                    if resp.data:
                        for tweet in resp.data[:3]:
                            m = tweet.public_metrics or {}
                            engagement = (
                                m.get("like_count", 0) * 2
                                + m.get("retweet_count", 0) * 5
                                + m.get("reply_count", 0) * 3
                            )
                            if engagement > 10:
                                items.append(TrendItem(
                                    topic=tweet.text[:80].replace("\n", " "),
                                    source="twitter",
                                    score=min(100, engagement / 10),
                                    headline=tweet.text[:120],
                                    niche=_query_to_niche(query),
                                ))
                    time.sleep(1)
                except Exception:
                    pass
            return items
        except Exception as e:
            log.warning(f"Twitter trends failed: {e}")
            return []

    # ── GPT angle generation ───────────────────────────────────────────────────

    def _generate_angles(self, trends: List[TrendItem]) -> List[TrendItem]:
        """Generate NarAI's content angle for the top trends."""
        top = [t for t in trends if not t.angle][:8]
        if not top:
            return trends

        try:
            from core.llm_client import safe_openai_call
            topics_str = "\n".join(f"{i + 1}. {t.topic}" for i, t in enumerate(top))
            resp = safe_openai_call(
                messages=[{
                    "role": "system",
                    "content": f"You are NarAI, a content creator focused on {BRAND_NICHE}. "
                    f"For each trending topic, write a 1-sentence content angle that connects "
                    f"it to making money, AI tools, or crypto investing. Be specific and punchy.",
                }, {
                    "role": "user",
                    "content": f"Generate content angles for these trends:\n{topics_str}\n\n"
                    f"Return as JSON array of strings, one per trend.",
                }],
                model=os.getenv("OPENAI_MODEL_FAST", "gpt-4o-mini"),
                max_tokens=400, temperature=0.7,
                bot_name="trending.angles",
            )
            raw = resp.choices[0].message.content.strip()
            m = re.search(r"\[[\s\S]+\]", raw)
            angles = json.loads(m.group(0)) if m else []
            for i, t in enumerate(top):
                if i < len(angles):
                    t.angle = angles[i]
        except Exception as e:
            log.warning(f"Angle generation failed: {e}")
        return trends

    # ── Main refresh ───────────────────────────────────────────────────────────

    def refresh(self) -> Dict:
        """Pull all trend sources, deduplicate, score, generate angles."""
        log.info("TrendingEngine: refreshing...")
        all_items: List[TrendItem] = []

        all_items.extend(self._fetch_news())
        all_items.extend(self._fetch_reddit())
        all_items.extend(self._fetch_crypto_movers())
        all_items.extend(self._fetch_twitter_trends())

        # Deduplicate by topic similarity
        seen: set = set()
        deduped: List[TrendItem] = []
        for item in all_items:
            key = item.topic.lower()[:40]
            if key not in seen:
                seen.add(key)
                deduped.append(item)

        # Sort by score
        deduped.sort(key=lambda x: x.score, reverse=True)

        # Generate angles for top items
        deduped = self._generate_angles(deduped)

        with self._lock:
            self._trends = deduped[:50]  # keep top 50
            self._last_refresh = datetime.now(timezone.utc)
            self._save()

        # Feed top topics into FeedbackLoop as "trending" signals
        try:
            from core.feedback_loop import FeedbackLoop
            fl = FeedbackLoop.get()
            for item in deduped[:5]:
                fl.register_post(
                    post_id=f"trend_{item.topic[:20].replace(' ', '_')}",
                    platform=item.source,
                    topic=item.topic,
                    content_type="trending",
                )
        except Exception:
            pass

        log.info(f"TrendingEngine: {len(deduped)} trends found")
        return {
            "status": "refreshed",
            "total": len(deduped),
            "sources": _count_by(deduped, "source"),
            "niches": _count_by(deduped, "niche"),
            "top_5": [t.to_dict() for t in deduped[:5]],
        }

    # ── Query methods ──────────────────────────────────────────────────────────

    def get_top(self, niche: str = "", limit: int = 10) -> List[Dict]:
        trends = self._trends
        if niche:
            trends = [t for t in trends if t.niche == niche or niche == "general"]
        return [t.to_dict() for t in sorted(trends, key=lambda x: x.score, reverse=True)[:limit]]

    def get_best_for_content(self, platform: str = "", niche: str = "") -> Optional[Dict]:
        """Return the single best trending topic to post about right now."""
        candidates = [t for t in self._trends if t.angle]
        if niche:
            niche_first = [t for t in candidates if t.niche == niche]
            candidates = niche_first or candidates
        if not candidates:
            candidates = self._trends
        if not candidates:
            return None
        best = max(candidates, key=lambda x: x.score)
        return best.to_dict()

    def get_viral_opportunities(self) -> List[Dict]:
        """High-score trends that haven't been used for content yet."""
        threshold = 70.0
        return [t.to_dict() for t in self._trends
                if t.score >= threshold]

    # ── Background loop ────────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="trending-engine")
        self._thread.start()
        log.info("TrendingEngine: started — refreshing every 2 hours")

    def _run(self):
        # Initial refresh with delay to avoid startup spike
        time.sleep(30)
        while True:
            try:
                self.refresh()
            except Exception as e:
                log.error(f"TrendingEngine loop error: {e}")
            time.sleep(7200)  # 2 hours

    # ── Summary ───────────────────────────────────────────────────────────────

    def summary(self) -> Dict:
        return {
            "total_trends": len(self._trends),
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else "never",
            "by_source": _count_by(self._trends, "source"),
            "by_niche": _count_by(self._trends, "niche"),
            "viral_opportunities": len(self.get_viral_opportunities()),
            "top_topic": self._trends[0].topic if self._trends else None,
        }


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _sub_to_niche(sub: str) -> str:
    mapping = {
        "CryptoCurrency": "crypto", "Bitcoin": "crypto",
        "investing": "investing", "personalfinance": "investing",
        "passive_income": "passive_income", "Entrepreneur": "general",
        "artificial": "ai_tools",
    }
    return mapping.get(sub, "general")


def _query_to_niche(q: str) -> str:
    if "crypto" in q.lower() or "bitcoin" in q.lower():
        return "crypto"
    if "ai" in q.lower():
        return "ai_tools"
    if "passive" in q.lower():
        return "passive_income"
    return "general"


def _count_by(items: list, field: str) -> Dict[str, int]:
    result: Dict[str, int] = {}
    for item in items:
        v = getattr(item, field, "")
        result[v] = result.get(v, 0) + 1
    return result


# ─── Module-level convenience ─────────────────────────────────────────────────

def get_top(niche: str = "", limit: int = 10) -> List[Dict]:
    return TrendingEngine.get().get_top(niche, limit)


def get_best_topic(platform: str = "", niche: str = "") -> Optional[Dict]:
    return TrendingEngine.get().get_best_for_content(platform, niche)


def refresh() -> Dict:
    return TrendingEngine.get().refresh()
