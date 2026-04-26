"""
Admin API for the multi-tenant Shopify dashboard.

Endpoints are gated by the platform's API_KEY — this is an *operator* surface
for the platform owner, not a per-merchant surface. Sent as X-API-Key header.
"""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import APIRouter, Depends, Header, HTTPException

from core.narai_user import get_supabase
from narai.core.shopify_mt.billing import PLAN_LIMITS, TIER_ORDER, PRICE_IDS


def verify_admin_api_key(x_api_key: str = Header(None)) -> bool:
    """FastAPI dep: require the X-API-Key header to match the platform API_KEY env."""
    expected = os.getenv("API_KEY")
    if not expected:
        # Fail closed — never accept admin requests if the env is missing
        raise HTTPException(503, "Admin API not configured (API_KEY env missing)")
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(401, "Invalid or missing X-API-Key")
    return True

log = logging.getLogger("shopify_admin")
router = APIRouter(prefix="/api/narai/shopify", tags=["shopify-admin"])

PLAN_MONTHLY_USD = {"free": 0, "starter": 19, "pro": 49, "elite": 149}


@router.get("/merchants")
def list_merchants(_=Depends(verify_admin_api_key)) -> dict:
    """List all connected merchants plus aggregate stats."""
    sb = get_supabase()

    merchants = sb.table("merchants").select("*").order("installed_at", desc=True).execute().data or []

    # Count products per merchant in one pass
    products = sb.table("merchant_products").select("merchant_id").execute().data or []
    product_counts: dict[str, int] = {}
    for p in products:
        product_counts[p["merchant_id"]] = product_counts.get(p["merchant_id"], 0) + 1

    enriched = []
    paid_count = 0
    mrr_usd = 0
    for m in merchants:
        m["products_count"] = product_counts.get(m["id"], 0)
        enriched.append(m)
        if not m.get("uninstalled_at") and m.get("plan_tier") in ("starter", "pro", "elite"):
            paid_count += 1
            mrr_usd += PLAN_MONTHLY_USD.get(m.get("plan_tier"), 0)

    return {
        "merchants": enriched,
        "stats": {
            "total": len([m for m in merchants if not m.get("uninstalled_at")]),
            "paid": paid_count,
            "products": sum(product_counts.values()),
            "mrr_usd": mrr_usd,
        },
    }


@router.get("/merchants/{merchant_id}")
def merchant_detail(merchant_id: str, _=Depends(verify_admin_api_key)) -> dict:
    sb = get_supabase()
    merchant = sb.table("merchants").select("*").eq("id", merchant_id).limit(1).execute().data
    if not merchant:
        raise HTTPException(404, "Merchant not found")
    merchant = merchant[0]

    products = sb.table("merchant_products").select("*").eq("merchant_id", merchant_id)\
        .order("created_at", desc=True).limit(100).execute().data or []

    events = sb.table("merchant_events").select("*").eq("merchant_id", merchant_id)\
        .order("created_at", desc=True).limit(100).execute().data or []

    billing = sb.table("merchant_billing").select("*").eq("merchant_id", merchant_id)\
        .order("created_at", desc=True).limit(50).execute().data or []

    # Never ever return the encrypted token to the client
    merchant.pop("access_token_encrypted", None)

    return {
        "merchant": merchant,
        "products": products,
        "events": events,
        "billing": billing,
        "plan_limits": PLAN_LIMITS.get(merchant.get("plan_tier") or "free", {}),
    }


@router.get("/plans")
def list_plans(_=Depends(verify_admin_api_key)) -> dict:
    """Plans the admin dashboard can offer to merchants."""
    return {
        "tiers": TIER_ORDER,
        "limits": PLAN_LIMITS,
        "monthly_usd": PLAN_MONTHLY_USD,
        "stripe_configured": all(PRICE_IDS.get(t) for t in ("starter", "pro", "elite")),
    }


@router.post("/merchants/{merchant_id}/test-product")
def push_test_product(merchant_id: str, _=Depends(verify_admin_api_key)) -> dict:
    """
    Smoke-test the full product pipeline on a merchant's store.
    Creates one DALL-E-imagery product end-to-end (draft → 4 images → gate → activate).
    Used by the admin dashboard's "Test product" button.
    """
    from narai.core.shopify_mt.products import (
        ProductBrief,
        create_product_for_merchant,
    )

    brief = ProductBrief(
        title="NarAI End-to-End Test Product",
        body_html=(
            "<p>This product was created by the multi-tenant Shopify pipeline "
            "as an end-to-end validation. Four 3D-rendered angles (hero, "
            "lifestyle, detail, flat-lay) were generated via DALL-E 3 and "
            "attached as a draft. The quality gate enforces ≥4 images, ≥300 "
            "character description, ≥3 tags, and price &gt; 0 before any "
            "product becomes active in the storefront. If you can see this "
            "listing live with four images, every layer of the pipeline is "
            "healthy: OAuth-issued token, Fernet decryption, Shopify Admin "
            "API integration, DALL-E image generation, and the activation "
            "gate.</p>"
        ),
        price=29.00,
        tags="test,narai,validation,multi-tenant",
        product_type="Digital Test",
        base_image_concept=(
            "futuristic minimalist product cube floating in a void, soft "
            "volumetric lighting, neon accents, premium digital good aesthetic"
        ),
        seo_title="NarAI End-to-End Test Product",
        seo_description="Validation product proving the multi-tenant pipeline works.",
        vendor="NarAI",
        requires_shipping=False,
    )
    result = create_product_for_merchant(merchant_id, brief)
    return result


@router.post("/test-printify")
def push_test_printify_product(_=Depends(verify_admin_api_key)) -> dict:
    """
    Smoke-test the Printify POD pipeline: generate a design via DALL-E,
    upload to Printify, create a POD product on the connected Shopify store
    using the new variant_ids+placeholders schema. Single-tenant (uses your
    own PRINTIFY_SHOP_ID env), not per-merchant.
    """
    from core.cover_engine import generate_cover
    from core.printify_client import create_pod_product, is_connected

    if not is_connected():
        return {"success": False, "error": "PRINTIFY_API_KEY env not set"}

    # 1. Generate a design via DALL-E
    cover = generate_cover(
        {"dalle": (
            "minimalist t-shirt design, bold geometric pattern in matte black "
            "and electric purple, centered composition on transparent background, "
            "vector-style 3D render, premium streetwear aesthetic"
        )},
        "printify-test",
        "narai_printify_smoke_test",
        "T-Shirt",
    )
    if not cover.get("success") or not cover.get("url"):
        return {"success": False, "stage": "dalle", "error": cover.get("error", "unknown")}

    # 2. Push through the fixed create_pod_product (image + correct print_areas schema)
    result = create_pod_product(
        title="NarAI Printify Smoke Test",
        description=(
            "Validation product proving the multi-tenant Printify pipeline works "
            "end-to-end after the print_areas schema fix and image-upload patch."
        ),
        niche="streetwear",
        product_type="t-shirt",
        design_image_path=cover["url"],  # hosted URL — printify_client handles both paths and URLs
        price=29.99,
    )
    return {
        "success": result.get("success", False),
        "design_url": cover["url"],
        "printify_result": result,
    }
