#!/usr/bin/env python3
"""
core/funnel_builder.py
─────────────────────────────────────────────────────────────────────────────
5-Step Monetization Funnel Builder for NarAI Shopify Autopilot

Builds a complete value ladder:
  Step 1: Free lead magnet PDF (Shopify $0 product → ConvertKit opt-in)
  Step 2: $9 ebook (upsell after lead magnet download)
  Step 3: $29 template/toolkit (email Day 3 + page upsell)
  Step 4: $99 course PDF or tool (email Day 7)
  Step 5: $19/month subscription (email Day 14 + checkout upsell)

State file: data/shopify_funnel.json
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

FUNNEL_FILE = DATA_DIR / "shopify_funnel.json"

log = logging.getLogger("funnel_builder")


# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE HELPER
# ══════════════════════════════════════════════════════════════════════════════

def _claude(prompt: str, system: str = "", max_tokens: int = 4000) -> str:
    import anthropic
    model = os.getenv("NARAI_MODEL", "claude-sonnet-4-6")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    r = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system or _system(),
        messages=[{"role": "user", "content": prompt}],
    )
    return r.content[0].text.strip()


def _claude_json(prompt: str, system: str = "", max_tokens: int = 3000) -> Any:
    raw = _claude(prompt, system, max_tokens)
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
    try:
        return json.loads(raw.strip())
    except Exception:
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", raw)
        if m:
            try:
                return json.loads(m.group(1))
            except Exception:
                pass
    return {}


def _system() -> str:
    return (
        "You are NarAI's conversion optimization expert. You build monetization funnels "
        "that turn free subscribers into paying customers across a 5-step value ladder. "
        "Your copy is direct-response: benefit-led, proof-driven, urgency-creating. "
        "You know that 'free → $9 → $29 → $99 → $19/month' is the proven progression. "
        "Output pure JSON only. No prose, no markdown outside the JSON."
    )


# ══════════════════════════════════════════════════════════════════════════════
# COPY GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def generate_funnel_copy(step: int, niche: str, product: dict) -> dict:
    """
    Generate AIDA/PAS copy for a specific funnel step.

    Args:
        step: 1-5 (1=free lead magnet, 5=subscription)
        niche: the niche context
        product: product dict with title, description, price, etc.

    Returns:
        {headline, subheadline, body, cta, upsell_line, email_subject, email_preview}
    """
    step_contexts = {
        1: "free lead magnet — maximum perceived value, zero friction",
        2: f"$9 upsell — momentum from free download, 'you just got X now get Y'",
        3: f"$29 mid-ticket — problem deepened after $9, ready for more",
        4: f"$99 high-ticket — committed buyer who wants comprehensive solution",
        5: f"$19/month subscription — ongoing access, recurring value proof",
    }
    context = step_contexts.get(step, "product page")
    price   = product.get("price", 0)

    prompt = f"""Write conversion copy for funnel step {step}: {context}

NICHE: {niche}
PRODUCT: {json.dumps(product, default=str)}
PRICE: ${price}

This is step {step} of a 5-step value ladder. Buyer context:
{context}

Return JSON:
{{
  "headline": "power headline under 12 words — benefit or curiosity gap",
  "subheadline": "1-sentence expansion, adds specificity or social proof",
  "body": "3-4 sentences of body copy using PAS or AIDA framework",
  "cta": "call to action button text (action verb + outcome, under 6 words)",
  "upsell_line": "one-line transition to the next funnel step (tease the next product)",
  "email_subject": "email subject line for this step sequence (under 50 chars)",
  "email_preview": "email preview text shown in inbox (under 90 chars)",
  "email_body_opening": "first 2 sentences of the email body"
}}"""

    result = _claude_json(prompt, max_tokens=1500)

    if not isinstance(result, dict) or not result.get("headline"):
        result = {
            "headline":           f"Get {product.get('title', 'This Resource')} {'Free' if price == 0 else f'for ${price}'}",
            "subheadline":        f"Everything you need to succeed in {niche}",
            "body":               "Join thousands who are already using this system to build income online.",
            "cta":                "Get Instant Access" if price == 0 else f"Get It Now — ${price}",
            "upsell_line":        "Ready to go deeper? See what's next →",
            "email_subject":      f"Your {product.get('title', 'resource')} is ready",
            "email_preview":      f"Here's everything you need to get started with {niche}",
            "email_body_opening": "Thank you for joining. Here's your resource below.",
        }

    return result


# ══════════════════════════════════════════════════════════════════════════════
# LEAD MAGNET (Step 1 — Free)
# ══════════════════════════════════════════════════════════════════════════════

def _build_lead_magnet(niche: str, market_intel: dict) -> dict:
    """
    Step 1: Create a free PDF/checklist as Shopify $0 product.
    Returns product dict including shopify_product_id if creation succeeds.
    """
    prompt = f"""Design a high-value FREE lead magnet for this niche.

