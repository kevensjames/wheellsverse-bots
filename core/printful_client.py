#!/usr/bin/env python3
"""
core/printful_client.py
─────────────────────────────────────────────────────────────────────────────
Printful Print-on-Demand Integration for NarAI Shopify Autopilot

Handles POD product creation for 3 identity niches:
  • Entrepreneur mindset → hoodies, mugs, journals
  • Hacker / Programmer  → t-shirts, posters, desk mats
  • Dark Fantasy / Anime → t-shirts, art prints, stickers

Env var: PRINTFUL_API_KEY
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

log = logging.getLogger("printful_client")

PRINTFUL_BASE = "https://api.printful.com"

# ── Identity niche → product catalog mapping ──────────────────────────────────
# Printful product IDs (stable catalog IDs as of 2024)
NICHE_PRODUCTS: Dict[str, List[Dict]] = {
    "entrepreneur mindset": [
        {"printful_id": 380, "type": "hoodie", "label": "Unisex Hoodie"},
        {"printful_id": 19, "type": "mug", "label": "White Glossy Mug"},
        {"printful_id": 471, "type": "journal", "label": "Spiral Notebook"},
    ],
    "hacker / programmer": [
        {"printful_id": 71, "type": "tshirt", "label": "Unisex Staple T-Shirt"},
        {"printful_id": 1, "type": "poster", "label": "Poster"},
        {"printful_id": 491, "type": "desk_mat", "label": "Gaming Mouse Pad"},
    ],
    "dark fantasy / anime": [
        {"printful_id": 71, "type": "tshirt", "label": "Unisex Staple T-Shirt"},
        {"printful_id": 1, "type": "art_print", "label": "Poster"},
        {"printful_id": 358, "type": "sticker", "label": "Kiss-Cut Stickers"},
    ],
}

# Default variant options per product type
DEFAULT_VARIANTS: Dict[str, List[Dict]] = {
    "tshirt": [{"size": "S"}, {"size": "M"}, {"size": "L"}, {"size": "XL"}, {"size": "2XL"}],
    "hoodie": [{"size": "S"}, {"size": "M"}, {"size": "L"}, {"size": "XL"}],
    "mug": [{"size": "11oz"}, {"size": "15oz"}],
    "poster": [{"size": "12x16"}, {"size": "18x24"}],
    "journal": [{"size": "lined"}],
    "desk_mat": [{"size": "36x18"}],
    "art_print": [{"size": "12x16"}, {"size": "18x24"}],
    "sticker": [{"size": "3x3"}, {"size": "4x4"}],
}


# ══════════════════════════════════════════════════════════════════════════════
# AUTH + HTTP
# ══════════════════════════════════════════════════════════════════════════════

def is_connected() -> bool:
    """True if PRINTFUL_API_KEY is configured."""
    return bool(os.getenv("PRINTFUL_API_KEY", "").strip())


def _api(
    method: str,
    endpoint: str,
    body: Optional[dict] = None,
) -> dict:
    """Base Printful REST caller."""
    api_key = os.getenv("PRINTFUL_API_KEY", "")
    if not api_key:
        raise RuntimeError("PRINTFUL_API_KEY not set")

    url = f"{PRINTFUL_BASE}/{endpoint.lstrip('/')}"
    data = json.dumps(body).encode() if body else None

    req = urllib.request.Request(
        url,
        data=data,
        method=method.upper(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body_bytes = e.read()
        try:
            err = json.loads(body_bytes)
        except Exception:
            err = {"raw": body_bytes.decode(errors="replace")}
        log.error(f"[Printful] {method} {endpoint} → HTTP {e.code}: {err}")
        return {"error": True, "code": e.code, "detail": err}
    except Exception as e:
        log.error(f"[Printful] {method} {endpoint} → {e}")
        return {"error": True, "detail": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# CATALOG
# ══════════════════════════════════════════════════════════════════════════════

def get_catalog(category: str = "") -> List[dict]:
    """
    Fetch available Printful product templates.

    Args:
        category: optional filter keyword (e.g. "shirt", "mug")

    Returns:
        List of product template dicts
    """
    resp = _api("GET", "/products")
    products = resp.get("result", [])
    if category:
        kw = category.lower()
        products = [p for p in products if kw in p.get("model", "").lower()
                    or kw in p.get("type", "").lower()]
    return products


def get_product_variants(printful_product_id: int) -> List[dict]:
    """Fetch available variants for a Printful catalog product."""
    resp = _api("GET", f"/products/{printful_product_id}")
    return resp.get("result", {}).get("variants", [])


# ══════════════════════════════════════════════════════════════════════════════
# DESIGN GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def _claude_json(prompt: str, max_tokens: int = 2000) -> Any:
    """Local Claude JSON helper — routed through claude_logged for budget guard."""
    from core.claude_logged import create as claude_create
    r = claude_create(
        model=os.getenv("NARAI_MODEL", "claude-sonnet-4-6"),
        max_tokens=max_tokens,
        system=(
            "You are NarAI's design director. You create compelling print-on-demand "
            "product designs for identity-driven niches: entrepreneurs, programmers, "
            "and dark fantasy / anime fans. Output pure JSON only — no prose."
        ),
        messages=[{"role": "user", "content": prompt}],
        bot_name="printful_client",
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


def generate_pod_design(niche: str, product_type: str) -> dict:
    """
    Generate a POD design concept and cover image for the given niche + product type.

    Args:
        niche: one of the identity niches (e.g. "entrepreneur mindset")
        product_type: e.g. "tshirt", "hoodie", "mug"

    Returns:
        {
          "design_prompt": str,
          "negative_prompt": str,
          "image_path": str | None,
          "image_url": str | None,
          "colors": list[str],
          "style": str,
          "text_overlay": str,
          "tagline": str,
        }
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
  "design_prompt": "detailed DALL-E / image generation prompt for the design (describe composition, style, colors, typography, mood)",
  "negative_prompt": "what to avoid in generation",
  "colors": ["#hex1", "#hex2", "#hex3"],
  "style": "minimal typographic / bold graphic / dark illustration / etc",
  "text_overlay": "the main text/quote on the design (under 8 words, punchy)",
  "tagline": "secondary text line (under 12 words)",
  "product_title": "what to call this product on Shopify (under 60 chars)",
  "product_description": "2-sentence product description that sells the identity, not just the item"
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
        log.warning(f"[Printful] Cover generation failed: {e}")

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
# PRODUCT CREATION
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_printful_product_id(niche: str, product_type: str) -> int:
    """Look up the Printful catalog ID for niche + product type."""
    niche_lower = niche.lower()
    # Find closest niche key
    catalog = NICHE_PRODUCTS.get(niche_lower)
    if not catalog:
        for key in NICHE_PRODUCTS:
            if any(word in niche_lower for word in key.split()):
                catalog = NICHE_PRODUCTS[key]
                break
    if not catalog:
        catalog = NICHE_PRODUCTS["entrepreneur mindset"]

    ptype_lower = product_type.lower().replace(" ", "_")
    for item in catalog:
        if item["type"] == ptype_lower or ptype_lower in item["label"].lower():
            return item["printful_id"]

    return catalog[0]["printful_id"]


