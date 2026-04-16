#!/usr/bin/env python3
"""
Bot #107 — Product Agent
Category: agent_workforce
Purpose: Autonomous digital product creator and seller. Creates ebooks, prompt packs,
         templates, mini-courses, and SaaS concepts. Generates Gumroad listings,
         sales pages, email sequences, and launch campaigns. Runs daily.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are a prolific digital product creator and info-marketing expert.
You've launched 50+ digital products generating $2M+ in revenue. You know exactly
what sells: the right price points, the perfect sales copy, the irresistible offer.
You specialize in AI tools, productivity systems, passive income education, and
crypto guides. You write sales pages that convert at 3%+, email sequences that
warm cold leads into buyers, and product descriptions that make people feel stupid
for NOT buying. Every product you design has a clear transformation promise and
proven delivery mechanism. You think in funnels, LTV, and recurring revenue."""


PRODUCT_IDEAS = [
    ("AI Prompt Bible", "10,000 ChatGPT prompts for entrepreneurs", "$47"),
    ("Passive Income Blueprint", "Step-by-step system to earn $2K/month passively", "$97"),
    ("Crypto Starter Kit", "Everything a beginner needs to invest safely in crypto", "$37"),
    ("AI Automation Toolkit", "10 automation workflows that save 20 hours/week", "$67"),
    ("WheellsVerse Bot Pack", "Access to all WheellsVerse AI bots for 6 months", "$197"),
]


class ProductAgentBot(BaseBot):

    def __init__(self):
        super().__init__("107_product_agent", "agent_workforce")
        import os
        self.gumroad_token = os.getenv("GUMROAD_ACCESS_TOKEN", "")
        self.stripe_url = os.getenv("STRIPE_BOT_PACK_URL", "#")

    def run(self, action: str = "create", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "create")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "create": self._create_product,
            "sales_page": self._sales_page,
            "email_seq": self._email_sequence,
            "launch": self._launch_campaign,
            "upsell": self._upsell_funnel,
            "catalog": self._product_catalog,
        }
        fn = actions.get(action, self._create_product)
        return fn(ts, **kwargs)

    def _get_product(self, **kwargs):
        idx = kwargs.get("product_idx", datetime.now().day % len(PRODUCT_IDEAS))
        custom = kwargs.get("product")
        if custom:
            return custom, kwargs.get("description", ""), kwargs.get("price", "$47")
        return PRODUCT_IDEAS[idx]

    def _create_product(self, ts: str, **kwargs) -> dict:
        name, desc, price = self._get_product(**kwargs)

        prompt = f"""Create a complete digital product package for: {name}

Description: {desc}
Price point: {price}

Deliver:
1. PRODUCT OUTLINE — full table of contents / module list (8-12 sections)
2. SAMPLE CONTENT — write the first 2 sections in full (300 words each)
3. BONUS IDEAS — 3 bonuses to stack value without adding cost
4. TRANSFORMATION PROMISE — the before → after (20 words)
5. TARGET BUYER PROFILE — who they are, their pain, their dream outcome
6. POSITIONING — why this is different from anything else available
7. FORMAT RECOMMENDATION — PDF ebook / video course / template pack / notion doc?

Make this feel like a $200 product even if priced at {price}.
Include actionable, specific content — not generic frameworks."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        path = self.save_output(f"# Product: {name}\n\n{result}", f"product_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"📦 Product Agent — New Product Created\n{name} @ {price}\n📁 {Path(str(path)).name}")
        except Exception:
            pass

        return {"file": str(path), "action": "create", "product": name, "price": price}

    def _sales_page(self, ts: str, **kwargs) -> dict:
        name, desc, price = self._get_product(**kwargs)

        prompt = f"""Write a high-converting sales page for: {name}

Price: {price} | Description: {desc}

Sales page structure (long-form):
[HEADLINE] — Bold, benefit-driven, pattern-interrupt (max 10 words)
[SUBHEADLINE] — Expands on promise, adds specificity
[HERO SECTION] — Who this is for + transformation promise
[PROBLEM AGITATION] — 3 pain points, each 2-3 sentences
[SOLUTION INTRO] — Introduce the product as THE answer
[WHAT YOU GET] — Feature → Benefit list (10 items minimum)
[SOCIAL PROOF] — 3 fake-realistic testimonials with full names and results
[PRICE REVEAL] — Anchor to higher value, justify {price} as a steal
[BONUS STACK] — 3 bonuses with individual values (totaling 3x the price)
[FAQ] — 5 objection-busting Q&As
[GUARANTEE] — 30-day money-back, risk reversal language
[FINAL CTA] — Urgency + scarcity + "Get Instant Access" button

CTA links to: {self.stripe_url}

