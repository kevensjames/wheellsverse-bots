#!/usr/bin/env python3
"""
Bot #88 — High Value Affiliate Bot (Ultra)
Category: Specialized
Purpose: Targets the highest-commission affiliate niches (AI tools, crypto, investing)
         with premium content that converts at a high rate.
Revenue goal: $200/day through high-ticket affiliate programs
"""
import sys
import os
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

COINBASE_URL = os.getenv("AFFILIATE_COINBASE_URL", "https://app.wheellsverse.com/go/coinbase")
ROBINHOOD_URL = os.getenv("AFFILIATE_WEBULL_URL", "https://app.wheellsverse.com/go/webull")
AMAZON_TAG = os.getenv("AFFILIATE_AMAZON_TAG", "wheellsverse-20")
AMAZON_TAG2 = os.getenv("AFFILIATE_AMAZON_TAG_2", "naraiinsights-20")
AMAZON_VIDEO = os.getenv("AFFILIATE_AMAZON_VIDEO_URL", "https://www.amazon.com/gp/video/storefront?tag=naraiinsights-20")
CLICKBANK_URL = os.getenv("AFFILIATE_CLICKBANK_URL", "https://hop.clickbank.net/?affiliate=Wheelsvers&vendor=jointgen&v=bvsl")
CONVERTKIT_URL = os.getenv("AFFILIATE_CONVERTKIT_URL", "https://convertkit.com/")
JASPER_URL = os.getenv("AFFILIATE_JASPER_URL", "https://www.jasper.ai/")
APPSUMO_URL = os.getenv("AFFILIATE_APPSUMO_URL", "https://appsumo.com/")
FIVERR_URL = os.getenv("AFFILIATE_FIVERR_URL", "https://www.fiverr.com/")
BLUEHOST_URL = os.getenv("AFFILIATE_BLUEHOST_URL", "https://www.bluehost.com/")
CTA_URL = os.getenv("CTA_URL", "https://grateful-flexibility-production.up.railway.app/landing")
BRAND = os.getenv("BRAND_NAME", "WheellsVerse")
AUTHOR = os.getenv("AUTHOR_NAME", "J.K. Blaze")

HIGH_VALUE_ANGLES = [
    # AI Tools niche — $25-75 recurring commissions
    "The 5 AI tools that pay back their subscription cost in the first week",
    "Jasper AI vs ChatGPT: which one actually makes money for content creators?",
    "How I use AI tools to generate $3,000/month in affiliate revenue",
    "The best AI writing assistant for affiliate marketers in 2025",
    "AppSumo lifetime deals: my top AI tool picks worth every penny",

    # Crypto niche — $10+ per signup
    "Bitcoin in 2025: the beginner's blueprint to not getting wrecked",
    "Coinbase vs Kraken: which exchange should you start with?",
    "How to earn crypto without trading: staking, rewards, and referrals",
    "The 5 safest ways to start investing in crypto with under $500",
    "Why Coinbase is still the best on-ramp for new crypto investors",

    # Investing niche — free stock referrals
    "Robinhood in 2025: still worth it, or time to switch?",
    "Commission-free investing: how to build a portfolio starting from zero",
    "The dividend investing strategy that generates passive income monthly",
    "ETFs vs individual stocks: what actually works for beginners?",
    "How to use Robinhood's fractional shares to invest in big companies for $1",

    # Blended high-ticket
    "The AI + investing stack that's generating passive income for thousands",
    "How to start a profitable newsletter with ConvertKit and earn recurring income",
    "Build a blog, grow an email list, earn affiliate income — the 2025 playbook",
    "Fiverr affiliate program: how to earn $15-150 per sale promoting gigs",
    "Bluehost affiliate marketing: how bloggers earn $65+ per referral",
]

NICHES = ["ai_tools", "crypto", "investing", "email_marketing", "blogging", "mixed_high_value"]