NICHE: {niche}
MARKET CONTEXT: {json.dumps(market_intel, default=str)[:1000]}

The lead magnet must:
- Solve ONE specific, immediate problem
- Be completable in under 15 minutes (checklist, cheatsheet, or 5-page PDF)
- Make people feel they NEED the paid product after reading it
- Have a title that sounds worth $20+ (so free feels like a steal)

Return JSON:
{{
  "title": "lead magnet title (sounds valuable, under 60 chars)",
  "subtitle": "one-line promise",
  "format": "checklist | cheatsheet | mini-guide",
  "page_count": <5 to 10>,
  "problem_solved": "the specific problem this solves",
  "content_outline": [
    "Section 1: ...",
    "Section 2: ...",
    "Section 3: ..."
  ],
  "opt_in_reason": "why someone gives their email for this",
  "convertkit_tag": "tag name to apply in ConvertKit (snake_case)",
  "convertkit_sequence": "name of welcome email sequence to trigger"
}}"""

    data = _claude_json(prompt, max_tokens=2000)
    if not isinstance(data, dict) or not data.get("title"):
        data = {
            "title":              f"The {niche.title()} Quick-Start Checklist",
            "subtitle":           f"The 10-step system to get started with {niche} today",
            "format":             "checklist",
            "page_count":         7,
            "problem_solved":     f"Getting started with {niche} without overwhelm",
            "content_outline":    ["Step 1: Foundation", "Step 2: Setup", "Step 3: First Results"],
            "opt_in_reason":      "Free resource that saves hours of research",
            "convertkit_tag":     niche.lower().replace(" ", "_").replace("/", "_")[:30],
            "convertkit_sequence": f"{niche.title()} Welcome Sequence",
        }

    # Create Shopify product at $0
    shopify_product_id = None
    try:
        from core.shopify_client import create_product
        result = create_product({
            "title":            data["title"],
            "body_html":        f"<p>{data.get('subtitle', '')}</p>",
            "vendor":           "WheellsVerse",
            "product_type":     "Digital Download",
            "tags":             "lead-magnet, free, digital",
            "requires_shipping": False,
            "variants": [{
                "price":               "0.00",
                "requires_shipping":   False,
                "inventory_management": None,
                "inventory_policy":    "continue",
            }],
        })
        shopify_product_id = result.get("product_id")
    except Exception as e:
        log.warning(f"[FunnelBuilder] Lead magnet Shopify create failed: {e}")

    data["step"]              = 1
    data["price"]             = 0
    data["shopify_product_id"] = shopify_product_id
    return data


# ══════════════════════════════════════════════════════════════════════════════
# LOW TICKET (Step 2 — $9)
# ══════════════════════════════════════════════════════════════════════════════

def _build_low_ticket(niche: str, lead_magnet: dict) -> dict:
    """Step 2: $9 ebook that solves the deeper problem introduced by the lead magnet."""
    prompt = f"""Design a $9 ebook that upsells from this lead magnet.

NICHE: {niche}
LEAD MAGNET: {json.dumps(lead_magnet, default=str)[:500]}

The $9 ebook must:
- Pick up exactly where the lead magnet leaves off
- Go deeper on the #1 problem the lead magnet introduces
- Be 20-40 pages with real actionable content
- Feel worth $27 minimum (so $9 is a no-brainer)

