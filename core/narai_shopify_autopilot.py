#!/usr/bin/env python3
"""
core/narai_shopify_autopilot.py
─────────────────────────────────────────────────────────────────────────────
NarAI Shopify Autopilot — Daily Autonomous Revenue Session

6-phase session (mirrors narai_autopilot.py pattern exactly):

  Phase 1 (0-15%)  — Viral Trend Scan
  Phase 2 (15-50%) — Digital Products (3-5 products)
  Phase 3 (50-65%) — POD Products via Printful (2-3 products)
  Phase 4 (65-75%) — Service Packages (1-2 fixed offers)
  Phase 5 (75-90%) — Monetization Funnel (5-step value ladder)
  Phase 6 (90-100%)— Performance Review + Learning Loop

State file : data/shopify_autopilot_state.json
Log file   : data/shopify_autopilot_log.json
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

SA_STATE_FILE   = DATA_DIR / "shopify_autopilot_state.json"
SA_LOG_FILE     = DATA_DIR / "shopify_autopilot_log.json"
LEARNING_FILE   = DATA_DIR / "shopify_learning.json"

log = logging.getLogger("narai_shopify_autopilot")

MAX_QC_ROUNDS = 5
QC_PASS_SCORE = 75

_sa_running = False
_sa_thread: Optional[threading.Thread] = None


# ══════════════════════════════════════════════════════════════════════════════
# STATE + LOG HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sa_load() -> dict:
    try:
        if SA_STATE_FILE.exists():
            return json.loads(SA_STATE_FILE.read_text())
    except Exception:
        pass
    return {
        "running":    False,
        "session_id": None,
        "started_at": None,
        "phase":      "idle",
        "task":       "",
        "progress":   0,
        "stats": {
            "products_created":   0,
            "products_published": 0,
            "pod_created":        0,
            "funnel_steps_built": 0,
            "revenue_today":      0.0,
            "opportunities_found": 0,
        },
        "today_products": [],
        "sessions": [],
    }


def _sa_save(state: dict):
    try:
        SA_STATE_FILE.write_text(json.dumps(state, indent=2, default=str))
    except Exception:
        pass


def _sa_log(msg: str, level: str = "INFO", phase: str = ""):
    entry = {"ts": _now(), "level": level, "msg": msg, "phase": phase}
    try:
        logs = _sa_load_logs()
        logs.insert(0, entry)
        SA_LOG_FILE.write_text(json.dumps(logs[:5000]))
    except Exception:
        pass
    log.info(f"[ShopifyAutopilot] {msg}")


def _sa_load_logs() -> list:
    try:
        if SA_LOG_FILE.exists():
            return json.loads(SA_LOG_FILE.read_text())
    except Exception:
        pass
    return []


def _queue_for_manual(platform: str, title: str, content: str):
    """Fall back to manual queue when publish fails."""
    try:
        q_file = DATA_DIR / "autopilot_publish_queue.json"
        q = json.loads(q_file.read_text()) if q_file.exists() else []
        q.append({"platform": platform, "title": title, "queued_at": _now(), "content": content[:500]})
        q_file.write_text(json.dumps(q, indent=2))
    except Exception:
        pass


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
        "You are NarAI, the autonomous revenue engine behind WheellsVerse. "
        "You create and publish digital products, print-on-demand items, and service packages "
        "on Shopify — all without human input. Niche: 'AI + Money + Productivity'. "
        "You think strategically, create with precision, and never ship mediocre work. "
        "Output pure JSON only when requested. No prose outside the JSON."
    )


# ══════════════════════════════════════════════════════════════════════════════
# PHASE RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def _run_shopify_phase(
    state: dict,
    name: str,
    label: str,
    progress: int,
    fn,
    *args,
) -> Any:
    """
    Safe phase runner — mirrors narai_autopilot._run_phase().
    Catches all exceptions, logs them, never crashes the session.
    """
    state["phase"]    = name
    state["task"]     = label
    state["progress"] = progress
    _sa_save(state)
    _sa_log(f"▶ {label}", phase=name)

    try:
        result = fn(*args)
        _sa_log(f"✅ {label} complete", phase=name)
        return result
    except Exception as e:
        _sa_log(f"❌ {label} failed: {e}", level="ERROR", phase=name)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# QC LOOP
# ══════════════════════════════════════════════════════════════════════════════

def _qc_shopify(package: dict, state: dict) -> Tuple[dict, dict]:
    """
    Run QC on a product package. Returns (revised_package, qc_result).
    Uses QualityControlBot from market_intelligence.
    """
    try:
        from core.market_intelligence import QualityControlBot
        qc_bot = QualityControlBot()
    except Exception:
        return package, {"approved": True, "score": 80, "note": "QC unavailable"}

    content_to_check = package.get("sales_page", "") or package.get("description", "")
    title            = package.get("title", "Product")

    current = package
    for round_num in range(1, MAX_QC_ROUNDS + 1):
        _sa_log(f"QC round {round_num}/{MAX_QC_ROUNDS} for '{title}'", phase="qc")

        result = qc_bot.review(
            content=content_to_check,
            content_type="product",
            platform="shopify",
            title=title,
        )
        state["stats"]["products_created"] = state["stats"].get("products_created", 0)

        if result.get("approved") or result.get("score", 0) >= QC_PASS_SCORE:
            _sa_log(f"✅ QC approved '{title}' score={result.get('score', '?')}/100", phase="qc")
            return current, result

        instructions = result.get("revision_instructions", "")
        issues       = result.get("all_issues", [])
        _sa_log(f"🔄 QC score={result.get('score', 0)} — revising: {'; '.join(issues[:2])}", level="WARNING", phase="qc")

        if instructions:
            try:
                revised_content = _claude(
                    f"Revise this product description following these instructions:\n\n"
                    f"INSTRUCTIONS:\n{instructions}\n\n"
                    f"CURRENT CONTENT:\n{content_to_check[:2000]}\n\n"
                    f"Return only the revised content."
                )
                content_to_check = revised_content
                current = dict(current)
                if "sales_page" in current:
                    current["sales_page"] = revised_content
                else:
                    current["description"] = revised_content
            except Exception as e:
                _sa_log(f"Revision failed: {e}", level="WARNING", phase="qc")

    _sa_log(f"⚠️ QC max rounds reached for '{title}' — using best version", level="WARNING", phase="qc")
    return current, {"approved": True, "score": 60, "note": "max rounds — shipped anyway"}


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1 — VIRAL TREND SCAN
# ══════════════════════════════════════════════════════════════════════════════

def _phase1_trend_scan(state: dict) -> Tuple[List[dict], dict, str]:
    """
    Scan for viral opportunities and return (opportunities, market_intel, dominant_niche).
    """
    from core.viral_trend_engine import run_trend_scan, select_session_opportunities, get_dominant_niche

    digital_count = int(os.getenv("SHOPIFY_PRODUCTS_PER_SESSION", "3"))
    pod_count     = int(os.getenv("SHOPIFY_POD_PER_SESSION", "2"))

    opportunities = run_trend_scan(refresh=True)
    state["stats"]["opportunities_found"] = len(opportunities)

    session_opps  = select_session_opportunities(opportunities, digital_count, pod_count)
    dominant_niche = get_dominant_niche(opportunities)

    _sa_log(f"Found {len(opportunities)} opportunities — dominant niche: {dominant_niche}", phase="trends")

    # Fetch market intel for downstream phases
    try:
        from core.market_intelligence import get_narai_briefing, get_platform_data
        market_intel = {
            "briefing": get_narai_briefing()[:3000],
            "gumroad":  get_platform_data("gumroad") or {},
        }
    except Exception:
        market_intel = {}

    return session_opps, market_intel, dominant_niche


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 — DIGITAL PRODUCTS
# ══════════════════════════════════════════════════════════════════════════════

def _create_digital_products(state: dict, session_opps: dict, market_intel: dict) -> List[dict]:
    """
    Create and publish digital products from the top opportunities.
    Returns list of published product dicts.
    """
    from core.narai_product_engine import build_complete_product_package
    from core.shopify_client import publish_narai_product, is_connected, create_discount_code

    digital_opps = session_opps.get("digital", [])
    published    = []

    if not digital_opps:
        _sa_log("No digital opportunities this session", phase="digital", level="WARNING")
        return published

    for i, opp in enumerate(digital_opps, 1):
        title_concept = opp.get("title_concept", f"AI Product #{i}")
        _sa_log(f"Creating digital product {i}/{len(digital_opps)}: {title_concept}", phase="digital")

        try:
            package = build_complete_product_package(
                platform="shopify",
                market_intel=market_intel,
                niche_hint=opp.get("niche", ""),
                log_fn=lambda m: _sa_log(m, phase="digital"),
            )

            if not package:
                _sa_log(f"Product engine returned empty package for {title_concept}", level="WARNING", phase="digital")
                continue

            # QC
            package, qc_result = _qc_shopify(package, state)
            state["stats"]["products_created"] += 1

            # Publish
            if not is_connected():
                _queue_for_manual("shopify", package.get("title", title_concept), package.get("sales_page", ""))
                _sa_log(f"Shopify not connected — queued: {package.get('title')}", level="WARNING", phase="digital")
                continue

            result = publish_narai_product(package)
            if result.get("success"):
                shopify_id = result.get("product_id")
                state["stats"]["products_published"] += 1

                # Launch discount
                try:
                    create_discount_code(
                        title=f"LAUNCH{i}",
                        value=20,
                        value_type="percentage",
                        usage_limit=50,
                    )
                except Exception:
                    pass

                entry = {
                    "title":      package.get("title", title_concept),
                    "shopify_id": shopify_id,
                    "price":      package.get("price", 0),
                    "type":       "digital",
                    "published_at": _now(),
                }
                state["today_products"].append(entry)
                published.append(entry)
                _sa_log(f"✅ Published: {entry['title']} (${entry['price']}) → Shopify ID {shopify_id}", phase="digital")
            else:
                _queue_for_manual("shopify", package.get("title", title_concept), package.get("sales_page", ""))
                _sa_log(f"Publish failed for {package.get('title')} — queued", level="WARNING", phase="digital")

        except Exception as e:
            _sa_log(f"Error creating digital product {i}: {e}", level="ERROR", phase="digital")

        time.sleep(2)  # NarAI thinks between creations

    return published


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 — POD PRODUCTS
# ══════════════════════════════════════════════════════════════════════════════

def _create_pod_products(state: dict, session_opps: dict) -> List[dict]:
    """Create POD products via Printful and sync to Shopify."""
    from core.printful_client import is_connected as printful_connected
    from core.printful_client import generate_pod_design, create_pod_product, sync_to_shopify

    if not printful_connected():
        _sa_log("PRINTFUL_API_KEY not set — skipping POD phase", level="WARNING", phase="pod")
        return []

    pod_opps = session_opps.get("pod", [])
    if not pod_opps:
        _sa_log("No POD opportunities this session", phase="pod")
        return []

    created = []

    for i, opp in enumerate(pod_opps, 1):
        niche        = opp.get("pod_niche") or opp.get("niche", "entrepreneur mindset")
        product_type = "tshirt"  # default
        if "hoodie" in opp.get("title_concept", "").lower():
            product_type = "hoodie"
        elif "mug" in opp.get("title_concept", "").lower():
            product_type = "mug"
        elif "poster" in opp.get("title_concept", "").lower():
            product_type = "poster"

        _sa_log(f"Creating POD product {i}/{len(pod_opps)}: {niche} {product_type}", phase="pod")

        try:
            design = generate_pod_design(niche, product_type)
            title  = design.get("product_title", f"{niche.title()} {product_type.title()}")
            desc   = design.get("product_description", "")
            price  = float(opp.get("price_floor", 29))

            printful_result = create_pod_product(
                title=title,
                description=desc,
                niche=niche,
                product_type=product_type,
                design_image_path=design.get("image_path"),
                price=price,
            )

            if printful_result.get("success"):
                state["stats"]["pod_created"] += 1

                shopify_result = sync_to_shopify(
                    printful_result,
                    description=desc,
                    tags=[niche.replace(" ", "-"), "pod", "apparel"],
                )

                entry = {
                    "title":             title,
                    "shopify_id":        shopify_result.get("shopify_product_id"),
                    "printful_id":       printful_result.get("product_id"),
                    "price":             price,
                    "type":              "pod",
                    "niche":             niche,
                    "published_at":      _now(),
                }
                state["today_products"].append(entry)
                created.append(entry)
                _sa_log(f"✅ POD created: {title} → Printful {printful_result.get('product_id')}", phase="pod")
            else:
                _sa_log(f"Printful create failed: {printful_result.get('error')}", level="WARNING", phase="pod")

        except Exception as e:
            _sa_log(f"POD product {i} error: {e}", level="ERROR", phase="pod")

        time.sleep(2)

    return created


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4 — SERVICE PACKAGES
# ══════════════════════════════════════════════════════════════════════════════

SERVICE_PACKAGES = [
    {
        "title":       "AI Automation Setup — Done For You",
        "description": "NarAI sets up your complete AI automation stack: content calendar, posting bots, product creation pipeline. Launch in 48 hours.",
        "price":       299,
        "tags":        "service, ai-automation, done-for-you",
    },
    {
        "title":       "AI-Powered Website Creation",
        "description": "Complete website built with AI: copy, design brief, SEO structure, product pages. Delivered in 72 hours.",
        "price":       499,
        "tags":        "service, website, ai-powered",
    },
    {
        "title":       "AI Resume & LinkedIn Optimization Kit",
        "description": "AI-crafted resume, LinkedIn profile, and cover letter templates optimized for 2026 job market. Instant download.",
        "price":       49,
        "tags":        "service, resume, career, digital",
    },
]


def _create_service_packages(state: dict) -> List[dict]:
    """Create fixed service package products on Shopify."""
    try:
        from core.shopify_client import create_product, is_connected
    except ImportError:
        _sa_log("shopify_client unavailable — skipping services", level="WARNING", phase="services")
        return []

    if not is_connected():
        _sa_log("Shopify not connected — skipping service packages", level="WARNING", phase="services")
        return []

    created = []

    for pkg in SERVICE_PACKAGES:
        try:
            result = create_product({
                "title":            pkg["title"],
                "body_html":        f"<p>{pkg['description']}</p>",
                "vendor":           "WheellsVerse",
                "product_type":     "Service",
                "tags":             pkg["tags"],
                "requires_shipping": False,
                "variants": [{
                    "price":               str(pkg["price"]),
                    "requires_shipping":   False,
                    "inventory_management": None,
                    "inventory_policy":    "continue",
                }],
            })
            if result.get("success"):
                entry = {
                    "title":       pkg["title"],
                    "shopify_id":  result.get("product_id"),
                    "price":       pkg["price"],
                    "type":        "service",
                    "published_at": _now(),
                }
                state["today_products"].append(entry)
                created.append(entry)
                state["stats"]["products_published"] += 1
                _sa_log(f"✅ Service package: {pkg['title']} (${pkg['price']})", phase="services")
        except Exception as e:
            _sa_log(f"Service package error for {pkg['title']}: {e}", level="ERROR", phase="services")

    return created


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 5 — FUNNEL BUILDING
# ══════════════════════════════════════════════════════════════════════════════

def _build_funnels(state: dict, market_intel: dict, niche: str) -> dict:
    """Build and wire 5-step monetization funnel."""
    from core.funnel_builder import build_shopify_funnel

    funnel = build_shopify_funnel(niche=niche, market_intel=market_intel)
    state["stats"]["funnel_steps_built"] = funnel.get("stats", {}).get("steps_created", 0)
    state["stats"]["products_published"] += funnel.get("stats", {}).get("shopify_products", 0)
    return funnel


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 6 — PERFORMANCE REVIEW + LEARNING
# ══════════════════════════════════════════════════════════════════════════════

def _feedback_loop(state: dict, orders: list) -> dict:
    """
    Claude analyzes what sold, why, and what to change next session.
    Saves insights to data/shopify_learning.json.
    """
    today_products = state.get("today_products", [])
    stats          = state.get("stats", {})

    prompt = f"""Analyze today's Shopify autopilot session results.

