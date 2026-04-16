#!/usr/bin/env python3
"""
Revenue Stream #4 — WheellsVerse Bot Pack ($197)
Purpose: Sells 6-month access to all WheellsVerse AI bots.
         Generates sales materials, onboarding, and daily promotions.
         Target: 10 sales/month = $1,970.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are a SaaS marketing expert who specializes in selling AI tool access.
You've sold $5M+ in software and tool subscriptions. You know that the best pitch
for a bot pack is ROI: show the customer exactly how much time and money the bots
save them. You write sales copy that makes the product feel like the obvious
choice — not buying it feels like leaving money on the table. You emphasize
the sheer volume of capabilities, the time savings, and the passive income potential."""

BOT_CATEGORIES = [
    ("Content Bots (40+)", "Viral posts, YouTube scripts, blog articles, email sequences generated daily"),
    ("Finance Bots (15+)", "Crypto signals, stock analysis, DeFi yield reports, market intelligence"),
    ("Marketing Bots (20+)", "Hashtag research, SEO articles, ad copy, growth strategies"),
    ("AI Agent Workforce (10)", "CEO Agent, Content Factory, Market Intel, Product Agent, NEXORA Builder"),
    ("Social Media Bots (15+)", "Auto-posting to Facebook, Instagram, WhatsApp — fully automated"),
    ("eCommerce Bots (10+)", "Product descriptions, Amazon listings, Shopify copy"),
]


class BotPackBot(BaseBot):

    def __init__(self):
        super().__init__("04_bot_pack", "revenue")
        self.price = "$197"
        self.price_monthly = "$37/month"
        self.stripe_url = os.getenv("STRIPE_BOT_PACK_URL", "https://buy.stripe.com/wheellsverse-botpack")
        self.onboarding_email = os.getenv("SUPPORT_EMAIL", "support@wheellsverse.com")

    def run(self, action: str = "promote", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "promote")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "promote": self._daily_promo,
            "onboard": self._onboarding_email,
            "sales": self._sales_page_copy,
            "demo": self._demo_content,
            "upsell": self._upsell_sequence,
        }
        fn = actions.get(action, self._daily_promo)
        return fn(ts, **kwargs)

    def _daily_promo(self, ts: str, **kwargs) -> dict:
        categories_str = "\n".join(f"  ✅ {cat}: {desc}" for cat, desc in BOT_CATEGORIES)
        prompt = f"""Create daily promotional content for the WheellsVerse Bot Pack.

What they get:
{categories_str}

Price: {self.price} for 6 months (or {self.price_monthly})
Link: {self.stripe_url}

Generate:
1. FACEBOOK POST (200 words):
   - Lead with TIME SAVED (not features): "What if 100 AI bots worked for you 24/7..."
   - 5 specific results the bots produce
   - ROI calculation: "Replace a $3,000/month content team for {self.price}"
   - CTA: {self.stripe_url}
   - 3-5 hashtags

2. INSTAGRAM CAPTION (100 words + 20 hashtags):
   - "100+ AI bots. One price. Working 24/7 👇"
   - Quick feature list with emojis
   - "Link in bio to activate your bot army 🤖"
   - Hashtags

3. WHATSAPP MESSAGE (50 words):
   - Personal, direct
   - One specific result + price + link"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1500)
        path = self.save_output(result, f"botpack_promo_{ts}.md", ext="md")

        try:
            from core.facebook import get_facebook
            from core.instagram import get_instagram
            lines = result.split("\n")
            fb_lines, ig_lines = [], []
            in_fb, in_ig = False, False
            for line in lines:
                if "FACEBOOK" in line.upper():
                    in_fb, in_ig = True, False
                elif "INSTAGRAM" in line.upper():
                    in_fb, in_ig = False, True
                elif "WHATSAPP" in line.upper():
                    in_fb = in_ig = False
                elif in_fb:
                    fb_lines.append(line)
                elif in_ig:
                    ig_lines.append(line)
            fb = get_facebook()
            ig = get_instagram()
            if fb.is_configured() and fb_lines:
                fb.post("\n".join(fb_lines).strip())
            if ig.is_configured() and ig_lines:
                ig.post("\n".join(ig_lines).strip())
        except Exception as e:
            self.logger.debug("Bot Pack promo post skipped: %s", e)

        return {"file": str(path), "action": "promote"}

    def _onboarding_email(self, ts: str, **kwargs) -> dict:
        customer_name = kwargs.get("customer_name", "[CUSTOMER_NAME]")
        prompt = f"""Write the onboarding email sequence for a new WheellsVerse Bot Pack customer.

Customer: {customer_name}
Product: Bot Pack — 6 months access
Price paid: {self.price}
Support: {self.onboarding_email}