Return JSON:
{{
  "title": "ebook title — outcome-driven, under 65 chars",
  "subtitle": "what they'll know/do/have after reading",
  "price": 9,
  "compare_at_price": 27,
  "page_count": <20 to 40>,
  "chapters": ["Chapter 1: ...", "Chapter 2: ...", "Chapter 3: ...", "Chapter 4: ...", "Chapter 5: ..."],
  "main_promise": "the transformation promise of this ebook",
  "upsell_bridge": "one sentence that bridges to the $29 product"
}}"""

    data = _claude_json(prompt, max_tokens=2000)
    if not isinstance(data, dict) or not data.get("title"):
        data = {
            "title":           f"The Complete {niche.title()} Playbook",
            "subtitle":        f"From zero to results with {niche} — the full system",
            "price":           9,
            "compare_at_price": 27,
            "page_count":      30,
            "chapters":        ["Chapter 1: Foundation", "Chapter 2: Strategy", "Chapter 3: Execution", "Chapter 4: Scale"],
            "main_promise":    f"Master {niche} in 30 days",
            "upsell_bridge":   "Want the templates and tools to implement this faster?",
        }

    shopify_product_id = None
    try:
        from core.shopify_client import create_product
        result = create_product({
            "title":            data["title"],
            "body_html":        f"<p>{data.get('subtitle', '')}</p><p><strong>{data.get('main_promise', '')}</strong></p>",
            "vendor":           "WheellsVerse",
            "product_type":     "Digital Download",
            "tags":             f"ebook, {niche}, digital-product",
            "requires_shipping": False,
            "variants": [{
                "price":               str(data["price"]),
                "compare_at_price":    str(data.get("compare_at_price", 27)),
                "requires_shipping":   False,
                "inventory_management": None,
                "inventory_policy":    "continue",
            }],
        })
        shopify_product_id = result.get("product_id")
    except Exception as e:
        log.warning(f"[FunnelBuilder] Low-ticket Shopify create failed: {e}")

    data["step"]              = 2
    data["shopify_product_id"] = shopify_product_id
    return data


# ══════════════════════════════════════════════════════════════════════════════
# MID TICKET (Step 3 — $29)
# ══════════════════════════════════════════════════════════════════════════════

def _build_mid_ticket(niche: str) -> dict:
    """Step 3: $29 template/toolkit — the 'done-for-you' companion to the ebook."""
    prompt = f"""Design a $29 template/toolkit product for this niche.

NICHE: {niche}

This is step 3 of a funnel — the buyer has the theory ($9 ebook) and now wants tools to implement faster.

Must be a practical toolkit: Notion templates, prompt packs, spreadsheets, canva templates, or similar.

Return JSON:
{{
  "title": "toolkit title — 'done-for-you' or 'ready-to-use', under 65 chars",
  "subtitle": "what they get and why it saves them time/money",
  "price": 29,
  "compare_at_price": 67,
  "format": "Notion template | prompt pack | spreadsheet bundle | Canva kit",
  "item_count": <10 to 50>,
  "includes": ["Item 1: ...", "Item 2: ...", "Item 3: ...", "Item 4: ...", "Item 5: ..."],
  "time_saved": "e.g. '12 hours of setup time'",
  "upsell_bridge": "one sentence bridging to the $99 product"
}}"""

    data = _claude_json(prompt, max_tokens=2000)
    if not isinstance(data, dict) or not data.get("title"):
        data = {
            "title":           f"{niche.title()} Template Toolkit",
            "subtitle":        "Copy-paste templates to implement the system in hours, not weeks",
            "price":           29,
            "compare_at_price": 67,
            "format":          "Notion template + prompt pack",
            "item_count":      25,
            "includes":        ["Notion dashboard", "25 prompts", "Checklist PDF", "Swipe file", "Quick-start guide"],
            "time_saved":      "10+ hours of setup time",
            "upsell_bridge":   "Want the full course with step-by-step video walkthroughs?",
        }

    shopify_product_id = None
    try:
        from core.shopify_client import create_product
        result = create_product({
            "title":            data["title"],
            "body_html":        f"<p>{data.get('subtitle', '')}</p><ul>" + "".join(f"<li>{i}</li>" for i in data.get("includes", [])) + "</ul>",
            "vendor":           "WheellsVerse",
            "product_type":     "Digital Download",
            "tags":             f"template, toolkit, {niche}, digital-product",
            "requires_shipping": False,
            "variants": [{
                "price":               str(data["price"]),
                "compare_at_price":    str(data.get("compare_at_price", 67)),
                "requires_shipping":   False,
                "inventory_management": None,
                "inventory_policy":    "continue",
            }],
        })
        shopify_product_id = result.get("product_id")
    except Exception as e:
        log.warning(f"[FunnelBuilder] Mid-ticket Shopify create failed: {e}")

    data["step"]              = 3
    data["shopify_product_id"] = shopify_product_id
    return data


# ══════════════════════════════════════════════════════════════════════════════
# HIGH TICKET (Step 4 — $99)
# ══════════════════════════════════════════════════════════════════════════════

def _build_high_ticket(niche: str) -> dict:
    """Step 4: $99 course PDF or comprehensive system."""
    prompt = f"""Design a $99 premium digital product for this niche.

