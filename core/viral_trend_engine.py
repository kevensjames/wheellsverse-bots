#!/usr/bin/env python3
"""
core/viral_trend_engine.py
─────────────────────────────────────────────────────────────────────────────
Viral Trend Detection Engine for NarAI Shopify Autopilot

Detects viral product opportunities in the "AI + Money + Productivity" niche
using existing market intelligence (no external scraping). Claude synthesizes
and ranks opportunities by urgency, format, and revenue potential.

Product types (ranked by urgency):
  1. AI prompt packs    — highest velocity, lowest effort
  2. Notion templates   — proven Gumroad/Etsy format
  3. Trading toolkits   — high AOV
  4. Mini-courses PDF   — scalable
  5. POD identity       — passive
  6. Service packages   — high margin
  7. Subscriptions      — recurring revenue

State file: data/viral_trends.json
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

TRENDS_FILE = DATA_DIR / "viral_trends.json"

log = logging.getLogger("viral_trend_engine")

# ── Product type urgency ranking ──────────────────────────────────────────────
PRODUCT_TYPES = [
    {"type": "ai_prompt_pack",    "rank": 1, "format": "digital",  "aov_range": "$7-$27"},
    {"type": "notion_template",   "rank": 2, "format": "digital",  "aov_range": "$9-$37"},
    {"type": "trading_toolkit",   "rank": 3, "format": "digital",  "aov_range": "$27-$97"},
    {"type": "mini_course_pdf",   "rank": 4, "format": "digital",  "aov_range": "$17-$47"},
    {"type": "pod_product",       "rank": 5, "format": "pod",      "aov_range": "$19-$49"},
    {"type": "service_package",   "rank": 6, "format": "service",  "aov_range": "$49-$499"},
    {"type": "subscription",      "rank": 7, "format": "recurring","aov_range": "$9-$29/mo"},
]

# ── Validated niches ──────────────────────────────────────────────────────────
VALIDATED_NICHES = [
    "AI productivity & automation",
    "passive income with digital products",
    "make money online in 2026",
    "ChatGPT & Claude prompt engineering",
    "no-code tools & Notion systems",
    "trading psychology & data mindset",
]

# ── Identity niches for POD ───────────────────────────────────────────────────
POD_IDENTITY_NICHES = [
    "entrepreneur mindset",
    "hacker / programmer",
    "dark fantasy / anime",
]


# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE HELPERS
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
        "You are NarAI's market intelligence engine. You identify viral digital product "
        "opportunities in the 'AI + Money + Productivity' niche. You only recommend products "
        "with proven demand signals — formats that sell on Gumroad, Etsy, Payhip, and Shopify. "
        "Never suggest random or untested ideas. Every opportunity must have a clear viral hook, "
        "specific target buyer, and realistic price ceiling based on market data. "
        "Output pure JSON only — no markdown, no prose, no explanation outside the JSON structure."
    )


# ══════════════════════════════════════════════════════════════════════════════
# TREND SCANNING
# ══════════════════════════════════════════════════════════════════════════════

def scan_viral_opportunities(market_intel: dict) -> List[dict]:
    """
    Analyze market intelligence and synthesize ranked viral product opportunities.

    Args:
        market_intel: dict from market_intelligence.get_narai_briefing() or get_platform_data()

    Returns:
        List of opportunity dicts ranked by urgency_score (highest first)
    """
    briefing_text = ""
    if isinstance(market_intel, str):
        briefing_text = market_intel[:4000]
    elif isinstance(market_intel, dict):
        briefing_text = json.dumps(market_intel, default=str)[:4000]

    product_types_json = json.dumps(PRODUCT_TYPES, indent=2)
    niches_text = "\n".join(f"  • {n}" for n in VALIDATED_NICHES)
    pod_niches_text = "\n".join(f"  • {n}" for n in POD_IDENTITY_NICHES)

    prompt = f"""You are analyzing today's market intelligence for NarAI's Shopify store.

MARKET INTELLIGENCE:
{briefing_text}

PRODUCT TYPES TO CONSIDER (ranked by velocity):
{product_types_json}

VALIDATED NICHES (only use these):
{niches_text}

POD IDENTITY NICHES (for pod products only):
{pod_niches_text}

TASK: Identify the top 7 viral product opportunities right now. Each opportunity must:
- Map to one of the validated niches above
- Use one of the listed product types
- Have a specific viral hook that makes people want to BUY TODAY
- Have realistic pricing based on what actually sells at this format/niche intersection
- Score urgency 1-100 (100 = trending hard right now, people are buying this exact thing)

