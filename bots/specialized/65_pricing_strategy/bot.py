#!/usr/bin/env python3
"""
Bot #65 — Business Pricing Strategy Builder
Category: Specialized
Purpose: Build a complete pricing strategy framework for a business — including
         tier design, positioning, packaging, and revenue maximization tactics.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402

BUSINESS_TYPES = {
    "saas": "Software subscription product",
    "agency": "Done-for-you service business",
    "coaching": "1-on-1 or group coaching/consulting",
    "ecommerce": "Product sales (physical or digital)",
    "course": "Online education / info product",
    "freelance": "Freelancer or independent contractor",
    "marketplace": "Two-sided marketplace or platform",
}

PRICING_OBJECTIVES = {
    "maximize_revenue": "Extract maximum revenue from existing demand",
    "acquire_customers": "Lower entry barriers to grow user base",
    "move_upmarket": "Position for premium buyers, raise average deal size",
    "reduce_churn": "Increase retention and lifetime value",
    "launch_new": "Set pricing for a new product from scratch",
}


class PricingStrategyBot(BaseBot):

    def __init__(self):
        super().__init__("65_pricing_strategy", "specialized")

    def run(self, business_type: str = None, product_name: str = None,
            target_market: str = None, objective: str = None,
            revenue_goal: str = None, **kwargs):

        cfg = self.config
        business_type = business_type or cfg.get("business_type", "saas")
        product_name = product_name or cfg.get("product_name",
            "WheellsVerse AI Bot Platform")
        target_market = target_market or cfg.get("target_market",
            "entrepreneurs and small business owners, $10K-$500K annual revenue")
        objective = objective or cfg.get("objective", "maximize_revenue")
        revenue_goal = revenue_goal or cfg.get("revenue_goal", "$10K MRR")

        type_desc = BUSINESS_TYPES.get(business_type, business_type)
        obj_desc = PRICING_OBJECTIVES.get(objective, objective)

        self.logger.info(f"Building pricing strategy for: {product_name} ({objective})")

        system = (
            "You are a revenue strategist and pricing architect who has built pricing models "
            "for startups that have grown from $0 to $10M ARR. You know that pricing is strategy "
            "— it defines who you serve, how you compete, and what your business becomes. "
            "You build pricing systems that maximize customer lifetime value, not just conversion. "
            "You use real frameworks: Kano Model, Van Westendorp, Good-Better-Best tiers, "
            "jobs-to-be-done pricing, and expansion revenue design. "
            "You know that the best pricing system is one that grows with the customer."
        )

        prompt = f"""Build a complete pricing strategy for:

BUSINESS TYPE: {business_type} — {type_desc}
PRODUCT: {product_name}
TARGET MARKET: {target_market}
PRICING OBJECTIVE: {objective} — {obj_desc}
REVENUE GOAL: {revenue_goal}

---

## STRATEGIC PRICING FOUNDATION

### Pricing Philosophy
**Core pricing principle for {product_name}:** [The single most important thing pricing must accomplish]
**Who we're NOT pricing for:** [Customer segment to exclude — important for positioning]
**The price signal we want to send:** [What does our price communicate about quality/positioning]

### Jobs-to-be-Done Pricing Analysis
What are customers really paying for (not what the product is, but what it does for them):
1. **Functional job:** [What it does]
2. **Emotional job:** [How it makes them feel]
3. **Social job:** [How it helps them look or belong]
**Implication for pricing:** [Which of these 3 justifies the highest willingness to pay?]

---

## PRICING MODEL DESIGN

### Recommended Pricing Model
**Model type:** [e.g., Tiered flat-rate subscription / Usage-based / Per-seat / Project-based]
**Why this model:** [Why it fits {business_type} + {target_market}]
**Revenue predictability:** [High/Medium/Low — important for planning]

### Tier Architecture

#### TIER 1: [Name] — $[Price]/[period]
**Target persona:** [Specific description — who exactly buys this?]
**Core use case:** [What they use it for]
**Included:**
- [Feature 1]
- [Feature 2]
- [Feature 3]
**Strategic role:** [Acquire / Convert / Foot in the door]
**Upgrade trigger:** [When/why this customer upgrades to Tier 2]