NICHE: {niche}

This is step 4 — the buyer has proven commitment ($9 + $29). They want the COMPLETE system.
Could be a comprehensive PDF course, a massive resource bundle, or a system with ongoing-feel.

Return JSON:
{{
  "title": "premium product title — 'complete system' / 'masterclass' / 'blueprint', under 65 chars",
  "subtitle": "the total transformation promise",
  "price": 99,
  "compare_at_price": 197,
  "format": "PDF course | mega bundle | video script guide | comprehensive system",
  "modules": [
    "Module 1: ...",
    "Module 2: ...",
    "Module 3: ...",
    "Module 4: ...",
    "Module 5: ..."
  ],
  "bonuses": ["Bonus 1: ...", "Bonus 2: ...", "Bonus 3: ..."],
  "total_value": "e.g. '$497 worth of resources'",
  "upsell_bridge": "one sentence bridging to the $19/month subscription"
}}"""

    data = _claude_json(prompt, max_tokens=2000)
    if not isinstance(data, dict) or not data.get("title"):
        data = {
            "title":           f"The {niche.title()} Mastery Blueprint",
            "subtitle":        f"The complete A-to-Z system for dominating {niche}",
            "price":           99,
            "compare_at_price": 197,
            "format":          "PDF course",
            "modules":         ["Module 1: Foundation", "Module 2: Strategy", "Module 3: Execution", "Module 4: Scale", "Module 5: Optimize"],
            "bonuses":         ["Bonus 1: Private template vault", "Bonus 2: Swipe file library", "Bonus 3: Quick-start checklist"],
            "total_value":     "$497 worth of resources",
            "upsell_bridge":   "Get monthly updates and new resources — join the inner circle.",
        }

    shopify_product_id = None
    try:
        from core.shopify_client import create_product
        modules_html = "".join(f"<li>{m}</li>" for m in data.get("modules", []))
        bonuses_html = "".join(f"<li>{b}</li>" for b in data.get("bonuses", []))
        result = create_product({
            "title":            data["title"],
            "body_html":        f"<p>{data.get('subtitle', '')}</p><h3>What's Inside</h3><ul>{modules_html}</ul><h3>Bonuses</h3><ul>{bonuses_html}</ul>",
            "vendor":           "WheellsVerse",
            "product_type":     "Digital Download",
            "tags":             f"course, blueprint, {niche}, premium",
            "requires_shipping": False,
            "variants": [{
                "price":               str(data["price"]),
                "compare_at_price":    str(data.get("compare_at_price", 197)),
                "requires_shipping":   False,
                "inventory_management": None,
                "inventory_policy":    "continue",
            }],
        })
        shopify_product_id = result.get("product_id")
    except Exception as e:
        log.warning(f"[FunnelBuilder] High-ticket Shopify create failed: {e}")

    data["step"]              = 4
    data["shopify_product_id"] = shopify_product_id
    return data


# ══════════════════════════════════════════════════════════════════════════════
# SUBSCRIPTION (Step 5 — $19/month)
# ══════════════════════════════════════════════════════════════════════════════

def _build_subscription(niche: str) -> dict:
    """
    Step 5: $19/month recurring product.
    Uses Shopify Selling Plans API (GraphQL) for native subscriptions.
    """
    prompt = f"""Design a $19/month subscription product for this niche.