Return a JSON array of exactly 7 opportunities:
[
  {{
    "rank": 1,
    "product_type": "ai_prompt_pack",
    "format": "digital",
    "niche": "ChatGPT & Claude prompt engineering",
    "title_concept": "The Claude Prompt Vault: 200 Profit-Generating Prompts",
    "viral_hook": "The exact prompts I use to generate $500/day in digital product ideas",
    "price_ceiling": 27,
    "price_floor": 17,
    "urgency_score": 94,
    "why_now": "Claude 4 just dropped — everyone is searching for power prompts",
    "target_buyer": "freelancers and solopreneurs wanting to leverage Claude for income",
    "pod_niche": null
  }},
  ...
]

For pod products, set format="pod" and fill pod_niche from the POD IDENTITY NICHES list.
For service_package and subscription types, set format accordingly.
Urgency scores must be varied (not all 90+). Be realistic."""

    result = _claude_json(prompt, max_tokens=4000)

    if not isinstance(result, list):
        result = result.get("opportunities", []) if isinstance(result, dict) else []

    # Validate and clean
    cleaned = []
    for opp in result:
        if not isinstance(opp, dict):
            continue
        cleaned.append({
            "rank":          opp.get("rank", len(cleaned) + 1),
            "product_type":  opp.get("product_type", "ai_prompt_pack"),
            "format":        opp.get("format", "digital"),
            "niche":         opp.get("niche", "AI productivity & automation"),
            "title_concept": opp.get("title_concept", ""),
            "viral_hook":    opp.get("viral_hook", ""),
            "price_ceiling": float(opp.get("price_ceiling", 27)),
            "price_floor":   float(opp.get("price_floor", 9)),
            "urgency_score": int(opp.get("urgency_score", 70)),
            "why_now":       opp.get("why_now", ""),
            "target_buyer":  opp.get("target_buyer", ""),
            "pod_niche":     opp.get("pod_niche"),
            "scanned_at":    datetime.now(timezone.utc).isoformat(),
        })

    # Sort by urgency descending
    cleaned.sort(key=lambda x: x["urgency_score"], reverse=True)

    log.info(f"[ViralTrendEngine] Found {len(cleaned)} opportunities")
    return cleaned


def model_viral_product(opportunity: dict) -> dict:
    """
    Deep-dive into one opportunity and model the exact product to build.

    Args:
        opportunity: Single opportunity dict from scan_viral_opportunities()

    Returns:
        Complete product model with title, pricing, copy, cover style, etc.
    """
    prompt = f"""You are NarAI's product architect. Model the exact product to build for this opportunity.

OPPORTUNITY:
{json.dumps(opportunity, indent=2)}

Design the complete product model. Be specific — this goes directly into production.

