"""
Shopify webhook receivers.

All endpoints must verify X-Shopify-Hmac-Sha256 against the raw body, else 401.
The mandatory topics (app/uninstalled + 3 GDPR) are registered during OAuth
install and must return 200 within 5 seconds for App Store approval.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from narai.core.shopify_mt import db as mt_db
from narai.core.shopify_mt.webhooks import verify_hmac

log = logging.getLogger("shopify_webhooks")
router = APIRouter(prefix="/shopify/webhook", tags=["shopify-webhooks"])


async def _read_and_verify(request: Request,
                           hmac_header: str | None) -> tuple[str, dict]:
    raw = await request.body()
    if not verify_hmac(raw, hmac_header or ""):
        raise HTTPException(401, "HMAC verification failed")
    shop = request.headers.get("x-shopify-shop-domain", "").lower()
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}
    return shop, payload


@router.post("/app_uninstalled")
async def app_uninstalled(request: Request,
                          x_shopify_hmac_sha256: str | None = Header(None)):
    shop, payload = await _read_and_verify(request, x_shopify_hmac_sha256)
    merchant = mt_db.get_merchant_by_domain(shop)
    if merchant:
        mt_db.mark_uninstalled(shop)
        mt_db.log_event(merchant["id"], "uninstall", payload)
    return {"ok": True}


@router.post("/customers_data_request")
async def customers_data_request(request: Request,
                                  x_shopify_hmac_sha256: str | None = Header(None)):
    shop, payload = await _read_and_verify(request, x_shopify_hmac_sha256)
    merchant = mt_db.get_merchant_by_domain(shop)
    if merchant:
        mt_db.log_event(merchant["id"], "gdpr.customers_data_request", payload, severity="warn")
    # Shopify requires a 200 within 5s; actual export is handled async by ops.
    return {"ok": True}


@router.post("/customers_redact")
async def customers_redact(request: Request,
                           x_shopify_hmac_sha256: str | None = Header(None)):
    shop, payload = await _read_and_verify(request, x_shopify_hmac_sha256)
    merchant = mt_db.get_merchant_by_domain(shop)
    if merchant:
        mt_db.log_event(merchant["id"], "gdpr.customers_redact", payload, severity="warn")
    return {"ok": True}


@router.post("/shop_redact")
async def shop_redact(request: Request,
                      x_shopify_hmac_sha256: str | None = Header(None)):
    shop, payload = await _read_and_verify(request, x_shopify_hmac_sha256)
    merchant = mt_db.get_merchant_by_domain(shop)
    if merchant:
        mt_db.log_event(merchant["id"], "gdpr.shop_redact", payload, severity="warn")
    # Shopify sends this 48h after uninstall — delete merchant data on the ops side.
    return {"ok": True}
