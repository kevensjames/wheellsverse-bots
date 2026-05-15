#!/usr/bin/env python3
"""
core/whop_client.py
─────────────────────────────────────────────────────────────────────────────
WheellsVerse Whop API Client

Whop is a creator-economy marketplace + community + access-control platform.
We use it to sell digital products and gated subscriptions (e.g. Hook Vault Pro).

API base: https://api.whop.com/api/v5/
Docs:     https://dev.whop.com

Auth: Bearer token from WHOP_API_KEY env. Create at:
      whop.com/dashboard → Developer → API Keys

What this client does:
  • list_products()          — list your existing products
  • create_product(...)      — create a new product (digital download or membership)
  • update_product(...)      — update price/metadata
  • list_memberships()       — list active subscribers
  • create_access_pass(...)  — create a subscription tier

Note: Whop's API is read-heavy. Product CREATE is supported but most sellers
do final setup in the Whop dashboard (cover images, custom domains, etc.).
Use this client to bootstrap drafts, then finish in-app.

.env keys:
  WHOP_API_KEY  — bearer token (required)
  WHOP_COMPANY_ID — your Whop company ID (required for product creation)
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

logger = logging.getLogger("whop_client")

API_BASE = "https://api.whop.com/api/v5"


class WhopClient:
    """Minimal Whop API client for digital products + memberships."""

    def __init__(self, api_key: Optional[str] = None, company_id: Optional[str] = None):
        self.api_key = api_key or os.getenv("WHOP_API_KEY", "")
        self.company_id = company_id or os.getenv("WHOP_COMPANY_ID", "")
        if not self.api_key:
            logger.warning("WHOP_API_KEY not set — all calls will fail")

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        if not self.api_key:
            return {"error": "WHOP_API_KEY not set"}
        url = f"{API_BASE}{path}"
        try:
            r = httpx.request(method, url, headers=self._headers, timeout=30, **kwargs)
            if r.status_code >= 400:
                logger.error("Whop %s %s -> %d: %s", method, path, r.status_code, r.text[:200])
                return {"error": f"HTTP {r.status_code}", "detail": r.text[:500]}
            return r.json() if r.text else {}
        except Exception as e:
            logger.error("Whop request failed: %s", e)
            return {"error": str(e)}

    # ─── Products ──────────────────────────────────────────────────────────────

    def list_products(self) -> List[Dict[str, Any]]:
        resp = self._request("GET", "/products")
        return resp.get("data", []) if isinstance(resp, dict) else []

    def get_product(self, product_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/products/{product_id}")

    def create_product(
        self,
        title: str,
        description: str,
        price_usd: float,
        product_type: str = "digital",  # "digital" or "membership"
        tags: Optional[List[str]] = None,
        visibility: str = "visible",
    ) -> Dict[str, Any]:
        """Create a Whop product. Returns the new product object or error."""
        if not self.company_id:
            return {"error": "WHOP_COMPANY_ID not set"}
        body = {
            "company_id": self.company_id,
            "title": title,
            "description": description,
            "visibility": visibility,
            "tags": tags or [],
            "plans": [
                {
                    "plan_type": "one_time" if product_type == "digital" else "renewal",
                    "release_method": "buy_now",
                    "initial_price": price_usd,
                    "currency": "usd",
                    **({"billing_period": 30} if product_type == "membership" else {}),
                }
            ],
        }
        return self._request("POST", "/products", json=body)

    def update_product(self, product_id: str, **fields) -> Dict[str, Any]:
        return self._request("PATCH", f"/products/{product_id}", json=fields)

    # ─── Memberships ───────────────────────────────────────────────────────────

    def list_memberships(self, status: str = "active") -> List[Dict[str, Any]]:
        resp = self._request("GET", f"/memberships?status={status}")
        return resp.get("data", []) if isinstance(resp, dict) else []

    def revoke_membership(self, membership_id: str) -> Dict[str, Any]:
        return self._request("POST", f"/memberships/{membership_id}/cancel")


def _smoke_test():
    c = WhopClient()
    if not c.api_key:
        print("Set WHOP_API_KEY in .env first")
        return
    products = c.list_products()
    print(f"Whop products: {len(products)}")
    for p in products[:5]:
        print(f"  - {p.get('title', '?')} ({p.get('id', '?')})")


if __name__ == "__main__":
    _smoke_test()
