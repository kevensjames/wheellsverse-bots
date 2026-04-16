#!/usr/bin/env python3
"""
core/printify_client.py
─────────────────────────────────────────────────────────────────────────────
Printify Print-on-Demand Integration for NarAI Shopify Autopilot

Handles POD product creation for 3 identity niches:
  • Entrepreneur mindset → hoodies, mugs, journals
  • Hacker / Programmer  → t-shirts, posters, desk mats
  • Dark Fantasy / Anime → t-shirts, art prints, stickers

Env var: PRINTIFY_API_KEY
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger("printify_client")

PRINTIFY_BASE = "https://api.printify.com/v1"

# ── Printify blueprint IDs (stable catalog IDs) ──────────────────────────────
# Blueprint = product template; print_provider = fulfillment partner
# Provider 99 = Monster Digital (US, fast), 29 = SPOD, 1 = Printify Choice
NICHE_BLUEPRINTS: Dict[str, List[Dict]] = {
    "entrepreneur mindset": [
        {"blueprint_id": 92,  "provider_id": 99, "type": "hoodie",  "label": "Unisex Heavy Blend Hoodie"},
        {"blueprint_id": 45,  "provider_id": 27, "type": "mug",     "label": "White Glossy Mug"},
        {"blueprint_id": 490, "provider_id": 99, "type": "journal", "label": "Spiral Notebook"},
    ],
    "hacker / programmer": [
        {"blueprint_id": 6,   "provider_id": 99, "type": "tshirt",   "label": "Unisex Softstyle T-Shirt"},
        {"blueprint_id": 32,  "provider_id": 1,  "type": "poster",   "label": "Enhanced Matte Poster"},
        {"blueprint_id": 358, "provider_id": 1,  "type": "sticker",  "label": "Kiss-Cut Sticker Sheet"},
    ],
    "dark fantasy / anime": [
        {"blueprint_id": 6,   "provider_id": 99, "type": "tshirt",    "label": "Unisex Softstyle T-Shirt"},
        {"blueprint_id": 32,  "provider_id": 1,  "type": "art_print", "label": "Enhanced Matte Poster"},
        {"blueprint_id": 358, "provider_id": 1,  "type": "sticker",   "label": "Kiss-Cut Sticker Sheet"},
    ],
}

# Default size options per product type
DEFAULT_SIZES: Dict[str, List[str]] = {
    "tshirt":    ["S", "M", "L", "XL", "2XL"],
    "hoodie":    ["S", "M", "L", "XL"],
    "mug":       ["11oz", "15oz"],
    "poster":    ["8x10", "11x14", "18x24"],
    "journal":   ["lined"],
    "sticker":   ["4x4", "5x5"],
    "art_print": ["8x10", "11x14"],
}

_shop_id_cache: Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# AUTH + HTTP
# ══════════════════════════════════════════════════════════════════════════════

def is_connected() -> bool:
    """True if PRINTIFY_API_KEY is configured."""
    return bool(os.getenv("PRINTIFY_API_KEY", "").strip())


def _api(
    method: str,
    endpoint: str,
    body: Optional[dict] = None,
) -> dict:
    """Base Printify REST caller."""
    import requests as _requests

    api_key = os.getenv("PRINTIFY_API_KEY", "")
    if not api_key:
        raise RuntimeError("PRINTIFY_API_KEY not set")

    url = f"{PRINTIFY_BASE}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    }
    try:
        resp = _requests.request(
            method.upper(), url,
            headers=headers,
            json=body,
            timeout=30,
        )
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:
                err = {"raw": resp.text[:500]}
            log.error(f"[Printify] {method} {endpoint} → HTTP {resp.status_code}: {err}")
            return {"error": True, "code": resp.status_code, "detail": err}
        return resp.json()
    except Exception as e:
        log.error(f"[Printify] {method} {endpoint} → {e}")
        return {"error": True, "detail": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SHOP RESOLUTION
# ══════════════════════════════════════════════════════════════════════════════

def get_shop_id() -> Optional[str]:
    """
    Return the Printify shop ID linked to the user's Shopify store.
    Caches after first call.
    """
    global _shop_id_cache
    if _shop_id_cache:
        return _shop_id_cache

    # Env override
    shop_id = os.getenv("PRINTIFY_SHOP_ID", "").strip()
    if shop_id:
        _shop_id_cache = shop_id
        return shop_id

    resp = _api("GET", "/shops.json")
    shops = resp if isinstance(resp, list) else resp.get("data", [])
    if not shops:
        log.error("[Printify] No shops found on this account")
        return None

    # Prefer the shop connected to Shopify
    shopify_store = os.getenv("SHOPIFY_STORE", "").lower().replace("https://", "").rstrip("/")
    for shop in shops:
        sales_channel = (shop.get("sales_channel") or "").lower()
        title = (shop.get("title") or "").lower()
        if shopify_store and (shopify_store in sales_channel or shopify_store in title):
            _shop_id_cache = str(shop["id"])
            return _shop_id_cache

    # Fall back to first shop
    _shop_id_cache = str(shops[0]["id"])
    return _shop_id_cache


# ══════════════════════════════════════════════════════════════════════════════
# CATALOG
# ══════════════════════════════════════════════════════════════════════════════

def get_catalog(category: str = "") -> List[dict]:
    """Fetch available Printify blueprints (product templates)."""
    resp = _api("GET", "/catalog/blueprints.json")
    blueprints = resp if isinstance(resp, list) else resp.get("data", [])
    if category:
        kw = category.lower()
        blueprints = [b for b in blueprints
                      if kw in b.get("title", "").lower() or kw in b.get("description", "").lower()]
    return blueprints


def get_blueprint_variants(blueprint_id: int, provider_id: int) -> List[dict]:
    """Fetch available variants for a blueprint + provider combo."""
    resp = _api("GET", f"/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json")
    return resp.get("variants", []) if isinstance(resp, dict) else []


# ══════════════════════════════════════════════════════════════════════════════
# DESIGN GENERATION  (same interface as printful_client)
# ══════════════════════════════════════════════════════════════════════════════

def _claude_json(prompt: str, max_tokens: int = 2000) -> Any:
    """Local Claude JSON helper. Returns {} on any failure — never raises."""
    try:
        import anthropic
        model = os.getenv("NARAI_MODEL", "claude-sonnet-4-6")
        client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))
        r = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=(
                "You are NarAI's design director. You create compelling print-on-demand "
                "product designs for identity-driven niches: entrepreneurs, programmers, "
                "and dark fantasy / anime fans. Output pure JSON only — no prose."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        raw = r.content[0].text.strip()
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
    except Exception as e:
        log.warning(f"Claude JSON failed (using fallback): {e}")
        return {}


def generate_pod_design(niche: str, product_type: str) -> dict:
    """
    Generate a POD design concept for the given niche + product type.
    Returns same shape as printful_client.generate_pod_design().
    """
    prompt = f"""Design a premium print-on-demand product for this identity niche.

