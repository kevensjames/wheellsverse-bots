#!/usr/bin/env python3
"""
Revenue Stream #8 — Digital Store (AI Income Kit Bundle $299)
Purpose: Builds and manages WheellsVerse digital product store.
         Bundles 5+ products into AI Income Kit at $299.
         Also manages individual product listings and Gumroad catalog.
         Target: 5 bundles/month = $1,495.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from core.base_bot import BaseBot  # noqa: E402

SYSTEM = """You are an expert in digital product bundling and Gumroad/Stripe store optimization.
You've helped creators build 6-figure digital product stores. You know that bundles
outsell individual products 3:1 because they feel like an incredible deal. You write
product listings that make buyers feel like they're stealing — getting $1,000+ worth
of value for $299. Your copy emphasizes transformation, not features. You design
upsell paths that maximize revenue per customer."""

BUNDLE_PRODUCTS = [
    ("Prompt Bible", "10,000 ChatGPT prompts for entrepreneurs", "$47"),
    ("AI Income Blueprint Course", "5-module course: Make Your First $500 With AI", "$97"),
    ("Social Media Templates", "365 days of pre-written posts for FB + IG", "$37"),
    ("Crypto Starter Toolkit", "Complete guide to safe crypto investing + DeFi", "$47"),
    ("AI Business Automation Guide", "10 workflows to automate your online business", "$67"),
]

BUNDLE_PRICE = "$299"
INDIVIDUAL_TOTAL = sum(int(p[2].replace("$", "")) for p in BUNDLE_PRODUCTS)


class DigitalStoreBot(BaseBot):

    def __init__(self):
        super().__init__("08_digital_store", "revenue")
        self.bundle_price = BUNDLE_PRICE
        self.store_url = os.getenv("GUMROAD_STORE_URL", "https://gum.co/wheellsverse-store")
        self.bundle_url = os.getenv("GUMROAD_BUNDLE_URL", "https://gum.co/wheellsverse-ai-kit")
        self.stripe_url = os.getenv("STRIPE_BOT_PACK_URL", "#")

    def run(self, action: str = "promote", **kwargs):
        cfg = self.config
        action = action or cfg.get("action", "promote")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        actions = {
            "promote": self._daily_promo,
            "bundle": self._build_bundle_listing,
            "catalog": self._store_catalog,
            "flash": self._flash_sale,
            "upsell": self._store_upsell,
        }
        fn = actions.get(action, self._daily_promo)
        return fn(ts, **kwargs)

    def _daily_promo(self, ts: str, **kwargs) -> dict:
        products_str = "\n".join(f"  ✅ {p[0]}: {p[1]} (value: {p[2]})" for p in BUNDLE_PRODUCTS)
        prompt = f"""Create promotional content for the WheellsVerse AI Income Kit Bundle.

Bundle contains:
{products_str}

Individual value: ${INDIVIDUAL_TOTAL}
Bundle price: {BUNDLE_PRICE} (saves ${INDIVIDUAL_TOTAL - int(BUNDLE_PRICE.replace('$', ''))})
Link: {self.bundle_url}

Generate:
1. FACEBOOK POST (200 words):
   - Hook: "You'd normally pay ${INDIVIDUAL_TOTAL} for these 5 AI products separately..."
   - List all 5 products with their individual values
   - Bundle math: "But right now, get ALL 5 for just {BUNDLE_PRICE}"
   - Urgency: "Limited time bundle pricing"
   - CTA: {self.bundle_url}

2. INSTAGRAM CAPTION (100 words + 20 hashtags):
   - "5 AI products. 1 unbeatable price. 👇"
   - Product list with emojis
   - "Link in bio → AI Income Kit"

