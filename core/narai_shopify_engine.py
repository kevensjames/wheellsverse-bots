#!/usr/bin/env python3
"""
core/narai_shopify_engine.py
─────────────────────────────────────────────────────────────────────────────
NarAI Shopify Product Engine — Full Catalog + Boutique Builder

Product types NarAI creates and sells:
  1. ai_prompt_pack   — AI prompts (business, trading, copywriting)        $9–$29
  2. ebook            — Digital ebooks (trading, AI tools, finance)         $9–$49
  3. notion_template  — Productivity / finance Notion dashboards           $19–$49
  4. trading_tool     — Signal packs, dashboards, strategy guides          $29–$99
  5. website_template — HTML/CSS/Framer templates for SaaS, portfolios    $49–$199
  6. resume_template  — Resume, LinkedIn, portfolio kits                   $19–$49
  7. ai_starter_kit   — NarAI-lite bundles, automation kits               $49–$99
  8. subscription     — AI Stock Alerts Club ($19/month)
  9. pod              — Printful T-shirts/hoodies/posters/mugs
 10. service          — AI Automation Setup, Website Build, Resume Kit

Boutique: 3 Shopify Collections created automatically
  • "AI Tools & Templates"
  • "Trading Intelligence"
  • "Creator's Toolkit"
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger("narai_shopify_engine")

# ─── Product catalog ─────────────────────────────────────────────────────────

PRODUCT_TYPES = {
    "ai_prompt_pack": {
        "label": "AI Prompt Pack",
        "price_range": (9, 29),
        "tags": "ai-prompts, productivity, digital-download",
        "collection": "AI Tools & Templates",
        "deliver_via": "email_link",
        "description_template": (
            "Unlock the power of AI with expertly engineered prompts "
            "that get real results — instantly downloadable."
        ),
    },
    "ebook": {
        "label": "Ebook",
        "price_range": (9, 49),
        "tags": "ebook, digital-download, guide",
        "collection": "Creator's Toolkit",
        "deliver_via": "email_link",
        "description_template": "A comprehensive digital guide packed with actionable insights.",
    },
    "notion_template": {
        "label": "Notion Template",
        "price_range": (19, 49),
        "tags": "notion, template, productivity, finance",
        "collection": "AI Tools & Templates",
        "deliver_via": "email_link",
        "description_template": "Duplicate once. Stay organised forever.",
    },
    "trading_tool": {
        "label": "Trading Tool / Strategy Pack",
        "price_range": (29, 99),
        "tags": "trading, finance, strategy, signals",
        "collection": "Trading Intelligence",
        "deliver_via": "email_link",
        "description_template": (
            "Professional-grade trading intelligence: signals, frameworks, "
            "and dashboards built for consistent profits."
        ),
    },
    "website_template": {
        "label": "Website Template",
        "price_range": (49, 199),
        "tags": "website, template, saas, portfolio",
        "collection": "Creator's Toolkit",
        "deliver_via": "email_link",
        "description_template": "Ship your site in hours, not weeks.",
    },
    "resume_template": {
        "label": "Resume & Career Kit",
        "price_range": (19, 49),
        "tags": "resume, career, linkedin, template",
        "collection": "Creator's Toolkit",
        "deliver_via": "email_link",
        "description_template": "Stand out. Get hired. Built for the AI era.",
    },
    "ai_starter_kit": {
        "label": "AI Starter Kit",
        "price_range": (49, 99),
        "tags": "ai, automation, starter-kit, bundle",
        "collection": "AI Tools & Templates",
        "deliver_via": "email_link",
        "description_template": "Everything you need to launch your AI-powered workflow.",
    },
    # ── New categories (upgrade #1) ───────────────────────────────────────────
    "online_course": {
        "label": "Online Course",
        "price_range": (97, 497),
        "tags": "course, online-learning, video, education",
        "collection": "Creator's Toolkit",
        "deliver_via": "email_link",
        "description_template": "A step-by-step video course that takes you from zero to results.",
    },
    "software_license": {
        "label": "Software / App License",
        "price_range": (29, 199),
        "tags": "software, license, saas, tool, lifetime",
        "collection": "AI Tools & Templates",
        "deliver_via": "email_link",
        "description_template": "Lifetime license — buy once, use forever. No subscription required.",
    },
    "saas_template": {
        "label": "SaaS Starter Template",
        "price_range": (79, 299),
        "tags": "saas, template, code, boilerplate, nextjs",
        "collection": "Creator's Toolkit",
        "deliver_via": "email_link",
        "description_template": "Ship your SaaS in days, not months. Production-ready codebase included.",
    },
    "stock_media_pack": {
        "label": "Stock Media Pack",
        "price_range": (9, 49),
        "tags": "stock, photos, images, media, content-creation",
        "collection": "Creator's Toolkit",
        "deliver_via": "email_link",
        "description_template": "Royalty-free images, icons and graphics ready for your brand.",
    },
    "music_beat_pack": {
        "label": "Music & Beat Pack",
        "price_range": (19, 99),
        "tags": "music, beats, audio, license, content-creator",
        "collection": "Creator's Toolkit",
        "deliver_via": "email_link",
        "description_template": "Royalty-free beats and audio tracks — perfect for videos, podcasts, and ads.",
    },
    "video_preset_pack": {
        "label": "Video Preset / LUT Pack",
        "price_range": (19, 79),
        "tags": "video, presets, luts, editing, premiere, capcut",
        "collection": "Creator's Toolkit",
        "deliver_via": "email_link",
        "description_template": "Pro-grade video presets for instant cinematic looks. One-click apply.",
    },
}

POD_NICHES = {
    "entrepreneur": {
        "label": "Hustler / Entrepreneur Mindset",
        "themes": ["Build Different", "The Grind Never Stops", "Think Rich Act Rich",
                   "Discipline Over Motivation", "Stack Assets Not Excuses"],
        "colors": ["black", "navy", "charcoal"],
    },
    "hacker": {
        "label": "Programmer / Hacker Aesthetic",
        "themes": ["while(alive) { hustle(); }", "I Ship Therefore I Am",
                   "404: Sleep Not Found", "Neural Network Loading...", "sudo make money"],
        "colors": ["black", "dark green", "matrix-green"],
    },
    "dark_fantasy": {
        "label": "Anime / Dark Fantasy",
        "themes": ["Chosen by the Algorithm", "Summoned From the Digital Void",
                   "My Final Form is Profitable", "The AI Awakening Arc",
                   "Boss Level: Unlocked"],
        "colors": ["black", "deep purple", "midnight blue"],
    },
    "crypto": {
        "label": "Crypto / Web3",
        "themes": ["HODL Till I'm Rich", "Generational Wealth Loading...",
                   "I Bought the Dip", "My Portfolio is My Personality",
                   "Not Your Keys Not Your Coins"],
        "colors": ["black", "gold", "electric blue"],
    },
    "fitness_grind": {
        "label": "Fitness & Grind",
        "themes": ["Rest When You're Rich", "No Days Off", "Beast Mode: Activated",
                   "Lift Heavy Build Wealth", "Sleep is for the Weak (Mentally)"],
        "colors": ["black", "red", "charcoal"],
    },
    "mindset": {
        "label": "Mindset & Spirituality",
        "themes": ["Peace is Profit", "Manifest and Grind", "High Vibration High Income",
                   "Aligned and Paid", "God Mode Unlocked"],
        "colors": ["black", "sage green", "cream"],
    },
}

SERVICE_CATALOG = [
    {
        "title": "AI Automation Setup — Done For You",
        "tagline": "Your entire business runs on autopilot in 48 hours.",
        "price": 299,
        "what_you_get": [
            "Complete AI content calendar setup",
            "Automated posting to 5 platforms",
            "Product creation pipeline",
            "30-day support via Telegram",
        ],
        "tags": "service, ai-automation, done-for-you",
        "collection": "AI Tools & Templates",
    },
    {
        "title": "AI-Powered Website — Built For You",
        "tagline": "Professional website built with AI in 72 hours.",
        "price": 499,
        "what_you_get": [
            "Full copywriting with Claude",
            "SEO-optimised structure",
            "Product/sales pages",
            "Mobile responsive design brief",
        ],
        "tags": "service, website, custom-build",
        "collection": "Creator's Toolkit",
    },
    {
        "title": "AI Resume + LinkedIn Overhaul",
        "tagline": "Get hired faster with AI-crafted application materials.",
        "price": 49,
        "what_you_get": [
            "ATS-optimised resume (PDF + DOCX)",
            "LinkedIn headline + about section",
            "3 custom cover letter templates",
            "48-hour turnaround",
        ],
        "tags": "service, resume, career, instant",
        "collection": "Creator's Toolkit",
    },
    {
        "title": "Trading Strategy Coaching Pack",
        "tagline": "From chart-blind to consistently profitable.",
        "price": 199,
        "what_you_get": [
            "Personalised RSI + swing trading setup",
            "AI-generated watchlist",
            "Weekly signal review (4 weeks)",
            "Private Telegram access",
        ],
        "tags": "service, trading, coaching, strategy",
        "collection": "Trading Intelligence",
    },
]

BOUTIQUE_COLLECTIONS = [
    {
        "title": "AI Tools & Templates",
        "body_html": (
            "<p><strong>Supercharge your workflow with AI-powered tools.</strong> "
            "From prompt packs to automation kits — everything you need to work smarter, "
            "earn more, and build faster.</p>"
        ),
        "sort_order": "best-selling",
    },
    {
        "title": "Trading Intelligence",
        "body_html": (
            "<p><strong>Professional-grade trading tools for the modern investor.</strong> "
            "AI-powered signals, strategy packs, and dashboards built to give you an edge.</p>"
        ),
        "sort_order": "best-selling",
    },
    {
        "title": "Creator's Toolkit",
        "body_html": (
            "<p><strong>Build your brand, ship your ideas, level up your career.</strong> "
            "Notion templates, website templates, ebooks, and career kits for creators who mean business.</p>"
        ),
        "sort_order": "best-selling",
    },
    {
        "title": "Courses & Education",
        "body_html": (
            "<p><strong>Learn, implement, earn.</strong> "
            "Step-by-step courses covering AI, trading, freelancing, and digital business — "
            "built for doers who want results fast.</p>"
        ),
        "sort_order": "best-selling",
    },
    {
        "title": "Media & Creative Assets",
        "body_html": (
            "<p><strong>Premium creative assets for content creators.</strong> "
            "Stock photos, music beats, video presets — royalty-free and ready to use.</p>"
        ),
        "sort_order": "best-selling",
    },
    {
        "title": "Software & SaaS",
        "body_html": (
            "<p><strong>Tools that work while you sleep.</strong> "
            "Lifetime licenses, SaaS templates, and software bundles for builders and entrepreneurs.</p>"
        ),
        "sort_order": "best-selling",
    },
]

# ── Seasonal campaign mapping (upgrade #5) ────────────────────────────────────
import datetime as _dt

def get_seasonal_context() -> dict:
    """Return the current season/campaign context for product targeting."""
    month = _dt.datetime.now().month
    seasons = {
        1:  {"name": "New Year", "hook": "New Year New Income", "emoji": "🎯", "urgency": "Start 2026 strong"},
        2:  {"name": "Valentine's", "hook": "Gift of Knowledge", "emoji": "💝", "urgency": "Perfect gift idea"},
        3:  {"name": "Spring", "hook": "Spring Into Profit", "emoji": "🌱", "urgency": "Fresh start season"},
        4:  {"name": "Spring Sale", "hook": "Spring Cleaning Your Finances", "emoji": "💸", "urgency": "Limited time"},
        5:  {"name": "May Hustle", "hook": "Build Your Summer Income", "emoji": "☀️", "urgency": "Summer is coming"},
        6:  {"name": "Mid-Year", "hook": "Mid-Year Money Reset", "emoji": "📊", "urgency": "Half-year review"},
        7:  {"name": "Summer", "hook": "Summer Hustle Season", "emoji": "🔥", "urgency": "Peak motivation"},
        8:  {"name": "Back to Business", "hook": "Back to Business Bootcamp", "emoji": "💼", "urgency": "Q4 prep starts now"},
        9:  {"name": "Q4 Prep", "hook": "Q4 Is Where Fortunes Are Made", "emoji": "📈", "urgency": "Q4 starts in weeks"},
        10: {"name": "October Hustle", "hook": "Scary Good Deals", "emoji": "🎃", "urgency": "Limited Halloween offer"},
        11: {"name": "Black Friday", "hook": "Black Friday Wealth Bundle", "emoji": "🛍️", "urgency": "Biggest sale of the year"},
        12: {"name": "Holiday", "hook": "Gift Yourself Success", "emoji": "🎁", "urgency": "Holiday special pricing"},
    }
    return seasons.get(month, {"name": "Special", "hook": "Limited Offer", "emoji": "⚡", "urgency": "Today only"})

SUBSCRIPTION_PRODUCT = {
    "title": "AI Stock Alerts Club — $19/month",
    "body_html": (
        "<h2>Daily AI-powered stock + crypto signals</h2>"
        "<ul>"
        "<li>📈 Morning market briefing (7am EST)</li>"
        "<li>🤖 AI-generated entry/exit signals</li>"
        "<li>📊 Weekly portfolio review</li>"
        "<li>💬 Private Telegram community</li>"
        "<li>🔥 Swing trade ideas (RSI, MACD, momentum)</li>"
        "</ul>"
        "<p>Cancel any time. No contracts. Pure alpha.</p>"
    ),
    "price": 19.00,
    "tags": "subscription, trading, membership, signals",
    "collection": "Trading Intelligence",
}


# ─── Claude helper ────────────────────────────────────────────────────────────

def _claude(prompt: str, system: str = "", max_tokens: int = 4000) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
    r = client.messages.create(
        model=os.getenv("NARAI_MODEL", "claude-sonnet-4-6"),
        max_tokens=max_tokens,
        system=system or (
            "You are NarAI, autonomous revenue engine. You create polished, conversion-optimised "
            "digital products. Niche: AI + Money + Productivity. Output pure JSON when asked."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    return r.content[0].text.strip()


def _claude_json(prompt: str, max_tokens: int = 2500) -> Any:
    raw = _claude(prompt, max_tokens=max_tokens)
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


# ─── Shopify API helper ───────────────────────────────────────────────────────

def _shopify_request(method: str, endpoint: str, data: dict = None) -> dict:
    """
    Make a Shopify Admin REST API request.
    Returns the parsed JSON response or {"error": ...}.
    """
    import urllib.request
    from core.shopify_client import get_credentials
    shop, token, _ = get_credentials()
    if not shop or not token:
        return {"error": "Shopify not connected — set SHOPIFY_STORE and SHOPIFY_ACCESS_TOKEN"}

    url = f"https://{shop}/admin/api/2026-04/{endpoint}"
    payload = json.dumps(data).encode() if data else b""
    headers = {
        "X-Shopify-Access-Token": token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, data=payload if method != "GET" else None,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}: {body[:300]}"}
    except Exception as ex:
        return {"error": str(ex)}


# ─── Boutique Setup ───────────────────────────────────────────────────────────

def create_boutique_collections() -> List[dict]:
    """
    Create the 3 main collections if they don't already exist.
    Returns list of {title, id, handle}.
    """
    # Fetch existing collections
    existing = _shopify_request("GET", "custom_collections.json?limit=250")
    existing_titles = {c["title"].lower() for c in existing.get("custom_collections", [])}
    existing_map = {c["title"].lower(): c["id"] for c in existing.get("custom_collections", [])}

    results = []
    for col in BOUTIQUE_COLLECTIONS:
        title_lower = col["title"].lower()
        if title_lower in existing_titles:
            results.append({"title": col["title"], "id": existing_map[title_lower], "status": "exists"})
            continue

        resp = _shopify_request("POST", "custom_collections.json", {
            "custom_collection": {
                "title": col["title"],
                "body_html": col["body_html"],
                "sort_order": col["sort_order"],
                "published": True,
            }
        })
        created = resp.get("custom_collection", {})
        results.append({
            "title": col["title"],
            "id": created.get("id"),
            "handle": created.get("handle"),
            "status": "created",
        })
        log.info(f"[Boutique] Collection created: {col['title']}")
        time.sleep(0.5)

    return results


def _get_collection_id(title: str) -> Optional[int]:
    """Get Shopify collection ID by title."""
    resp = _shopify_request("GET", "custom_collections.json?limit=250")
    for c in resp.get("custom_collections", []):
        if c["title"].lower() == title.lower():
            return c["id"]
    return None


def _add_product_to_collection(product_id: int, collection_title: str):
    """Add a Shopify product to a named collection."""
    col_id = _get_collection_id(collection_title)
    if col_id:
        _shopify_request("POST", "collects.json", {
            "collect": {"product_id": product_id, "collection_id": col_id}
        })


def create_boutique_page() -> dict:
    """
    Create (or update) a Shopify page that acts as the main boutique landing.
    """
    page_html = """
