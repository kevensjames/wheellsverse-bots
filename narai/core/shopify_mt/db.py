"""
Supabase DB layer for multi-tenant Shopify.

All reads/writes to merchants / merchant_products / merchant_events /
merchant_billing go through this module. Access tokens are decrypted
lazily only where needed.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from core.narai_user import get_supabase  # reuses the existing service_role client
from narai.core.shopify_mt.crypto import decrypt, encrypt

log = logging.getLogger("shopify_mt.db")


# ─── merchants ────────────────────────────────────────────────────────────────

def upsert_merchant(
    shop_domain: str,
    access_token: str,
    scopes: str,
    owner_email: Optional[str] = None,
    shop_name: Optional[str] = None,
    shop_country: Optional[str] = None,
    shop_currency: Optional[str] = None,
) -> dict:
    """Insert or reinstall a merchant. Token is encrypted before persisting."""
    sb = get_supabase()
    row = {
        "shop_domain": shop_domain,
        "access_token_encrypted": encrypt(access_token),
        "scopes": scopes,
        "owner_email": owner_email,
        "shop_name": shop_name,
        "shop_country": shop_country,
        "shop_currency": shop_currency or "USD",
        "uninstalled_at": None,  # clear soft-delete on reinstall
    }
    resp = sb.table("merchants").upsert(row, on_conflict="shop_domain").execute()
    return resp.data[0] if resp.data else {}


def get_merchant_by_domain(shop_domain: str) -> Optional[dict]:
    sb = get_supabase()
    resp = sb.table("merchants").select("*").eq("shop_domain", shop_domain).limit(1).execute()
    return resp.data[0] if resp.data else None


def get_merchant_by_id(merchant_id: str) -> Optional[dict]:
    sb = get_supabase()
    resp = sb.table("merchants").select("*").eq("id", merchant_id).limit(1).execute()
    return resp.data[0] if resp.data else None


def get_decrypted_token(merchant: dict) -> str:
    """Decrypt only at the call site — never persist or log the plaintext."""
    return decrypt(merchant["access_token_encrypted"])


def mark_uninstalled(shop_domain: str) -> None:
    sb = get_supabase()
    sb.table("merchants").update({
        "uninstalled_at": "now()",
    }).eq("shop_domain", shop_domain).execute()


def update_plan(merchant_id: str, plan_tier: str,
                stripe_customer_id: Optional[str] = None,
                stripe_subscription_id: Optional[str] = None) -> None:
    sb = get_supabase()
    patch: dict[str, Any] = {"plan_tier": plan_tier}
    if stripe_customer_id:
        patch["stripe_customer_id"] = stripe_customer_id
    if stripe_subscription_id:
        patch["stripe_subscription_id"] = stripe_subscription_id
    sb.table("merchants").update(patch).eq("id", merchant_id).execute()


# ─── merchant_events (audit log) ──────────────────────────────────────────────

def log_event(
    merchant_id: str,
    event_type: str,
    payload: Optional[dict] = None,
    severity: str = "info",
) -> None:
    try:
        sb = get_supabase()
        sb.table("merchant_events").insert({
            "merchant_id": merchant_id,
            "event_type": event_type,
            "severity": severity,
            "payload": payload or {},
        }).execute()
    except Exception as e:
        # Audit log failure should never break the main flow — just warn.
        log.warning(f"[shopify_mt.db] log_event({event_type}) failed: {e}")


# ─── merchant_products ────────────────────────────────────────────────────────

def save_merchant_product(
    merchant_id: str,
    shopify_product_id: int,
    title: str,
    source: str,
    images_count: int,
    quality_gate_passed: bool,
    published: bool,
    price_cents: Optional[int] = None,
    shopify_handle: Optional[str] = None,
    printify_product_id: Optional[str] = None,
) -> dict:
    sb = get_supabase()
    resp = sb.table("merchant_products").upsert({
        "merchant_id": merchant_id,
        "shopify_product_id": shopify_product_id,
        "shopify_handle": shopify_handle,
        "title": title,
        "source": source,
        "images_count": images_count,
        "quality_gate_passed": quality_gate_passed,
        "published": published,
        "price_cents": price_cents,
        "printify_product_id": printify_product_id,
    }, on_conflict="merchant_id,shopify_product_id").execute()
    return resp.data[0] if resp.data else {}


# ─── merchant_billing ─────────────────────────────────────────────────────────

def record_billing_event(
    merchant_id: str,
    stripe_event_id: str,
    stripe_event_type: str,
    status: str,
    amount_cents: Optional[int] = None,
    currency: str = "usd",
    stripe_invoice_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> bool:
    """Return True if new, False if duplicate Stripe event."""
    sb = get_supabase()
    try:
        sb.table("merchant_billing").insert({
            "merchant_id": merchant_id,
            "stripe_event_id": stripe_event_id,
            "stripe_event_type": stripe_event_type,
            "status": status,
            "amount_cents": amount_cents,
            "currency": currency,
            "stripe_invoice_id": stripe_invoice_id,
            "metadata": metadata or {},
        }).execute()
        return True
    except Exception as e:
        # Unique constraint violation → already recorded
        if "duplicate" in str(e).lower() or "unique" in str(e).lower():
            return False
        raise