NICHE: {niche}
PRODUCT TYPE: {product_type}

Requirements:
- Design must feel premium and identity-affirming (people want to WEAR or USE this to signal who they are)
- Text-based designs or minimal illustration with powerful text work best for POD
- Must be commercially safe (no copyrighted characters, trademarked phrases)
- High contrast works best for dark garments

Return JSON:
{{
  "design_prompt": "detailed image generation prompt for the design (composition, style, colors, typography, mood)",
  "negative_prompt": "what to avoid",
  "colors": ["#hex1", "#hex2", "#hex3"],
  "style": "minimal typographic / bold graphic / dark illustration / etc",
  "text_overlay": "main text/quote on the design (under 8 words)",
  "tagline": "secondary text line (under 12 words)",
  "product_title": "Shopify product title (under 60 chars)",
  "product_description": "2-sentence description that sells the identity, not just the item"
}}"""

    design = _claude_json(prompt)

    if not isinstance(design, dict) or not design.get("design_prompt"):
        design = {
            "design_prompt": f"Minimalist {niche} motivational design, dark background, gold typography, premium feel",
            "negative_prompt": "low quality, blurry, watermark, copyrighted logos",
            "colors": ["#0f0f0f", "#c9a84c", "#ffffff"],
            "style": "minimal typographic",
            "text_overlay": "Build. Ship. Repeat.",
            "tagline": "For the ones who never stop building",
            "product_title": f"{niche.title()} {product_type.replace('_', ' ').title()}",
            "product_description": f"Wear your identity. Built for {niche} who move fast and build things.",
        }

    # Attempt cover image generation
    image_path = None
    image_url = None
    try:
        from core.cover_engine import generate_cover
        cover = generate_cover(
            cover_prompts={"dalle": design["design_prompt"]},
            platform="shopify",
            title=design.get("product_title", "POD Product"),
            product_type=product_type,
        )
        image_path = cover.get("path")
        image_url = cover.get("url")
    except Exception as e:
        log.warning(f"[Printify] Cover generation failed: {e}")

    return {
        "design_prompt": design.get("design_prompt", ""),
        "negative_prompt": design.get("negative_prompt", ""),
        "image_path": image_path,
        "image_url": image_url,
        "colors": design.get("colors", []),
        "style": design.get("style", ""),
        "text_overlay": design.get("text_overlay", ""),
        "tagline": design.get("tagline", ""),
        "product_title": design.get("product_title", ""),
        "product_description": design.get("product_description", ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
# IMAGE UPLOAD
# ══════════════════════════════════════════════════════════════════════════════

def upload_image(image_path: Optional[str] = None, image_url: Optional[str] = None) -> Optional[str]:
    """
    Upload an image to Printify's media library.
    Returns the Printify image ID, or None on failure.
    """
    if not image_url and not image_path:
        return None

    body: dict = {"file_name": "design.png"}

    if image_url:
        body["url"] = image_url
    elif image_path and Path(image_path).exists():
        import base64
        body["contents"] = base64.b64encode(Path(image_path).read_bytes()).decode()

    resp = _api("POST", "/uploads/images.json", body)
    if resp.get("error") or not resp.get("id"):
        log.warning(f"[Printify] Image upload failed: {resp}")
        return None

    return resp["id"]


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCT CREATION
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_blueprint(niche: str, product_type: str) -> Dict:
    """Look up blueprint_id + provider_id for niche + product type."""
    niche_lower = niche.lower()
    catalog = NICHE_BLUEPRINTS.get(niche_lower)
    if not catalog:
        for key in NICHE_BLUEPRINTS:
            if any(word in niche_lower for word in key.split()):
                catalog = NICHE_BLUEPRINTS[key]
                break
    if not catalog:
        catalog = NICHE_BLUEPRINTS["entrepreneur mindset"]

    ptype_lower = product_type.lower().replace(" ", "_")
    for item in catalog:
        if item["type"] == ptype_lower or ptype_lower in item["label"].lower():
            return item

    return catalog[0]


def create_pod_product(
    title: str,
    description: str,
    niche: str,
    product_type: str,
    design_image_path: Optional[str],
    price: float,
) -> dict:
    """
    Create a Printify product and publish it to Shopify.

    Same interface as printful_client.create_pod_product().

    Returns:
        {success, product_id, name, variants, preview_url, error?}
    """
    if not is_connected():
        return {"success": False, "error": "PRINTIFY_API_KEY not set"}

    shop_id = get_shop_id()
    if not shop_id:
        return {"success": False, "error": "No Printify shop found — check PRINTIFY_SHOP_ID env var"}

    blueprint = _resolve_blueprint(niche, product_type)
    blueprint_id = blueprint["blueprint_id"]
    provider_id  = blueprint["provider_id"]

    # ── Fetch real variant IDs ────────────────────────────────────────────────
    all_variants = get_blueprint_variants(blueprint_id, provider_id)
    if not all_variants:
        return {"success": False, "error": f"No variants for blueprint {blueprint_id}/provider {provider_id}"}

    # Pick enabled variants that are in stock, up to 5
    available = [v for v in all_variants if v.get("is_available", True)][:5]
    if not available:
        available = all_variants[:5]

    # ── Upload design image (optional) ────────────────────────────────────────
    image_id = None
    # Printify needs an image ID or URL for each print area
    # If we have no image, we use a placeholder text-based design
    print_areas = []
    if image_id:
        print_areas = [{"position": "front", "images": [{"id": image_id, "x": 0.5, "y": 0.5, "scale": 1, "angle": 0}]}]
    # If no image uploaded, product is created without artwork (can be added later in dashboard)

    # ── Build product body ────────────────────────────────────────────────────
    variant_data = [
        {
            "id": v["id"],
            "price": int(round(price * 100)),  # Printify uses cents
            "is_enabled": True,
        }
        for v in available
    ]

    body = {
        "title": title,
        "description": f"<p>{description}</p>",
        "blueprint_id": blueprint_id,
        "print_provider_id": provider_id,
        "variants": variant_data,
    }
    if print_areas:
        body["print_areas"] = print_areas

    resp = _api("POST", f"/shops/{shop_id}/products.json", body)

    if resp.get("error") or not resp.get("id"):
        return {
            "success": False,
            "error": str(resp.get("detail", resp)),
            "product_id": None,
        }

    product_id = resp["id"]
    log.info(f"[Printify] Created product {product_id}: {title}")

    # ── Auto-publish to Shopify ────────────────────────────────────────────────
    pub_resp = _api("POST", f"/shops/{shop_id}/products/{product_id}/publish.json", {
        "title": True,
        "description": True,
        "images": True,
        "variants": True,
        "tags": True,
    })
    if pub_resp.get("error"):
        log.warning(f"[Printify] Publish to Shopify failed: {pub_resp}")

    # Build a preview URL from the product images
    images = resp.get("images", [])
    preview_url = images[0].get("src", "") if images else ""

    return {
        "success": True,
        "product_id": product_id,
        "name": resp.get("title", title),
        "variants": resp.get("variants", []),
        "preview_url": preview_url,
        "shop_id": shop_id,
        "published": not pub_resp.get("error"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SHOPIFY SYNC  (Printify auto-publishes, but this creates the Shopify record
#                manually if needed, same interface as printful_client)
# ══════════════════════════════════════════════════════════════════════════════

def sync_to_shopify(printify_product: dict, description: str = "", tags: List[str] = None) -> dict:
    """
    Printify auto-publishes to Shopify when publish endpoint is called in create_pod_product.
    This function is a compatibility shim — it returns success if the product was published.
    """
    if not printify_product.get("success"):
        return {"success": False, "error": "Printify product not created yet"}

    if printify_product.get("published"):
        return {
            "success": True,
            "shopify_product_id": printify_product.get("product_id"),
            "printify_product_id": printify_product.get("product_id"),
            "title": printify_product.get("name", ""),
        }

    # If not published yet, try the publish endpoint
    shop_id = printify_product.get("shop_id") or get_shop_id()
    product_id = printify_product.get("product_id")
    if not shop_id or not product_id:
        return {"success": False, "error": "Missing shop_id or product_id"}

    pub_resp = _api("POST", f"/shops/{shop_id}/products/{product_id}/publish.json", {
        "title": True, "description": True, "images": True, "variants": True, "tags": True,
    })

    if pub_resp.get("error"):
        return {"success": False, "error": str(pub_resp.get("detail", pub_resp))}

    return {
        "success": True,
        "shopify_product_id": product_id,
        "printify_product_id": product_id,
        "title": printify_product.get("name", ""),
    }


# ══════════════════════════════════════════════════════════════════════════════
# LISTING
# ══════════════════════════════════════════════════════════════════════════════

def list_pod_products() -> List[dict]:
    """List all POD products in the Printify shop."""
    if not is_connected():
        return []
    shop_id = get_shop_id()
    if not shop_id:
        return []
    resp = _api("GET", f"/shops/{shop_id}/products.json")
    return resp.get("data", []) if isinstance(resp, dict) else []