<div style="font-family:system-ui,sans-serif;max-width:900px;margin:0 auto;padding:40px 20px">
  <h1 style="font-size:2.5rem;font-weight:900;margin-bottom:8px">WheellsVerse Store</h1>
  <p style="font-size:1.1rem;color:#555;margin-bottom:40px">
    AI-powered digital products, trading tools, and creative resources — built by NarAI.
  </p>

  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:24px;margin-bottom:48px">
    <div style="border:1px solid #e5e7eb;border-radius:12px;padding:24px">
      <div style="font-size:2rem;margin-bottom:12px">🤖</div>
      <h3 style="margin:0 0 8px">AI Tools &amp; Templates</h3>
      <p style="color:#666;font-size:0.9rem">Prompt packs, automation kits, Notion dashboards.</p>
    </div>
    <div style="border:1px solid #e5e7eb;border-radius:12px;padding:24px">
      <div style="font-size:2rem;margin-bottom:12px">📈</div>
      <h3 style="margin:0 0 8px">Trading Intelligence</h3>
      <p style="color:#666;font-size:0.9rem">AI signals, strategy packs, market tools.</p>
    </div>
    <div style="border:1px solid #e5e7eb;border-radius:12px;padding:24px">
      <div style="font-size:2rem;margin-bottom:12px">🎨</div>
      <h3 style="margin:0 0 8px">Creator's Toolkit</h3>
      <p style="color:#666;font-size:0.9rem">Ebooks, website templates, resume kits.</p>
    </div>
  </div>

  <div style="background:#0f0f0f;color:#fff;border-radius:16px;padding:32px;text-align:center;margin-bottom:48px">
    <h2 style="margin:0 0 8px;font-size:1.8rem">AI Stock Alerts Club</h2>
    <p style="color:#aaa;margin:0 0 16px">Daily AI-powered signals. Real alpha. No noise.</p>
    <span style="font-size:2.5rem;font-weight:900;color:#96bf47">$19<span style="font-size:1rem;color:#888">/month</span></span>
    <br><br>
    <a href="/products/ai-stock-alerts-club" style="background:#96bf47;color:#000;padding:12px 32px;border-radius:8px;font-weight:700;text-decoration:none">Join the Club →</a>
  </div>

  <p style="text-align:center;color:#888;font-size:0.85rem">
    All digital products delivered instantly via email. Powered by NarAI — WheellsVerse's autonomous AI engine.
  </p>