#### TIER 2: [Name] — $[Price]/[period] ★ RECOMMENDED
**Target persona:** [Primary buyer — the majority of customers]
**Core use case:** [Main use case]
**Included:**
- Everything in [Tier 1]
- [Upgrade 1]
- [Upgrade 2]
- [Upgrade 3]
**Why Tier 2 is the anchor:** [Design logic — middle option effect]

#### TIER 3: [Name] — $[Price]/[period]
**Target persona:** [Power users / larger accounts]
**Core use case:** [Advanced use case]
**Included:**
- Everything in [Tier 2]
- [Premium feature 1]
- [Premium feature 2]
- [Support level upgrade]
**Strategic role:** [Anchor Tier 2 as "affordable" / Serve power users]

---

## PACKAGING STRATEGY

### What to include vs. gate
**Free features (all tiers):** [Features that increase adoption but don't differentiate]
**Gating logic:** [What feature type to save for paid tiers — power features, not basic]
**Usage limits as upgrade triggers:** [e.g., "10 bots free, 70 on paid"]

### Add-on / Expansion Revenue
| Add-on | Price | Who Buys It | When to Offer |
| [Add-on 1] | $[X] | | |
| [Add-on 2] | $[X] | | |
[3-5 add-on options]

**Expansion revenue goal:** [Target % of revenue from expansions]

---

## PATH TO {revenue_goal}

**Revenue model:**
- Tier 1: $[X]/month × [Y customers needed] = $[Z]
- Tier 2: $[X]/month × [Y customers needed] = $[Z]
- Tier 3: $[X]/month × [Y customers needed] = $[Z]
- Add-ons: $[X]/month estimated
- **Total at target mix:** {revenue_goal}

**Customer acquisition needed:** [Total customers at blended ACV to hit {revenue_goal}]

---

## PRICING PAGE STRATEGY

**5 elements that must be on the pricing page:**
1. [Element — e.g., clear tier comparison table]
2. [Element — ROI calculator or value statement]
3. [Element — social proof + logos]
4. [Element — FAQ addressing price objections]
5. [Element — strong guarantee/risk reversal]

**Copy for the most important button:**
[Not just "Get Started" — something that reinforces the value]

---

## PRICING TESTS TO RUN

| Test | Current | Variant | Hypothesis |
| [Test 1] | | | |
| [Test 2] | | | |
| [Test 3] | | | |

**Which test to run first:** [The highest-impact, lowest-risk test]

---

## PRICING EVOLUTION ROADMAP

**Year 1:** [Current pricing strategy — establish market position]
**Year 2:** [How to adjust as product matures and customer data accumulates]
**Year 3+:** [Move upmarket / introduce enterprise tier / usage-based components]"""

        result = self.ai(prompt, system=system,
                         model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                         max_tokens=3000)

        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        safe_product = "".join(c if c.isalnum() else "_" for c in product_name[:25])

        output = f"""# Pricing Strategy: {product_name}
**Business Type:** {business_type}
**Objective:** {objective}
**Revenue Goal:** {revenue_goal}
**Generated:** {_dt.now().strftime('%Y-%m-%d %H:%M')}

---

{result}

---
*Generated by WheellsVerse Pricing Strategy Bot*
"""
        path = self.save_output(output, f"pricing_strat_{safe_product}_{ts}.md", ext="md")
        self.logger.info(f"Pricing strategy saved → {path}")
        return {"file": str(path), "product": product_name, "objective": objective}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Business Pricing Strategy Builder")
    parser.add_argument("--type", type=str, default="saas",
                        choices=list(BUSINESS_TYPES.keys()))
    parser.add_argument("--product", type=str, default=None)
    parser.add_argument("--market", type=str, default=None)
    parser.add_argument("--goal", type=str, default="maximize_revenue",
                        choices=list(PRICING_OBJECTIVES.keys()))
    parser.add_argument("--revenue", type=str, default="$10K MRR")
    args = parser.parse_args()
    bot = PricingStrategyBot()
    result = bot.execute(business_type=args.type, product_name=args.product,
                         target_market=args.market, objective=args.goal,
                         revenue_goal=args.revenue)
    print(f"\n✅ Pricing Strategy: {result['file']}")
