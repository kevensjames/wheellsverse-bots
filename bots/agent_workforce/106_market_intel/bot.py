#!/usr/bin/env python3
"""
Bot #106 — Market Intelligence Agent
Category: agent_workforce
Purpose: Autonomous market research and competitive intelligence. Monitors competitor
         moves, viral trends, product gaps, audience sentiment, and emerging niches.
         Feeds intelligence to CEO Agent and Content Factory. Runs every 6 hours.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are a world-class market intelligence analyst with deep expertise in
digital business, AI tools, creator economy, and online marketing. You analyze
competitive landscapes, spot emerging trends before they peak, identify audience
pain points, and translate market signals into actionable business opportunities.
You think like a McKinsey consultant meets a Silicon Valley growth hacker.
Your intelligence reports are specific, data-driven, and immediately actionable.
You never waste words — every insight must have a clear business implication."""


class MarketIntelBot(BaseBot):

    def __init__(self):
        super().__init__("106_market_intel", "agent_workforce")

    def run(self, action: str = "trends", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "trends")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "trends": self._trend_report,
            "competitor": self._competitor_analysis,
            "sentiment": self._audience_sentiment,
            "gaps": self._product_gaps,
            "viral": self._viral_monitor,
            "weekly": self._weekly_intel,
        }
        fn = actions.get(action, self._trend_report)
        return fn(ts, **kwargs)

    def _fetch_live_data(self, query: str, num: int = 5) -> list:
        try:
            from bots.narai.narai.bot import NarAIInternet
            return NarAIInternet().search(query, num=num)
        except Exception:
            return []

    def _fetch_news(self, query: str, num: int = 5) -> list:
        try:
            from bots.narai.narai.bot import NarAIInternet
            return NarAIInternet().news(query, num=num)
        except Exception:
            return []

    def _trend_report(self, ts: str, **kwargs) -> dict:
        results = self._fetch_live_data("viral AI tools passive income trends 2026", num=8)
        news = self._fetch_news("AI business opportunity trending 2026", num=5)

        search_ctx = "\n".join(f"- {r.get('title', '')} — {r.get('snippet', '')[:100]}"
                                for r in results) or "No live data"
        news_ctx = "\n".join(f"- {n.get('title', '')}" for n in news) or "No news"

        prompt = f"""Generate a trending market intelligence report for WheellsVerse.

Live search signals:
{search_ctx}

Latest news:
{news_ctx}

Intelligence Report — include:
1. TOP 5 TRENDING OPPORTUNITIES this week (rank by speed + profit potential)
2. EMERGING PLATFORMS — any new place where audiences are gathering
3. CONTENT FORMAT TRENDS — what's performing best right now (Reels, Shorts, Threads)
4. KEYWORD GOLD — 10 high-opportunity search terms with low competition
5. TIMING ALERTS — trends at peak vs trends just starting (which to act on NOW)
6. RECOMMENDED ACTION — one specific move WheellsVerse should make THIS WEEK

Output: intelligence-grade brevity. Facts, not filler."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(f"# Market Trend Report — {datetime.now().strftime('%Y-%m-%d')}\n\n{result}",
                                f"trends_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            lines = result.split("\n")[:6]
            notify("🔭 Market Intel — Trend Report\n" + "\n".join(lines))
        except Exception:
            pass

        return {"file": str(path), "action": "trends"}

    def _competitor_analysis(self, ts: str, **kwargs) -> dict:
        competitor = kwargs.get("competitor", "Make Money Online influencers on Instagram")
        results = self._fetch_live_data(f"{competitor} strategy content 2026", num=6)
        ctx = "\n".join(f"- {r.get('title', '')}" for r in results) or "No data"

        prompt = f"""Conduct competitive intelligence analysis on: {competitor}

Market signals:
{ctx}

Analysis framework:
1. WHAT THEY'RE DOING WELL — top 3 tactics driving their growth
2. CONTENT GAPS — what they're NOT covering that audiences want
3. AUDIENCE OVERLAP — who follows them that we could capture
4. POSITIONING OPPORTUNITY — how WheellsVerse can differentiate
5. CONTENT TO CREATE — 5 specific post/video ideas to steal their audience
6. CHANNEL VULNERABILITY — where they're weakest

Recommend concrete action for each point. Be aggressive."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(f"# Competitor Analysis: {competitor}\n\n{result}",
                                f"competitor_{ts}.md", ext="md")
        return {"file": str(path), "action": "competitor", "competitor": competitor}

    def _audience_sentiment(self, ts: str, **kwargs) -> dict:
        topic = kwargs.get("topic", "AI replacing jobs passive income crypto")
        results = self._fetch_live_data(f"{topic} reddit forum discussion 2026", num=6)
        ctx = "\n".join(f"- {r.get('title', '')} — {r.get('snippet', '')[:100]}"
                         for r in results) or "No data"

        prompt = f"""Analyze audience sentiment around: {topic}

Community signals:
{ctx}

Sentiment analysis:
1. DOMINANT EMOTIONS — fear, excitement, skepticism, FOMO? (rank by frequency)
2. TOP PAIN POINTS — the 5 biggest problems/frustrations people express
3. TOP DESIRES — what outcomes they desperately want
4. OBJECTIONS TO OVERCOME — the #1 reason people don't buy/act
5. VIRAL HOOKS — the exact phrases/angles resonating most right now
6. CONTENT ANGLES — 5 post ideas that will trigger emotional response

Use this to craft content that speaks directly to what the audience is feeling.
Be specific — include actual phrases people use."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(f"# Audience Sentiment: {topic}\n\n{result}",
                                f"sentiment_{ts}.md", ext="md")
        return {"file": str(path), "action": "sentiment", "topic": topic}

    def _product_gaps(self, ts: str, **kwargs) -> dict:
        niche = kwargs.get("niche", "AI automation tools for content creators")
        results = self._fetch_live_data(f"{niche} product review complaints missing feature", num=6)
        ctx = "\n".join(f"- {r.get('title', '')} — {r.get('snippet', '')[:100]}"
                         for r in results) or "No data"

        prompt = f"""Identify product and service gaps in the market for: {niche}