</div>
"""
    # Check if page already exists
    existing = _shopify_request("GET", "pages.json?limit=250&title=WheellsVerse+Store")
    pages = existing.get("pages", [])
    if pages:
        page_id = pages[0]["id"]
        resp = _shopify_request("PUT", f"pages/{page_id}.json", {
            "page": {"id": page_id, "body_html": page_html, "published": True}
        })
        return {"status": "updated", "handle": pages[0].get("handle")}

    resp = _shopify_request("POST", "pages.json", {
        "page": {
            "title": "WheellsVerse Store",
            "body_html": page_html,
            "published": True,
        }
    })
    page = resp.get("page", {})
    return {"status": "created", "handle": page.get("handle"), "id": page.get("id")}


# ─── Product Generators ───────────────────────────────────────────────────────

def generate_digital_product(product_type: str, trend_topic: str = "", niche: str = "") -> dict:
    """
    Use Claude to generate a complete digital product for the given type.
    Returns a product dict with all Shopify-ready fields.
    """
    ptype = PRODUCT_TYPES.get(product_type, PRODUCT_TYPES["ai_prompt_pack"])
    price_min, price_max = ptype["price_range"]
    topic = trend_topic or niche or "AI productivity"

    prompt = f"""Create a compelling Shopify digital product.

