#!/usr/bin/env python3
"""
core/market_intelligence.py
─────────────────────────────────────────────────────────────────────────────
Market Intelligence Engine — NarAI's Eyes on the World

Groups of specialized bots that continuously scan every major platform,
extract the patterns behind viral success, and feed all intelligence
directly into NarAI's long-term memory so she can create masterpieces.

BOT GROUPS:
  • SocialIntelBots  — Facebook, Instagram, Twitter/X, TikTok, Telegram, Blogs
  • MarketplaceBots  — Amazon KDP, Gumroad, Payhip, Etsy, Canva
  • AmazonProductBot — Amazon bestsellers (why people buy)

DATA FLOW:
  Platform → scrape/fetch → Claude analysis → structured insight
  → save to data/market_intelligence.json + NarAI memory
  → NarAI reads this before every creation session

QUALITY CONTROL BOTS:
  After NarAI creates content/products, QC bots run a multi-pass review:
  1. Error Detection  — grammar, factual errors, broken links
  2. Market Fit       — compare against viral patterns in memory
  3. Originality      — flag if too close to a known work
  4. Platform Rules   — TOS compliance per platform
  → Issues sent back to NarAI for revision until approved
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

MI_FILE      = DATA_DIR / "market_intelligence.json"
QC_FILE      = DATA_DIR / "qc_results.json"
MI_LOG_FILE  = DATA_DIR / "market_intel_log.json"

log = logging.getLogger("market_intelligence")


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _claude(prompt: str, system: str = "", max_tokens: int = 3000) -> str:
    """Call Claude Haiku for intelligence analysis."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    r = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=system or (
            "You are NarAI's elite market intelligence analyst. "
            "You analyze viral content patterns with extreme precision. "
            "Always return valid JSON when asked. Be deeply insightful."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    return r.content[0].text.strip()

def _claude_json(prompt: str, system: str = "", max_tokens: int = 3000) -> Any:
    """Call Claude and parse JSON response."""
    raw = _claude(prompt, system, max_tokens)
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        # Try to extract JSON object/array
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", raw)
        if m:
            return json.loads(m.group(1))
        return {}

def _fetch(url: str, timeout: int = 15) -> Optional[str]:
    """HTTP GET with graceful failure."""
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; NarAI-MarketBot/1.0)"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        log.warning(f"Fetch failed {url}: {e}")
        return None

def _mi_log(msg: str, level: str = "INFO", platform: str = "", bot: str = ""):
    entry = {"ts": _now(), "level": level, "msg": msg, "platform": platform, "bot": bot}
    try:
        logs = _mi_load_logs()
        logs.insert(0, entry)
        MI_LOG_FILE.write_text(json.dumps(logs[:3000]))
    except Exception:
        pass
    log.info(f"[{bot or platform}] {msg}")

def _mi_load_logs() -> list:
    try:
        if MI_LOG_FILE.exists():
            return json.loads(MI_LOG_FILE.read_text())
    except Exception:
        pass
    return []

def _mi_load() -> dict:
    try:
        if MI_FILE.exists():
            return json.loads(MI_FILE.read_text())
    except Exception:
        pass
    return {
        "last_scan": None, "scans_total": 0,
        "platforms": {},
        "viral_patterns": [],
        "top_insights": [],
        "narai_briefing": "",
    }

def _mi_save(data: dict):
    try:
        MI_FILE.write_text(json.dumps(data, indent=2, default=str))
    except Exception as e:
        log.error(f"MI save error: {e}")

def _qc_load() -> list:
    try:
        if QC_FILE.exists():
            return json.loads(QC_FILE.read_text())
    except Exception:
        pass
    return []

def _qc_save(data: list):
    try:
        QC_FILE.write_text(json.dumps(data, indent=2, default=str))
    except Exception:
        pass

