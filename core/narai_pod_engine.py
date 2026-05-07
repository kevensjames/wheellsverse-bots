#!/usr/bin/env python3
"""
core/narai_pod_engine.py
─────────────────────────────────────────────────────────────────────────────
NarAI Autonomous POD Engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Narai is an autonomous AI product engine. She connects to Printify + Shopify,
generates viral product concepts, creates masterpiece designs with DALL-E 3,
builds fully-detailed Printify products, and publishes them to Shopify with
every single field filled — SEO, metafields, variants, images, descriptions.

She never repeats a product. She creates masterpieces. She never stops.

Env vars required:
  PRINTIFY_API_KEY   — Printify Bearer token
  SHOPIFY_STORE      — e.g. 7tiy1y-wd.myshopify.com
  SHOPIFY_TOKEN      — Shopify Admin API token
  OPENAI_API_KEY     — for DALL-E 3 image generation
  ANTHROPIC_API_KEY  — for concept + copy generation (fallback)
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger("narai_pod_engine")

PRINTIFY_BASE = "https://api.printify.com/v1"
MEMORY_FILE   = ROOT / "data" / "narai_pod_memory.json"

# ── Blueprint registry (Printify stable IDs) ──────────────────────────────────
# Format: {slug: {"blueprint_id": int, "type": str, "label": str,
#                  "primary_provider": int, "price_range": (min, max)}}
BLUEPRINT_REGISTRY: Dict[str, Dict] = {
    "tshirt":        {"blueprint_id": 6,   "type": "T-Shirt",      "label": "Unisex Softstyle T-Shirt",       "primary_provider": 99, "price_range": (2499, 3499)},
    "hoodie":        {"blueprint_id": 92,  "type": "Hoodie",       "label": "Unisex Heavy Blend Hoodie",      "primary_provider": 99, "price_range": (4499, 5999)},
    "mug":           {"blueprint_id": 45,  "type": "Mug",          "label": "White Glossy Mug",               "primary_provider": 27, "price_range": (1999, 2499)},
    "poster":        {"blueprint_id": 32,  "type": "Poster",       "label": "Enhanced Matte Paper Poster",    "primary_provider": 1,  "price_range": (1999, 2999)},
    "tote_bag":      {"blueprint_id": 38,  "type": "Tote Bag",     "label": "Heavy Cotton Tote Bag",          "primary_provider": 29, "price_range": (1999, 2499)},
    "sweatshirt":    {"blueprint_id": 380, "type": "Sweatshirt",   "label": "Unisex Crew Neck Sweatshirt",    "primary_provider": 99, "price_range": (3499, 4499)},
    "sticker":       {"blueprint_id": 358, "type": "Sticker",      "label": "Kiss-Cut Sticker Sheet",         "primary_provider": 1,  "price_range": (599,  1299)},
    "canvas":        {"blueprint_id": 66,  "type": "Canvas Print", "label": "Museum-Quality Canvas Print",   "primary_provider": 1,  "price_range": (3999, 5999)},
    "notebook":      {"blueprint_id": 490, "type": "Notebook",     "label": "Spiral Notebook",                "primary_provider": 1,  "price_range": (1499, 1999)},
    "tank_top":      {"blueprint_id": 64,  "type": "Tank Top",     "label": "Unisex Jersey Tank Top",         "primary_provider": 99, "price_range": (1999, 2799)},
    "phone_case":    {"blueprint_id": 52,  "type": "Phone Case",   "label": "Tough Phone Case",               "primary_provider": 1,  "price_range": (2299, 2999)},
    "hat":           {"blueprint_id": 112, "type": "Hat",          "label": "Classic Dad Hat",                "primary_provider": 1,  "price_range": (2499, 3499)},
    "pillow_case":   {"blueprint_id": 156, "type": "Pillow Case",  "label": "Throw Pillow Case",              "primary_provider": 1,  "price_range": (1999, 2999)},
    "blanket":       {"blueprint_id": 247, "type": "Blanket",      "label": "Sherpa Fleece Blanket",          "primary_provider": 1,  "price_range": (4999, 6999)},
    "baby_onesie":   {"blueprint_id": 149, "type": "Baby Onesie",  "label": "Baby Short Sleeve Onesie",       "primary_provider": 99, "price_range": (1899, 2499)},
}

# Rotation order — used to cycle through product types
PRODUCT_ROTATION = [
    "tshirt", "hoodie", "mug", "poster", "tote_bag",
    "sweatshirt", "sticker", "canvas", "notebook", "tank_top",
    "phone_case", "hat", "pillow_case", "blanket", "baby_onesie",
]

# Viral niche pool — rotated + combined for infinite variety
NICHES = [
    "entrepreneur mindset", "hacker / programmer", "dark fantasy", "anime aesthetic",
    "astrology / zodiac", "fitness motivation", "retro gaming", "pet lovers (dogs)",
    "pet lovers (cats)", "travel wanderlust", "vintage Americana", "streetwear culture",
    "spiritual awakening", "dark humor", "family love", "plant parent",
    "coffee culture", "mental health awareness", "feminism / girl power", "dad jokes",
    "nurse / medical", "teacher life", "military / veteran", "mountain / outdoor",
    "beach vibes", "gothic aesthetic", "kawaii / cute", "music lover",
    "book lover / reading", "gym / bodybuilder", "yoga / wellness", "vegan / plant-based",
    "true crime fan", "horror fan", "space / cosmos", "dinosaur lover",
    "car / racing culture", "skateboarding", "tattoo culture", "cottagecore",
]

# Design styles
DESIGN_STYLES = [
    "bold minimal typography", "vintage illustration with distressed texture",
    "neon retro 80s", "Japanese woodblock art style", "watercolor illustration",
    "geometric abstract", "photorealistic mockup", "hand-drawn cartoon",
    "glitch art / cyberpunk", "Art Deco luxury", "maximalist surrealism",
    "pastel kawaii", "dark moody oil painting style", "pixel art / 8-bit",
    "high contrast black and white graphic", "stained glass illustration",
    "botanical line art", "grunge streetwear graphic",
]


# ══════════════════════════════════════════════════════════════════════════════
# MEMORY  — prevents product duplication
# ══════════════════════════════════════════════════════════════════════════════

def _load_memory() -> List[dict]:
    try:
        if MEMORY_FILE.exists():
            return json.loads(MEMORY_FILE.read_text())
    except Exception:
        pass
    return []


def _save_memory(memory: List[dict]) -> None:
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEMORY_FILE.write_text(json.dumps(memory, indent=2))


def _memory_summary(memory: List[dict]) -> str:
    """Compact summary of past products for the AI prompt."""
    if not memory:
        return "No products created yet."
    lines = []
    for m in memory[-50:]:  # last 50
        lines.append(f"- [{m.get('product_type','')}] \"{m.get('title','')}\" | niche: {m.get('niche','')} | style: {m.get('design_style','')}")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# PRINTIFY HTTP CLIENT
# ══════════════════════════════════════════════════════════════════════════════

def _printify(method: str, endpoint: str, body: Optional[dict] = None) -> Any:
    """Printify REST client with retry."""
    api_key = os.getenv("PRINTIFY_API_KEY", "")
    if not api_key:
        raise RuntimeError("PRINTIFY_API_KEY not set")

    url  = f"{PRINTIFY_BASE}/{endpoint.lstrip('/')}"
    data = json.dumps(body).encode() if body else None

    for attempt in range(3):
        req = urllib.request.Request(
            url, data=data, method=method.upper(),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                err = json.loads(raw)
            except Exception:
                err = {"raw": raw.decode(errors="replace")}
            if e.code == 429 or e.code >= 500:
                wait = 2 ** attempt
                log.warning(f"[Printify] {e.code} on {endpoint} — retry {attempt+1}/3 in {wait}s")
                time.sleep(wait)
                continue
            log.error(f"[Printify] HTTP {e.code} {endpoint}: {err}")
            return {"error": True, "code": e.code, "detail": err}
        except Exception as e:
            log.error(f"[Printify] {endpoint}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)
            else:
                return {"error": True, "detail": str(e)}

    return {"error": True, "detail": "Max retries exceeded"}


# ══════════════════════════════════════════════════════════════════════════════
# SHOPIFY HTTP CLIENT
# ══════════════════════════════════════════════════════════════════════════════

def _shopify(method: str, endpoint: str, body: Optional[dict] = None) -> dict:
    """Shopify Admin REST client."""
    store = os.getenv("SHOPIFY_STORE", "").strip().rstrip("/").replace("https://", "")
    token = os.getenv("SHOPIFY_TOKEN", "") or os.getenv("SHOPIFY_ACCESS_TOKEN", "")
    if not store or not token:
        return {"error": True, "detail": "SHOPIFY_STORE or SHOPIFY_TOKEN not set"}

    url  = f"https://{store}/admin/api/2024-01/{endpoint.lstrip('/')}"
    data = json.dumps(body).encode() if body else None

    req = urllib.request.Request(
        url, data=data, method=method.upper(),
        headers={
            "X-Shopify-Access-Token": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            err = json.loads(raw)
        except Exception:
            err = {"raw": raw.decode(errors="replace")}
        log.error(f"[Shopify] HTTP {e.code} {endpoint}: {err}")
        return {"error": True, "code": e.code, "detail": err}
    except Exception as e:
        log.error(f"[Shopify] {endpoint}: {e}")
        return {"error": True, "detail": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# AI HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _ai_json(prompt: str, system: str = "", max_tokens: int = 2500) -> Any:
    """
    Call OpenAI GPT-4o (primary) or Claude (fallback). Returns parsed JSON.
    """
    # Try OpenAI first
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if openai_key:
        try:
            from core.llm_client import safe_openai_call
            msgs = []
            if system:
                msgs.append({"role": "system", "content": system})
            msgs.append({"role": "user", "content": prompt})
            resp = safe_openai_call(
                messages=msgs,
                model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
                api_key=openai_key,
                bot_name="narai_pod_engine.json",
            )
            return json.loads(resp.choices[0].message.content)
        except Exception as e:
            log.warning(f"[NarAI] OpenAI JSON call failed: {e}, trying Claude...")

    # Claude fallback
    try:
        from core.claude_logged import create as _claude_create
        full_prompt = prompt if not system else f"{system}\n\n{prompt}"
        resp = _claude_create(
            model="claude-haiku-4-5-20251001",
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": full_prompt + "\n\nOutput pure JSON only."}],
            bot_name="narai_pod_engine",
        )
        raw = resp.content[0].text.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.MULTILINE)
        raw = re.sub(r"```\s*$", "", raw, flags=re.MULTILINE)
        return json.loads(raw.strip())
    except Exception as e:
        log.error(f"[NarAI] Claude JSON call failed: {e}")
        return {}


def _dalle(prompt: str) -> Optional[str]:
    """
    Generate an image with DALL-E 3. Returns a public image URL or None.
    Uses square 1024x1024 format (best for POD designs).
    """
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        return None

    body = json.dumps({
        "model": "dall-e-3",
        "prompt": prompt[:4000],
        "size": "1024x1024",
        "quality": "hd",
        "style": "vivid",
        "n": 1,
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/images/generations",
        data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode())
            url = data["data"][0]["url"]
            log.info("[NarAI] DALL-E 3 ✅ image generated")
            return url
    except Exception as e:
        log.warning(f"[NarAI] DALL-E 3 failed: {e}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — CONNECT & LOAD CATALOG
# ══════════════════════════════════════════════════════════════════════════════

def connect_and_verify() -> Tuple[bool, str]:
    """Verify Printify connection. Returns (ok, shop_id)."""
    resp = _printify("GET", "/shops.json")
    if isinstance(resp, dict) and resp.get("error"):
        return False, ""
    shops = resp if isinstance(resp, list) else []
    if not shops:
        return False, ""

    shopify_store = os.getenv("SHOPIFY_STORE", "").lower().replace("https://", "").rstrip("/")
    shop_id = None
    for shop in shops:
        title = (shop.get("title") or "").lower()
        sales_channel = (shop.get("sales_channel") or "").lower()
        if shopify_store and (shopify_store in sales_channel or shopify_store in title):
            shop_id = str(shop["id"])
            break
    if not shop_id:
        shop_id = str(shops[0]["id"])

    log.info(f"✅ Narai is connected to Printify. Shop ID: {shop_id}. Ready to create.")
    return True, shop_id


_catalog_cache: Dict[Tuple[int, int], dict] = {}  # (blueprint_id, provider_id) → {variants}


def _load_variants_for_blueprint(blueprint_id: int, provider_id: int) -> List[dict]:
    """Fetch + cache variants for a blueprint/provider pair."""
    cache_key = (blueprint_id, provider_id)
    if cache_key in _catalog_cache:
        return _catalog_cache[cache_key].get("variants", [])

    resp = _printify("GET", f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json")
    if isinstance(resp, dict) and resp.get("error"):
        return []

    variants = resp.get("variants", []) if isinstance(resp, dict) else []
    # Filter to only enabled/available variants
    variants = [v for v in variants if v.get("is_available", True)]

    _catalog_cache[cache_key] = {"variants": variants}
    return variants


def _get_print_areas(blueprint_id: int) -> List[str]:
    """Return available print area positions for a blueprint."""
    # We get this from the first blueprint variants response if it includes placeholders
    # Otherwise use sensible defaults per product type
    defaults = {
        6:   ["front", "back"],           # T-shirt
        92:  ["front", "back"],           # Hoodie
        45:  ["front"],                   # Mug (wraps)
        32:  ["front"],                   # Poster
        38:  ["front"],                   # Tote bag
        380: ["front", "back"],           # Sweatshirt
        358: ["front"],                   # Sticker
        66:  ["front"],                   # Canvas
        490: ["front"],                   # Notebook
        64:  ["front", "back"],           # Tank top
        52:  ["front", "back"],           # Phone case
        112: ["front"],                   # Hat
        156: ["front", "back"],           # Pillow case
        247: ["front", "back"],           # Blanket
        149: ["front", "back"],           # Baby onesie
    }
    return defaults.get(blueprint_id, ["front"])


# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — CONCEPT GENERATION (Narai's creative mind)
# ══════════════════════════════════════════════════════════════════════════════

def generate_concept(
    product_type_slug: str,
    memory: List[dict],
    used_niches: List[str] = None,
) -> dict:
    """
    Generate a unique, viral product concept that has never been created before.

    Returns:
    {
      title, niche, design_style, tagline, design_prompt,
      description_hook, product_description_html, tags,
      seo_title, seo_description, product_story, care_instructions
    }
    """
    blueprint_info = BLUEPRINT_REGISTRY.get(product_type_slug, BLUEPRINT_REGISTRY["tshirt"])
    product_label  = blueprint_info["label"]
    price_range    = blueprint_info["price_range"]
    min_price      = price_range[0] / 100
    max_price      = price_range[1] / 100

    # Pick niches not recently used
    recent_niches = {m.get("niche", "") for m in memory[-20:]}
    fresh_niches  = [n for n in NICHES if n not in recent_niches]
    niche_pool    = fresh_niches[:8] if fresh_niches else NICHES[:8]
    niche_options = ", ".join(niche_pool)

    # Pick styles not recently used
    recent_styles = {m.get("design_style", "") for m in memory[-10:]}
    fresh_styles  = [s for s in DESIGN_STYLES if s not in recent_styles]
    style_options = ", ".join((fresh_styles[:5] if fresh_styles else DESIGN_STYLES[:5]))

    past_summary  = _memory_summary(memory)

    system = (
        "You are Narai — the world's most creative autonomous product designer. "
        "You make viral, identity-driven, emotionally resonant products that people want to buy and share. "
        "You NEVER copy past work. Every concept is 100% unique. Output pure JSON."
    )

    prompt = f"""Create a VIRAL, unique, masterpiece product concept for a {product_label}.

