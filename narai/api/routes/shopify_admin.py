"""
Admin API for the multi-tenant Shopify dashboard.

Endpoints are auth-gated via the existing Bearer-token guard (reuses
whichever auth pattern the other admin routes use).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from core.narai_user import get_supabase, verify_token
from narai.core.shopify_mt.billing import PLAN_LIMITS, TIER_ORDER, PRICE_IDS


def verify_token_user(authorization: str = Header(None)) -> dict:
    """FastAPI dep: extract Bearer token, verify against Supabase, return user."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.split(None, 1)[1].strip()
    user = verify_token(token)
    if not user:
        raise HTTPException(401, "Invalid or expired token")
    return user

log = logging.getLogger("shopify_admin")
router = APIRouter(prefix="/api/narai/shopify", tags=["shopify-admin"])

PLAN_MONTHLY_USD = {"free": 0, "starter": 19, "pro": 49, "elite": 149}


@router.get("/merchants")
def list_merchants(user=Depends(verify_token_user)) -> dict:
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
def merchant_detail(merchant_id: str, user=Depends(verify_token_user)) -> dict:
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
def list_plans(user=Depends(verify_token_user)) -> dict:
    """Plans the admin dashboard can offer to merchants."""
    return {
        "tiers": TIER_ORDER,
        "limits": PLAN_LIMITS,
        "monthly_usd": PLAN_MONTHLY_USD,
        "stripe_configured": all(PRICE_IDS.get(t) for t in ("starter", "pro", "elite")),
    }