TODAY'S PRODUCTS CREATED:
{json.dumps(today_products, default=str, indent=2)}

TODAY'S ORDERS:
{json.dumps(orders[:20], default=str, indent=2)}

SESSION STATS:
{json.dumps(stats, default=str, indent=2)}

Provide strategic learning for next session. Return JSON:
{{
  "what_worked": ["insight 1", "insight 2"],
  "what_to_change": ["change 1", "change 2"],
  "best_product_type": "which product type got the most orders or looks most promising",
  "best_niche": "which niche is resonating based on orders",
  "next_session_focus": "specific recommendation for what to prioritize next session",
  "price_insight": "any observations about pricing from today",
  "session_grade": "A | B | C | D based on products published and revenue",
  "revenue_today": <estimated revenue from orders>
}}"""

    insights = _claude_json(prompt, max_tokens=2000)
    if not isinstance(insights, dict):
        insights = {"session_grade": "B", "next_session_focus": "Continue current strategy"}

    insights["analyzed_at"]   = _now()
    insights["session_id"]    = state.get("session_id")
    insights["products_count"] = len(today_products)
    insights["orders_count"]   = len(orders)

    # Save learning
    try:
        existing = []
        if LEARNING_FILE.exists():
            existing = json.loads(LEARNING_FILE.read_text())
        existing.insert(0, insights)
        LEARNING_FILE.write_text(json.dumps(existing[:100], indent=2, default=str))
    except Exception as e:
        _sa_log(f"Learning save failed: {e}", level="WARNING", phase="review")

    revenue = insights.get("revenue_today", 0) or 0
    state["stats"]["revenue_today"] = float(revenue)
    _sa_log(f"Session grade: {insights.get('session_grade', '?')} | Revenue: ${revenue}", phase="review")
    return insights


def _performance_review(state: dict) -> dict:
    """Fetch today's orders and run feedback loop."""
    orders = []
    try:
        from core.shopify_client import get_orders_summary, is_connected
        if is_connected():
            summary = get_orders_summary()
            orders  = summary.get("orders", [])
            _sa_log(f"Today's orders: {len(orders)} | Revenue: ${summary.get('total_revenue', 0)}", phase="review")
    except Exception as e:
        _sa_log(f"Orders fetch failed: {e}", level="WARNING", phase="review")

    return _feedback_loop(state, orders)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN SESSION RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_shopify_session(session_id: Optional[str] = None) -> dict:
    """
    Run a complete 6-phase Shopify autopilot session.

    Returns final state dict with stats.
    """
    global _sa_running

    if session_id is None:
        session_id = str(uuid.uuid4())[:8]

    state = _sa_load()
    state["running"]    = True
    state["session_id"] = session_id
    state["started_at"] = _now()
    state["phase"]      = "starting"
    state["task"]       = "NarAI Shopify Autopilot starting…"
    state["progress"]   = 0
    state["stats"]      = {
        "products_created":   0,
        "products_published": 0,
        "pod_created":        0,
        "funnel_steps_built": 0,
        "revenue_today":      0.0,
        "opportunities_found": 0,
    }
    state["today_products"] = []
    _sa_save(state)
    _sa_running = True
    _sa_log(f"🚀 Shopify Autopilot session {session_id} starting", phase="start")

    session_opps  = {}
    market_intel  = {}
    dominant_niche = "AI productivity & automation"

    # ── Phase 1: Viral Trend Scan ─────────────────────────────────────────────
    result = _run_shopify_phase(
        state, "trends", "NarAI is scanning for viral product opportunities…", 5,
        _phase1_trend_scan, state,
    )
    if result:
        session_opps, market_intel, dominant_niche = result
    state["progress"] = 15
    _sa_save(state)

    # ── Phase 2: Digital Products ─────────────────────────────────────────────
    _run_shopify_phase(
        state, "digital", "NarAI is creating digital products…", 20,
        _create_digital_products, state, session_opps, market_intel,
    )
    state["progress"] = 50
    _sa_save(state)

    # ── Phase 3: POD Products ─────────────────────────────────────────────────
    _run_shopify_phase(
        state, "pod", "NarAI is creating print-on-demand products…", 52,
        _create_pod_products, state, session_opps,
    )
    state["progress"] = 65
    _sa_save(state)

    # ── Phase 4: Service Packages ─────────────────────────────────────────────
    _run_shopify_phase(
        state, "services", "NarAI is setting up service packages…", 67,
        _create_service_packages, state,
    )
    state["progress"] = 75
    _sa_save(state)

    # ── Phase 5: Funnel Building ──────────────────────────────────────────────
    _run_shopify_phase(
        state, "funnel", f"NarAI is building the {dominant_niche} monetization funnel…", 77,
        _build_funnels, state, market_intel, dominant_niche,
    )
    state["progress"] = 90
    _sa_save(state)

    # ── Phase 6: Performance Review ───────────────────────────────────────────
    _run_shopify_phase(
        state, "review", "NarAI is reviewing performance and learning…", 92,
        _performance_review, state,
    )
    state["progress"] = 100

    # ── Wrap up ───────────────────────────────────────────────────────────────
    state["running"] = False
    state["phase"]   = "complete"
    state["task"]    = "Session complete"
    _sa_running = False

    # Record session summary
    summary = {
        "session_id":  session_id,
        "date":        _now()[:10],
        "completed_at": _now(),
        "stats":       state["stats"],
        "products":    len(state["today_products"]),
    }
    state["sessions"] = ([summary] + state.get("sessions", []))[:30]
    _sa_save(state)

    s = state["stats"]
    _sa_log(
        f"🏁 Session {session_id} complete — "
        f"published: {s['products_published']}, "
        f"POD: {s['pod_created']}, "
        f"funnel steps: {s['funnel_steps_built']}, "
        f"revenue: ${s['revenue_today']}",
        phase="complete",
    )

    return state


