"""
Shopify OAuth routes — install + callback.

Flow:
  1. Merchant hits /shopify/install?shop=acme.myshopify.com
  2. We validate domain, build authorize URL with signed state, redirect.
  3. Shopify sends merchant back to /shopify/callback with code + hmac + state.
  4. We verify hmac, exchange code for access token, encrypt + store.
  5. Register mandatory webhooks (uninstall, GDPR).
  6. Redirect to connected page.

Required env vars:
  SHOPIFY_API_KEY          — Partner app client ID
  SHOPIFY_API_SECRET       — Partner app client secret
  APP_URL                  — https://app.wheellsverse.com (public callback URL)
  MERCHANT_TOKEN_KEY       — Fernet key for access-token encryption
  SHOPIFY_OAUTH_STATE_KEY  — HMAC key for signing the state nonce
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import time
import urllib.parse
import urllib.request
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from narai.core.shopify_mt import db as mt_db

log = logging.getLogger("shopify_oauth")
router = APIRouter(prefix="/shopify", tags=["shopify-oauth"])

SHOPIFY_API_KEY = os.getenv("SHOPIFY_API_KEY", "")
SHOPIFY_API_SECRET = os.getenv("SHOPIFY_API_SECRET", "")
SHOPIFY_SCOPES = os.getenv(
    "SHOPIFY_SCOPES",
    "read_products,write_products,read_orders,read_inventory,write_inventory",
)
APP_URL = os.getenv("APP_URL", "https://app.wheellsverse.com").rstrip("/")
STATE_KEY = os.getenv("SHOPIFY_OAUTH_STATE_KEY", SHOPIFY_API_SECRET)

SHOP_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
STATE_TTL_SECONDS = 600  # state nonces expire after 10 min


# ─── State nonce (HMAC-signed, stateless) ────────────────────────────────────

def _sign_state(shop: str, nonce: str, ts: int) -> str:
    """state = base64(shop|nonce|ts|hmac)"""
    raw = f"{shop}|{nonce}|{ts}".encode()
    sig = hmac.new(STATE_KEY.encode(), raw, hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{shop}|{nonce}|{ts}|{sig}".encode()).decode()


def _verify_state(state: str, shop: str) -> bool:
    try:
        decoded = base64.urlsafe_b64decode(state.encode()).decode()
        s_shop, nonce, ts_str, sig = decoded.rsplit("|", 3)
        if s_shop != shop:
            return False
        if int(time.time()) - int(ts_str) > STATE_TTL_SECONDS:
            return False
        expected = hmac.new(
            STATE_KEY.encode(), f"{s_shop}|{nonce}|{ts_str}".encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(sig, expected)
    except Exception:
        return False


# ─── HMAC verification of Shopify's callback query params ────────────────────

def _verify_callback_hmac(params: dict) -> bool:
    supplied = params.get("hmac", "")
    if not supplied:
        return False
    query = "&".join(
        f"{k}={v}" for k, v in sorted(params.items()) if k != "hmac"
    )
    digest = hmac.new(
        SHOPIFY_API_SECRET.encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(digest, supplied)


# ─── Routes ──────────────────────────────────────────────────────────────────

@router.get("/install")
def install(shop: str = Query(...)) -> RedirectResponse:
    shop = shop.lower().strip()
    if not SHOP_DOMAIN_RE.match(shop):
        raise HTTPException(400, "Invalid shop domain. Expected *.myshopify.com")
    if not SHOPIFY_API_KEY or not SHOPIFY_API_SECRET:
        raise HTTPException(500, "Shopify app not configured on server")

    nonce = secrets.token_urlsafe(16)
    state = _sign_state(shop, nonce, int(time.time()))

    authorize_url = (
        f"https://{shop}/admin/oauth/authorize?"
        + urllib.parse.urlencode({
            "client_id": SHOPIFY_API_KEY,
            "scope": SHOPIFY_SCOPES,
            "redirect_uri": f"{APP_URL}/shopify/callback",
            "state": state,
        })
    )
    return RedirectResponse(authorize_url)


@router.get("/callback")
def callback(request: Request) -> RedirectResponse:
    params = dict(request.query_params)
    shop = (params.get("shop") or "").lower().strip()
    code = params.get("code", "")
    state = params.get("state", "")

    if not SHOP_DOMAIN_RE.match(shop):
        raise HTTPException(400, "Invalid shop domain")
    if not _verify_callback_hmac(params):
        raise HTTPException(401, "HMAC verification failed")
    if not _verify_state(state, shop):
        raise HTTPException(401, "Invalid or expired state nonce")

    # Exchange authorization code for access token
    body = urllib.parse.urlencode({
        "client_id": SHOPIFY_API_KEY,
        "client_secret": SHOPIFY_API_SECRET,
        "code": code,
    }).encode()
    req = urllib.request.Request(
        f"https://{shop}/admin/oauth/access_token",
        data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            import json
            token_resp = json.loads(resp.read())
    except Exception as e:
        log.exception(f"[shopify_oauth] token exchange failed for {shop}")
        raise HTTPException(502, f"Token exchange failed: {e}")

    access_token = token_resp.get("access_token", "")
    scopes = token_resp.get("scope", "")
    if not access_token:
        raise HTTPException(502, "No access_token in Shopify response")

    # Fetch shop metadata (nice-to-have, not required)
    shop_name: Optional[str] = None
    shop_country: Optional[str] = None
    shop_currency: Optional[str] = None
    owner_email: Optional[str] = None
    try:
        info_req = urllib.request.Request(
            f"https://{shop}/admin/api/2026-04/shop.json",
            headers={"X-Shopify-Access-Token": access_token, "Accept": "application/json"},
        )
        with urllib.request.urlopen(info_req, timeout=10) as r:
            import json
            info = json.loads(r.read()).get("shop", {})
            shop_name = info.get("name")
            shop_country = info.get("country_code")
            shop_currency = info.get("currency")
            owner_email = info.get("email")
    except Exception as e:
        log.warning(f"[shopify_oauth] shop info fetch failed for {shop}: {e}")

    merchant = mt_db.upsert_merchant(
        shop_domain=shop,
        access_token=access_token,
        scopes=scopes,
        owner_email=owner_email,
        shop_name=shop_name,
        shop_country=shop_country,
        shop_currency=shop_currency,
    )
    mt_db.log_event(merchant["id"], "install", {"scopes": scopes})

    # Register mandatory webhooks (uninstall, GDPR) — best-effort.
    try:
        from narai.core.shopify_mt.webhooks import register_mandatory_webhooks
        register_mandatory_webhooks(shop, access_token)
    except Exception as e:
        log.warning(f"[shopify_oauth] webhook registration failed for {shop}: {e}")

    return RedirectResponse(f"{APP_URL}/admin/shopify?installed={shop}")