Conversion copywriting style: Dan Kennedy meets Alex Hormozi."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=4000)
        path = self.save_output(f"# Sales Page: {name}\n\n{result}", f"sales_page_{ts}.md", ext="md")
        return {"file": str(path), "action": "sales_page", "product": name}

    def _email_sequence(self, ts: str, **kwargs) -> dict:
        name, desc, price = self._get_product(**kwargs)

        prompt = f"""Write a 7-email launch sequence to sell: {name} at {price}

Each email:
- Subject line (A + B variant)
- Preview text
- Full email body (200-400 words)
- One clear CTA

Email sequence:
Email 1 (Day 0 — Launch Day): Announce the product, lead with transformation
Email 2 (Day 1): The story — why you built this, the pain you solved
Email 3 (Day 2): Social proof + testimonials + results
Email 4 (Day 3): Content value email — teach something from the product
Email 5 (Day 4): FAQ + objection busting
Email 6 (Day 5): Scarcity — "48 hours left / bonuses expire"
Email 7 (Day 6): Final call — last chance, direct + urgent

Tone: Authentic, conversational, never pushy — but always urgent.
Every email must make them feel like they'll regret NOT buying."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=4000)
        path = self.save_output(f"# Email Sequence: {name}\n\n{result}", f"email_seq_{ts}.md", ext="md")
        return {"file": str(path), "action": "email_seq", "product": name}

    def _launch_campaign(self, ts: str, **kwargs) -> dict:
        name, desc, price = self._get_product(**kwargs)
        today = datetime.now().strftime("%B %d, %Y")

        prompt = f"""Plan a complete product launch campaign for: {name} at {price}

Launch date: {today} + 7 days

30-Day Launch Plan:
WEEK 1 — PRE-LAUNCH (build anticipation):
- Day 1-3: Teaser content strategy (3 posts, hooks, topics)
- Day 4-7: Waitlist campaign + early bird offer

WEEK 2 — LAUNCH WEEK:
- Launch day content (FB, IG posts + email blast)
- Mid-week follow-up
- Weekend urgency push

WEEK 3-4 — EVERGREEN:
- Repurposing strategy
- Affiliate recruitment message template
- Retargeting content ideas

REVENUE PROJECTION:
- Conservative estimate (1% conversion on 500 audience)
- Realistic estimate (2% conversion on 1000 audience)
- Optimistic estimate (5% conversion with paid ads)

TOTAL CAMPAIGN ASSETS NEEDED: (list every piece)"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        path = self.save_output(f"# Launch Campaign: {name}\n\n{result}", f"launch_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"🚀 Product Agent — Launch Campaign Ready\n{name}\n📁 {Path(str(path)).name}")
        except Exception:
            pass

        return {"file": str(path), "action": "launch", "product": name}

    def _upsell_funnel(self, ts: str, **kwargs) -> dict:
        name, desc, price = self._get_product(**kwargs)

        prompt = f"""Design a complete upsell/downsell funnel for: {name}

Main offer: {price}

Funnel structure:
TRIPWIRE (entry): $7-$17 product — easy yes, delivers immediate value
CORE OFFER: {name} at {price} — the main transformation
OTO 1 (immediate upsell): $47-$97 — implementation accelerator
OTO 2 (second upsell): $197-$297 — done-for-you version
DOWNSELL: Reduced version at 50% off if they decline OTO 1
CONTINUITY OFFER: $29/month membership or subscription

For each offer:
- Name + tagline
- What's included
- Why it complements the core offer
- Sales copy (headline + 3 bullets + CTA)

Total funnel value: $500+ LTV per customer.
Map the complete flow with decision points."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        path = self.save_output(f"# Upsell Funnel: {name}\n\n{result}", f"upsell_{ts}.md", ext="md")
        return {"file": str(path), "action": "upsell", "product": name}

    def _product_catalog(self, ts: str, **kwargs) -> dict:
        prompt = """Generate a complete WheellsVerse digital product catalog for 2026.

Create 10 ready-to-launch digital products covering our niches:
AI tools, passive income, crypto, automation, creator economy.

For each product:
1. Product name + tagline
2. Price ($7 / $27 / $47 / $97 / $197 / $497 / $997)
3. Format (ebook / template pack / mini-course / membership / SaaS)
4. What's inside (5 bullet points)
5. Target buyer
6. Revenue potential (monthly, at 2% conversion, 1000 monthly visitors)
7. Time to build with AI (days)

Rank by: (highest revenue × lowest build time)
Total catalog revenue potential: sum it all up.
Recommend top 3 to launch FIRST."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        path = self.save_output(f"# Product Catalog 2026\n\n{result}", f"catalog_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"📚 Product Agent — Full Catalog Generated\n10 products analyzed\n📁 {Path(str(path)).name}")
        except Exception:
            pass

        return {"file": str(path), "action": "catalog"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Product Agent")
    parser.add_argument("--action", default="create",
                        choices=["create", "sales_page", "email_seq", "launch", "upsell", "catalog"])
    parser.add_argument("--product", type=str, default=None)
    parser.add_argument("--price", type=str, default=None)
    args = parser.parse_args()
    bot = ProductAgentBot()
    result = bot.execute(action=args.action, product=args.product, price=args.price)
    print(f"\n✅ Product Agent: {result['file']}")
