#!/usr/bin/env python3
"""
core/store_intelligence.py
─────────────────────────────────────────────────────────────────────────────
WheellsVerse Store Intelligence Engine

Continuously analyses the live Shopify store to:
  1. Identify what's selling fast vs dead stock
  2. Spot gaps — profitable niches with zero products
  3. Score each opportunity by market velocity + seasonal demand
  4. Auto-generate and publish the highest-potential products
  5. (Optionally) auto-generate covers/3D/video for every published product

Designed to run on a schedule or be triggered on-demand from the dashboard.
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger("store_intelligence")

# ── State file ────────────────────────────────────────────────────────────────
_INTEL_FILE = ROOT / "data" / "store_intelligence.json"
_INTEL_FILE.parent.mkdir(parents=True, exist_ok=True)

# ── Niche velocity catalogue ──────────────────────────────────────────────────
# Each entry: a market niche with proven demand, matching product_type keys,
# typical price range, and a velocity score (1–10).
NICHE_CATALOGUE: list[dict] = [
    {
        "niche": "AI & Automation",
        "types": ["ai_prompt_pack", "ai_starter_kit", "software_license"],
        "topics": [
            "ChatGPT business automation",
            "AI content creation system",
            "No-code AI workflow builder",
            "Claude prompt mastery",
            "AI agent toolkit",
        ],
        "price": (17, 97),
        "velocity": 9,
        "collection": "AI Tools & Templates",
    },
    {
        "niche": "Creator Economy",
        "types": ["stock_media_pack", "music_beat_pack", "video_preset_pack"],
        "topics": [
            "YouTube thumbnail pack",
            "TikTok viral template pack",
            "Instagram reel preset bundle",
            "Podcast intro music pack",
            "Short-form video LUT pack",
        ],
        "price": (17, 67),
        "velocity": 8,
        "collection": "Media & Creative Assets",
    },
    {
        "niche": "Online Education",
        "types": ["online_course", "ebook", "notion_template"],
        "topics": [
            "Make money with AI in 30 days",
            "Trading for beginners complete guide",
            "Passive income blueprint 2025",
            "Freelancing to $10k/month",
            "Digital product empire masterclass",
        ],
        "price": (27, 197),
        "velocity": 8,
        "collection": "Courses & Education",
    },
    {
        "niche": "Developer Tools & SaaS",
        "types": ["saas_template", "software_license", "website_template"],
        "topics": [
            "Next.js SaaS boilerplate",
            "FastAPI AI backend starter",
            "React dashboard UI kit",
            "Stripe subscription SaaS template",
            "Full-stack TypeScript starter",
        ],
        "price": (47, 497),
        "velocity": 7,
        "collection": "Software & SaaS",
    },
    {
        "niche": "Finance & Trading",
        "types": ["trading_tool", "ebook"],
        "topics": [
            "AI stock signal pack",
            "Crypto RSI strategy guide",
            "Options trading for beginners",
            "DCA automation calculator",
            "Multi-timeframe trading system",
        ],
        "price": (29, 127),
        "velocity": 9,
        "collection": "Trading Intelligence",
    },
    {
        "niche": "Career & Professional Growth",
        "types": ["resume_template", "online_course"],
        "topics": [
            "ATS-optimised resume 2025",
            "LinkedIn profile overhaul kit",
            "Six-figure job hunt system",
            "Freelancer client acquisition guide",
            "Salary negotiation mastery",
        ],
        "price": (19, 97),
        "velocity": 7,
        "collection": "AI Tools & Templates",
    },
    {
        "niche": "Productivity & Notion",
        "types": ["notion_template", "ai_starter_kit"],
        "topics": [
            "Ultimate Notion life OS",
            "Notion AI productivity dashboard",
            "Second brain Notion system",
            "Freelancer CRM Notion template",
            "Goal tracker Notion dashboard",
        ],
        "price": (17, 49),
        "velocity": 7,
        "collection": "AI Tools & Templates",
    },
    {
        "niche": "Print-On-Demand",
        "types": ["pod"],
        "topics": [
            "crypto grind",
            "fitness mindset",
            "entrepreneur hustle",
            "AI revolution",
            "silent millionaire",
        ],
        "price": (19, 39),
        "velocity": 6,
        "collection": "Creator's Toolkit",
    },
]


# ─── Store data fetcher ────────────────────────────────────────────────────────

def _fetch_store_data() -> tuple[list, list]:
    """Return (products, orders) from Shopify. Each is a list of dicts."""
    from core.shopify_client import _api

    products_resp = _api("GET", "products.json?limit=250&status=active")
    products = products_resp.get("products", [])

    orders_resp = _api("GET", "orders.json?limit=250&status=paid&fields=id,line_items,total_price,created_at,customer")
    orders = orders_resp.get("orders", [])

    return products, orders


# ─── Core analysis ────────────────────────────────────────────────────────────

def analyze_store() -> dict:
    """
    Pull live Shopify data and compute:
      - Total revenue / orders
      - Revenue + units per category / niche
      - Category gaps (niches in NICHE_CATALOGUE with zero products)
      - Dead stock (active products with 0 orders in last 30 days)
      - Top 10 best sellers
      - Niche velocity scores adjusted by real performance

    Returns full analysis dict (also cached to data/store_intelligence.json).
    """
    log.info("[StoreIntel] Starting store analysis…")
    try:
        products, orders = _fetch_store_data()
    except Exception as e:
        log.error(f"[StoreIntel] Failed to fetch store data: {e}")
        return {"error": str(e), "analyzed_at": _now()}

    # ── Revenue per product ──────────────────────────────────────────────────
    product_perf: dict[str, dict] = {}   # product_id → {revenue, units, title}
    total_revenue = 0.0

    for order in orders:
        for item in order.get("line_items", []):
            pid   = str(item.get("product_id") or "")
            price = float(item.get("price") or 0)
            qty   = int(item.get("quantity") or 1)
            rev   = price * qty
            total_revenue += rev
            if pid not in product_perf:
                product_perf[pid] = {"revenue": 0.0, "units": 0, "title": item.get("title", "")}
            product_perf[pid]["revenue"] += rev
            product_perf[pid]["units"]   += qty

    # ── Category breakdown ────────────────────────────────────────────────────
    category_stats: dict[str, dict] = {}

    for p in products:
        ptype = (p.get("product_type") or "Other").strip() or "Other"
        pid   = str(p.get("id") or "")
        perf  = product_perf.get(pid, {"revenue": 0.0, "units": 0})

        if ptype not in category_stats:
            category_stats[ptype] = {
                "revenue": 0.0, "units": 0, "product_count": 0, "products": []
            }
        category_stats[ptype]["revenue"]       += perf["revenue"]
        category_stats[ptype]["units"]         += perf["units"]
        category_stats[ptype]["product_count"] += 1
        category_stats[ptype]["products"].append({
            "id":      pid,
            "title":   p.get("title"),
            "revenue": round(perf["revenue"], 2),
            "units":   perf["units"],
            "status":  p.get("status"),
        })

    # ── Niche gaps (zero products in a fast-moving niche) ────────────────────
    existing_product_types = set(
        (p.get("product_type") or "").lower().replace(" ", "_")
        for p in products
    )
    category_gaps = []
    for niche in NICHE_CATALOGUE:
        has_any = any(t in existing_product_types for t in niche["types"])
        if not has_any:
            category_gaps.append(niche)

    # ── Dead stock (active, 0 sales) ─────────────────────────────────────────
    dead_stock = [
        {"id": p.get("id"), "title": p.get("title"), "type": p.get("product_type")}
        for p in products
        if str(p.get("id") or "") not in product_perf
    ]

    # ── Top 10 best sellers ───────────────────────────────────────────────────
    top_products = sorted(
        [{"id": pid, **stats} for pid, stats in product_perf.items()],
        key=lambda x: x["revenue"],
        reverse=True,
    )[:10]

    analysis = {
        "total_products":  len(products),
        "total_orders":    len(orders),
        "total_revenue":   round(total_revenue, 2),
        "category_stats":  category_stats,
        "category_gaps":   category_gaps,
        "dead_stock":      dead_stock[:20],
        "top_products":    top_products,
        "analyzed_at":     _now(),
    }

    # Cache to disk
    try:
        _INTEL_FILE.write_text(json.dumps(analysis, indent=2, default=str))
    except Exception:
        pass

    log.info(
        f"[StoreIntel] Analysis done — {len(products)} products, "
        f"{len(orders)} orders, ${total_revenue:.2f} revenue, "
        f"{len(category_gaps)} gaps"
    )
    return analysis


def get_cached_analysis() -> Optional[dict]:
    """Return the last cached store analysis, or None if not available."""
    try:
        if _INTEL_FILE.exists():
            return json.loads(_INTEL_FILE.read_text())
    except Exception:
        pass
    return None


# ─── Opportunity scoring ──────────────────────────────────────────────────────

def score_opportunities(analysis: dict) -> list[dict]:
    """
    Rank product creation opportunities by:
      1. Niche velocity (market demand baseline)
      2. Gap bonus  (+3 if zero products in this niche)
      3. Proven demand bonus (+1 for every 5 units sold in same niche)
      4. Seasonal boost (from get_seasonal_context)
      5. Expansion signal (+1 if niche has revenue but < 3 products)

    Returns top-10 opportunities sorted by composite score descending.
    """
    from core.narai_shopify_engine import get_seasonal_context   # type: ignore
    season = get_seasonal_context()
    season_name = season.get("name", "").lower().replace(" ", "_")

    opportunities: list[dict] = []
    cat_stats = analysis.get("category_stats", {})

    for niche in NICHE_CATALOGUE:
        score = niche["velocity"]

        # Gap bonus: no products at all in this niche
        gap_match = any(
            ng["niche"] == niche["niche"]
            for ng in analysis.get("category_gaps", [])
        )
        if gap_match:
            score += 3
            priority = "HIGH"
            reason   = f"Zero products in fast niche '{niche['niche']}' — immediate gap"
        else:
            priority = "MEDIUM"
            reason   = f"Expand '{niche['niche']}' with more products"

        # Proven demand bonus
        niche_units = sum(
            cat_stats.get(t, {}).get("units", 0)
            for t in niche["types"]
        )
        score += min(niche_units // 5, 3)  # cap at +3

        # Expansion bonus
        niche_products = sum(
            cat_stats.get(t, {}).get("product_count", 0)
            for t in niche["types"]
        )
        if niche_units > 0 and niche_products < 3:
            score += 1
            reason += f" — {niche_units} units sold, only {niche_products} products"

        # Seasonal boost for Finance/Trading in Q1, Creator in Q4, etc.
        seasonal_boost = {
            "Finance & Trading":       ["q1", "new_year", "tax_season"],
            "Online Education":        ["q1", "back_to_school", "new_year"],
            "Creator Economy":         ["q4", "summer", "holiday"],
            "AI & Automation":         ["q1", "q3"],
            "Developer Tools & SaaS":  ["q1", "q3"],
        }
        if season_name in [s.lower() for s in seasonal_boost.get(niche["niche"], [])]:
            score += 1

        opportunities.append({
            "priority":     priority,
            "score":        score,
            "niche":        niche["niche"],
            "reason":       reason,
            "product_types": niche["types"],
            "topics":       niche["topics"],
            "price_range":  niche["price"],
            "collection":   niche["collection"],
            "action":       "create" if gap_match else "expand",
        })

    opportunities.sort(key=lambda x: x["score"], reverse=True)
    return opportunities[:10]


# ─── Product spec generator ───────────────────────────────────────────────────

def generate_fast_seller_specs(opportunities: list[dict], n_products: int = 5) -> list[dict]:
    """
    Build publish-ready product_data dicts from the top-scored opportunities.
    These are passed directly to publish_digital_product() or publish_pod_via_printful().
    """
    from core.narai_shopify_engine import (   # type: ignore
        PRODUCT_TYPES, generate_digital_product, generate_pod_product,
    )

    specs: list[dict] = []
    used_topics: set[str] = set()

    for opp in opportunities:
        if len(specs) >= n_products:
            break

        for ptype in opp["product_types"]:
            if len(specs) >= n_products:
                break
            if ptype not in PRODUCT_TYPES and ptype != "pod":
                continue

            # Pick an unused topic for variety
            available = [t for t in opp["topics"] if t not in used_topics]
            if not available:
                available = opp["topics"]
            topic = random.choice(available)
            used_topics.add(topic)

            try:
                if ptype == "pod":
                    data = generate_pod_product(
                        niche_key=random.choice(["crypto", "fitness_grind", "mindset", "entrepreneur"]),
                        product_type=random.choice(["tshirt", "hoodie", "mug"]),
                    )
                else:
                    data = generate_digital_product(ptype, trend_topic=topic)

                data["_opportunity_score"] = opp["score"]
                data["_niche"]             = opp["niche"]
                data["_priority"]          = opp["priority"]
                data["_collection"]        = opp.get("collection", data.get("_collection", "AI Tools & Templates"))
                specs.append(data)
                log.info(f"[StoreIntel] Spec: {ptype} / '{topic}' (score={opp['score']})")
            except Exception as e:
                log.warning(f"[StoreIntel] Failed to build spec for {ptype}/{topic}: {e}")

    return specs


# ─── Full intelligence autopilot ──────────────────────────────────────────────

def run_intelligence_autopilot(
    n_products: int = 5,
    media_mode: bool = False,
    log_fn=None,
) -> dict:
    """
    Full intelligence cycle:
      1. Analyse the live store
      2. Score opportunities
      3. Generate product specs for the top opportunities
      4. Publish each product to Shopify
      5. (media_mode=True) Generate covers + 3D + video and upload

    Returns a summary dict suitable for the dashboard.
    """
    from core.narai_shopify_engine import (   # type: ignore
        publish_digital_product, publish_pod_via_printful,
    )
    from core.shopify_client import is_connected

    _log = log_fn or (lambda m: log.info(f"[StoreIntel] {m}"))

    _log("🧠 Store Intelligence: analysing live store…")
    analysis = analyze_store()
    if "error" in analysis:
        return {"success": False, "error": analysis["error"]}

    _log(
        f"📊 Analysis: {analysis['total_products']} products, "
        f"{analysis['total_orders']} orders, ${analysis['total_revenue']:.2f} revenue, "
        f"{len(analysis['category_gaps'])} niche gaps"
    )

    opportunities = score_opportunities(analysis)
    _log(f"🎯 {len(opportunities)} opportunities ranked — top: {opportunities[0]['niche'] if opportunities else 'none'}")

    specs = generate_fast_seller_specs(opportunities, n_products)
    _log(f"📦 {len(specs)} product specs ready to publish")

    published: list[dict] = []
    errors:    list[dict] = []

    for i, spec in enumerate(specs):
        _log(f"🚀 Publishing {i+1}/{len(specs)}: {spec.get('title', '?')} [{spec.get('_niche', '?')}]")
        try:
            ptype = spec.get("_product_type_key", "")
            if ptype == "pod":
                result = publish_pod_via_printful(spec)
            else:
                result = publish_digital_product(spec)

            if result.get("success"):
                result["niche"]    = spec.get("_niche")
                result["priority"] = spec.get("_priority")
                result["score"]    = spec.get("_opportunity_score")
                published.append(result)
                _log(f"✅ Published: {result.get('title')} @ ${result.get('price')}")

                # ── Optional media generation ────────────────────────────────
                if media_mode and result.get("product_id"):
                    _log(f"🎨 Generating media pack for {result.get('title')}…")
                    try:
                        from core.media_engine import generate_and_upload   # type: ignore
                        media_result = generate_and_upload(result["product_id"], spec)
                        result["media"] = media_result
                        _log(
                            f"🖼 Media: {media_result['uploaded_images']} images, "
                            f"{media_result['uploaded_videos']} videos"
                        )
                    except Exception as me:
                        _log(f"⚠️ Media error: {me}")
                        result["media_error"] = str(me)
            else:
                err = {"spec": spec.get("title", "?"), "error": result.get("error", "unknown")}
                errors.append(err)
                _log(f"⚠️ Failed: {err['spec']} — {err['error']}")

        except Exception as e:
            errors.append({"spec": spec.get("title", "?"), "error": str(e)})
            _log(f"❌ Exception publishing {spec.get('title', '?')}: {e}")

        time.sleep(1)

    summary = {
        "success": True,
        "mode": "intelligence" + ("+media" if media_mode else ""),
        "analysis": {
            "total_products": analysis["total_products"],
            "total_revenue":  analysis["total_revenue"],
            "gaps_found":     len(analysis["category_gaps"]),
            "top_niche":      opportunities[0]["niche"] if opportunities else "—",
        },
        "opportunities": len(opportunities),
        "specs_built":   len(specs),
        "published":     len(published),
        "products":      published,
        "errors":        errors,
        "completed_at":  _now(),
    }
    _log(f"🏁 Intelligence autopilot complete — {len(published)} published, {len(errors)} errors")
    return summary


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