3. PRODUCT SPOTLIGHT (alternate daily, today: {BUNDLE_PRODUCTS[datetime.now().day % len(BUNDLE_PRODUCTS)][0]}):
   - 150-word deep-dive on one product's value
   - How it helps make money
   - CTA to buy bundle"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=1500)
        path = self.save_output(result, f"store_promo_{ts}.md", ext="md")

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
                elif "PRODUCT SPOTLIGHT" in line.upper():
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
            self.logger.debug("Store promo skipped: %s", e)

        return {"file": str(path), "action": "promote"}

    def _build_bundle_listing(self, ts: str, **kwargs) -> dict:
        products_str = "\n".join(f"- {p[0]}: {p[1]} — value {p[2]}" for p in BUNDLE_PRODUCTS)
        prompt = f"""Write the complete Gumroad listing for the WheellsVerse AI Income Kit Bundle.

Bundle: WheellsVerse AI Income Kit
Price: {BUNDLE_PRICE} (saves you ${INDIVIDUAL_TOTAL - int(BUNDLE_PRICE.replace('$', ''))} vs buying separately!)

Products included:
{products_str}

Listing structure:
1. TITLE — "The WheellsVerse AI Income Kit — 5 Products, 1 Unbeatable Price"
2. SHORT DESCRIPTION (150 chars)
3. LONG DESCRIPTION (900 words):
   - "Everything you need to start making money with AI — in one bundle"
   - Each product section: what it is, what you get, why it's worth it
   - Value stack breakdown (show total: ${INDIVIDUAL_TOTAL})
   - "You get all of this for just {BUNDLE_PRICE}"
   - Who it's for: beginner who wants to earn online with AI
   - 30-day money-back guarantee
4. WHAT'S INCLUDED — visual checklist
5. BONUSES (2 bonuses to sweeten the deal)
6. FAQ (6 questions)
7. URGENCY — "Bundle pricing ends soon"

Format: ready to paste into Gumroad"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2500)
        out_dir = Path(__file__).resolve().parents[3] / "frontend" / "store"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "bundle_listing.md").write_text(result, encoding="utf-8")
        path = self.save_output(result, f"bundle_listing_{ts}.md", ext="md")

        try:
            from core.telegram import notify
            notify(f"🛒 Digital Store — Bundle Listing Ready!\n💰 {BUNDLE_PRICE} (saves ${INDIVIDUAL_TOTAL - int(BUNDLE_PRICE.replace('$', ''))})\n📁 Upload to Gumroad!")
        except Exception:
            pass

        return {"file": str(path), "action": "bundle"}

    def _store_catalog(self, ts: str, **kwargs) -> dict:
        products_str = "\n".join(f"- {p[0]}: {p[1]} — {p[2]}" for p in BUNDLE_PRODUCTS)
        prompt = f"""Create the full WheellsVerse Digital Store catalog.

Current products:
{products_str}

Also create 5 NEW product ideas to add to the store:
Each should be: AI/income/crypto niche, digital format, $17-$97 price point

For each product (existing + new):
1. Product page title + tagline
2. Description (200 words)
3. What's included (bullet list)
4. Price + value justification
5. Who it's for
6. Gumroad tags (5)
7. Cross-sell suggestion (which other product to recommend)

Also generate:
- Store homepage copy (300 words)
- Category organization (how to group products)
- Bundle strategy (which products to bundle together)"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=3000)
        path = self.save_output(result, f"store_catalog_{ts}.md", ext="md")
        return {"file": str(path), "action": "catalog"}

    def _flash_sale(self, ts: str, **kwargs) -> dict:
        discount = kwargs.get("discount", "30%")
        hours = kwargs.get("hours", "24")
        prompt = f"""Create a flash sale campaign for WheellsVerse Digital Store.

Sale: {discount} off all products
Duration: {hours} hours only
Bundle flash price: ${int(int(BUNDLE_PRICE.replace('$', '')) * (1 - int(discount.replace('%', '')) / 100)):.0f}
Link: {self.bundle_url}

Generate:
1. FLASH SALE ANNOUNCEMENT POST (Facebook + Instagram):
   - Countdown urgency ("24 hours only!")
   - The deal in bold numbers
   - Every product listed with crossed-out original price → sale price
   - "This is the ONLY sale we run all month"

2. FLASH SALE EMAIL (subject line + 200-word body):
   - Subject: "⚡ 24-Hour Flash Sale — {discount} Off Everything"
   - Urgent, personal, specific

3. REMINDER POSTS (at 12h and 2h remaining):
   - Short urgency posts for each milestone

4. POST-SALE FOLLOW UP:
   - "Sale is over — but here's what's still available at regular price"

Use countdown psychology throughout."""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(result, f"flash_sale_{ts}.md", ext="md")
        return {"file": str(path), "action": "flash", "discount": discount}

    def _store_upsell(self, ts: str, **kwargs) -> dict:
        prompt = f"""Design the complete upsell and cross-sell system for WheellsVerse Digital Store.

Products: {', '.join(p[0] for p in BUNDLE_PRODUCTS)}
Bundle: AI Income Kit ({BUNDLE_PRICE})

System design:
1. CHECKOUT UPSELL — what to offer at the Gumroad checkout page (OTO)
2. POST-PURCHASE EMAIL SEQUENCE — 3 emails to upsell buyers to the bundle
3. ABANDONED CART EMAIL — email for people who viewed but didn't buy
4. CROSS-SELL LOGIC — after buying Product A, recommend Product B
5. LOYALTY DISCOUNT — return buyer discount (10% off)
6. REFERRAL PROGRAM — "Share and earn 30% commission" structure

For each touchpoint: exact copy + offer details + timing"""

        result = self.claude(prompt, system=SYSTEM, max_tokens=2000)
        path = self.save_output(result, f"store_upsell_{ts}.md", ext="md")
        return {"file": str(path), "action": "upsell"}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Digital Store Bot")
    parser.add_argument("--action", default="promote",
                        choices=["promote", "bundle", "catalog", "flash", "upsell"])
    parser.add_argument("--discount", type=str, default="30%")
    args = parser.parse_args()
    bot = DigitalStoreBot()
    result = bot.execute(action=args.action, discount=args.discount)
    print(f"\n✅ Digital Store: {result['file']}")