Return JSON:
{{
  "title": "exact product title (compelling, benefit-driven, under 70 chars)",
  "subtitle": "one-line value proposition",
  "format": "{opportunity.get('format', 'digital')}",
  "product_type": "{opportunity.get('product_type', 'ai_prompt_pack')}",
  "niche": "{opportunity.get('niche', '')}",
  "price": <number between {opportunity.get('price_floor', 9)} and {opportunity.get('price_ceiling', 27)}>,
  "compare_at_price": <original price, 20-40% higher than price>,
  "value_stack": [
    "Main product: [what exactly they get]",
    "Bonus 1: [specific bonus]",
    "Bonus 2: [specific bonus]",
    "Bonus 3: [specific bonus]"
  ],
  "copy_angle": "the emotional/logical hook driving purchases (curiosity/FOMO/desire/pain)",
  "headline": "sales page headline (power statement, under 12 words)",
  "cover_style": "visual style description for the product cover image",
  "cover_palette": ["#hex1", "#hex2", "#hex3"],
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "target_buyer_pain": "the specific pain this solves in one sentence",
  "viral_hook": "{opportunity.get('viral_hook', '')}",
  "delivery_format": "PDF / Notion template / zip bundle / etc",
  "page_count_or_items": "e.g. '47 pages' or '120 prompts' or '15 templates'"
}}"""

    result = _claude_json(prompt, max_tokens=2000)

    if not isinstance(result, dict) or not result.get("title"):
        # Fallback structure
        result = {
            "title":            opportunity.get("title_concept", "AI Productivity Toolkit"),
            "subtitle":         "The complete system for AI-powered income",
            "format":           opportunity.get("format", "digital"),
            "product_type":     opportunity.get("product_type", "ai_prompt_pack"),
            "niche":            opportunity.get("niche", ""),
            "price":            float(opportunity.get("price_floor", 17)),
            "compare_at_price": float(opportunity.get("price_ceiling", 27)),
            "value_stack":      ["Main product: complete toolkit", "Bonus: quick-start guide"],
            "copy_angle":       "desire",
            "headline":         opportunity.get("viral_hook", ""),
            "cover_style":      "dark gradient with neon accent",
            "cover_palette":    ["#0f0f0f", "#7c3aed", "#ffffff"],
            "tags":             ["ai", "productivity", "digital", "tools", "2026"],
            "target_buyer_pain": opportunity.get("target_buyer", ""),
            "viral_hook":       opportunity.get("viral_hook", ""),
            "delivery_format":  "PDF",
            "page_count_or_items": "30 pages",
        }

    result["opportunity"] = opportunity
    return result


# ══════════════════════════════════════════════════════════════════════════════
# NICHE + SESSION SELECTION
# ══════════════════════════════════════════════════════════════════════════════

def select_session_opportunities(
    opportunities: List[dict],
    digital_count: int = 3,
    pod_count: int = 2,
) -> dict:
    """
    Split opportunities into digital and POD buckets for a session.

    Returns:
        {"digital": [...], "pod": [...], "service": [...], "all": [...]}
    """
    digital  = [o for o in opportunities if o.get("format") == "digital"][:digital_count]
    pod      = [o for o in opportunities if o.get("format") == "pod"][:pod_count]
    service  = [o for o in opportunities if o.get("format") == "service"][:1]
    # Fill digital quota from non-pod if needed
    if len(digital) < digital_count:
        extras = [o for o in opportunities if o not in digital and o not in pod and o not in service]
        digital += extras[: digital_count - len(digital)]

    return {
        "digital": digital,
        "pod":     pod,
        "service": service,
        "all":     opportunities,
    }


def get_dominant_niche(opportunities: List[dict]) -> str:
    """Return the most common niche across opportunities (used for funnel building)."""
    if not opportunities:
        return "AI productivity & automation"
    niche_counts: Dict[str, int] = {}
    for opp in opportunities:
        n = opp.get("niche", "")
        niche_counts[n] = niche_counts.get(n, 0) + 1
    return max(niche_counts, key=niche_counts.get)


# ══════════════════════════════════════════════════════════════════════════════
# STATE PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

def get_trending_opportunities() -> List[dict]:
    """Read cached opportunities from data/viral_trends.json."""
    try:
        if TRENDS_FILE.exists():
            data = json.loads(TRENDS_FILE.read_text())
            return data.get("opportunities", [])
    except Exception:
        pass
    return []


def save_opportunities(opportunities: List[dict], market_intel: Optional[dict] = None):
    """Persist opportunities to data/viral_trends.json."""
    try:
        payload = {
            "saved_at":     datetime.now(timezone.utc).isoformat(),
            "count":        len(opportunities),
            "opportunities": opportunities,
        }
        if market_intel:
            payload["market_snapshot"] = str(market_intel)[:500]
        TRENDS_FILE.write_text(json.dumps(payload, indent=2, default=str))
    except Exception as e:
        log.error(f"[ViralTrendEngine] Failed to save trends: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE WRAPPER
# ══════════════════════════════════════════════════════════════════════════════

def run_trend_scan(refresh: bool = False) -> List[dict]:
    """
    Full trend scan. Returns cached results unless refresh=True.
    Automatically saves results to data/viral_trends.json.
    """
    if not refresh:
        cached = get_trending_opportunities()
        if cached:
            log.info(f"[ViralTrendEngine] Using cached {len(cached)} opportunities")
            return cached

    # Pull market intelligence
    try:
        from core.market_intelligence import get_narai_briefing, get_platform_data
        briefing = get_narai_briefing()
        gumroad  = get_platform_data("gumroad") or {}
        etsy     = get_platform_data("etsy")    or {}
        market_intel = {
            "briefing": briefing[:3000],
            "gumroad":  gumroad,
            "etsy":     etsy,
        }
    except Exception as e:
        log.warning(f"[ViralTrendEngine] Market intel unavailable: {e}")
        market_intel = {}

    opportunities = scan_viral_opportunities(market_intel)
    save_opportunities(opportunities, market_intel)
    return opportunities
