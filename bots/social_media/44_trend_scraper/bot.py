#!/usr/bin/env python3
"""
Bot #44 — Social Media Trend Research & Content Opportunity Finder
Category: Social Media
Purpose: Research trending topics in a niche, identify content opportunities,
         and provide a 30-day trend-driven content plan.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

TREND_NICHES = [
    "AI tools and automation",
    "entrepreneurship and startups",
    "passive income strategies",
    "crypto and digital assets",
    "personal finance and investing",
    "digital marketing and growth",
    "content creation and creator economy",
    "productivity and remote work",
    "e-commerce and dropshipping",
    "tech and SaaS products",
]

PLATFORM_TREND_SOURCES = {
    "tiktok": "TikTok Creative Center, trending sounds, duet/stitch trends",
    "instagram": "Explore page, Reels trending audio, Instagram Topics",
    "twitter": "Twitter Trending, Spaces, trending hashtags",
    "linkedin": "LinkedIn Trending Articles, newsletter growth topics",
    "youtube": "YouTube Trending, Search autocomplete, TubeBuddy",
    "google": "Google Trends, Search Console, Answer The Public",
}


class TrendScraperBot(BaseBot):

    def __init__(self):
        super().__init__("44_trend_scraper", "social_media")

    def run(self, niche: str = None, platforms: str = None,
            timeframe: str = None, num_trends: int = None, **kwargs):

        cfg = self.config
        niche = niche or cfg.get("niche", "AI tools and automation")
        platforms = platforms or cfg.get("platforms", "tiktok,instagram,twitter,linkedin")
        timeframe = timeframe or cfg.get("timeframe", "next 30 days")
        num_trends = num_trends or cfg.get("num_trends", 15)

        platform_list = [p.strip() for p in platforms.split(",")]
        trend_sources = " | ".join([f"{p}: {PLATFORM_TREND_SOURCES.get(p, 'platform analytics')}"
                                     for p in platform_list])

        self.logger.info(f"Researching trends for: {niche} over {timeframe}")

        # Pre-compute platform opportunities to avoid nested triple-quoted f-strings (Python 3.11)
        platform_opportunities = "".join(
            f"### {p.upper()} OPPORTUNITIES\n"
            f"**Top 3 content formats trending on {p} right now:**\n"
            "1. [Format + why it's performing]\n"
            "2. [Format + why it's performing]\n"
            "3. [Format + why it's performing]\n\n"
            f"**{p.upper()}-specific content idea for {niche}:**\n"
            "[One highly specific, immediately usable idea]\n\n"
            f"**Trending audio/hashtags on {p} for this niche:**\n"
            "[3-5 specific examples]\n\n"
            for p in platform_list
        )

        system = (
            "You are a trend research analyst and content strategist who helps creators "
            "identify and capitalize on emerging trends before they peak. You understand "
            "the trend lifecycle: emerging -> rising -> peak -> declining -> dead. "
            "Your goal is to find trends in the EMERGING to RISING phase -- where early "
            "movers get the most algorithmic reward. You connect macro trends to niche-specific "
            "content opportunities and provide specific, actionable content ideas -- not just "
            "trend names. You think like a news editor: what's happening NOW that your audience "
            "needs to know about?"
        )

        prompt = f"""Research trending topics and content opportunities for:

NICHE: {niche}
PLATFORMS: {', '.join(platform_list)}
TIMEFRAME: {timeframe}
NUMBER OF TRENDS: {num_trends}
BRAND: WheellsVerse - AI automation tools for entrepreneurs

Trend sources by platform: {trend_sources}

## TREND LANDSCAPE OVERVIEW

**Current macro environment for {niche}:**
[3-4 sentences on the broader trends shaping this niche right now]

**Algorithm climate:**
[What platforms are currently boosting vs. suppressing in {niche}]

---

## {num_trends} TRENDING TOPICS & CONTENT OPPORTUNITIES

For each trend:

### TREND [N]: [Trend Name]
**Trend Status:** [Emerging / Rising / Peaking - act fast / Declining]
**Platform(s):** [Where this trend is hottest]
**Why it's trending:** [Brief explanation - what's driving this]
**Window of opportunity:** [How long before this trend peaks/dies]

**Content angles for {niche}:**
1. [Specific content idea - title/hook + format]
2. [Specific content idea - title/hook + format]
3. [Specific content idea - title/hook + format]

**Hook template:**
```
[Fill-in-the-blank hook using this trend]
```

**Relevant hashtags:** [5-8 hashtags with engagement level notes]

---

[Repeat for all {num_trends} trends]

## TREND TIERS

### Act This Week (Highest urgency)
[3-4 trends about to peak - content needed NOW]

### Plan for Next 2-4 Weeks
[4-5 rising trends - build content now, publish soon]

### Research Now, Execute in 30+ Days
[3-4 emerging trends - get ahead of the curve]

### Avoid These (Already Dead)
[3-4 trends that have peaked - not worth creating content about]

## PLATFORM-BY-PLATFORM OPPORTUNITY MAP

{platform_opportunities}

## 30-DAY TREND-DRIVEN CONTENT CALENDAR

| Week | Focus Theme | Trending Angle | Platforms | Format |
| Week 1 | | | | |
| Week 2 | | | | |
| Week 3 | | | | |
| Week 4 | | | | |

## TREND MONITORING SYSTEM

**Daily (5 min):** [Where to check + what to look for]
**Weekly (30 min):** [Deeper trend audit process]
**Monthly (1 hour):** [Strategic trend review + content planning]

**Free tools to track these trends:**
| Tool | Platform | What It Shows | How to Use It |
[5 tools with specific setup instructions]

## EVERGREEN VS TREND BALANCE

For sustainable growth in {niche}:
- **Trending content:** [X%] of your output - drives discovery
- **Evergreen content:** [Y%] of your output - builds long-term authority
- **Why this ratio:** [Explanation for this balance in {niche}]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_niche = self.slugify(niche, 20)

        output = f"""# Trend Research Report: {niche}
**Platforms:** {platforms}
**Timeframe:** {timeframe}
**Trends Identified:** {num_trends}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Trend Scraper Bot*
"""
        path = self.save_output(output, f"trends_{safe_niche}_{ts}.md", ext="md")
        self.logger.info(f"Trend report saved -> {path}")
        return {"file": str(path), "niche": niche, "platforms": platform_list}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Social Media Trend Research & Opportunity Finder")
    parser.add_argument("--niche", type=str, default=None)
    parser.add_argument("--platforms", type=str, default="tiktok,instagram,twitter,linkedin")
    parser.add_argument("--timeframe", type=str, default="next 30 days")
    parser.add_argument("--count", type=int, default=15)
    args = parser.parse_args()
    bot = TrendScraperBot()
    result = bot.execute(niche=args.niche, platforms=args.platforms,
                         timeframe=args.timeframe, num_trends=args.count)
    print(f"\n✅ Trend Report: {result['file']}")