Product type: {ptype['label']}
Topic/niche: {topic}
Price range: ${price_min}–${price_max}

Return ONLY valid JSON:
{{
  "title": "product title (punchy, SEO-optimised, under 70 chars)",
  "tagline": "one-sentence hook that makes people click Buy Now",
  "price": <number in range {price_min}–{price_max}>,
  "body_html": "<p>full product description in HTML — minimum 200 words, include what's inside, benefits, who it's for, call to action</p>",
  "seo_title": "SEO title under 60 chars",
  "seo_description": "meta description under 155 chars",
  "what_you_get": ["item 1", "item 2", "item 3", "item 4", "item 5"],
  "content_outline": ["section 1 title", "section 2 title", "section 3 title"],
  "tags": "{ptype['tags']}",
  "product_type": "{ptype['label']}"
}}"""

    data = _claude_json(prompt)
    if not data or not data.get("title"):
        # Fallback
        data = {
            "title": f"{topic.title()} — {ptype['label']}",
            "tagline": f"The ultimate {ptype['label'].lower()} for {topic}.",
            "price": price_min,
            "body_html": f"<p>{ptype['description_template']} Topic: {topic}.</p>",
            "seo_title": f"{topic.title()} {ptype['label']}",
            "seo_description": f"Premium {ptype['label'].lower()} covering {topic}.",
            "what_you_get": [f"{ptype['label']} PDF/template", "Instant download", "Free updates"],
            "tags": ptype["tags"],
            "product_type": ptype["label"],
        }

    data["_product_type_key"] = product_type
    data["_collection"] = ptype["collection"]
    data["_deliver_via"] = ptype["deliver_via"]
    return data


def publish_digital_product(product_data: dict) -> dict:
    """
    Create the product on Shopify, add to collection, return result.
    Includes: cover image, trust badges, upsell tags, seasonal pricing, SEO fields.
    """
    season = get_seasonal_context()
    price_raw = float(product_data.get("price", 9))

    # ── Price A/B optimization (upgrade #9) ──────────────────────────────────
    # Nudge price to proven psychological price points
    import random
    anchors = [9, 17, 19, 27, 29, 37, 47, 49, 67, 79, 97, 127, 147, 197, 247, 297, 497]
    best = min(anchors, key=lambda x: abs(x - price_raw))
    price = str(float(best))

    title = product_data.get("title", "Digital Product")
    product_type_key = product_data.get("_product_type_key", "ai_prompt_pack")

    # ── Upsell/cross-sell tags (upgrade #6) ──────────────────────────────────
    upsell_tags = {
        "ai_prompt_pack": "upsell-starter-kit, bundle-eligible",
        "ebook":          "upsell-course, bundle-eligible",
        "notion_template":"upsell-ai-starter, bundle-eligible",
        "trading_tool":   "upsell-coaching, bundle-eligible",
        "online_course":  "upsell-coaching, premium",
        "software_license":"upsell-saas, lifetime",
        "saas_template":  "upsell-coaching, developer",
        "stock_media_pack":"upsell-video-presets, content-creator",
        "music_beat_pack": "upsell-video-presets, content-creator",
        "video_preset_pack":"upsell-media-pack, content-creator",
        "website_template":"upsell-ai-automation, developer",
        "resume_template": "upsell-coaching, career",
        "ai_starter_kit":  "upsell-coaching, bundle-eligible",
    }
    extra_tags = upsell_tags.get(product_type_key, "bundle-eligible")
    base_tags = product_data.get("tags", "digital-download")
    all_tags = f"{base_tags}, {extra_tags}, {season['name'].lower().replace(' ','-')}"

    # ── Build body HTML with trust badges + seasonal hook (upgrades #7, #5) ──
    what_you_get = product_data.get("what_you_get", [])
    wug_html = ""
    if what_you_get:
        items = "".join(f"<li>✓ {item}</li>" for item in what_you_get)
        wug_html = f"<h3>What's Included:</h3><ul>{items}</ul>"

    tagline = product_data.get("tagline", "")
    body = product_data.get("body_html", "")

    trust_badges = (
        '<div style="display:flex;gap:12px;flex-wrap:wrap;margin:16px 0">'
        '<span>🔒 Secure Checkout</span>'
        '<span>⚡ Instant Delivery</span>'
        '<span>💯 30-Day Money-Back Guarantee</span>'
        '<span>🌍 Sold Worldwide</span>'
        '</div>'
    )
    seasonal_banner = (
        f'<div style="background:#f0fdf4;border:1px solid #86efac;border-radius:8px;'
        f'padding:12px 16px;margin:12px 0">'
        f'<strong>{season["emoji"]} {season["hook"]}</strong> — {season["urgency"]}'
        f'</div>'
    ) if season["name"] != "Special" else ""

    full_body = (
        f"<p><strong>{tagline}</strong></p>\n"
        f"{seasonal_banner}\n"
        f"{body}\n"
        f"{wug_html}\n"
        f"{trust_badges}\n"
        f"<p><em>📦 Instant digital delivery via email after purchase.</em></p>"
    )

    # ── SEO keywords (upgrade #3) ──────────────────────────────────────────────
    seo_keywords = f"{product_type_key.replace('_',' ')}, digital download, wheellsverse, {season['name'].lower()}"

    payload = {
        "product": {
            "title": title,
            "body_html": full_body,
            "vendor": "WheellsVerse",
            "product_type": product_data.get("product_type", "Digital Download"),
            "tags": all_tags,
            "status": "active",
            "variants": [{
                "price": price,
                "compare_at_price": str(float(best) * 1.4),  # ← anchor price (upgrade #9)
                "requires_shipping": False,
                "taxable": True,
                "inventory_management": None,
                "fulfillment_service": "manual",
            }],
            "metafields": [
                {
                    "namespace": "seo",
                    "key": "title",
                    "value": product_data.get("seo_title", title)[:70],
                    "type": "single_line_text_field",
                },
                {
                    "namespace": "seo",
                    "key": "description",
                    "value": product_data.get("seo_description", tagline)[:160],
                    "type": "single_line_text_field",
                },
                {
                    "namespace": "custom",
                    "key": "seo_keywords",
                    "value": seo_keywords,
                    "type": "single_line_text_field",
                },
            ],
        }
    }

    resp = _shopify_request("POST", "products.json", payload)
    product = resp.get("product", {})
    if not product.get("id"):
        return {"success": False, "error": resp.get("error", "Unknown error")}

    product_id = product["id"]
    handle = product.get("handle", "")

    # ── Cover image via cover_engine (upgrade #2) ─────────────────────────────
    cover_url = None
    try:
        from core.cover_engine import generate_cover
        cover_prompts = product_data.get(
            "cover_prompts",
            [f"professional product cover for {title}, digital product, clean design"]
        )
        cover_result = generate_cover(cover_prompts, "shopify", title, product_type_key)
        if cover_result.get("success") and cover_result.get("url"):
            cover_url = cover_result["url"]
            _shopify_request("POST", f"products/{product_id}/images.json", {
                "image": {"src": cover_url, "alt": title}
            })
    except Exception as e:
        log.warning(f"[ShopifyEngine] Cover image skipped: {e}")

    # ── Add to collection ──────────────────────────────────────────────────────
    collection = product_data.get("_collection", "AI Tools & Templates")
    _add_product_to_collection(product_id, collection)

    log.info(f"[ShopifyEngine] Published: {title} → /products/{handle}")
    return {
        "success": True,
        "product_id": product_id,
        "handle": handle,
        "title": title,
        "price": float(price),
        "compare_at_price": float(best) * 1.4,
        "url": f"/products/{handle}",
        "collection": collection,
        "cover_url": cover_url,
        "tags": all_tags,
        "season": season["name"],
    }


def publish_service_product(service: dict) -> dict:
    """Publish a service package as a Shopify product."""
    what_you_get = service.get("what_you_get", [])
    wug_html = ""
    if what_you_get:
        items = "".join(f"<li>✓ {item}</li>" for item in what_you_get)
        wug_html = f"<h3>What You Get:</h3><ul>{items}</ul>"

    tagline = service.get("tagline", "")
    body_html = f"<p><strong>{tagline}</strong></p>\n{wug_html}\n<p><em>📩 We'll be in touch within 24 hours to get started.</em></p>"

    payload = {
        "product": {
            "title": service["title"],
            "body_html": body_html,
            "vendor": "WheellsVerse",
            "product_type": "Service",
            "tags": service.get("tags", "service"),
            "status": "active",
            "variants": [{
                "price": str(float(service["price"])),
                "requires_shipping": False,
                "taxable": True,
                "inventory_management": None,
            }],
        }
    }

    resp = _shopify_request("POST", "products.json", payload)
    product = resp.get("product", {})
    if not product.get("id"):
        return {"success": False, "error": resp.get("error", "Unknown")}

    product_id = product["id"]
    collection = service.get("collection", "AI Tools & Templates")
    _add_product_to_collection(product_id, collection)

    return {
        "success": True,
        "product_id": product_id,
        "handle": product.get("handle", ""),
        "title": service["title"],
        "price": float(service["price"]),
        "type": "service",
        "collection": collection,
    }


def publish_subscription_product() -> dict:
    """Create the $19/month AI Stock Alerts Club on Shopify."""
    sp = SUBSCRIPTION_PRODUCT

    payload = {
        "product": {
            "title": sp["title"],
            "body_html": sp["body_html"],
            "vendor": "WheellsVerse",
            "product_type": "Subscription",
            "tags": sp["tags"],
            "status": "active",
            "variants": [{
                "price": str(sp["price"]),
                "requires_shipping": False,
                "taxable": True,
                "inventory_management": None,
                "fulfillment_service": "manual",
            }],
        }
    }

    resp = _shopify_request("POST", "products.json", payload)
    product = resp.get("product", {})
    if not product.get("id"):
        # Check if already exists
        existing_check = _shopify_request("GET", "products.json?title=AI+Stock+Alerts+Club&limit=5")
        existing = existing_check.get("products", [])
        if existing:
            return {
                "success": True,
                "product_id": existing[0]["id"],
                "title": sp["title"],
                "price": sp["price"],
                "type": "subscription",
                "status": "already_exists",
            }
        return {"success": False, "error": resp.get("error", "Unknown")}

    product_id = product["id"]
    _add_product_to_collection(product_id, sp["collection"])

    return {
        "success": True,
        "product_id": product_id,
        "handle": product.get("handle", ""),
        "title": sp["title"],
        "price": sp["price"],
        "type": "subscription",
    }


def generate_pod_product(niche_key: str, product_type: str = "tshirt") -> dict:
    """
    Use Claude to generate POD product details for the given niche.
    product_type: tshirt | hoodie | phone_case | poster | journal | mug
    """
    niche = POD_NICHES.get(niche_key, POD_NICHES["entrepreneur"])
    theme = niche["themes"][int(time.time()) % len(niche["themes"])]

    label_map = {
        "tshirt": "T-Shirt", "hoodie": "Hoodie", "phone_case": "Phone Case",
        "poster": "Poster", "journal": "Notebook/Journal", "mug": "Mug",
    }
    product_label = label_map.get(product_type, "T-Shirt")

    price_map = {
        "tshirt": 35, "hoodie": 55, "phone_case": 25,
        "poster": 22, "journal": 28, "mug": 20,
    }
    price = price_map.get(product_type, 35)

    prompt = f"""Create a Shopify POD product listing.