NICHE: {niche}

This is the final funnel step — maximum buyer commitment. The subscription must deliver
ONGOING value: new resources monthly, community access, or curated intelligence.

Return JSON:
{{
  "title": "subscription name — 'Inner Circle' / 'Pro Access' / 'Monthly Vault', under 60 chars",
  "subtitle": "what members get every month",
  "price_monthly": 19,
  "billing_cycle": "monthly",
  "deliverables": [
    "Monthly resource: ...",
    "Monthly resource: ...",
    "Monthly resource: ..."
  ],
  "retention_hook": "why people stay subscribed month after month",
  "cancel_anytime": true
}}"""

    data = _claude_json(prompt, max_tokens=1500)
    if not isinstance(data, dict) or not data.get("title"):
        data = {
            "title":          f"{niche.title()} Inner Circle",
            "subtitle":       "New AI tools, templates, and strategies delivered every month",
            "price_monthly":  19,
            "billing_cycle":  "monthly",
            "deliverables":   ["Monthly resource pack", "New prompt collection", "Market intelligence report"],
            "retention_hook": "Fresh resources every month — stay ahead of the curve",
            "cancel_anytime": True,
        }

    shopify_product_id    = None
    selling_plan_group_id = None

    try:
        from core.shopify_client import _gql, get_credentials
        shop, token, _ = get_credentials()

        # Create product first
        from core.shopify_client import create_product
        result = create_product({
            "title":            data["title"],
            "body_html":        f"<p>{data.get('subtitle', '')}</p><ul>" + "".join(f"<li>{d}</li>" for d in data.get("deliverables", [])) + "</ul>",
            "vendor":           "WheellsVerse",
            "product_type":     "Subscription",
            "tags":             f"subscription, monthly, {niche}, membership",
            "requires_shipping": False,
            "variants": [{
                "price":               str(data["price_monthly"]),
                "requires_shipping":   False,
                "inventory_management": None,
                "inventory_policy":    "continue",
            }],
        })
        shopify_product_id = result.get("product_id")

        # Create Selling Plan Group via GraphQL
        if shopify_product_id:
            mutation = """
