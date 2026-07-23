#!/usr/bin/env python3
"""
Bot #51 — Sales & Marketing Copywriter
Category: Writing
Purpose: Write high-converting sales and marketing copy for landing pages, emails,
         ads, sales letters, and product descriptions using proven copywriting frameworks.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

COPY_TYPES = {
    "landing_page": {
        "desc": "Full landing page copy from headline to footer",
        "framework": "AIDA (Attention → Interest → Desire → Action)",
        "sections": "Headline, subheadline, hero, problem, solution, features/benefits, social proof, FAQ, CTA",
    },
    "email_sequence": {
        "desc": "Sales email sequence (3-7 emails)",
        "framework": "Indoctrination → Problem → Solution → Proof → Offer → Urgency",
        "sections": "Subject, preview text, body, CTA — per email",
    },
    "sales_letter": {
        "desc": "Long-form sales letter (VSL or direct mail format)",
        "framework": "Problem → Agitate → Solution → Proof → Offer → Guarantee → Close",
        "sections": "All sections of a complete sales letter",
    },
    "ad_copy": {
        "desc": "Paid ad copy (Facebook/Instagram/Google/TikTok)",
        "framework": "Hook → Problem → Solution → CTA (short form)",
        "sections": "Headline variants, body copy, ad descriptions, CTAs",
    },
    "product_description": {
        "desc": "E-commerce or SaaS product description",
        "framework": "Feature → Benefit → Transformation",
        "sections": "Headline, tagline, feature/benefit table, story, CTA",
    },
    "homepage_copy": {
        "desc": "Website homepage with clear value proposition",
        "framework": "Who you are → What you do → Who it's for → Why it's different → Social proof → Next step",
        "sections": "Hero section, value props, features, testimonials, CTA",
    },
    "webinar_invite": {
        "desc": "Webinar registration page and invite email",
        "framework": "Problem → Promise → Proof → Push (register now)",
        "sections": "Registration page copy + invite email",
    },
}


class CopywriterBot(BaseBot):

    def __init__(self):
        super().__init__("51_copywriter", "writing")

    def run(self, copy_type: str = None, product: str = None,
            audience: str = None, goal: str = None,
            key_benefit: str = None, **kwargs):

        cfg = self.config
        copy_type = copy_type or cfg.get("copy_type", "landing_page")
        product = product or cfg.get("product",
            "WheellsVerse AI Bot Platform — 70+ pre-built automation bots for entrepreneurs")
        audience = audience or cfg.get("audience",
            "entrepreneurs and small business owners who want to automate operations")
        goal = goal or cfg.get("goal", "sign up for free trial / purchase subscription")
        key_benefit = key_benefit or cfg.get("key_benefit",
            "save 20+ hours per week by automating content, sales, and customer support")

        ct = COPY_TYPES.get(copy_type, COPY_TYPES["landing_page"])
        ct_desc = ct["desc"]
        ct_framework = ct["framework"]
        ct_sections = ct["sections"]

        self.logger.info(f"Writing {copy_type} copy for: {product}")

        system = (
            "You are a direct-response copywriter in the tradition of Gary Halbert, Dan Kennedy, "
            "and David Ogilvy. You write copy that converts — not copy that wins awards. "
            "You know that people buy on emotion and justify with logic. You lead with the "
            "reader's pain, amplify it, then offer the solution. You use specific numbers, "
            "stories, and social proof — not vague claims. Your headlines are impossible to ignore. "
            "Your CTAs create urgency without feeling manipulative. You write for conversion, "
            "not for admiration. Every line either moves the reader closer to action or it gets cut."
        )

        prompt = f"""Write complete, high-converting {copy_type} copy for:

PRODUCT/SERVICE: {product}
TARGET AUDIENCE: {audience}
CONVERSION GOAL: {goal}
KEY BENEFIT: {key_benefit}
COPY FORMAT: {copy_type} — {ct_desc}
FRAMEWORK: {ct_framework}
SECTIONS TO INCLUDE: {ct_sections}

---

## COPY BRIEF

**Core promise (one sentence):** [What the product promises the customer]
**Target pain point:** [The #1 thing keeping this audience up at night]
**Unique mechanism:** [What makes this solution different from alternatives]
**Credibility anchor:** [The proof element that makes the promise believable]
**Objections to pre-handle:** [Top 3 objections — address in copy]

---

## THE COPY

[Write complete, publish-ready copy following the {ct_framework} framework.
Include ALL sections: {ct_sections}
Use emotional triggers: fear of missing out, desire for transformation, social proof, authority.
Be specific — use numbers, timeframes, and concrete outcomes.
Write for {audience} — use their language, mirror their fears and desires.
The copy should make saying NO feel like a loss.]

---

## HEADLINE VARIATIONS (A/B TEST THESE)

**Headline A (Benefit-led):**
[Headline]

**Headline B (Curiosity-led):**
[Headline]

**Headline C (Problem-led):**
[Headline]

**Headline D (Social proof-led):**
[Headline]

**Headline E (Bold claim):**
[Headline]

## CTA VARIATIONS

| CTA Text | Intent | Best Used |
| [CTA 1] | High urgency | |
| [CTA 2] | Value-focused | |
| [CTA 3] | Risk-reversal | |
| [CTA 4] | Curiosity | |

## COPY AUDIT

Rate this copy on:
- **Clarity** (reader knows exactly what they're getting): [X/10]
- **Relevance** (speaks directly to {audience}): [X/10]
- **Desire** (reader wants this after reading): [X/10]
- **Trust** (reader believes the claims): [X/10]
- **Action** (clear and compelling next step): [X/10]

**Top 3 things to test first:**
1. [Element to A/B test]
2. [Element to A/B test]
3. [Element to A/B test]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_product = self.slugify(product, 20)

        output = f"""# Copy: {copy_type} for {product[:40]}
**Format:** {copy_type}
**Goal:** {goal}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Copywriter Bot*
"""
        path = self.save_output(output, f"copy_{copy_type}_{safe_product}_{ts}.md", ext="md")
        self.logger.info(f"Copy saved → {path}")
        return {"file": str(path), "copy_type": copy_type, "product": product}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Sales & Marketing Copywriter")
    parser.add_argument("--type", type=str, default="landing_page",
                        choices=list(COPY_TYPES.keys()))
    parser.add_argument("--product", type=str, default=None)
    parser.add_argument("--audience", type=str, default=None)
    parser.add_argument("--goal", type=str, default=None)
    parser.add_argument("--benefit", type=str, default=None)
    args = parser.parse_args()
    bot = CopywriterBot()
    result = bot.execute(copy_type=args.type, product=args.product,
                         audience=args.audience, goal=args.goal,
                         key_benefit=args.benefit)
    print(f"\n✅ Copy: {result['file']}")
