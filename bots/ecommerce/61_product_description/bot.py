#!/usr/bin/env python3
"""
Bot #61 — E-Commerce Product Description Writer
Category: E-Commerce
Purpose: Write compelling, conversion-optimized product descriptions for e-commerce,
         digital products, and SaaS — with SEO optimization and feature/benefit framing.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

PRODUCT_CATEGORIES = {
    "digital_product": "Downloadable software, templates, courses, or tools",
    "saas_product": "Software as a Service — subscription-based tool or platform",
    "physical_product": "Physical goods shipped to customers",
    "service": "Done-for-you service or consulting offering",
    "info_product": "Ebook, guide, framework, or knowledge product",
    "membership": "Recurring access subscription — community, content, or tools",
}

DESCRIPTION_TYPES = {
    "full_listing": "Complete product page with all sections",
    "short_teaser": "1-2 sentence elevator pitch for ads or snippets",
    "email_pitch": "Email product introduction for existing audience",
    "marketplace": "Gumroad / AppSumo / Product Hunt listing format",
    "amazon_style": "Bullet-point feature list with short/long descriptions",
}


class ProductDescriptionBot(BaseBot):

    def __init__(self):
        super().__init__("61_product_description", "ecommerce")

    def generate_affiliate_link(self, product_name: str, keywords: str) -> str:
        base_url = "https://affiliate.example.com"
        query = f"?product={product_name.replace(' ', '+')}&keywords={keywords.replace(' ', '+')}"
        return f"{base_url}{query}"

    def run(self, product_name: str = None, product_category: str = None,
            target_audience: str = None, key_features: str = None,
            price_point: str = None, description_type: str = None, **kwargs):

        cfg = self.config
        product_name = product_name or cfg.get("product_name",
            "WheellsVerse AI Bot Platform")
        product_category = product_category or cfg.get("product_category", "saas_product")
        target_audience = target_audience or cfg.get("target_audience",
            "entrepreneurs and small business owners who want to automate operations")
        key_features = key_features or cfg.get("key_features",
            "70+ pre-built automation bots, content creation, sales, customer support, affiliate marketing, one-click execution")
        price_point = price_point or cfg.get("price_point", "$497/month or $4,997/year")
        description_type = description_type or cfg.get("description_type", "full_listing")

        cat_desc = PRODUCT_CATEGORIES.get(product_category, product_category)
        desc_type = DESCRIPTION_TYPES.get(description_type, description_type)

        self.logger.info(f"Writing {description_type} description for: {product_name}")

        affiliate_link = self.generate_affiliate_link(product_name, key_features)

        system = (
            "You are a product copywriter and conversion optimization specialist who has written "
            "descriptions for products that generate millions in revenue. You understand the "
            "psychology of online purchasing: people buy transformations, not features. "
            "You lead with the outcome the customer gets, not what the product is. "
            "You write bullet points that feel like promises, not spec lists. "
            "You use social proof, specificity, and urgency without cheap tricks. "
            "Every description you write answers the customer's core question: "
            "'How does this change my life or business?'"
        )

        prompt = f"""Write a complete, conversion-optimized product description for:

PRODUCT NAME: {product_name}
CATEGORY: {product_category} — {cat_desc}
TARGET AUDIENCE: {target_audience}
KEY FEATURES: {key_features}
PRICE POINT: {price_point}
DESCRIPTION TYPE: {description_type} — {desc_type}
AFFILIATE LINK: {affiliate_link}

---

## SEO METADATA

**Product page title (under 60 chars):** [Keyword-rich, benefit-led]
**Meta description (under 155 chars):** [Compelling, includes price or value signal]
**Primary keyword:** [Main search term this product should rank for]
**Secondary keywords:** [5 related keywords]
**Product tags:** [10-15 relevant tags]

---

## THE PRODUCT DESCRIPTION

### HEADLINE
[Main hero headline — the transformation, not the product name]

### SUBHEADLINE
[One sentence expanding on the headline — who it's for + the specific outcome]

---

### WHAT THIS IS
[1-2 sentences — the clearest, simplest explanation of what {product_name} does]
[Written as if explaining to someone who has never heard of it]

---

### THE PROBLEM IT SOLVES
[3-4 sentences — paint the painful before state for {target_audience}]
[Use their language — the words they use to describe their struggle]

---

### WHAT YOU GET
[Benefit-led bullet points — 8-12 bullets]
[Format: ✓ [Outcome] — [How it works in one line]]

Key features to cover: {key_features}

---

### HOW IT WORKS
[3-step process — make it look simple and achievable]
1. **Step 1:** [Action + what happens]
2. **Step 2:** [Action + what happens]
3. **Step 3:** [The transformation]

---

### PERFECT FOR YOU IF...
[5 "if" statements that mirror the ideal customer's situation]
- If you're tired of [pain]...
- If you've tried [alternative] but [why it failed]...
[Continue with 5 total]

---

### WHAT MAKES IT DIFFERENT
[3 specific differentiators from alternatives — not generic claims]
1. **[Differentiator 1]:** [Specific comparison to alternative]
2. **[Differentiator 2]:** [Why this matters to the buyer]
3. **[Differentiator 3]:** [The unique mechanism or approach]

---

### INVESTMENT
**{price_point}**
[Justify the value — what does this replace? What does it save in time/money?]

**What's included:**
- [Deliverable 1]
- [Deliverable 2]
[Continue for all features]

**Guarantee:** [Risk reversal — return policy, satisfaction guarantee, etc.]

---

### FREQUENTLY ASKED QUESTIONS
[5 questions {target_audience} would actually ask — with honest, complete answers]
Q1: [Question]
A: [Answer]
[Continue for 5 Q&As]

---

## SHORT VERSIONS

**30-word pitch (for ads):**
[Ultra-concise value proposition]

**3-bullet Amazon-style:**
• [Bullet 1]
• [Bullet 2]
• [Bullet 3]

**Social proof placeholder:**
"[Template testimonial showing the transformation — fill in with real customer words]"

## A/B TEST HEADLINE VARIANTS

| Variant | Hook Style | Headline |
| A | Outcome-led | [Headline] |
| B | Pain-led | [Headline] |
| C | Social proof | [Headline] |
| D | Curiosity | [Headline] |"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_name = self.slugify(product_name, 25)

        output = f"""# Product Description: {product_name}
**Category:** {product_category}
**Description Type:** {description_type}
**Price:** {price_point}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Product Description Bot*
"""
        path = self.save_output(output, f"product_{safe_name}_{ts}.md", ext="md")
        self.logger.info(f"Product description saved → {path}")
        return {"file": str(path), "product": product_name, "type": description_type}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="E-Commerce Product Description Writer")
    parser.add_argument("--product", type=str, default=None)
    parser.add_argument("--category", type=str, default="saas_product",
                        choices=list(PRODUCT_CATEGORIES.keys()))
    parser.add_argument("--audience", type=str, default=None)
    parser.add_argument("--features", type=str, default=None)
    parser.add_argument("--price", type=str, default=None)
    parser.add_argument("--type", type=str, default="full_listing",
                        choices=list(DESCRIPTION_TYPES.keys()))
    args = parser.parse_args()
    bot = ProductDescriptionBot()
    result = bot.execute(product_name=args.product, product_category=args.category,
                         target_audience=args.audience, key_features=args.features,
                         price_point=args.price, description_type=args.type)
    print(f"\n✅ Product Description: {result['file']}")