mutation sellingPlanGroupCreate($input: SellingPlanGroupInput!, $resources: SellingPlanGroupResourceInput) {
  sellingPlanGroupCreate(input: $input, resources: $resources) {
    sellingPlanGroup {
      id
      name
      sellingPlans(first: 1) {
        edges { node { id name } }
      }
    }
    userErrors { field message }
  }
}"""
            variables = {
                "input": {
                    "name":             data["title"],
                    "merchantCode":     "narai-subscription",
                    "options":          ["Billing Frequency"],
                    "position":         1,
                    "sellingPlansToCreate": [{
                        "name":     "Monthly subscription",
                        "options":  ["Monthly"],
                        "position": 1,
                        "billingPolicy": {
                            "recurring": {
                                "interval":      "MONTH",
                                "intervalCount": 1,
                            }
                        },
                        "deliveryPolicy": {
                            "recurring": {
                                "interval":      "MONTH",
                                "intervalCount": 1,
                            }
                        },
                        "pricingPolicies": [{
                            "fixed": {
                                "adjustmentType":  "PRICE",
                                "adjustmentValue": {"fixedValue": str(data["price_monthly"])},
                            }
                        }],
                    }],
                },
                "resources": {
                    "productIds": [f"gid://shopify/Product/{shopify_product_id}"],
                },
            }
            gql_resp = _gql(mutation, variables)
            spg = gql_resp.get("data", {}).get("sellingPlanGroupCreate", {}).get("sellingPlanGroup", {})
            selling_plan_group_id = spg.get("id")

    except Exception as e:
        log.warning(f"[FunnelBuilder] Subscription Shopify create failed: {e}")

    data["step"]                 = 5
    data["price"]                = data.get("price_monthly", 19)
    data["shopify_product_id"]   = shopify_product_id
    data["selling_plan_group_id"] = selling_plan_group_id
    return data


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL SEQUENCE WIRING
# ══════════════════════════════════════════════════════════════════════════════

def wire_email_sequences(funnel: dict) -> dict:
    """
    Wire up ConvertKit email sequences for each funnel step.

    Returns:
        Updated funnel dict with convertkit_sequence_ids added to each step
    """
    steps = funnel.get("steps", [])
    sequence_ids: Dict[int, Optional[int]] = {}

    for step in steps:
        step_num = step.get("step")
        if not step_num:
            continue
        try:
            from core.email_funnel import build_sequence
            copy = generate_funnel_copy(step_num, funnel.get("niche", ""), step)
            seq_id = build_sequence(
                name=f"Funnel Step {step_num}: {step.get('title', '')}",
                niche=funnel.get("niche", ""),
                step=step_num,
                product=step,
                copy=copy,
            )
            sequence_ids[step_num] = seq_id
            step["convertkit_sequence_id"] = seq_id
        except Exception as e:
            log.warning(f"[FunnelBuilder] Email sequence step {step_num} failed: {e}")
            sequence_ids[step_num] = None

    funnel["email_sequences"] = sequence_ids
    return funnel


# ══════════════════════════════════════════════════════════════════════════════
# MASTER FUNNEL BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def build_shopify_funnel(niche: str, market_intel: dict) -> dict:
    """
    Master function: build complete 5-step funnel.

    Creates Shopify products at each tier, wires ConvertKit sequences,
    and saves to data/shopify_funnel.json.

    Args:
        niche: the dominant niche for this session
        market_intel: dict from market intelligence

    Returns:
        Complete funnel dict
    """
    log.info(f"[FunnelBuilder] Building funnel for niche: {niche}")

    funnel: Dict[str, Any] = {
        "niche":      niche,
        "built_at":   datetime.now(timezone.utc).isoformat(),
        "steps":      [],
        "stats": {
            "steps_created":  0,
            "shopify_products": 0,
            "email_sequences":  0,
        },
    }

    def _run_step(label: str, fn, *args):
        try:
            log.info(f"[FunnelBuilder] {label}…")
            result = fn(*args)
            funnel["steps"].append(result)
            funnel["stats"]["steps_created"] += 1
            if result.get("shopify_product_id"):
                funnel["stats"]["shopify_products"] += 1
            return result
        except Exception as e:
            log.error(f"[FunnelBuilder] {label} failed: {e}")
            return {}

    lead_magnet = _run_step("Step 1 — Free lead magnet", _build_lead_magnet, niche, market_intel)
    _run_step("Step 2 — $9 ebook",         _build_low_ticket,  niche, lead_magnet)
    _run_step("Step 3 — $29 toolkit",      _build_mid_ticket,  niche)
    _run_step("Step 4 — $99 masterclass",  _build_high_ticket, niche)
    _run_step("Step 5 — $19/mo subscription", _build_subscription, niche)

    # Wire email sequences
    try:
        funnel = wire_email_sequences(funnel)
        funnel["stats"]["email_sequences"] = len([s for s in funnel.get("email_sequences", {}).values() if s])
    except Exception as e:
        log.warning(f"[FunnelBuilder] Email wiring failed: {e}")

    save_funnel(funnel)
    log.info(f"[FunnelBuilder] Funnel complete — {funnel['stats']['steps_created']} steps, "
             f"{funnel['stats']['shopify_products']} Shopify products")
    return funnel


# ══════════════════════════════════════════════════════════════════════════════
# STATE PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

def get_active_funnel() -> dict:
    """Read the current funnel from data/shopify_funnel.json."""
    try:
        if FUNNEL_FILE.exists():
            return json.loads(FUNNEL_FILE.read_text())
    except Exception:
        pass
    return {}


def save_funnel(funnel: dict):
    """Persist funnel to data/shopify_funnel.json."""
    try:
        FUNNEL_FILE.write_text(json.dumps(funnel, indent=2, default=str))
    except Exception as e:
        log.error(f"[FunnelBuilder] Failed to save funnel: {e}")
