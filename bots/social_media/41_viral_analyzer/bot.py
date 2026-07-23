#!/usr/bin/env python3
"""
Bot #41 — Viral Content Analyzer & Formula Builder
Category: Social Media
Purpose: Analyze what makes content go viral in a specific niche, reverse-engineer
         viral formulas, and provide actionable templates to replicate success.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

VIRAL_NICHES = [
    "AI tools and automation",
    "entrepreneurship and business building",
    "passive income and investing",
    "personal development and productivity",
    "tech tutorials and software reviews",
    "side hustles and freelancing",
    "digital marketing and growth hacking",
    "crypto and Web3",
    "content creation tips",
    "finance and money management",
]

PLATFORM_ALGORITHMS = {
    "tiktok": "watch time, completion rate, shares -- first 3 seconds are everything",
    "instagram": "saves and shares outweigh likes -- content that makes people stop-and-save wins",
    "twitter": "replies and retweets dominate -- controversial takes and utility threads spread fastest",
    "linkedin": "comments in first hour are critical -- professional storytelling with data performs best",
    "youtube": "CTR + watch time -- thumbnails and hooks determine 90% of success",
}


class ViralAnalyzerBot(BaseBot):

    def __init__(self):
        super().__init__("41_viral_analyzer", "social_media")

    def run(self, niche: str = None, platform: str = None,
            content_type: str = None, goal: str = None, **kwargs):

        cfg = self.config
        niche = niche or cfg.get("niche", "AI tools and automation")
        platform = platform or cfg.get("platform", "tiktok,instagram,twitter")
        content_type = content_type or cfg.get("content_type", "short-form video, carousel, text post")
        goal = goal or cfg.get("goal", "grow followers and drive traffic to WheellsVerse")

        platform_list = [p.strip() for p in platform.split(",")]
        alg_notes = " | ".join([f"{p.upper()}: {PLATFORM_ALGORITHMS.get(p, 'engagement-driven')}"
                                 for p in platform_list])

        self.logger.info(f"Analyzing viral formulas for: {niche} on {platform}")

        # Pre-compute platform formulas to avoid nested triple-quoted f-strings (Python 3.11)
        platform_formulas = "".join(
            f"\n### {p.upper()} VIRAL FORMULA\n\n"
            f"**Algorithm priority:** {PLATFORM_ALGORITHMS.get(p, 'engagement-driven')}\n\n"
            "**Hook Formula:**\n"
            f"[Exact template for a viral {p} hook - use brackets for fill-in variables]\n"
            "Examples:\n"
            f'- "[Hook example 1 for {niche}]"\n'
            f'- "[Hook example 2 for {niche}]"\n'
            f'- "[Hook example 3 for {niche}]"\n\n'
            "**Content Structure Template:**\n"
            "```\n"
            "[0-3s] Hook: [Template]\n"
            "[3-15s] Pain amplification: [Template]\n"
            "[15-45s] Value delivery: [Template]\n"
            "[45-60s] Payoff + CTA: [Template]\n"
            "```\n\n"
            "**Viral post format:** [The specific format - length, structure, visual style]\n"
            "**Engagement trigger:** [What you add to get saves/shares/comments]\n"
            "**5 Viral Title/Hook Templates:**\n"
            "1. [Template]\n"
            "2. [Template]\n"
            "3. [Template]\n"
            "4. [Template]\n"
            "5. [Template]\n\n"
            for p in platform_list
        )

        system = (
            "You are a viral content strategist and data analyst who has studied thousands of "
            "viral posts across every major platform. You reverse-engineer why content spreads -- "
            "not 'be authentic' platitudes, but specific, replicable formulas. You identify the "
            "psychological triggers (curiosity gap, social proof, identity signal, controversy, "
            "utility) that cause people to share. Your analysis is specific and actionable: "
            "you give creators exact templates they can fill in, not vague advice."
        )

        prompt = f"""Analyze viral content patterns and build replicable formulas for:

NICHE: {niche}
PLATFORMS: {', '.join(platform_list)}
CONTENT TYPES: {content_type}
GOAL: {goal}
Algorithm context: {alg_notes}

## VIRAL ANATOMY

### Why Content Goes Viral in {niche}
The 3 psychological triggers that make {niche} content shareable:
1. **[Trigger 1]:** [Why this works for this niche + example]
2. **[Trigger 2]:** [Why this works for this niche + example]
3. **[Trigger 3]:** [Why this works for this niche + example]

### The Virality Equation for This Niche
**Virality Score = [Formula]**
[Explain what factors matter most and why]

## PLATFORM-BY-PLATFORM VIRAL FORMULAS

{platform_formulas}

## REVERSE-ENGINEERED VIRAL POSTS

Analyze these viral content archetypes in {niche}:

### Archetype 1: The Contrarian Take
**Formula:** [Exact structure]
**Why it works:** [Psychology]
**Example for {niche}:**
```
[Complete example post using this formula]
```

### Archetype 2: The Insider Secret
**Formula:** [Exact structure]
**Why it works:** [Psychology]
**Example for {niche}:**
```
[Complete example post using this formula]
```

### Archetype 3: The Before/After Story
**Formula:** [Exact structure]
**Why it works:** [Psychology]
**Example for {niche}:**
```
[Complete example post using this formula]
```

### Archetype 4: The Curated List
**Formula:** [Exact structure]
**Why it works:** [Psychology]
**Example for {niche}:**
```
[Complete example post using this formula]
```

## 15 VIRAL CONTENT IDEAS FOR {niche.upper()}

Ready-to-create ideas with viral potential:
| # | Title/Hook | Format | Platform | Viral Trigger | Expected Reach |
[15 rows -- specific, immediately usable]

## TIMING & DISTRIBUTION STRATEGY

**Post timing for maximum velocity:**
[Specific times by platform -- when the algorithm gives new posts the most push]

**Distribution sequence after posting:**
1. [Action 1 -- first 15 minutes]
2. [Action 2 -- first hour]
3. [Action 3 -- hours 2-4]
4. [Action 4 -- day 2-3]

## VIRAL FAILURE AUDIT

Top 5 reasons content in {niche} fails to spread:
1. [Mistake + what to do instead]
2. [Mistake + what to do instead]
3. [Mistake + what to do instead]
4. [Mistake + what to do instead]
5. [Mistake + what to do instead]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_niche = self.slugify(niche, 20)

        output = f"""# Viral Content Formulas: {niche}
**Platforms:** {platform}
**Content Types:** {content_type}
**Goal:** {goal}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Viral Analyzer Bot*
"""
        path = self.save_output(output, f"viral_{safe_niche}_{ts}.md", ext="md")
        self.logger.info(f"Viral analysis saved -> {path}")
        return {"file": str(path), "niche": niche, "platforms": platform_list}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Viral Content Analyzer & Formula Builder")
    parser.add_argument("--niche", type=str, default=None)
    parser.add_argument("--platform", type=str, default="tiktok,instagram,twitter")
    parser.add_argument("--type", type=str, default="short-form video, carousel, text post")
    parser.add_argument("--goal", type=str, default=None)
    args = parser.parse_args()
    bot = ViralAnalyzerBot()
    result = bot.execute(niche=args.niche, platform=args.platform,
                         content_type=args.type, goal=args.goal)
    print(f"\n✅ Viral Analysis: {result['file']}")