class HighValueAffiliateBotBot(BaseBot):
    """Creates premium affiliate content targeting the highest-commission programs."""

    def __init__(self):
        super().__init__("88_high_value_affiliate_bot", "specialized")

    def run(self, topic: str = None, niche: str = None, **kwargs):
        cfg = self.config
        topic = topic or cfg.get("default_topic") or random.choice(HIGH_VALUE_ANGLES)
        niche = niche or cfg.get("niche") or random.choice(NICHES)
        self.logger.info(f"Running {self.name}: [{niche}] {topic}")

        # Select relevant affiliate programs by niche
        niche_programs = {
            "ai_tools": [
                f"Jasper AI — 25% recurring commission: {JASPER_URL}",
                f"AppSumo lifetime deals — up to $200/sale: {APPSUMO_URL}",
                f"Amazon AI books & courses (tag={AMAZON_TAG}): https://amazon.com/?tag={AMAZON_TAG}",
                f"WheellsVerse AI Blueprint: {CTA_URL}",
            ],
            "crypto": [
                f"Coinbase — $10 BTC per signup: {COINBASE_URL}",
                f"Amazon crypto books (tag={AMAZON_TAG2}): https://amazon.com/s?k=crypto+investing&tag={AMAZON_TAG2}",
                f"ClickBank high-ticket crypto products: {CLICKBANK_URL}",
            ],
            "investing": [
                f"Webull — free stocks referral ($3-$225 value): {ROBINHOOD_URL}",
                f"Coinbase — get started in crypto: {COINBASE_URL}",
                f"Amazon investing books (tag={AMAZON_TAG}): https://amazon.com/s?k=investing+beginners&tag={AMAZON_TAG}",
            ],
            "email_marketing": [
                f"ConvertKit — 30% recurring monthly commission: {CONVERTKIT_URL}",
                f"Bluehost — $65 per hosting signup: {BLUEHOST_URL}",
                f"Jasper AI for email copywriting — 25% recurring: {JASPER_URL}",
            ],
            "blogging": [
                f"Bluehost — $65 per signup: {BLUEHOST_URL}",
                f"Jasper AI — fastest blog writing tool, 25% recurring: {JASPER_URL}",
                f"ConvertKit — email list building, 30% recurring: {CONVERTKIT_URL}",
                f"Fiverr — hire blog designers/writers, $15-150/sale: {FIVERR_URL}",
            ],
            "mixed_high_value": [
                f"Coinbase — $10 BTC signup bonus: {COINBASE_URL}",
                f"Webull — free stocks on signup: {ROBINHOOD_URL}",
                f"Jasper AI — 25% recurring: {JASPER_URL}",
                f"AppSumo — up to $200/sale: {APPSUMO_URL}",
                f"ConvertKit — 30% recurring: {CONVERTKIT_URL}",
                f"ClickBank high-ticket: {CLICKBANK_URL}",
            ],
        }

        programs = niche_programs.get(niche, niche_programs["mixed_high_value"])
        programs_str = "\n".join(f"- {p}" for p in programs)

        system_str = f"""You are {AUTHOR}, founder of {BRAND} — an AI entrepreneur and affiliate marketing expert.
You've generated over $50,000 in affiliate commissions and know exactly what content drives high-value signups.

Your content is:
- Deeply credible — you cite specific features, real numbers, genuine pros/cons
- Emotionally resonant — readers feel understood, not sold to
- Conversion-optimized — every section guides the reader toward the affiliate action
- SEO-smart — naturally targeting 3-5 high-intent keywords

You never write generic content. Every sentence earns its place."""

        prompt = f"""Write a premium, high-converting affiliate article on: "{topic}"

**Niche focus:** {niche.replace('_', ' ').title()}
**Target reader:** Someone actively searching for ways to invest, earn, or grow their income online

## Affiliate Programs to Feature
{programs_str}

## Content Blueprint

### 1. Power Headline
- Primary: Must target a specific high-intent search query
- Emotional hook: Why this matters to the reader RIGHT NOW

### 2. Introduction (200 words)
- Open with a bold statement or surprising statistic
- Validate the reader's desire/frustration immediately
- Promise exactly what they'll get from this article

### 3. Main Body (700-900 words)
- At least 3 clear sections with H2 headings
- Each section: insight → context → recommendation → affiliate link (when natural)
- Use real-world examples, specific numbers, tangible outcomes
- Build trust by acknowledging what the products DON'T do well

### 4. Comparison Table (if applicable)
- Feature comparison for 2-3 options with our preferred choice highlighted

### 5. Conclusion + CTA (150 words)
- Summarize the key insight in 1-2 sentences
- Soft affiliate CTA: "If you're ready to start, [Product] is where I'd begin"
- Hard CTA: link to free resource at {CTA_URL}

## Additional Deliverables
- **Meta description** (155 chars, includes primary keyword)
- **3 Pinterest pin titles** (curiosity + benefit)
- **Email subject line** to promote this article

Format as clean, beautifully structured Markdown."""

        result = self.ai(
            prompt, system=system_str,
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_tokens=3200
        )

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(c if c.isalnum() else "_" for c in topic[:50])

        output = f"""---
title: "{topic}"
niche: {niche}
author: {AUTHOR}
brand: {BRAND}
generated: {_dt.now().strftime('%Y-%m-%d %H:%M')}
programs: {', '.join(p.split('—')[0].strip() for p in programs)}
---

{result}

---
*Generated by {BRAND} High-Value Affiliate Intelligence Bot — {self.name}*
"""
        path = self.save_output(output, f"hv_affiliate_{niche}_{safe}_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "topic": topic, "niche": niche, "bot": self.name}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="High Value Affiliate Bot")
    parser.add_argument("--topic", type=str, default=None)
    parser.add_argument("--niche", type=str, default=None, choices=NICHES)
    args = parser.parse_args()
    bot = HighValueAffiliateBotBot()
    result = bot.execute(topic=args.topic, niche=args.niche)
    print(f"\n✅ Output: {result['file']}")