PAST PRODUCTS (NEVER DUPLICATE THESE):
{past_summary}

Available niches to pick from (choose ONE that feels freshest and most viral right now):
{niche_options}

Available design styles (choose ONE):
{style_options}

REQUIREMENTS:
- The concept must be something a real person would immediately want to buy
- It must trigger an emotion: pride, humor, belonging, nostalgia, aspiration, or love
- The title must be catchy, keyword-rich, max 70 characters
- Think: would someone screenshot this and share it on Instagram/TikTok?
- Retail price range: ${min_price:.2f} – ${max_price:.2f}

Return this exact JSON structure:
{{
  "title": "catchy product title (max 70 chars, keyword-rich)",
  "niche": "chosen niche from the list",
  "design_style": "chosen design style",
  "tagline": "short punchy tagline (max 10 words) that goes on the design",
  "sub_tagline": "secondary text line for design (max 15 words, optional)",
  "design_prompt": "detailed DALL-E 3 prompt for generating the design artwork (describe composition, typography style, colors, mood, visual elements, 150+ words)",
  "design_negative_prompt": "what to avoid: blurry, watermark, text errors, pixelated, low quality",
  "description_hook": "1 sentence hook for the product description (emotionally compelling)",
  "product_description_html": "Full rich HTML description (min 400 words). Include: what it is, who it's for, story behind design, why they'll love it. Use <h2> headings, <p> paragraphs, <ul> lists. Include a FAQ section with 5 Q&As. Include a size guide mention. Include care instructions paragraph. Include a satisfaction guarantee statement. End with a call to action.",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5", "tag6", "tag7", "tag8", "tag9", "tag10", "tag11", "tag12", "tag13", "tag14", "tag15", "tag16", "tag17", "tag18", "tag19", "tag20"],
  "seo_title": "SEO meta title 50-60 chars with primary keyword",
  "seo_description": "SEO meta description 150-160 chars, includes keyword + CTA",
  "product_story": "2-3 sentence story/inspiration behind the design",
  "size_guide": "Size guide: S=35-37in chest, M=38-40in, L=41-43in, XL=44-46in, 2XL=47-49in, 3XL=50-52in. Runs true to size.",
  "care_instructions": "Machine wash cold with like colors. Tumble dry low. Do not bleach. Do not iron on print. Inside out wash recommended.",
  "vendor": "WheellsVerse",
  "compare_at_multiplier": 1.25
}}"""

    concept = _ai_json(prompt, system=system, max_tokens=3000)

    # Fallbacks for any missing fields
    slug_title = f"{product_type_slug.replace('_', ' ').title()}"
    niche_default = fresh_niches[0] if fresh_niches else "entrepreneur mindset"
    concept.setdefault("title", f"Narai {slug_title} — Born Different")
    concept.setdefault("niche", niche_default)
    concept.setdefault("design_style", fresh_styles[0] if fresh_styles else "bold minimal typography")
    concept.setdefault("tagline", "Make Your Mark")
    concept.setdefault("sub_tagline", "")
    concept.setdefault("design_prompt",
        f"Premium {product_type_slug} design for {niche_default}. "
        f"Bold typography, dark background, gold accents. "
        f"Text reads: '{concept.get('tagline', 'Make Your Mark')}'. "
        f"Ultra-detailed, 300 DPI, transparent background, print-ready artwork.")
    concept.setdefault("design_negative_prompt", "blurry, watermark, low quality, pixelated, bad text")
    concept.setdefault("description_hook", "Made for the ones who dare to be different.")
    concept.setdefault("tags", ["graphic tee", "unisex", "gift idea", "trendy", "unique design",
                                  niche_default.replace(" ", "-"), product_type_slug.replace("_", "-"),
                                  "premium quality", "fast shipping", "limited edition",
                                  "birthday gift", "Christmas gift", "aesthetic",
                                  "viral design", "statement piece", "streetwear",
                                  "motivational", "funny", "cool gifts", "best seller"])
    concept.setdefault("seo_title", concept["title"][:60])
    concept.setdefault("seo_description", f"Shop {concept['title']} | Premium quality, fast shipping. Perfect gift.")
    concept.setdefault("product_story", f"Designed for those who live the {niche_default} lifestyle.")
    concept.setdefault("size_guide", "Size guide: S=35-37in chest, M=38-40in, L=41-43in, XL=44-46in, 2XL=47-49in, 3XL=50-52in.")
    concept.setdefault("care_instructions", "Machine wash cold, tumble dry low, do not bleach, do not iron on print.")
    concept.setdefault("vendor", "WheellsVerse")
    concept.setdefault("compare_at_multiplier", 1.25)
    concept.setdefault("product_description_html",
        f"<h2>{concept['title']}</h2>"
        f"<p>{concept['description_hook']}</p>"
        f"<p>This {blueprint_info['label'].lower()} is made for the {niche_default} community — "
        f"designed with love, built to last, and guaranteed to turn heads.</p>"
        f"<h2>Why You'll Love It</h2>"
        f"<ul><li>Premium quality materials</li>"
        f"<li>Vibrant, long-lasting print</li>"
        f"<li>Comfortable fit for everyday wear</li>"
        f"<li>Makes a perfect gift</li></ul>"
        f"<h2>Care Instructions</h2>"
        f"<p>{concept['care_instructions']}</p>"
        f"<h2>Satisfaction Guarantee</h2>"
        f"<p>Not happy? We'll make it right. 30-day hassle-free returns.</p>")

    return concept


# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — DESIGN GENERATION + UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def generate_and_upload_design(concept: dict) -> Optional[str]:
    """
    Generate a design with DALL-E 3 and upload it to Printify.
    Returns the Printify image ID or None if everything fails.
    """
    design_prompt = (
        f"{concept.get('design_prompt', '')}\n\n"
        f"IMPORTANT: Print-ready artwork for a {concept.get('niche','')} themed product. "
        f"The design should prominently feature the text: '{concept.get('tagline','')}'. "
        f"Style: {concept.get('design_style','')}. "
        f"High resolution, 300 DPI equivalent quality, transparent or white background only, "
        f"no realistic photography, no copyrighted characters or logos, "
        f"vibrant CMYK-safe colors, print-ready."
    )

    image_url = _dalle(design_prompt)
    if not image_url:
        log.warning("[NarAI] DALL-E 3 unavailable — creating product without design image")
        return None

    # Upload to Printify
    resp = _printify("POST", "/uploads/images.json", {
        "file_name": f"narai_design_{int(time.time())}.png",
        "url": image_url,
    })

    if isinstance(resp, dict) and resp.get("id"):
        img_id = resp["id"]
        log.info(f"[NarAI] Design uploaded to Printify: {img_id}")
        return img_id

    log.warning(f"[NarAI] Image upload failed: {resp}")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — BUILD PRINTIFY PRODUCT (ALL FIELDS)
# ══════════════════════════════════════════════════════════════════════════════

def build_printify_product(
    shop_id: str,
    concept: dict,
    product_type_slug: str,
    image_id: Optional[str],
) -> Optional[str]:
    """
    Create the full Printify product with all fields populated.
    Returns Printify product_id or None on failure.
    """
    info = BLUEPRINT_REGISTRY.get(product_type_slug, BLUEPRINT_REGISTRY["tshirt"])
    blueprint_id = info["blueprint_id"]
    provider_id  = info["primary_provider"]
    price_min, price_max = info["price_range"]
    price_cents  = (price_min + price_max) // 2  # midpoint price

    # ── Fetch variants ─────────────────────────────────────────────────────────
    variants_raw = _load_variants_for_blueprint(blueprint_id, provider_id)

    if not variants_raw:
        log.warning(f"[NarAI] No variants for blueprint {blueprint_id}/provider {provider_id} — trying fallback provider 1")
        provider_id  = 1
        variants_raw = _load_variants_for_blueprint(blueprint_id, provider_id)

    if not variants_raw:
        log.error(f"[NarAI] Could not get variants for {product_type_slug} — skipping")
        return None

    # Enable ALL variants at the target price
    variant_ids = []
    variants_payload = []
    for v in variants_raw:
        vid = v.get("id")
        if not vid:
            continue
        variant_ids.append(vid)
        variants_payload.append({
            "id": vid,
            "price": price_cents,
            "is_enabled": True,
        })

    if not variant_ids:
        log.error(f"[NarAI] No valid variant IDs for {product_type_slug}")
        return None

    # ── Build print areas ─────────────────────────────────────────────────────
    positions = _get_print_areas(blueprint_id)
    print_areas = []
    if image_id:
        placeholders = [
            {
                "position": pos,
                "images": [{"id": image_id, "x": 0.5, "y": 0.5, "scale": 1.0, "angle": 0}],
            }
            for pos in positions
        ]
        print_areas = [{"variant_ids": variant_ids, "placeholders": placeholders}]

    # ── Tags (max 13 for Printify) ─────────────────────────────────────────────
    tags = (concept.get("tags") or [])[:13]
    if len(tags) < 5:
        tags = ["graphic design", "unisex", "gift idea", "trendy", "unique", "premium", "viral"]

    # ── Product body ──────────────────────────────────────────────────────────
    body: dict = {
        "title":             concept["title"][:70],
        "description":       concept.get("product_description_html", ""),
        "blueprint_id":      blueprint_id,
        "print_provider_id": provider_id,
        "variants":          variants_payload,
        "tags":              tags,
    }
    if print_areas:
        body["print_areas"] = print_areas

    resp = _printify("POST", f"/shops/{shop_id}/products.json", body)

    if isinstance(resp, dict) and resp.get("id"):
        pid = resp["id"]
        log.info(f"[NarAI] ✅ Printify product created: {pid} — \"{concept['title']}\"")
        return pid

    log.error(f"[NarAI] Printify product creation failed: {resp}")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — PUBLISH TO SHOPIFY (ALL FIELDS)
# ══════════════════════════════════════════════════════════════════════════════

def publish_and_enrich(
    shop_id: str,
    printify_product_id: str,
    concept: dict,
    product_type_slug: str,
) -> Optional[str]:
    """
    1. Publish Printify product → Shopify
    2. Enrich Shopify product with ALL fields: SEO, metafields, compare_at_price, SKUs, etc.
    Returns Shopify product ID or None.
    """
    # ── Publish to Shopify ───────────────────────────────────────────────────
    pub = _printify("POST", f"/shops/{shop_id}/products/{printify_product_id}/publish.json", {
        "title": True, "description": True, "images": True,
        "variants": True, "tags": True, "keyFeatures": True,
    })
    if isinstance(pub, dict) and pub.get("error"):
        log.warning(f"[NarAI] Printify publish returned error: {pub} — product may still exist in Shopify")

    # Give Shopify a moment to receive the product
    time.sleep(3)

    # ── Find the Shopify product ID ───────────────────────────────────────────
    # Fetch the Printify product to get its Shopify external_id
    pfy_product = _printify("GET", f"/shops/{shop_id}/products/{printify_product_id}.json")
    shopify_id  = None

    if isinstance(pfy_product, dict):
        external_id = pfy_product.get("external", {})
        if isinstance(external_id, dict):
            shopify_id = external_id.get("id")
        elif isinstance(external_id, str):
            shopify_id = external_id

    if not shopify_id:
        # Try to find it in Shopify by title
        search = _shopify("GET", f"products.json?title={urllib.parse.quote(concept['title'][:50])}&limit=5")
        for p in (search.get("products") or []):
            if concept["title"].lower() in (p.get("title") or "").lower():
                shopify_id = str(p["id"])
                break

    if not shopify_id:
        log.warning(f"[NarAI] Could not find Shopify product for Printify {printify_product_id}")
        return None

    log.info(f"[NarAI] Shopify product ID: {shopify_id}")

    # ── Get current Shopify product to build variant updates ─────────────────
    current = _shopify("GET", f"products/{shopify_id}.json")
    current_product = current.get("product", {})
    current_variants = current_product.get("variants", [])

    info = BLUEPRINT_REGISTRY.get(product_type_slug, BLUEPRINT_REGISTRY["tshirt"])
    price_min, price_max = info["price_range"]
    base_price = f"{(price_min + price_max) / 2 / 100:.2f}"
    compare_price = f"{(price_min + price_max) / 2 / 100 * concept.get('compare_at_multiplier', 1.25):.2f}"

    # Build updated variants with SKU, compare_at_price, etc.
    brand_code = "WV"
    ptype_code = product_type_slug.upper()[:3]
    updated_variants = []
    for i, v in enumerate(current_variants):
        # Use variant_id as the unique suffix — guarantees no duplicate SKUs
        # even when option1/option2 are missing or identical
        color = (v.get("option2") or "").upper().replace(" ", "")[:6] or ""
        size  = (v.get("option1") or "").upper().replace(" ", "")[:4] or ""
        opts  = f"-{color}" if color else ""
        opts += f"-{size}"  if size  else ""
        sku   = f"{brand_code}-{ptype_code}{opts}-{v['id']}"
        updated_variants.append({
            "id":                   v["id"],
            "price":                v.get("price") or base_price,
            "compare_at_price":     compare_price,
            "sku":                  sku,
            "requires_shipping":    True,
            "taxable":              True,
            "inventory_management": "shopify",
            "inventory_policy":     "continue",
            "fulfillment_service":  "manual",
        })

    # ── Build images with alt text ────────────────────────────────────────────
    current_images = current_product.get("images", [])
    updated_images = []
    for i, img in enumerate(current_images):
        alt = (
            f"{concept['title']} — {concept.get('niche', '')} "
            f"{'| Front View' if i == 0 else '| View ' + str(i + 1)}"
        )
        updated_images.append({"id": img["id"], "alt": alt[:512]})

    # ── Full Shopify product update ───────────────────────────────────────────
    now_ts = datetime.now(timezone.utc).isoformat()
    tags_str = ", ".join((concept.get("tags") or [])[:20])

    product_update = {
        "product": {
            "id":                            shopify_id,
            "title":                         concept["title"][:255],
            "body_html":                     concept.get("product_description_html", ""),
            "vendor":                        concept.get("vendor", "WheellsVerse"),
            "product_type":                  info["type"],
            "status":                        "active",
            "tags":                          tags_str,
            "published_at":                  now_ts,
            "metafields_global_title_tag":   concept.get("seo_title", concept["title"])[:60],
            "metafields_global_description_tag": concept.get("seo_description", "")[:160],
        }
    }
    if updated_variants:
        product_update["product"]["variants"] = updated_variants
    if updated_images:
        product_update["product"]["images"] = updated_images

    update_resp = _shopify("PUT", f"products/{shopify_id}.json", product_update)
    if update_resp.get("error"):
        log.warning(f"[NarAI] Shopify product update partial: {update_resp.get('detail', '')}")

    # ── Add metafields ─────────────────────────────────────────────────────────
    metafields = [
        {"namespace": "custom", "key": "product_story",      "value": concept.get("product_story", ""),         "type": "single_line_text_field"},
        {"namespace": "custom", "key": "size_guide",         "value": concept.get("size_guide", ""),             "type": "multi_line_text_field"},
        {"namespace": "custom", "key": "care_instructions",  "value": concept.get("care_instructions", ""),     "type": "multi_line_text_field"},
        {"namespace": "seo",    "key": "hidden",             "value": "false",                                   "type": "single_line_text_field"},
        {"namespace": "custom", "key": "narai_niche",        "value": concept.get("niche", ""),                  "type": "single_line_text_field"},
        {"namespace": "custom", "key": "design_style",       "value": concept.get("design_style", ""),           "type": "single_line_text_field"},
    ]
    for mf in metafields:
        if mf["value"]:
            mf_resp = _shopify("POST", f"products/{shopify_id}/metafields.json", {"metafield": mf})
            if mf_resp.get("error"):
                log.warning(f"[NarAI] Metafield {mf['key']} failed: {mf_resp.get('detail','')}")

    log.info(f"[NarAI] ✅ Shopify enriched: {shopify_id} — \"{concept['title']}\"")
    return shopify_id


# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — FULL VERIFICATION + AUTO-FIX PROTOCOL
# ══════════════════════════════════════════════════════════════════════════════

def _error_entry(product_title: str, platform: str, error_type: str,
                 message: str, fix: str = "", result: str = "") -> dict:
    """Build a structured error log entry."""
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "product": product_title,
        "platform": platform,
        "error_type": error_type,
        "error_message": message,
        "fix_applied": fix,
        "fix_result": result or "⏳ pending",
    }


def verify_printify_product(shop_id: str, printify_id: str, concept: dict,
                             product_type_slug: str) -> dict:
    """
    Phase 2 — Printify product verification.
    Fetches the live product and checks every required field.
    Auto-fixes what it can. Returns {ok, checks, errors}.
    """
    errors = []
    checks = {}
    title = concept.get("title", "unknown")

    resp = _printify("GET", f"/shops/{shop_id}/products/{printify_id}.json")
    if isinstance(resp, dict) and resp.get("error"):
        return {"ok": False, "checks": {}, "errors": [
            _error_entry(title, "Printify", "fetch_failed",
                         str(resp.get("detail", resp)), "", "❌ Unresolved")
        ]}

    product = resp if isinstance(resp, dict) else {}

    # ── Field checks ──────────────────────────────────────────────────────────
    checks["title"] = bool(product.get("title", "").strip())
    checks["description"] = len(product.get("description", "")) >= 100
    checks["blueprint_id"] = bool(product.get("blueprint_id"))
    checks["print_provider_id"] = bool(product.get("print_provider_id"))

    variants = product.get("variants", [])
    enabled = [v for v in variants if v.get("is_enabled")]
    checks["has_variants"] = len(variants) > 0
    checks["variants_enabled"] = len(enabled) > 0
    checks["variant_prices"] = all(int(v.get("price", 0)) > 0 for v in enabled) if enabled else False

    print_areas = product.get("print_areas", [])
    has_images_in_print_areas = any(
        any(img.get("id") for ph in pa.get("placeholders", []) for img in ph.get("images", []))
        for pa in print_areas
    )
    checks["print_areas_filled"] = has_images_in_print_areas or not print_areas
    checks["is_not_locked"] = not product.get("is_locked", False)
    tags = product.get("tags", [])
    checks["has_tags"] = len(tags) >= 3

    failed = [k for k, v in checks.items() if not v]

    # ── Auto-fix ───────────────────────────────────────────────────────────────
    patch = {}

    if not checks["title"]:
        patch["title"] = concept["title"][:70]
        errors.append(_error_entry(title, "Printify", "empty_title",
                                   "Title is empty", f"Set to: {patch['title']}", "✅ Fixed"))

    if not checks["description"]:
        patch["description"] = concept.get("product_description_html", f"<p>{concept.get('description_hook','')}</p>")
        errors.append(_error_entry(title, "Printify", "empty_description",
                                   "Description too short", "Injected AI-generated HTML", "✅ Fixed"))

    if not checks["has_tags"]:
        patch["tags"] = (concept.get("tags") or [])[:13]
        errors.append(_error_entry(title, "Printify", "missing_tags",
                                   f"Only {len(tags)} tags", "Added 13 SEO tags", "✅ Fixed"))

    if not checks["variant_prices"] and variants:
        info = BLUEPRINT_REGISTRY.get(product_type_slug, BLUEPRINT_REGISTRY["tshirt"])
        price = (info["price_range"][0] + info["price_range"][1]) // 2
        patch["variants"] = [{"id": v["id"], "price": price, "is_enabled": True}
                              for v in variants]
        errors.append(_error_entry(title, "Printify", "missing_prices",
                                   "Some variants have $0 price", f"Set all to {price/100:.2f}", "✅ Fixed"))

    if patch:
        fix_resp = _printify("PUT", f"/shops/{shop_id}/products/{printify_id}.json", patch)
        if isinstance(fix_resp, dict) and fix_resp.get("error"):
            for e in errors:
                e["fix_result"] = "❌ Fix failed"

    for check in failed:
        if not any(e["error_type"] == check for e in errors):
            errors.append(_error_entry(title, "Printify", check,
                                       f"Check failed: {check}", "No auto-fix available", "❌ Unresolved"))

    return {
        "ok": len(failed) == 0,
        "checks": checks,
        "failed": failed,
        "errors": errors,
        "product_id": printify_id,
    }


def verify_shopify_product(shopify_id: str, concept: dict,
                            product_type_slug: str) -> dict:
    """
    Phase 3 — Shopify product verification.
    Fetches the live product and checks every required field.
    Auto-fixes everything it can. Returns {ok, checks, errors, handle}.
    """
    errors = []
    checks = {}
    title = concept.get("title", "unknown")

    resp = _shopify("GET", f"products/{shopify_id}.json")
    product = resp.get("product", {})
    if not product:
        return {"ok": False, "checks": {}, "errors": [
            _error_entry(title, "Shopify", "fetch_failed",
                         f"Could not fetch product {shopify_id}", "", "❌ Unresolved")
        ]}

    info       = BLUEPRINT_REGISTRY.get(product_type_slug, BLUEPRINT_REGISTRY["tshirt"])
    variants   = product.get("variants", [])
    images     = product.get("images", [])
    tag_list   = [t.strip() for t in (product.get("tags") or "").split(",") if t.strip()]
    body_words = len(re.sub(r"<[^>]+>", " ", product.get("body_html") or "").split())

    # ── All required field checks ─────────────────────────────────────────────
    checks["title"]              = bool((product.get("title") or "").strip())
    checks["description_words"]  = body_words >= 50
    checks["vendor"]             = bool(product.get("vendor"))
    checks["product_type"]       = bool(product.get("product_type"))
    checks["status_active"]      = product.get("status") == "active"
    checks["published"]          = bool(product.get("published_at"))
    checks["tags_10plus"]        = len(tag_list) >= 10
    checks["has_images"]         = len(images) >= 1
    checks["images_have_alt"]    = all(bool(img.get("alt")) for img in images) if images else True
    checks["has_variants"]       = len(variants) > 0
    checks["variant_prices"]     = all(float(v.get("price", 0)) > 0 for v in variants) if variants else False
    checks["compare_at_price"]   = any(v.get("compare_at_price") for v in variants) if variants else False
    checks["variant_skus"]       = all(bool(v.get("sku")) for v in variants) if variants else False
    checks["inventory_managed"]  = all(v.get("inventory_management") == "shopify" for v in variants) if variants else False
    checks["taxable"]            = all(v.get("taxable", True) for v in variants) if variants else True
    checks["requires_shipping"]  = all(v.get("requires_shipping", True) for v in variants) if variants else True

    failed = [k for k, v in checks.items() if not v]

    # ── Build auto-fix payload ─────────────────────────────────────────────────
    fix_product: dict = {"id": shopify_id}
    fix_variants: list = []
    now_ts = datetime.now(timezone.utc).isoformat()
    price_cents   = (info["price_range"][0] + info["price_range"][1]) // 2
    base_price    = f"{price_cents / 100:.2f}"
    compare_price = f"{price_cents / 100 * 1.25:.2f}"
    brand_code    = "WV"
    ptype_code    = product_type_slug.upper()[:3]

    if not checks["title"]:
        fix_product["title"] = concept["title"][:255]
        errors.append(_error_entry(title, "Shopify", "empty_title", "Title empty",
                                   f"Set: {concept['title'][:50]}", "✅ Fixed"))

    if not checks["description_words"]:
        fix_product["body_html"] = concept.get("product_description_html",
                                                f"<p>{concept.get('description_hook','Premium product by WheellsVerse.')}</p>")
        errors.append(_error_entry(title, "Shopify", "thin_description",
                                   f"Only {body_words} words", "Injected full HTML description", "✅ Fixed"))

    if not checks["vendor"]:
        fix_product["vendor"] = concept.get("vendor", "WheellsVerse")
        errors.append(_error_entry(title, "Shopify", "missing_vendor", "Vendor empty",
                                   "Set to WheellsVerse", "✅ Fixed"))

    if not checks["product_type"]:
        fix_product["product_type"] = info["type"]
        errors.append(_error_entry(title, "Shopify", "missing_product_type", "Product type empty",
                                   f"Set to {info['type']}", "✅ Fixed"))

    if not checks["status_active"]:
        fix_product["status"] = "active"
        fix_product["published_at"] = now_ts
        errors.append(_error_entry(title, "Shopify", "not_active", "Product in draft",
                                   "Set status=active, published_at=now", "✅ Fixed"))

    if not checks["published"]:
        fix_product["published_at"] = now_ts
        errors.append(_error_entry(title, "Shopify", "not_published", "published_at is null",
                                   "Set to now", "✅ Fixed"))

    if not checks["tags_10plus"]:
        fix_product["tags"] = ", ".join((concept.get("tags") or [])[:20])
        errors.append(_error_entry(title, "Shopify", "insufficient_tags",
                                   f"Only {len(tag_list)} tags", "Added 20 SEO tags", "✅ Fixed"))

    if not checks["images_have_alt"] and images:
        fixed_images = []
        for i, img in enumerate(images):
            alt = img.get("alt") or f"{concept['title']} | {concept.get('niche','')} | View {i+1}"
            fixed_images.append({"id": img["id"], "alt": alt[:512]})
        fix_product["images"] = fixed_images
        errors.append(_error_entry(title, "Shopify", "missing_alt_text",
                                   "Images missing alt text", "Added descriptive alt text to all images", "✅ Fixed"))

    # Variant-level fixes
    for i, v in enumerate(variants):
        vfix = {"id": v["id"]}
        changed = False

        if not v.get("sku"):
            color = (v.get("option2") or "").upper().replace(" ", "")[:6] or "DFLT"
            size  = (v.get("option1") or "").upper().replace(" ", "")[:4] or str(i)
            vfix["sku"] = f"{brand_code}-{ptype_code}-{color}-{size}"
            changed = True

        if not v.get("compare_at_price"):
            vfix["compare_at_price"] = compare_price
            changed = True

        if float(v.get("price", 0)) <= 0:
            vfix["price"] = base_price
            changed = True

        if v.get("inventory_management") != "shopify":
            vfix["inventory_management"] = "shopify"
            vfix["inventory_policy"] = "continue"
            changed = True

        if not v.get("taxable", True):
            vfix["taxable"] = True
            changed = True

        if not v.get("requires_shipping", True):
            vfix["requires_shipping"] = True
            changed = True

        if changed:
            fix_variants.append(vfix)

    if fix_variants:
        fix_product["variants"] = fix_variants
        errors.append(_error_entry(title, "Shopify", "variant_fields",
                                   f"{len(fix_variants)} variants missing SKU/price/compare_at",
                                   "Auto-generated SKUs, compare_at_price, inventory settings", "✅ Fixed"))

    # ── Apply all fixes in one PUT ─────────────────────────────────────────────
    if len(fix_product) > 1:  # more than just "id"
        fix_resp = _shopify("PUT", f"products/{shopify_id}.json", {"product": fix_product})
        if fix_resp.get("error"):
            for e in errors:
                e["fix_result"] = "❌ Fix failed — " + str(fix_resp.get("detail", ""))

    # ── SEO metafields check (separate endpoint) ───────────────────────────────
    mf_resp = _shopify("GET", f"products/{shopify_id}/metafields.json")
    existing_mf = {f"{m['namespace']}.{m['key']}": m for m in mf_resp.get("metafields", [])}

    seo_title = concept.get("seo_title", concept["title"])[:60]
    seo_desc  = concept.get("seo_description", "")[:160]

    for mf_def in [
        ("global", "title_tag",       seo_title,  "single_line_text_field"),
        ("global", "description_tag", seo_desc,   "single_line_text_field"),
    ]:
        ns, key, val, mf_type = mf_def
        if val and f"{ns}.{key}" not in existing_mf:
            mf_r = _shopify("POST", f"products/{shopify_id}/metafields.json",
                            {"metafield": {"namespace": ns, "key": key,
                                           "value": val, "type": mf_type}})
            if mf_r.get("metafield"):
                errors.append(_error_entry(title, "Shopify", f"missing_seo_{key}",
                                           f"SEO {key} metafield missing",
                                           f"Added: {val[:40]}", "✅ Fixed"))

    checks["seo_meta"] = bool(existing_mf or seo_title)

    # Re-evaluate after fixes
    failed_after = [k for k, v in checks.items() if not v]

    return {
        "ok": len(failed_after) == 0,
        "checks": checks,
        "failed_before": failed,
        "failed_after": failed_after,
        "errors": errors,
        "shopify_id": shopify_id,
        "handle": product.get("handle", ""),
    }


def verify_live_url(shop_handle: str, product_handle: str, title: str) -> dict:
    """
    Phase 4 — Live store URL check.
    Confirms the product URL is reachable (HTTP 200).
    """
    store = os.getenv("SHOPIFY_STORE", "").replace("https://", "").rstrip("/")
    if not store or not product_handle:
        return {"ok": False, "url": "", "status": None}

    url = f"https://{store}/products/{product_handle}"
    try:
        req = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "NarAI-Verify/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            status = r.status
            ok = status in (200, 301, 302)
            log.info(f"[NarAI] Live URL check {url} → HTTP {status}")
            return {"ok": ok, "url": url, "status": status}
    except urllib.error.HTTPError as e:
        return {"ok": e.code in (200, 301, 302), "url": url, "status": e.code}
    except Exception as e:
        return {"ok": False, "url": url, "status": None, "error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — SESSION LOOP
# ══════════════════════════════════════════════════════════════════════════════

_session_state: dict = {
    "running": False,
    "session_id": None,
    "products_created": 0,
    "products_target": 10,
    "current_product": "",
    "log": [],
    "errors": [],
    "error_log": [],
    "created_products": [],
}


def _log(msg: str, level: str = "INFO") -> None:
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    entry = f"[{ts}] [{level}] {msg}"
    _session_state["log"].append(entry)
    log_fn = getattr(log, level.lower(), log.info)
    log_fn(f"[NarAI] {msg}")


def run_pod_session(target: int = 10, product_types: Optional[List[str]] = None) -> dict:
    """
    Main autonomous session — creates `target` unique masterpiece products.

    Args:
        target: number of products to create (default 10)
        product_types: optional list of slugs to use; if None, rotates through all

    Returns session summary dict.
    """
    global _session_state

    _session_state = {
        "running": True,
        "session_id": f"pod_{int(time.time())}",
        "products_created": 0,
        "products_target": target,
        "current_product": "",
        "log": [],
        "errors": [],
        "error_log": [],
        "created_products": [],
    }

    # ── Step 1: Connect ────────────────────────────────────────────────────────
    _log("Narai POD Engine starting...")
    ok, shop_id = connect_and_verify()
    if not ok:
        _log("Failed to connect to Printify — aborting", "ERROR")
        _session_state["running"] = False
        return _session_state

    _log(f"Connected to Printify shop: {shop_id}")

    # ── Load product memory ────────────────────────────────────────────────────
    memory = _load_memory()
    _log(f"Product memory loaded: {len(memory)} past products")

    # ── Choose product type rotation ───────────────────────────────────────────
    types_to_use = product_types or PRODUCT_ROTATION
    rotation_idx = len(memory) % len(types_to_use)

    # ── Main creation loop ─────────────────────────────────────────────────────
    while _session_state["products_created"] < target:
        ptype = types_to_use[rotation_idx % len(types_to_use)]
        rotation_idx += 1

        _log(f"━━━ Product {_session_state['products_created']+1}/{target}: {ptype.upper()} ━━━")
        _session_state["current_product"] = ptype

        try:
            # Step 2: Generate concept
            _log(f"Generating concept for {ptype}...")
            concept = generate_concept(ptype, memory)
            _log(f"Concept: \"{concept['title']}\" | niche: {concept['niche']} | style: {concept['design_style']}")

            # Step 3: Generate + upload design
            _log("Generating design with DALL-E 3...")
            image_id = generate_and_upload_design(concept)
            if image_id:
                _log(f"Design uploaded: {image_id}")
            else:
                _log("No design image — product will be created without artwork", "WARNING")

            # Step 4: Build Printify product
            _log("Building Printify product...")
            printify_id = build_printify_product(shop_id, concept, ptype, image_id)
            if not printify_id:
                _log(f"Failed to create Printify product for {ptype} — skipping", "ERROR")
                _session_state["errors"].append({"type": ptype, "concept": concept.get("title"), "step": "printify_create"})
                time.sleep(3)
                continue

            # Step 5: Publish + enrich Shopify
            _log("Publishing to Shopify and enriching all fields...")
            shopify_id = publish_and_enrich(shop_id, printify_id, concept, ptype)
            if not shopify_id:
                _log(f"Shopify publish/enrich failed for {printify_id}", "WARNING")

            # Step 6: Verify (3-phase protocol)
            if shopify_id:
                # Phase 2: Printify data integrity
                pfy_v = verify_printify_product(shop_id, printify_id, concept, ptype)
                if pfy_v.get("ok"):
                    _log("✅ Phase 2 (Printify): all checks passed")
                else:
                    failed = pfy_v.get("failed", [])
                    fixed  = pfy_v.get("fixed",  [])
                    _log(f"⚠️ Phase 2 (Printify): failed={failed} fixed={fixed}", "WARNING")
                _session_state["error_log"].extend(pfy_v.get("errors", []))

                # Phase 3: Shopify product completeness
                sh_v = verify_shopify_product(shopify_id, concept, ptype)
                if sh_v.get("ok"):
                    _log("✅ Phase 3 (Shopify): all checks passed")
                else:
                    failed = sh_v.get("failed", [])
                    fixed  = sh_v.get("fixed",  [])
                    _log(f"⚠️ Phase 3 (Shopify): failed={failed} fixed={fixed}", "WARNING")
                _session_state["error_log"].extend(sh_v.get("errors", []))

                # Phase 4: Live URL reachable
                handle = sh_v.get("handle", "")
                live_v = verify_live_url("", handle, concept["title"])
                if live_v.get("ok"):
                    _log(f"✅ Phase 4 (Live URL): {live_v.get('url')} → HTTP {live_v.get('status')}")
                else:
                    _log(f"⚠️ Phase 4 (Live URL): {live_v.get('url')} unreachable (HTTP {live_v.get('status')})", "WARNING")

            # Save to memory
            memory_entry = {
                "title": concept["title"],
                "niche": concept["niche"],
                "design_style": concept["design_style"],
                "product_type": ptype,
                "tagline": concept.get("tagline", ""),
                "printify_id": printify_id,
                "shopify_id": shopify_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            memory.append(memory_entry)
            _save_memory(memory)

            _session_state["products_created"] += 1
            _session_state["created_products"].append({
                "title": concept["title"],
                "type": ptype,
                "niche": concept["niche"],
                "printify_id": printify_id,
                "shopify_id": shopify_id,
            })

            _log(f"🎉 Product {_session_state['products_created']}/{target} LIVE: \"{concept['title']}\"")

            # Brief pause between products (respect rate limits)
            if _session_state["products_created"] < target:
                time.sleep(4)

        except Exception as e:
            _log(f"Unexpected error on {ptype}: {e}", "ERROR")
            _session_state["errors"].append({"type": ptype, "error": str(e)})
            time.sleep(5)

    _session_state["running"] = False
    _session_state["current_product"] = ""

    # ── Session summary report ─────────────────────────────────────────────────
    total_errors    = len(_session_state["error_log"])
    auto_fixed      = sum(1 for e in _session_state["error_log"] if e.get("fixed"))
    unresolved      = total_errors - auto_fixed
    _log("━━━ SESSION COMPLETE ━━━")
    _log(f"  Products created : {_session_state['products_created']}/{target}")
    _log(f"  Verification issues: {total_errors} total | {auto_fixed} auto-fixed | {unresolved} unresolved")
    if _session_state["errors"]:
        _log(f"  Creation failures: {len(_session_state['errors'])}")

    _session_state["summary"] = {
        "products_created": _session_state["products_created"],
        "products_target": target,
        "verification_issues": total_errors,
        "auto_fixed": auto_fixed,
        "unresolved": unresolved,
        "creation_failures": len(_session_state["errors"]),
    }

    return _session_state


def get_pod_session_status() -> dict:
    """Return current session status (used by API endpoint)."""
    return {
        "running":          _session_state["running"],
        "session_id":       _session_state.get("session_id"),
        "products_created": _session_state["products_created"],
        "products_target":  _session_state["products_target"],
        "current_product":  _session_state["current_product"],
        "errors":           _session_state["errors"],
        "error_log":        _session_state.get("error_log", []),
        "created_products": _session_state["created_products"],
        "recent_log":       _session_state["log"][-20:],
        "summary":          _session_state.get("summary"),
    }


def get_pod_memory_stats() -> dict:
    """Return stats about the product memory log."""
    memory = _load_memory()
    niches  = {}
    ptypes  = {}
    for m in memory:
        niches[m.get("niche", "unknown")] = niches.get(m.get("niche","unknown"), 0) + 1
        ptypes[m.get("product_type","unknown")] = ptypes.get(m.get("product_type","unknown"), 0) + 1
    return {
        "total_products": len(memory),
        "by_niche":       dict(sorted(niches.items(), key=lambda x: -x[1])),
        "by_type":        dict(sorted(ptypes.items(), key=lambda x: -x[1])),
        "last_5":         [{"title": m["title"], "type": m["product_type"], "niche": m["niche"]}
                           for m in memory[-5:]],
    }