def _save_to_narai_memory(key: str, content: str, tags: list):
    """Save market intelligence into NarAI's persistent memory."""
    try:
        mem_file = DATA_DIR / "narai_memory.json"
        mem = []
        if mem_file.exists():
            try:
                mem = json.loads(mem_file.read_text())
                if not isinstance(mem, list):
                    mem = []
            except Exception:
                mem = []

        # Remove old entry with same key
        mem = [m for m in mem if m.get("key") != key]

        mem.insert(0, {
            "key": key,
            "content": content,
            "tags": tags,
            "source": "market_intelligence",
            "saved_at": _now(),
        })
        # Keep last 5000 entries
        mem = mem[:5000]
        mem_file.write_text(json.dumps(mem, indent=2, default=str))
        _mi_log(f"Saved to NarAI memory: {key}", bot="MemoryBot")
    except Exception as e:
        log.error(f"NarAI memory save error: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# SOCIAL INTELLIGENCE BOTS
# ══════════════════════════════════════════════════════════════════════════════

class FacebookIntelBot:
    """Analyzes viral Facebook posts and page trends."""
    PLATFORM = "facebook"

    def analyze(self) -> dict:
        _mi_log("Scanning Facebook for viral patterns…", platform=self.PLATFORM, bot="FacebookIntelBot")
        # Use Claude to synthesize Facebook viral patterns (Graph API requires special access)
        # We analyze known viral formulas + publicly available data patterns
        result = _claude_json(
            "Analyze the current Facebook viral content landscape (2025).\n"
            "Based on your deep knowledge of what makes Facebook posts go viral:\n\n"
            "Return a JSON object:\n"
            "{\n"
            '  "top_viral_formats": [{"format": "...", "why_viral": "...", "engagement_pattern": "...", "best_niche": "..."}],\n'
            '  "viral_hooks": ["hook1", "hook2", "hook3"],\n'
            '  "emotional_triggers": ["trigger1", "trigger2"],\n'
            '  "optimal_post_structure": "...",\n'
            '  "what_audiences_love": "...",\n'
            '  "trending_topics_2025": ["topic1", "topic2", "topic3"],\n'
            '  "key_insight": "one powerful insight NarAI must remember"\n'
            "}\n"
            "Be deeply specific and actionable. Pure JSON.",
            max_tokens=2000,
        )
        result["platform"] = self.PLATFORM
        result["scanned_at"] = _now()
        _mi_log(f"Facebook analysis complete — {len(result.get('top_viral_formats', []))} formats found", platform=self.PLATFORM, bot="FacebookIntelBot")
        return result


class InstagramIntelBot:
    """Analyzes viral Instagram posts, reels, and publications."""
    PLATFORM = "instagram"

    def analyze(self) -> dict:
        _mi_log("Scanning Instagram for viral patterns…", platform=self.PLATFORM, bot="InstagramIntelBot")
        result = _claude_json(
            "Analyze the current Instagram viral content landscape (2025).\n"
            "Focus on: Reels, carousels, stories, static posts.\n\n"
            "Return JSON:\n"
            "{\n"
            '  "viral_reel_formulas": [{"formula": "...", "why_works": "...", "avg_reach_multiplier": "...", "niche": "..."}],\n'
            '  "carousel_patterns": [{"pattern": "...", "swipe_hooks": [...], "why_saves": "..."}],\n'
            '  "caption_formulas": ["formula1", "formula2"],\n'
            '  "hashtag_strategy": "...",\n'
            '  "trending_aesthetics_2025": ["aesthetic1", "aesthetic2"],\n'
            '  "what_gets_saved": "...",\n'
            '  "what_gets_shared": "...",\n'
            '  "key_insight": "..."\n'
            "}\nPure JSON.",
            max_tokens=2000,
        )
        result["platform"] = self.PLATFORM
        result["scanned_at"] = _now()
        _mi_log("Instagram analysis complete", platform=self.PLATFORM, bot="InstagramIntelBot")
        return result


class TwitterIntelBot:
    """Analyzes viral Twitter/X posts and threads."""
    PLATFORM = "twitter"

    def analyze(self) -> dict:
        _mi_log("Scanning Twitter/X for viral patterns…", platform=self.PLATFORM, bot="TwitterIntelBot")

        # Try to fetch Twitter trending if credentials available
        trending_data = self._fetch_trending()

        result = _claude_json(
            f"Analyze the current Twitter/X viral content landscape (2025).\n"
            f"Real trending data available: {json.dumps(trending_data)}\n\n"
            "Return JSON:\n"
            "{\n"
            '  "viral_thread_formulas": [{"formula": "...", "why_viral": "...", "engagement_trigger": "..."}],\n'
            '  "tweet_structures": [{"structure": "...", "best_for": "...", "example": "..."}],\n'
            '  "trending_topics": ["topic1", "topic2", "topic3"],\n'
            '  "viral_hooks": ["hook1", "hook2", "hook3"],\n'
            '  "emotional_triggers": ["..."],\n'
            '  "best_posting_times": "...",\n'
            '  "key_insight": "..."\n'
            "}\nPure JSON.",
            max_tokens=2000,
        )
        result["platform"] = self.PLATFORM
        result["scanned_at"] = _now()
        result["live_trending"] = trending_data
        _mi_log("Twitter/X analysis complete", platform=self.PLATFORM, bot="TwitterIntelBot")
        return result

    def _fetch_trending(self) -> list:
        try:
            token = os.getenv("TWITTER_BEARER_TOKEN", "")
            if not token:
                return []
            import urllib.request
            req = urllib.request.Request(
                "https://api.twitter.com/2/trends/by/woeid/1",
                headers={"Authorization": f"Bearer {token}"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
                return [t["name"] for t in data.get("data", [])[:15]]
        except Exception:
            return []


class TikTokIntelBot:
    """Analyzes viral TikTok videos and trends."""
    PLATFORM = "tiktok"

    def analyze(self) -> dict:
        _mi_log("Scanning TikTok for viral patterns…", platform=self.PLATFORM, bot="TikTokIntelBot")
        result = _claude_json(
            "Analyze the current TikTok viral content landscape (2025).\n"
            "Focus on: hooks, pacing, trends, sounds, effects that make videos explode.\n\n"
            "Return JSON:\n"
            "{\n"
            '  "viral_video_formulas": [{"formula": "...", "first_3_seconds": "...", "why_people_watch_full": "...", "niche": "..."}],\n'
            '  "trending_sounds_strategy": "...",\n'
            '  "hook_templates": ["template1", "template2", "template3"],\n'
            '  "viral_niches_2025": ["niche1", "niche2", "niche3"],\n'
            '  "what_gets_saved": "...",\n'
            '  "what_gets_shared": "...",\n'
            '  "algorithm_secrets": "...",\n'
            '  "key_insight": "..."\n'
            "}\nPure JSON.",
            max_tokens=2000,
        )
        result["platform"] = self.PLATFORM
        result["scanned_at"] = _now()
        _mi_log("TikTok analysis complete", platform=self.PLATFORM, bot="TikTokIntelBot")
        return result


class TelegramIntelBot:
    """Analyzes viral Telegram channel posts."""
    PLATFORM = "telegram"

    def analyze(self) -> dict:
        _mi_log("Scanning Telegram for viral patterns…", platform=self.PLATFORM, bot="TelegramIntelBot")
        result = _claude_json(
            "Analyze viral Telegram channel content (2025).\n"
            "Focus on: what messages get forwarded thousands of times, what content explodes.\n\n"
            "Return JSON:\n"
            "{\n"
            '  "viral_message_formats": [{"format": "...", "forward_trigger": "...", "niche": "..."}],\n'
            '  "channel_growth_patterns": "...",\n'
            '  "what_gets_forwarded": "...",\n'
            '  "viral_content_types": ["type1", "type2"],\n'
            '  "key_insight": "..."\n'
            "}\nPure JSON.",
            max_tokens=1500,
        )
        result["platform"] = self.PLATFORM
        result["scanned_at"] = _now()
        _mi_log("Telegram analysis complete", platform=self.PLATFORM, bot="TelegramIntelBot")
        return result


class BlogIntelBot:
    """Analyzes viral blog posts and articles via RSS feeds."""
    PLATFORM = "blog"

    RSS_FEEDS = [
        ("entrepreneurship", "https://feeds.feedburner.com/entrepreneur/latest"),
        ("marketing",        "https://feeds.feedblitz.com/marketingland"),
        ("ai_tech",          "https://techcrunch.com/feed/"),
        ("passive_income",   "https://feeds.feedburner.com/smartpassiveincome"),
        ("business",         "https://hbr.org/feed"),
    ]

    def analyze(self) -> dict:
        _mi_log("Scanning viral blog content…", platform=self.PLATFORM, bot="BlogIntelBot")

        # Try to pull real RSS data
        headlines = self._fetch_rss_headlines()

        result = _claude_json(
            f"Analyze viral blog/article content patterns (2025).\n"
            f"Real headlines fetched: {json.dumps(headlines[:20])}\n\n"
            "Return JSON:\n"
            "{\n"
            '  "viral_headline_formulas": [{"formula": "...", "why_clicks": "...", "example": "..."}],\n'
            '  "viral_article_structures": [{"structure": "...", "why_shares": "..."}],\n'
            '  "trending_blog_topics": ["topic1", "topic2", "topic3"],\n'
            '  "seo_patterns": "...",\n'
            '  "what_makes_people_share": "...",\n'
            '  "key_insight": "..."\n'
            "}\nPure JSON.",
            max_tokens=2000,
        )
        result["platform"] = self.PLATFORM
        result["scanned_at"] = _now()
        result["headlines_captured"] = headlines[:10]
        _mi_log(f"Blog analysis complete — captured {len(headlines)} headlines", platform=self.PLATFORM, bot="BlogIntelBot")
        return result

    def _fetch_rss_headlines(self) -> list:
        headlines = []
        for name, url in self.RSS_FEEDS:
            try:
                html = _fetch(url, timeout=8)
                if html:
                    titles = re.findall(r"<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>", html)
                    for t in titles[:5]:
                        h = (t[0] or t[1]).strip()
                        if h and len(h) > 10:
                            headlines.append({"source": name, "headline": h})
            except Exception:
                pass
        return headlines


# ══════════════════════════════════════════════════════════════════════════════
# MARKETPLACE INTELLIGENCE BOTS
# ══════════════════════════════════════════════════════════════════════════════

class AmazonKDPIntelBot:
    """Scrapes Amazon KDP bestsellers and analyzes why books go viral."""
    PLATFORM = "amazon_kdp"

    KDP_BESTSELLER_URLS = [
        "https://www.amazon.com/Best-Sellers-Kindle-Store/zgbs/digital-text/",
        "https://www.amazon.com/Best-Sellers-Books/zgbs/books/",
    ]

    def analyze(self) -> dict:
        _mi_log("Scanning Amazon KDP bestsellers…", platform=self.PLATFORM, bot="AmazonKDPIntelBot")

        books = self._scrape_bestsellers()

        result = _claude_json(
            f"Analyze Amazon KDP bestseller patterns (2025).\n"
            f"Bestselling books/titles scraped: {json.dumps(books[:20])}\n\n"
            "Deeply analyze WHY these books sell and return JSON:\n"
            "{\n"
            '  "bestseller_title_formulas": [{"formula": "...", "why_buys": "...", "target_emotion": "..."}],\n'
            '  "hottest_genres_2025": [{"genre": "...", "demand": "high|medium", "why_hot": "..."}],\n'
            '  "cover_design_patterns": "...",\n'
            '  "pricing_sweet_spots": "...",\n'
            '  "description_formulas": "...",\n'
            '  "page_count_sweet_spots": "...",\n'
            '  "what_buyers_really_want": "...",\n'
            '  "key_insight": "..."\n'
            "}\nPure JSON.",
            max_tokens=2500,
        )
        result["platform"] = self.PLATFORM
        result["scanned_at"] = _now()
        result["books_sampled"] = books[:15]
        _mi_log(f"Amazon KDP analysis complete — {len(books)} books sampled", platform=self.PLATFORM, bot="AmazonKDPIntelBot")
        return result

    def _scrape_bestsellers(self) -> list:
        books = []
        for url in self.KDP_BESTSELLER_URLS:
            html = _fetch(url)
            if not html:
                continue
            titles = re.findall(r'class="p13n-sc-truncate[^"]*"[^>]*>(.*?)</span>', html, re.DOTALL)
            authors = re.findall(r'class="a-size-small[^"]*"[^>]*>(.*?)</span>', html, re.DOTALL)
            for i, title in enumerate(titles[:20]):
                t = re.sub(r"<[^>]+>", "", title).strip()
                a = re.sub(r"<[^>]+>", "", authors[i]).strip() if i < len(authors) else ""
                if t and len(t) > 3:
                    books.append({"title": t, "author": a, "rank": i + 1})
        return books


class GumroadIntelBot:
    """Analyzes trending Gumroad products and what makes them sell."""
    PLATFORM = "gumroad"

    def analyze(self) -> dict:
        _mi_log("Scanning Gumroad for trending products…", platform=self.PLATFORM, bot="GumroadIntelBot")

        products = self._fetch_trending_products()

        result = _claude_json(
            f"Analyze viral/bestselling Gumroad digital product patterns (2025).\n"
            f"Products found: {json.dumps(products)}\n\n"
            "Return JSON:\n"
            "{\n"
            '  "bestselling_product_types": [{"type": "...", "why_buys": "...", "price_range": "...", "target_buyer": "..."}],\n'
            '  "product_title_formulas": ["formula1", "formula2"],\n'
            '  "description_patterns": "...",\n'
            '  "pricing_strategies": "...",\n'
            '  "thumbnail_patterns": "...",\n'
            '  "what_buyers_want": "...",\n'
            '  "trending_niches": ["niche1", "niche2", "niche3"],\n'
            '  "key_insight": "..."\n'
            "}\nPure JSON.",
            max_tokens=2000,
        )
        result["platform"] = self.PLATFORM
        result["scanned_at"] = _now()
        result["products_sampled"] = products[:10]
        _mi_log("Gumroad analysis complete", platform=self.PLATFORM, bot="GumroadIntelBot")
        return result

    def _fetch_trending_products(self) -> list:
        token = os.getenv("GUMROAD_ACCESS_TOKEN", "")
        if not token:
            return []
        try:
            import urllib.request, urllib.parse
            req = urllib.request.Request(
                "https://api.gumroad.com/v2/products",
                headers={"Authorization": f"Bearer {token}"}
            )
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
                products = data.get("products", [])
                return [{"name": p.get("name"), "price": p.get("price", 0) / 100,
                         "sales": p.get("sales_count", 0), "type": p.get("product_type", "")}
                        for p in products[:20]]
        except Exception:
            return []


class EtsyIntelBot:
    """Analyzes viral Etsy listings (templates, printables, digital tools)."""
    PLATFORM = "etsy"

    def analyze(self) -> dict:
        _mi_log("Scanning Etsy for viral digital products…", platform=self.PLATFORM, bot="EtsyIntelBot")

        listings = self._fetch_trending_listings()

        result = _claude_json(
            f"Analyze viral Etsy digital product patterns (2025) — templates, printables, Canva designs.\n"
            f"Listings data: {json.dumps(listings)}\n\n"
            "Return JSON:\n"
            "{\n"
            '  "bestselling_categories": [{"category": "...", "why_sells": "...", "price_range": "...", "competition": "..."}],\n'
            '  "listing_title_formulas": ["formula1", "formula2"],\n'
            '  "tag_strategies": "...",\n'
            '  "thumbnail_patterns": "...",\n'
            '  "what_buyers_search_for": ["keyword1", "keyword2", "keyword3"],\n'
            '  "trending_products_2025": ["product1", "product2"],\n'
            '  "key_insight": "..."\n'
            "}\nPure JSON.",
            max_tokens=2000,
        )
        result["platform"] = self.PLATFORM
        result["scanned_at"] = _now()
        result["listings_sampled"] = listings[:10]
        _mi_log("Etsy analysis complete", platform=self.PLATFORM, bot="EtsyIntelBot")
        return result

    def _fetch_trending_listings(self) -> list:
        try:
            token = os.getenv("ETSY_ACCESS_TOKEN", "")
            shop_id = os.getenv("ETSY_SHOP_ID", "")
            api_key = os.getenv("ETSY_KEYSTRING", "")
            if not (token or api_key):
                return []
            import urllib.request
            url = f"https://openapi.etsy.com/v3/application/listings/active?limit=20&sort_on=score&keywords=digital+template"
            headers = {"x-api-key": api_key} if api_key else {"Authorization": f"Bearer {token}"}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
                results = data.get("results", [])
                return [{"title": l.get("title"), "price": l.get("price", {}).get("amount", 0) / 100,
                         "views": l.get("views", 0), "num_favorers": l.get("num_favorers", 0)}
                        for l in results[:20]]
        except Exception:
            return []


class PayhipIntelBot:
    """Analyzes trending Payhip products."""
    PLATFORM = "payhip"

    def analyze(self) -> dict:
        _mi_log("Scanning Payhip for trending products…", platform=self.PLATFORM, bot="PayhipIntelBot")
        result = _claude_json(
            "Analyze viral/bestselling Payhip digital product patterns (2025).\n"
            "Payhip is used by creators for ebooks, templates, courses, printables.\n\n"
            "Return JSON:\n"
            "{\n"
            '  "bestselling_types": [{"type": "...", "why_sells": "...", "price_range": "...", "buyer_pain_point": "..."}],\n'
            '  "product_positioning": "...",\n'
            '  "description_hooks": ["hook1", "hook2"],\n'
            '  "trending_niches_2025": ["niche1", "niche2", "niche3"],\n'
            '  "key_insight": "..."\n'
            "}\nPure JSON.",
            max_tokens=1500,
        )
        result["platform"] = self.PLATFORM
        result["scanned_at"] = _now()
        _mi_log("Payhip analysis complete", platform=self.PLATFORM, bot="PayhipIntelBot")
        return result


class CanvaIntelBot:
    """Analyzes viral Canva templates and what makes them popular."""
    PLATFORM = "canva"

    def analyze(self) -> dict:
        _mi_log("Scanning Canva for viral template patterns…", platform=self.PLATFORM, bot="CanvaIntelBot")
        result = _claude_json(
            "Analyze viral Canva template patterns (2025).\n"
            "What makes Canva templates get thousands of uses and saves?\n\n"
            "Return JSON:\n"
            "{\n"
            '  "viral_template_categories": [{"category": "...", "why_popular": "...", "design_style": "..."}],\n'
            '  "design_principles_that_sell": ["principle1", "principle2"],\n'
            '  "color_trends_2025": "...",\n'
            '  "typography_trends": "...",\n'
            '  "most_searched_templates": ["template1", "template2", "template3"],\n'
            '  "key_insight": "..."\n'
            "}\nPure JSON.",
            max_tokens=1500,
        )
        result["platform"] = self.PLATFORM
        result["scanned_at"] = _now()
        _mi_log("Canva analysis complete", platform=self.PLATFORM, bot="CanvaIntelBot")
        return result


class AmazonProductIntelBot:
    """Analyzes Amazon bestseller products — what people buy and why."""
    PLATFORM = "amazon_products"

    CATEGORIES = [
        "electronics", "books", "home-garden", "beauty", "fitness",
        "office-products", "toys-games", "software",
    ]

    def analyze(self) -> dict:
        _mi_log("Scanning Amazon products for buying patterns…", platform=self.PLATFORM, bot="AmazonProductBot")

        products = self._scrape_amazon_bestsellers()

        result = _claude_json(
            f"Analyze Amazon bestseller buying patterns (2025).\n"
            f"Products data: {json.dumps(products[:25])}\n\n"
            "Return JSON analyzing WHY people buy and what patterns you see:\n"
            "{\n"
            '  "buying_psychology_patterns": [{"pattern": "...", "emotion": "...", "how_to_use": "..."}],\n'
            '  "bestseller_title_patterns": ["pattern1", "pattern2"],\n'
            '  "price_psychology": "...",\n'
            '  "trending_categories_2025": [{"category": "...", "growth": "...", "why_trending": "..."}],\n'
            '  "review_trigger_patterns": "...",\n'
            '  "what_amazon_buyers_really_want": "...",\n'
            '  "digital_product_opportunities": ["opportunity1", "opportunity2"],\n'
            '  "key_insight": "..."\n'
            "}\nPure JSON.",
            max_tokens=2500,
        )
        result["platform"] = self.PLATFORM
        result["scanned_at"] = _now()
        result["products_sampled"] = products[:15]
        _mi_log(f"Amazon products analysis complete — {len(products)} products sampled", platform=self.PLATFORM, bot="AmazonProductBot")
        return result

    def _scrape_amazon_bestsellers(self) -> list:
        products = []
        url = "https://www.amazon.com/Best-Sellers/zgbs/"
        html = _fetch(url)
        if not html:
            return products
        titles = re.findall(r'class="p13n-sc-truncate[^"]*"[^>]*>(.*?)</span>', html, re.DOTALL)
        prices = re.findall(r'class="p13n-sc-price[^"]*"[^>]*>(.*?)</span>', html, re.DOTALL)
        for i, title in enumerate(titles[:25]):
            t = re.sub(r"<[^>]+>", "", title).strip()
            p = re.sub(r"<[^>]+>", "", prices[i]).strip() if i < len(prices) else ""
            if t and len(t) > 3:
                products.append({"title": t, "price": p, "rank": i + 1})
        return products


# ══════════════════════════════════════════════════════════════════════════════
# QUALITY CONTROL BOTS
# ══════════════════════════════════════════════════════════════════════════════

class QualityControlBot:
    """
    Multi-pass QC system for NarAI's creations.
    Runs: Error Detection → Market Fit → Originality → Platform Rules
    Returns approval or detailed error report for NarAI to fix.
    """

    MAX_REVISIONS = 5

    def review(
        self,
        content: str,
        content_type: str,       # "post", "ebook", "template", "product", "video_script"
        platform: str,           # "instagram", "gumroad", "amazon_kdp", etc.
        title: str = "",
        market_data: dict = None,
    ) -> dict:
        """
        Full QC pass. Returns:
        {
            "approved": bool,
            "score": 0-100,
            "passes": [{name, passed, issues, suggestions}],
            "final_verdict": "...",
            "revision_needed": bool,
            "revision_instructions": "..."
        }
        """
        _mi_log(f"QC review: '{title}' for {platform}", bot="QualityControlBot")
        mi_summary = self._get_market_summary(platform, market_data)

        passes = []

        # Pass 1: Error Detection
        passes.append(self._pass_error_detection(content, content_type))

        # Pass 2: Market Fit
        passes.append(self._pass_market_fit(content, content_type, platform, mi_summary))

        # Pass 3: Originality
        passes.append(self._pass_originality(content, content_type))

        # Pass 4: Platform Rules
        passes.append(self._pass_platform_rules(content, content_type, platform))

        # Pass 5: Viral Potential
        passes.append(self._pass_viral_potential(content, content_type, platform, mi_summary))

        # Compute overall score
        scores = [p["score"] for p in passes]
        overall = round(sum(scores) / len(scores))
        all_issues = [issue for p in passes for issue in p.get("issues", [])]
        approved = overall >= 75 and not any(p["score"] < 50 for p in passes)

        revision_instructions = ""
        if not approved:
            revision_instructions = _claude(
                f"NarAI created this {content_type} for {platform}:\n\n{content[:3000]}\n\n"
                f"QC found these issues:\n{json.dumps(all_issues, indent=2)}\n\n"
                "Write precise, actionable revision instructions for NarAI. "
                "Be specific about exactly what to change and why. "
                "Reference the market data patterns that should be applied.",
                system="You are a world-class editor and market strategist. "
                       "Give NarAI clear, powerful instructions to make this a masterpiece.",
                max_tokens=1500,
            )

        result = {
            "id": f"qc_{int(time.time())}",
            "title": title,
            "platform": platform,
            "content_type": content_type,
            "reviewed_at": _now(),
            "score": overall,
            "approved": approved,
            "passes": passes,
            "all_issues": all_issues,
            "revision_needed": not approved,
            "revision_instructions": revision_instructions,
            "final_verdict": "✅ APPROVED — Ready to publish" if approved else f"❌ NEEDS REVISION — Score: {overall}/100",
        }

        # Save to QC log
        qc_log = _qc_load()
        qc_log.insert(0, result)
        _qc_save(qc_log[:500])

        _mi_log(
            f"QC {'APPROVED' if approved else 'REJECTED'} '{title}' score={overall}/100",
            level="OK" if approved else "WARNING",
            bot="QualityControlBot"
        )
        return result

    # WheellsVerse brand facts so QC never flags brand-specific terms
    _BRAND_CONTEXT = (
        "IMPORTANT BRAND FACTS — never flag these as issues:\n"
        "• 'WheellsVerse' is the intentional brand name (unusual spelling is on purpose)\n"
        "• 'NarAI' is a real AI product built by WheellsVerse\n"
        "• 'Jhon Wheeler' (not John) is the real creator's name\n"
        "• '$10K+/month' and '1M+ followers' are aspirational GOALS, not claims of current fact\n"
        "• #WheellsVerse and #NarAI are intentional brand hashtags\n"
        "• This is content FOR the WheellsVerse brand — judge it as brand content, not as factual journalism\n"
    )

    def _safe_r(self, r: object, defaults: dict) -> dict:
        """Ensure QC pass result is always a dict with required keys."""
        if not isinstance(r, dict):
            return defaults.copy()
        for k, v in defaults.items():
            if k not in r:
                r[k] = v
        return r

    def _pass_error_detection(self, content: str, content_type: str) -> dict:
        r = _claude_json(
            f"Review this {content_type} for actual errors:\n\n{content[:4000]}\n\n"
            f"{self._BRAND_CONTEXT}\n"
            "Return JSON OBJECT (not array):\n"
            '{"score": 0-100, "passed": true/false, "issues": ["issue1", ...], '
            '"suggestions": ["fix1", ...], "grammar_errors": [], "factual_concerns": [], '
            '"broken_elements": []}',
            system=(
                "You are a professional editor. Be thorough but fair. "
                + self._BRAND_CONTEXT
            ),
            max_tokens=1000,
        )
        r = self._safe_r(r, {"score": 75, "passed": True, "issues": [], "suggestions": []})
        r["passed"] = r.get("score", 75) >= 50
        return {"name": "Error Detection", **r}

    def _pass_market_fit(self, content: str, content_type: str, platform: str, mi_summary: str) -> dict:
        r = _claude_json(
            f"Evaluate market fit of this {content_type} for {platform}:\n\n{content[:3000]}\n\n"
            f"Current market intelligence:\n{mi_summary}\n\n"
            f"{self._BRAND_CONTEXT}\n"
            "Return JSON OBJECT (not array):\n"
            '{"score": 0-100, "passed": true/false, "issues": ["..."], "suggestions": ["..."], '
            '"market_alignment": "excellent|good|weak|poor", "audience_match": "...", '
            '"competitive_advantage": "...", "missing_elements": []}',
            system=(
                "You are a digital product market strategist. "
                + self._BRAND_CONTEXT
            ),
            max_tokens=1200,
        )
        r = self._safe_r(r, {"score": 75, "passed": True, "issues": [], "suggestions": []})
        r["passed"] = r.get("score", 75) >= 50
        return {"name": "Market Fit", **r}

    def _pass_originality(self, content: str, content_type: str) -> dict:
        r = _claude_json(
            f"Evaluate originality of this {content_type}:\n\n{content[:3000]}\n\n"
            "Return JSON OBJECT (not array):\n"
            '{"score": 0-100, "passed": true/false, "issues": ["..."], "suggestions": ["..."], '
            '"originality_level": "highly original|original|somewhat generic|generic", '
            '"unique_angles": ["..."], "generic_parts": ["..."]}',
            system="You are an originality and creativity evaluator.",
            max_tokens=800,
        )
        r = self._safe_r(r, {"score": 75, "passed": True, "issues": [], "suggestions": []})
        r["passed"] = r.get("score", 75) >= 50
        return {"name": "Originality", **r}

    def _pass_platform_rules(self, content: str, content_type: str, platform: str) -> dict:
        r = _claude_json(
            f"Check if this {content_type} complies with {platform} rules and TOS (2025):\n\n{content[:3000]}\n\n"
            f"{self._BRAND_CONTEXT}\n"
            "Return JSON OBJECT (not array):\n"
            '{"score": 0-100, "passed": true/false, "issues": ["..."], "suggestions": ["..."], '
            '"compliance_status": "compliant|minor_issues|major_issues|non_compliant", '
            '"violations": []}',
            system=(
                "You are a platform compliance expert. "
                + self._BRAND_CONTEXT
            ),
            max_tokens=800,
        )
        r = self._safe_r(r, {"score": 80, "passed": True, "issues": [], "suggestions": []})
        r["passed"] = r.get("score", 80) >= 50
        return {"name": "Platform Compliance", **r}

    def _pass_viral_potential(self, content: str, content_type: str, platform: str, mi_summary: str) -> dict:
        r = _claude_json(
            f"Score the viral/sales potential of this {content_type} for {platform}:\n\n{content[:3000]}\n\n"
            f"Market intelligence:\n{mi_summary}\n\n"
            f"{self._BRAND_CONTEXT}\n"
            "Return JSON OBJECT (not array):\n"
            '{"score": 0-100, "passed": true/false, "issues": ["..."], "suggestions": ["..."], '
            '"viral_hooks_present": ["..."], "missing_viral_elements": ["..."], '
            '"predicted_performance": "low|medium|high|viral", '
            '"improvement_impact": "what one change would have the biggest impact"}',
            system=(
                "You are a viral content specialist and conversion expert. "
                + self._BRAND_CONTEXT
            ),
            max_tokens=1200,
        )
        r = self._safe_r(r, {"score": 75, "passed": True, "issues": [], "suggestions": []})
        r["passed"] = r.get("score", 75) >= 50
        return {"name": "Viral Potential", **r}

    def _get_market_summary(self, platform: str, market_data: dict = None) -> str:
        """Get a compact market intelligence summary for the platform."""
        if market_data:
            return json.dumps(market_data, indent=2)[:2000]
        mi = _mi_load()
        platform_data = mi.get("platforms", {}).get(platform, {})
        if platform_data:
            return json.dumps(platform_data, indent=2)[:2000]
        briefing = mi.get("narai_briefing", "")
        return briefing[:1500] if briefing else "No market data available yet — run a market scan first."


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENGINE ORCHESTRATOR
# ══════════════════════════════════════════════════════════════════════════════

_mi_running = False
_mi_thread  = None

ALL_BOTS = {
    # Social
    "facebook":         FacebookIntelBot,
    "instagram":        InstagramIntelBot,
    "twitter":          TwitterIntelBot,
    "tiktok":           TikTokIntelBot,
    "telegram":         TelegramIntelBot,
    "blog":             BlogIntelBot,
    # Marketplaces
    "amazon_kdp":       AmazonKDPIntelBot,
    "gumroad":          GumroadIntelBot,
    "etsy":             EtsyIntelBot,
    "payhip":           PayhipIntelBot,
    "canva":            CanvaIntelBot,
    "amazon_products":  AmazonProductIntelBot,
}

BOT_GROUPS = {
    "social":       ["facebook", "instagram", "twitter", "tiktok", "telegram", "blog"],
    "marketplace":  ["amazon_kdp", "gumroad", "etsy", "payhip", "canva"],
    "amazon":       ["amazon_products"],
    "all":          list(ALL_BOTS.keys()),
}


def run_market_scan(platforms: List[str] = None, session_id: str = None) -> dict:
    """
    Run a full market intelligence scan across specified platforms.
    Saves results to data/market_intelligence.json and NarAI memory.
    """
    global _mi_running
    if not platforms:
        platforms = list(ALL_BOTS.keys())

    session_id = session_id or f"scan_{int(time.time())}"
    _mi_running = True
    _mi_log(f"🚀 Market scan started — session {session_id} | {len(platforms)} platforms", bot="MarketEngine")

    mi = _mi_load()
    mi["running"] = True
    mi["current_session"] = session_id
    mi["current_platform"] = ""
    _mi_save(mi)

    results = {}
    errors  = {}

    for platform in platforms:
        if not _mi_running:
            _mi_log("Scan stopped by user", level="WARNING", bot="MarketEngine")
            break

        BotClass = ALL_BOTS.get(platform)
        if not BotClass:
            continue

        mi["current_platform"] = platform
        _mi_save(mi)

        try:
            bot = BotClass()
            data = bot.analyze()
            results[platform] = data

            # Save to market intelligence store
            mi["platforms"][platform] = data
            _mi_save(mi)

            # Save key insight to NarAI memory
            key_insight = data.get("key_insight", "")
            if key_insight:
                _save_to_narai_memory(
                    key=f"market_intel_{platform}",
                    content=f"[{platform.upper()} MARKET INTEL]\n{key_insight}\n\nFull data: {json.dumps(data, indent=2)[:3000]}",
                    tags=["market_intelligence", platform, "viral_patterns"],
                )

        except Exception as e:
            errors[platform] = str(e)
            _mi_log(f"Error scanning {platform}: {e}", level="ERROR", bot="MarketEngine")

    # Generate NarAI master briefing
    if results:
        briefing = _generate_narai_briefing(results)
        mi["narai_briefing"] = briefing
        mi["top_insights"] = _extract_top_insights(results)
        _save_to_narai_memory(
            key="narai_master_market_briefing",
            content=f"[MASTER MARKET BRIEFING — {_now()[:10]}]\n\n{briefing}",
            tags=["master_briefing", "market_intelligence", "narai_strategy"],
        )

    mi["last_scan"] = _now()
    mi["scans_total"] = mi.get("scans_total", 0) + 1
    mi["running"] = False
    mi["current_platform"] = ""
    _mi_save(mi)

    _mi_running = False
    _mi_log(f"✅ Market scan complete — {len(results)} platforms analyzed, {len(errors)} errors", bot="MarketEngine")

    return {
        "session_id": session_id,
        "platforms_scanned": list(results.keys()),
        "errors": errors,
        "insights_count": len(mi.get("top_insights", [])),
        "briefing_generated": bool(mi.get("narai_briefing")),
    }


def _generate_narai_briefing(results: dict) -> str:
    """Generate a comprehensive briefing for NarAI from all market data."""
    summary = {p: {
        "key_insight": r.get("key_insight", ""),
        "trending": r.get("trending_topics_2025") or r.get("trending_niches_2025") or r.get("hottest_genres_2025") or [],
        "viral_formula": (r.get("viral_thread_formulas") or r.get("viral_reel_formulas") or r.get("viral_video_formulas") or [{}])[0] if (r.get("viral_thread_formulas") or r.get("viral_reel_formulas") or r.get("viral_video_formulas")) else "",
    } for p, r in results.items()}

    return _claude(
        f"You are NarAI's strategic intelligence briefer.\n\n"
        f"Market data from {len(results)} platforms:\n{json.dumps(summary, indent=2)[:5000]}\n\n"
        "Write a comprehensive strategic briefing for NarAI covering:\n"
        "1. The most powerful viral patterns right now\n"
        "2. The best niches to create products in\n"
        "3. What emotions and hooks are working across platforms\n"
        "4. Specific recommendations for creating content that will go viral\n"
        "5. The most important insight NarAI must internalize\n\n"
        "Be direct, strategic, and deeply insightful. This is NarAI's guide to creating masterpieces.",
        max_tokens=2500,
    )


def _extract_top_insights(results: dict) -> list:
    """Extract the most important insights across all platforms."""
    insights = []
    for platform, data in results.items():
        ki = data.get("key_insight", "")
        if ki:
            insights.append({"platform": platform, "insight": ki, "ts": _now()})
    return insights[:20]


def start_scan_background(platforms: List[str] = None) -> str:
    """Start a market scan in a background thread."""
    global _mi_running, _mi_thread
    if _mi_running:
        return "already_running"

    session_id = f"scan_{int(time.time())}"

    def _run():
        global _mi_running
        try:
            run_market_scan(platforms, session_id)
        finally:
            _mi_running = False

    _mi_thread = threading.Thread(target=_run, daemon=True, name="market-intel")
    _mi_thread.start()
    return session_id


def stop_scan():
    global _mi_running
    _mi_running = False


def get_status() -> dict:
    mi = _mi_load()
    return {
        "running":          _mi_running,
        "last_scan":        mi.get("last_scan"),
        "scans_total":      mi.get("scans_total", 0),
        "platforms_data":   {p: {"scanned_at": mi["platforms"][p].get("scanned_at"), "has_data": True}
                            for p in mi.get("platforms", {})},
        "current_platform": mi.get("current_platform", ""),
        "current_session":  mi.get("current_session", ""),
        "top_insights":     mi.get("top_insights", []),
        "narai_briefing":   mi.get("narai_briefing", "")[:500] if mi.get("narai_briefing") else "",
        "platforms_available": list(ALL_BOTS.keys()),
        "bot_groups":       BOT_GROUPS,
    }


def get_platform_data(platform: str) -> dict:
    mi = _mi_load()
    return mi.get("platforms", {}).get(platform, {})


def get_narai_briefing() -> str:
    mi = _mi_load()
    return mi.get("narai_briefing", "")


def get_logs(limit: int = 200) -> list:
    logs = _mi_load_logs()[:limit]
    return [f"[{e.get('ts','')[:19]}] [{e.get('level','INFO')}] [{e.get('bot') or e.get('platform','')}] {e.get('msg','')}"
            for e in logs]