def create_pod_product(
    title: str,
    description: str,
    niche: str,
    product_type: str,
    design_image_path: Optional[str],
    price: float,
) -> dict:
    """
    Create a Printful store product.

    Args:
        title: product title
        description: product description
        niche: identity niche
        product_type: e.g. "tshirt"
        design_image_path: local path to design image (optional, uses placeholder if None)
        price: retail price in USD

    Returns:
        {success, product_id, variants, preview_url, error?}
    """
    if not is_connected():
        return {"success": False, "error": "PRINTFUL_API_KEY not set"}

    printful_product_id = _resolve_printful_product_id(niche, product_type)

    # Build variant list for Printful
    # We need to fetch real variant IDs from the catalog
    catalog_variants = get_product_variants(printful_product_id)
    if not catalog_variants:
        return {"success": False, "error": f"No variants found for Printful product {printful_product_id}"}

    # Pick up to 5 variants (sizes S-XL or equivalent)
    chosen_variants = catalog_variants[:5]

    # Build files list
    files = []
    if design_image_path and Path(design_image_path).exists():
        files = [{"type": "front", "url": design_image_path}]
    # If no image path — Printful still creates the product, design can be uploaded later

    sync_variants = []
    for cv in chosen_variants:
        v = {
            "variant_id": cv.get("id"),
            "retail_price": str(round(price, 2)),
        }
        if files:
            v["files"] = files
        sync_variants.append(v)

    body = {
        "sync_product": {
            "name": title,
            "description": description,
            "thumbnail": files[0]["url"] if files else "",
        },
        "sync_variants": sync_variants,
    }

    resp = _api("POST", "/store/products", body)

    if resp.get("error") or resp.get("code", 200) != 200:
        return {
            "success": False,
            "error": str(resp.get("detail", resp)),
            "printful_id": None,
        }

    result = resp.get("result", {})
    sync_product = result.get("sync_product", {})

    return {
        "success": True,
        "product_id": sync_product.get("id"),
        "printful_id": printful_product_id,
        "name": sync_product.get("name", title),
        "variants": result.get("sync_variants", []),
        "preview_url": sync_product.get("thumbnail_url", ""),
        "external_id": sync_product.get("external_id"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# SHOPIFY SYNC
# ══════════════════════════════════════════════════════════════════════════════

def sync_to_shopify(printful_product: dict, description: str = "", tags: List[str] = None) -> dict:
    """
    Create matching Shopify product linked to Printful fulfillment.

    Args:
        printful_product: dict returned by create_pod_product()
        description: product description for Shopify
        tags: Shopify tags

    Returns:
        {success, shopify_product_id, printful_product_id}
    """
    if not printful_product.get("success"):
        return {"success": False, "error": "Printful product not created yet"}

    try:
        from core.shopify_client import create_product, add_product_image
    except ImportError:
        return {"success": False, "error": "shopify_client not available"}

    title = printful_product.get("name", "POD Product")
    p_id = printful_product.get("product_id")
    preview = printful_product.get("preview_url", "")

    # Build variant list for Shopify
    shopify_variants = []
    for v in printful_product.get("variants", []):
        shopify_variants.append({
            "option1": v.get("name", "Default"),
            "price": str(v.get("retail_price", "29.99")),
            "requires_shipping": True,
            "inventory_management": None,
            "inventory_policy": "continue",
            "fulfillment_service": "manual",
        })

    if not shopify_variants:
        shopify_variants = [{
            "option1": "Default",
            "price": "29.99",
            "requires_shipping": True,
            "inventory_management": None,
            "inventory_policy": "continue",
        }]

    product_data = {
        "title": title,
        "body_html": f"<p>{description}</p>" if description else "",
        "vendor": "WheellsVerse",
        "product_type": "POD",
        "tags": ", ".join(tags or ["pod", "print-on-demand", "apparel"]),
        "requires_shipping": True,
        "variants": shopify_variants,
        "options": [{"name": "Size", "values": [v.get("option1", "M") for v in shopify_variants[:5]]}],
        "metafields": [
            {
                "namespace": "printful",
                "key": "product_id",
                "value": str(p_id),
                "type": "single_line_text_field",
            }
        ],
    }

    result = create_product(product_data)

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error", "Shopify create failed"),
            "printful_product_id": p_id,
        }

    shopify_id = result.get("product_id")

    # Add preview image if available
    if preview and shopify_id:
        try:
            add_product_image(shopify_id, src=preview)
        except Exception:
            pass

    return {
        "success": True,
        "shopify_product_id": shopify_id,
        "printful_product_id": p_id,
        "title": title,
    }


# ══════════════════════════════════════════════════════════════════════════════
# LISTING
# ══════════════════════════════════════════════════════════════════════════════

def list_pod_products() -> List[dict]:
    """List all POD products in the Printful store."""
    if not is_connected():
        return []
    resp = _api("GET", "/store/products")
    return resp.get("result", [])