Market signals:
{ctx}

Gap analysis:
1. UNMET NEEDS — 5 specific problems no existing product fully solves
2. PRICING GAPS — price points the market is missing ($0-$10, $50-$100, $500+)
3. FEATURE GAPS — features people request but can't find
4. AUDIENCE SEGMENTS IGNORED — who's being left out by current solutions
5. QUICK WIN PRODUCTS — 3 digital products WheellsVerse could launch in 30 days
6. VALIDATION SIGNALS — how to test demand before building (Reddit method, etc.)

Each gap = a potential revenue stream. Prioritize by speed + margin."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(f"# Product Gap Analysis: {niche}\n\n{result}",
                                f"gaps_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"🎯 Market Intel — Product Gaps Found\nNiche: {niche}\n📁 {Path(str(path)).name}")
        except Exception:
            pass

        return {"file": str(path), "action": "gaps", "niche": niche}

    def _viral_monitor(self, ts: str, **kwargs) -> dict:
        results = self._fetch_live_data("viral post going crazy AI income crypto 2026", num=8)
        ctx = "\n".join(f"- {r.get('title', '')} — {r.get('snippet', '')[:80]}"
                         for r in results) or "No data"

        prompt = f"""Monitor what's going viral RIGHT NOW that WheellsVerse should newsjack.

Signals:
{ctx}

Viral monitor report:
1. VIRAL STORIES THIS WEEK — 5 stories/topics currently exploding
2. NEWSJACK ANGLES — how to tie each story to our brand (AI, income, crypto)
3. CONTENT TO CREATE NOW — specific post/video idea for each story
4. SPEED RANKING — which to act on in next 24h vs next 7 days
5. HASHTAG OPPORTUNITIES — trending tags to attach our content to
6. RISK ASSESSMENT — any stories to avoid (controversial, divisive, legal risk)

Speed is alpha in content marketing. Give us our edge."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1500)
        path = self.save_output(f"# Viral Monitor — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{result}",
                                f"viral_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            lines = result.split("\n")[:8]
            notify("🔥 Market Intel — Viral Monitor\n" + "\n".join(lines))
        except Exception:
            pass

        return {"file": str(path), "action": "viral"}

    def _weekly_intel(self, ts: str, **kwargs) -> dict:
        """Comprehensive weekly intelligence package."""
        trends = self._fetch_live_data("AI business online income trending week 2026", num=5)
        news = self._fetch_news("AI creator economy crypto passive income 2026", num=8)

        trends_ctx = "\n".join(f"- {r.get('title', '')}" for r in trends)
        news_ctx = "\n".join(f"- {n.get('title', '')} ({n.get('source', '')})" for n in news)

        prompt = f"""Generate the WheellsVerse Weekly Market Intelligence Package.

This week's signals:
TRENDS: {trends_ctx or 'AI automation growing rapidly'}
NEWS: {news_ctx or 'Creator economy expanding, DeFi yields rising'}

Weekly Intel Package:

SECTION 1: MARKET PULSE (3-sentence snapshot)
SECTION 2: TOP 5 OPPORTUNITIES (ranked, with 30-day revenue estimate)
SECTION 3: COMPETITIVE LANDSCAPE (who moved, who fell, who to watch)
SECTION 4: CONTENT CALENDAR INTEL (what topics will dominate next 7 days)
SECTION 5: PRODUCT OPPORTUNITY (one specific product idea with launch plan)
SECTION 6: AUDIENCE MOOD (sentiment shift, what they want more/less of)
SECTION 7: CEO RECOMMENDATION (one strategic priority for the week)

Length: 600-800 words. Dense with insight, zero fluff."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(
            f"# Weekly Market Intelligence — {datetime.now().strftime('%B %d, %Y')}\n\n{result}",
            f"weekly_intel_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            lines = result.split("\n")[:10]
            notify("📊 Market Intel — Weekly Package\n" + "\n".join(lines) + "\n\n📁 Full report saved.")
        except Exception:
            pass

        return {"file": str(path), "action": "weekly"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Market Intelligence Agent")
    parser.add_argument("--action", default="trends",
                        choices=["trends", "competitor", "sentiment", "gaps", "viral", "weekly"])
    parser.add_argument("--competitor", type=str, default=None)
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--niche", type=str, default=None)
    args = parser.parse_args()
    bot = MarketIntelBot()
    result = bot.execute(action=args.action, competitor=args.competitor,
                         topic=args.topic, niche=args.niche)
    print(f"\n✅ Market Intel: {result['file']}")
