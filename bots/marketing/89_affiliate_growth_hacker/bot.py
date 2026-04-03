#!/usr/bin/env python3
"""
Bot #89 — Affiliate Growth Hacker (Ultra)
Category: Marketing
Purpose: Data-driven affiliate strategy — picks the highest-converting angle,
         generates multi-platform content, embeds all real affiliate links.
Revenue goal: $300/day through high-intent affiliate funnels
"""
import sys
import os
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot

COINBASE_URL   = os.getenv("AFFILIATE_COINBASE_URL",  "https://coinbase.com/join/IRZL3QBqT2Fa7117979C7RLARc7WFdWBH1")
ROBINHOOD_URL  = os.getenv("AFFILIATE_ROBINHOOD_URL", "https://join.robinhood.com/IRhjrdSej2Ms7117979PpUNgqcMUkCW7g1")
AMAZON_TAG     = os.getenv("AFFILIATE_AMAZON_TAG",    "wheellsverse-20")
AMAZON_TAG2    = os.getenv("AFFILIATE_AMAZON_TAG_2",  "naraiinsights-20")
CLICKBANK_URL  = os.getenv("AFFILIATE_CLICKBANK_URL", "https://hop.clickbank.net/?affiliate=Wheelsvers&vendor=jointgen&v=bvsl")
CONVERTKIT_URL = os.getenv("AFFILIATE_CONVERTKIT_URL", "https://convertkit.com/")
JASPER_URL     = os.getenv("AFFILIATE_JASPER_URL",    "https://www.jasper.ai/")
APPSUMO_URL    = os.getenv("AFFILIATE_APPSUMO_URL",   "https://appsumo.com/")
CTA_URL        = os.getenv("CTA_URL", "https://grateful-flexibility-production.up.railway.app/landing")
BRAND          = os.getenv("BRAND_NAME", "WheellsVerse")

HIGH_INTENT_ANGLES = [
    "How to start investing with $100 and actually grow it in 2025",
    "The beginner crypto guide: Coinbase vs Binance — which is safer?",
    "Robinhood vs Webull: which commission-free app wins in 2025?",
    "I tried 7 AI writing tools — here's the only one worth paying for",
    "How affiliate marketers make $500/day without a big audience",
    "The email list growth hack that 10x'd our affiliate income",
    "AppSumo lifetime deals: my top picks for AI entrepreneurs this year",
    "How to turn a $0 blog into a $2,000/month passive income machine",
    "ConvertKit vs Mailchimp: which email tool earns affiliates more?",
    "The crypto affiliate programs paying the highest commissions in 2025",
    "How Jasper AI helped me write 30 blog posts in a single week",
    "The exact affiliate marketing stack I use to earn $1K/week",
    "ClickBank high-ticket products: which niches convert best?",
    "Why micro-niche affiliate sites still beat broad blogs in 2025",
    "The 5-step affiliate funnel that converts cold traffic to buyers",
]

STRATEGIES = ["content", "email_sequence", "social_blitz", "review_deep_dive", "comparison_post"]