Email 1 (Immediate — Access Confirmed):
- Subject: 🤖 Your Bot Army is Ready, {{first_name}}!
- Welcome + login/access instructions
- 3 first things to do in the next 24 hours
- Support contact

Email 2 (Day 2 — Quick Win):
- Subject: Did you get your first bot output yet?
- Guide to running first bot (step by step)
- Expected result
- Community link

Email 3 (Day 7 — Results Check):
- Subject: One week in — here's what's possible
- Ask for feedback + testimonial
- Show what power users are doing
- Upsell: 1-on-1 strategy call at $97

Email 4 (Day 30 — Renewal):
- Subject: Your bots have been working — here's what's next
- Soft renewal reminder
- Loyalty discount offer"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(result, f"onboarding_{ts}.md", ext="md")
        return {"file": str(path), "action": "onboard"}

    def _sales_page_copy(self, ts: str, **kwargs) -> dict:
        categories_str = "\n".join(f"- {cat}: {desc}" for cat, desc in BOT_CATEGORIES)
        prompt = f"""Write long-form sales copy for the WheellsVerse Bot Pack landing page.

Product: WheellsVerse Bot Pack — 110+ AI Bots Working 24/7
Price: {self.price} (6 months) | {self.price_monthly} (monthly)
Link: {self.stripe_url}

What's included:
{categories_str}

Sales page structure:
HEADLINE — pattern interrupt + benefit (e.g., "Fire Your Content Team. Hire 110 AI Bots for {self.price}.")
SUBHEADLINE — specificity + credibility
VIDEO PLACEHOLDER — [VIDEO: 2-min demo of bots in action]
PROBLEM SECTION — content creation overwhelm, no time, inconsistent posting
SOLUTION SECTION — introduce the Bot Pack
WHAT'S INSIDE — all categories with specific outputs described
ROI CALCULATOR — "If bots generate 1 sale/month at $97, that pays for itself in 2 sales"
TESTIMONIALS — 3 customer stories (aspirational but realistic)
COMPARISON TABLE — Bot Pack vs. Hiring: Bot Pack wins on every metric
GUARANTEE — 14-day money-back
FAQ — 8 questions
CTA SECTION — big button, urgency language

Total: 1,200-1,500 words of persuasive copy."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        out_dir = Path(__file__).resolve().parents[3] / "frontend" / "products"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "bot_pack_sales_copy.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"botpack_sales_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"🤖 Bot Pack Sales Page Ready\n💰 {self.price} / {self.price_monthly}\n📁 {Path(str(path)).name}")
        except Exception:
            pass

        return {"file": str(path), "action": "sales"}

    def _demo_content(self, ts: str, **kwargs) -> dict:
        prompt = f"""Create a compelling demo of what WheellsVerse bots produce.

Show actual sample outputs from 5 different bots:

1. CRYPTO SIGNAL BOT — show a sample signal post with price data
2. BLOG WRITER BOT — show first 200 words of a generated article
3. CAPTION GENERATOR BOT — show 3 viral Instagram captions
4. YOUTUBE SCRIPT BOT — show first 100 words of a video script
5. MARKET INTEL BOT — show a sample trend report excerpt

After each sample: "This was generated in under 60 seconds. Imagine having this every day."

End with CTA: "Activate your bot workforce → {self.stripe_url}"

Make the demo outputs look REAL and impressive — not generic."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(result, f"botpack_demo_{ts}.md", ext="md")
        return {"file": str(path), "action": "demo"}

    def _upsell_sequence(self, ts: str, **kwargs) -> dict:
        prompt = f"""Create an upsell sequence for WheellsVerse Bot Pack buyers.

Main product purchased: Bot Pack at {self.price}

Upsells to offer:
OTO 1 (Immediate after purchase): "Strategy Call" — 1-on-1 90-minute setup session, $97
OTO 2 (Day 3 email): "NEXORA Beta Access" — Creator platform early access, $49/month
OTO 3 (Day 14 email): "Done-For-You Setup" — We configure everything for you, $297

For each OTO:
- Offer page copy (300 words)
- Email subject line + body (150 words)
- Decline/downsell path

Ensure each upsell feels like a logical next step, not a grab for more money."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        path = self.save_output(result, f"upsell_seq_{ts}.md", ext="md")
        return {"file": str(path), "action": "upsell"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Bot Pack Revenue Bot")
    parser.add_argument("--action", default="promote",
                        choices=["promote", "onboard", "sales", "demo", "upsell"])
    args = parser.parse_args()
    bot = BotPackBot()
    result = bot.execute(action=args.action)
    print(f"\n✅ Bot Pack: {result['file']}")