Product: {product_label}
Niche: {niche['label']}
Design theme: "{theme}"

Return ONLY valid JSON:
{{
  "title": "product title with theme, under 70 chars",
  "tagline": "one-sentence hook",
  "body_html": "<p>full description in HTML about this {product_label} and what it represents</p>",
  "design_text": "{theme}",
  "design_concept": "brief description for the designer/AI image tool",
  "tags": "pod, {niche_key}, apparel, print-on-demand",
  "price": {price}
}}"""

    data = _claude_json(prompt)
    if not data:
        data = {
            "title": f"{theme} — {product_label}",
            "tagline": f"Wear your mindset. {theme}.",
            "body_html": f"<p>Premium quality {product_label}. {niche['label']} design. {theme}.</p>",
            "design_text": theme,
            "design_concept": f"{niche['label']} aesthetic, {theme}, bold typography",
            "tags": f"pod, {niche_key}, {product_type}",
            "price": price,
        }

    data["_niche_key"] = niche_key
    data["_product_type"] = product_type
    data["_price"] = price
    return data


def publish_pod_via_printful(pod_data: dict) -> dict:
    """
    Create POD product on Printful and sync to Shopify.
    Falls back to creating directly on Shopify if Printful not connected.
    """
    try:
        from core.printful_client import is_connected, create_pod_product, sync_to_shopify
        if is_connected():
            result = create_pod_product(
                title=pod_data.get("title", "POD Product"),
                description=pod_data.get("body_html", ""),
                niche=pod_data.get("_niche_key", "entrepreneur"),
                product_type=pod_data.get("_product_type", "tshirt"),
                design_image_path=None,
                price=pod_data.get("_price", 35),
            )
            if result.get("success"):
                shopify_result = sync_to_shopify(result, description=pod_data.get("body_html", ""),
                                                 tags=pod_data.get("tags", "pod"))
                return {
                    "success": True,
                    "product_id": shopify_result.get("shopify_product_id"),
                    "title": pod_data["title"],
                    "price": pod_data["_price"],
                    "type": "pod",
                    "source": "printful",
                }
    except Exception as e:
        log.warning(f"[ShopifyEngine] Printful error: {e} — publishing POD directly to Shopify")

    # Fallback: publish directly to Shopify as a product with POD note
    body = pod_data.get("body_html", "") + (
        "<p><em>🖨️ Printed and shipped on demand. Allow 5-7 business days for delivery.</em></p>"
    )
    payload = {
        "product": {
            "title": pod_data.get("title", "POD Product"),
            "body_html": body,
            "vendor": "WheellsVerse",
            "product_type": "Apparel",
            "tags": pod_data.get("tags", "pod"),
            "status": "active",
            "variants": [
                {"price": str(pod_data.get("_price", 35)), "option1": "S", "requires_shipping": True},
                {"price": str(pod_data.get("_price", 35)), "option1": "M", "requires_shipping": True},
                {"price": str(pod_data.get("_price", 35)), "option1": "L", "requires_shipping": True},
                {"price": str(pod_data.get("_price", 35)), "option1": "XL", "requires_shipping": True},
            ],
            "options": [{"name": "Size", "values": ["S", "M", "L", "XL"]}],
        }
    }

    resp = _shopify_request("POST", "products.json", payload)
    product = resp.get("product", {})
    if not product.get("id"):
        return {"success": False, "error": resp.get("error", "Unknown")}

    product_id = product["id"]
    _add_product_to_collection(product_id, "Creator's Toolkit")
    return {
        "success": True,
        "product_id": product_id,
        "handle": product.get("handle", ""),
        "title": pod_data.get("title"),
        "price": pod_data.get("_price", 35),
        "type": "pod",
        "source": "shopify_direct",
    }


# ─── Full Session Runner ──────────────────────────────────────────────────────

def run_full_shopify_session(
    trend_topics: List[str] = None,
    log_fn=None,
) -> dict:
    """
    Run a complete NarAI Shopify session:
    1. Create boutique collections + page
    2. Publish digital products (2 per type rotation)
    3. Publish POD products (1 per niche)
    4. Ensure subscription product exists
    5. Ensure service products exist
    Returns summary dict.
    """
    _log = log_fn or (lambda m: log.info(f"[ShopifySession] {m}"))
    results = {
        "session_id": str(uuid.uuid4())[:8],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "boutique": {},
        "digital": [],
        "pod": [],
        "services": [],
        "subscription": {},
        "total_published": 0,
        "total_revenue": 0.0,
        "errors": [],
    }

    from core.shopify_client import is_connected
    if not is_connected():
        results["errors"].append("Shopify not connected — set SHOPIFY_STORE + SHOPIFY_ACCESS_TOKEN in Railway env")
        _log("❌ Shopify not connected — see env setup below")
        return results

    # ── Step 1: Boutique setup ────────────────────────────────────────────────
    _log("🏪 Setting up boutique collections…")
    try:
        cols = create_boutique_collections()
        page = create_boutique_page()
        results["boutique"] = {"collections": cols, "page": page}
        _log(f"✅ Boutique: {len(cols)} collections, page {page.get('status', '?')}")
    except Exception as e:
        results["errors"].append(f"Boutique setup: {e}")
        _log(f"⚠️ Boutique setup failed: {e}")

    # ── Step 2: Digital products (rotate through types) ──────────────────────
    topics = trend_topics or ["AI productivity", "stock trading", "freelancing", "crypto"]
    digital_types_rotation = [
        "ai_prompt_pack", "notion_template", "trading_tool",
        "ebook", "resume_template", "ai_starter_kit", "website_template",
    ]

    products_target = int(os.getenv("SHOPIFY_PRODUCTS_PER_SESSION", "3"))
    for i in range(products_target):
        ptype = digital_types_rotation[i % len(digital_types_rotation)]
        topic = topics[i % len(topics)]
        _log(f"📦 Creating digital product {i + 1}/{products_target}: {ptype} — {topic}")
        try:
            data = generate_digital_product(ptype, trend_topic=topic)
            result = publish_digital_product(data)
            if result.get("success"):
                results["digital"].append(result)
                results["total_published"] += 1
                results["total_revenue"] += result.get("price", 0)
                _log(f"✅ Published: {result['title']} (${result['price']}) → {result['url']}")
            else:
                err = f"Digital {ptype}: {result.get('error', 'unknown')}"
                results["errors"].append(err)
                _log(f"⚠️ {err}")
        except Exception as e:
            results["errors"].append(f"Digital {ptype} exception: {e}")
            _log(f"❌ Digital {ptype} exception: {e}")
        time.sleep(1)

    # ── Step 3: POD products ─────────────────────────────────────────────────
    pod_target = int(os.getenv("SHOPIFY_POD_PER_SESSION", "2"))
    pod_types = ["tshirt", "hoodie", "poster", "journal", "phone_case", "mug"]
    niche_keys = list(POD_NICHES.keys())

    for i in range(pod_target):
        niche_key = niche_keys[i % len(niche_keys)]
        product_type = pod_types[i % len(pod_types)]
        _log(f"🎨 Creating POD product {i + 1}/{pod_target}: {niche_key} {product_type}")
        try:
            pod_data = generate_pod_product(niche_key, product_type)
            result = publish_pod_via_printful(pod_data)
            if result.get("success"):
                results["pod"].append(result)
                results["total_published"] += 1
                results["total_revenue"] += result.get("price", 0)
                _log(f"✅ POD published: {result['title']} (${result['price']})")
            else:
                err = f"POD {niche_key}: {result.get('error', 'unknown')}"
                results["errors"].append(err)
                _log(f"⚠️ {err}")
        except Exception as e:
            results["errors"].append(f"POD exception: {e}")
            _log(f"❌ POD exception: {e}")
        time.sleep(1)

    # ── Step 4: Subscription ─────────────────────────────────────────────────
    _log("💳 Ensuring subscription product exists…")
    try:
        sub_result = publish_subscription_product()
        results["subscription"] = sub_result
        if sub_result.get("success"):
            _log(f"✅ Subscription: {sub_result.get('title')} ({sub_result.get('status', 'created')})")
    except Exception as e:
        results["errors"].append(f"Subscription: {e}")
        _log(f"⚠️ Subscription error: {e}")

    # ── Step 5: Service products ─────────────────────────────────────────────
    _log("🛠️ Ensuring service products exist…")
    existing_products = _shopify_request("GET", "products.json?product_type=Service&limit=50")
    existing_service_titles = {p["title"].lower() for p in existing_products.get("products", [])}

    for service in SERVICE_CATALOG:
        if service["title"].lower() in existing_service_titles:
            _log(f"   ↳ Service exists: {service['title']}")
            continue
        try:
            result = publish_service_product(service)
            if result.get("success"):
                results["services"].append(result)
                _log(f"✅ Service published: {service['title']} (${service['price']})")
            else:
                results["errors"].append(f"Service {service['title']}: {result.get('error')}")
        except Exception as e:
            results["errors"].append(f"Service exception: {e}")
        time.sleep(0.5)

    results["completed_at"] = datetime.now(timezone.utc).isoformat()
    _log(f"🏁 Session complete — {results['total_published']} products published, "
         f"${results['total_revenue']:.0f} potential revenue")
    return results


def get_store_stats() -> dict:
    """Fetch live product/revenue stats from Shopify."""
    from core.shopify_client import get_credentials, is_connected
    shop, token, _ = get_credentials()

    if not is_connected():
        return {
            "connected": False,
            "error": "Shopify not connected — set SHOPIFY_STORE and SHOPIFY_ACCESS_TOKEN in Railway",
            "total_products": 0, "total_orders": 0, "total_revenue": 0,
            "total_revenue_today": 0, "product_types": {}, "products": [],
            "orders": [], "store_domain": shop or "",
        }

    products = _shopify_request("GET", "products.json?limit=250&status=active")
    orders = _shopify_request("GET", "orders.json?limit=50&status=any&financial_status=paid")

    # Surface API errors instead of silently returning zeros
    if "error" in products:
        return {
            "connected": False,
            "error": f"Shopify API error: {products['error']}",
            "total_products": 0, "total_orders": 0, "total_revenue": 0,
            "total_revenue_today": 0, "product_types": {}, "products": [],
            "orders": [], "store_domain": shop,
        }

    product_list = products.get("products", [])
    order_list = orders.get("orders", [])

    total_revenue = sum(float(o.get("total_price", 0)) for o in order_list)
    product_types = {}
    for p in product_list:
        pt = p.get("product_type", "Other")
        product_types[pt] = product_types.get(pt, 0) + 1

    return {
        "connected": True,
        "store_domain": shop,
        "total_products": len(product_list),
        "total_orders": len(order_list),
        "total_revenue": round(total_revenue, 2),
        "total_revenue_today": round(total_revenue, 2),
        "product_types": product_types,
        "products": [
            {"id": p["id"], "title": p["title"], "handle": p.get("handle"),
             "variants": p.get("variants", []),
             "images": p.get("images", []),
             "product_type": p.get("product_type", ""), "status": p.get("status"),
             "created_at": p.get("created_at", "")}
            for p in product_list[:20]
        ],
        "orders": [
            {"id": o["id"], "order_number": o.get("order_number"),
             "total_price": o.get("total_price"),
             "email": o.get("email", "guest"),
             "created_at": o.get("created_at", "")}
            for o in order_list[:10]
        ],
    }