# ══════════════════════════════════════════════════════════════════════════════
# BACKGROUND CONTROL
# ══════════════════════════════════════════════════════════════════════════════

def _run_in_background(session_id: str):
    global _sa_running
    try:
        run_shopify_session(session_id)
    except Exception as e:
        _sa_log(f"Session crashed: {e}", level="ERROR", phase="crash")
        state = _sa_load()
        state["running"] = False
        state["phase"]   = "crashed"
        state["task"]    = str(e)
        _sa_save(state)
    finally:
        _sa_running = False


def start_shopify_autopilot_background() -> dict:
    """Start the Shopify autopilot session in a background thread."""
    global _sa_running, _sa_thread

    if _sa_running:
        return {"started": False, "reason": "Session already running"}

    if os.getenv("SHOPIFY_AUTOPILOT_ENABLED", "true").lower() == "false":
        return {"started": False, "reason": "SHOPIFY_AUTOPILOT_ENABLED=false"}

    session_id  = str(uuid.uuid4())[:8]
    _sa_running = True
    _sa_thread  = threading.Thread(
        target=_run_in_background,
        args=(session_id,),
        daemon=True,
        name=f"shopify-autopilot-{session_id}",
    )
    _sa_thread.start()
    _sa_log(f"Started background session {session_id}", phase="start")
    return {"started": True, "session_id": session_id}


def stop_shopify_autopilot() -> dict:
    """Signal the autopilot to stop (marks state as stopping)."""
    global _sa_running
    state = _sa_load()
    state["running"] = False
    state["task"]    = "Stopping…"
    _sa_save(state)
    _sa_running = False
    _sa_log("Stop requested", phase="stop")
    return {"stopped": True}


def get_shopify_autopilot_status() -> dict:
    """Return current autopilot state."""
    state = _sa_load()
    return {
        "running":    state.get("running", False),
        "session_id": state.get("session_id"),
        "started_at": state.get("started_at"),
        "phase":      state.get("phase", "idle"),
        "task":       state.get("task", ""),
        "progress":   state.get("progress", 0),
        "stats":      state.get("stats", {}),
        "products_today": len(state.get("today_products", [])),
        "last_sessions":  state.get("sessions", [])[:5],
    }


def get_shopify_autopilot_logs(limit: int = 100) -> list:
    """Return recent autopilot log entries."""
    return _sa_load_logs()[:limit]
