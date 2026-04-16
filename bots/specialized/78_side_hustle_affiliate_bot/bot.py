#!/usr/bin/env python3
"""
bots/specialized/78_side_hustle_affiliate_bot/bot.py
Generates side hustle and gig economy content with affiliate product integration.
Revenue goal: Drive affiliate conversions through actionable side hustle guides.
"""
import os
import sys
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

COINBASE_URL = os.getenv("AFFILIATE_COINBASE_URL", "https://coinbase.com/join/IRZL3QBqT2Fa7117979C7RLARc7WFdWBH1")
ROBINHOOD_URL = os.getenv("AFFILIATE_ROBINHOOD_URL", "https://join.robinhood.com/IRhjrdSej2Ms7117979PpUNgqcMUkCW7g1")
AMAZON_TAG = os.getenv("AFFILIATE_AMAZON_TAG", "wheellsverse-20")

SIDE_HUSTLE_TOPICS = [
    "10 side hustles you can start this weekend with $0",
    "How to make $500/month freelancing on the side of your 9-5",
    "The best side hustles for introverts who hate networking",
    "How to start affiliate marketing as a side hustle in 2025",
    "Side hustles that scale into full-time businesses",
    "How to use AI tools to run a side hustle on autopilot",
    "The fastest way to make your first $100 online",
    "Best side hustles for parents with limited time",
    "How to turn your skill into a $1,000/month side hustle",
    "Gig economy vs passive income: which side hustle is right for you?",
    "How I made $2,000 in my first month with a digital side hustle",
    "Side hustles that pay while you sleep: the real options",
]

HUSTLE_CATEGORIES = {
    "freelance": "service-based freelance work",
    "content": "content creation and monetization",
    "investing": "investing and financial side hustles",
    "ecommerce": "ecommerce and product-based hustles",
    "digital": "digital products and online businesses",
    "gig": "gig economy and platform-based work",
}


class SideHustleAffiliateBotBot(BaseBot):
    """Creates actionable side hustle content that builds trust and drives affiliate conversions."""

    def __init__(self):
        super().__init__("78_side_hustle_affiliate_bot", "specialized")

    def run(self, topic: str = None, hustle_type: str = "digital", **kwargs):
        cfg = self.config
        topic = topic or cfg.get("default_topic") or random.choice(SIDE_HUSTLE_TOPICS)
        hustle_type = hustle_type or cfg.get("hustle_type", "digital")
        hustle_label = HUSTLE_CATEGORIES.get(hustle_type, hustle_type)
        self.logger.info(f"Running {self.name}: {topic}")

        system_str = (
            "You are a side hustle coach and personal finance writer who has built multiple "
            "income streams alongside a full-time job. You give real, practical advice — "
            "not motivational fluff. You include specific platforms, realistic income ranges, "
            "exact steps to get started, and honest time investment estimates. "
            "Your readers are time-pressed people who need to know if something is actually "
            "worth pursuing before they invest time into it."
        )

        prompt = f"""Write a comprehensive, actionable guide on: "{topic}"
Category: {hustle_label}

## Affiliate Integration
Naturally include these where relevant to the hustle type:
- **Robinhood** ({ROBINHOOD_URL}): For investment-related side hustles (free stock for new users)
- **Coinbase** ({COINBASE_URL}): For crypto side hustles (earn $10 in BTC when you sign up)
- **Amazon tools/books** (https://www.amazon.com/s?k=side+hustle+tools+2025&tag={AMAZON_TAG}): For equipment, books, or learning resources

## Article Requirements
- **Length:** 900-1100 words
- **Tone:** Straight-talking, motivating, real — like advice from someone who's actually done it

## Required Sections

**1. Headline** (specific, outcome-focused, includes time/money context)

**2. The Reality Check** (set honest expectations upfront — how much time/money to start)

**3. Why This Works in 2025** (what's changed that makes this hustle viable now)

**4. Step-by-Step Launch Plan**:
   - Step 1: What to do in the first hour
   - Step 2: First week milestones
   - Step 3: First month targets
   - Specific platforms/tools to use for each step

**5. Income Potential** (realistic ranges at 1, 3, 6, 12 months)

**6. Tools & Resources** (embed affiliate links here naturally):
   - Free tools to get started
   - Paid tools worth investing in (with links)
   - Books/courses for leveling up

**7. The #1 Mistake** people make with this hustle and how to avoid it

**8. Your Action Step Today** (one specific thing to do in the next 30 minutes)

Be brutally honest. The best guides say 'this will take X months' not 'get rich quick.'"""

        result = self.ai(
            prompt, system=system_str,
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            max_tokens=2500
        )

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_topic = "".join(c if c.isalnum() else "_" for c in topic[:40])

        output = f"""# {topic}
*Hustle Type: {hustle_label} | Generated: {_dt.now().strftime('%Y-%m-%d %H:%M')}*

---

{result}

---
*Generated by WheellsVerse Side Hustle Affiliate Bot — {self.name}*
"""
        path = self.save_output(output, f"hustle_{safe_topic}_{ts}.md", ext="md")
        self.logger.info(f"Saved: {path}")
        return {"file": str(path), "hustle_type": hustle_type, "bot": self.name}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Side Hustle Affiliate Bot")
    parser.add_argument("--topic", type=str, default=None, help="Side hustle topic")
    parser.add_argument("--type", type=str, default="digital",
                        choices=["freelance", "content", "investing", "ecommerce", "digital", "gig"])
    args = parser.parse_args()
    bot = SideHustleAffiliateBotBot()
    result = bot.execute(topic=args.topic, hustle_type=args.type)
    print(f"\n✅ Output: {result['file']}")