class AffiliateGrowthHackerBot(BaseBot):
    """Generates hyper-targeted affiliate content using proven growth-hacking angles."""

    def __init__(self):
        super().__init__("89_affiliate_growth_hacker", "marketing")

    def run(self, topic: str = None, strategy: str = None, **kwargs):
        cfg = self.config
        topic    = topic or cfg.get("default_topic") or random.choice(HIGH_INTENT_ANGLES)
        strategy = strategy or cfg.get("strategy") or random.choice(STRATEGIES)
        self.logger.info(f"Running affiliate growth hack: [{strategy}] → {topic}")

        system_str = f"""You are a world-class affiliate growth hacker and conversion copywriter behind {BRAND}.
You have studied the top 1% of affiliate marketers and know exactly what makes readers click, sign up, and buy.

Your superpower: you create content that feels genuinely helpful — not salesy — yet converts at 3-5x the industry average.

Core beliefs:
- Specificity sells. Vague claims kill trust.
- The best affiliate content solves a burning problem AND recommends a product as the solution
- SEO intent + emotional trigger + social proof = unstoppable conversion machine
- Every piece of content must have one job: get the reader one step closer to clicking your affiliate link

You know these programs inside-out and have genuine enthusiasm for their value."""

        affiliate_block = f"""## Available Affiliate Programs (use the most relevant 2-4)
| Program | Link | Commission |
|---------|------|-----------|
| Coinbase | {COINBASE_URL} | $10 per signup |
| Robinhood | {ROBINHOOD_URL} | Free stock (~$3-225 value) |
| Amazon Books/Tools | tag={AMAZON_TAG} | 1-10% per sale |
| ClickBank (high ticket) | {CLICKBANK_URL} | 50-75% commission |
| ConvertKit (email) | {CONVERTKIT_URL} | 30% recurring |
| Jasper AI | {JASPER_URL} | 25% recurring |
| AppSumo | {APPSUMO_URL} | Up to $200/sale |
| WheellsVerse Blueprint | {CTA_URL} | Lead capture |"""

        strategy_prompts = {
            "content": f"""Write a 1,000-1,200 word blog post on: "{topic}"

{affiliate_block}

Requirements:
- Headline that targets a high-intent search query
- Hook that validates the reader's frustration or desire
- Problem → Agitation → Solution structure
- 3-4 affiliate links embedded at natural decision points
- Proof: stats, examples, or social proof to build credibility
- Strong CTA at the end (with urgency that feels real, not forced)
- Also output: meta description (155 chars) + 3 SEO-friendly H2 variants""",

            "email_sequence": f"""Create a 5-email affiliate nurture sequence around: "{topic}"

{affiliate_block}

Each email:
- Subject line (punchy, curiosity-driven, <50 chars)
- Preview text (35 chars)
- Body (150-250 words, conversational tone)
- One affiliate link per email at the natural climax
- P.S. line (the second-most-read part of any email)

Email flow: Welcome → Pain point → Solution intro → Deep dive → Final push""",

            "social_blitz": f"""Create a 7-day social media blitz for: "{topic}"

{affiliate_block}

For each day:
- Twitter/X thread (5-8 tweets, each building on the last, final tweet has CTA + affiliate link)
- LinkedIn post (professional, data-driven, 200-300 words)
- Instagram caption (visual storytelling, 150 words, 5 hashtags)

Day themes: Problem → Story → Proof → Tool reveal → Objection handling → FAQ → Final push""",

            "review_deep_dive": f"""Write an ultra-honest, comprehensive review article on: "{topic}"

{affiliate_block}

Structure:
- My experience using it (first-person, specific)
- Pros (specific features with real use cases)
- Cons (be honest — it builds more trust than hiding flaws)
- Who it's for / who it's NOT for
- Comparison to 1-2 alternatives
- Pricing breakdown (is it worth it?)
- Final verdict with affiliate CTA
- FAQ section (5 questions people search for)""",

            "comparison_post": f"""Create a definitive comparison article: "{topic}"

{affiliate_block}

Structure:
- Quick verdict table (feature comparison, winner per category)
- Deep dive on Option A (500 words)
- Deep dive on Option B (500 words)
- Head-to-head: 5 specific scenarios (who wins each?)
- Pricing comparison
- Our recommendation for different user types
- Conclusion with 2 affiliate CTAs (one per product)""",
        }

        prompt = strategy_prompts.get(strategy, strategy_prompts["content"])
        result = self.ai(
            prompt, system=system_str,
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_tokens=3000
        )

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(c if c.isalnum() else "_" for c in topic[:50])

        output = f"""# Affiliate Growth Hack: {topic}
*Strategy: {strategy} | Generated: {_dt.now().strftime('%Y-%m-%d %H:%M')}*

---

{result}

---
*Generated by {BRAND} Affiliate Growth Hacker Bot — {self.name}*
"""
        path = self.save_output(output, f"growth_{strategy}_{safe}_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "topic": topic, "strategy": strategy, "bot": self.name}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Affiliate Growth Hacker Bot")
    parser.add_argument("--topic",    type=str, default=None)
    parser.add_argument("--strategy", type=str, default=None,
                        choices=STRATEGIES)
    args = parser.parse_args()
    bot = AffiliateGrowthHackerBot()
    result = bot.execute(topic=args.topic, strategy=args.strategy)
    print(f"\n✅ Output: {result['file']}")
