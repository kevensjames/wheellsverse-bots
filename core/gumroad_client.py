#!/usr/bin/env python3
"""
core/gumroad_client.py
─────────────────────────────────────────────────────────────────────────────
WheellsVerse Gumroad API Client

Gumroad API v2: https://app.gumroad.com/api
Docs:           https://help.gumroad.com/category/api

Auth: Bearer access token. Generate at:
      app.gumroad.com/settings/advanced → "Generate access token"

⚠️ IMPORTANT LIMITATION
Gumroad's public API does NOT support creating products programmatically.
You must create each product manually in the Gumroad dashboard first.
After creation, this client can:
  • list_products()         — list all your products
  • get_product(id)         — get product details
  • update_product(id, ...) — update price/description/published state
  • list_sales(...)         — list recent sales
  • get_sale(id)            — get sale details

For initial product creation, use gumroad_products.csv (in repo root) as your
manual-upload reference, then use this client for ongoing automation.

.env keys:
  GUMROAD_ACCESS_TOKEN  — access token from app.gumroad.com/settings/advanced
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

logger = logging.getLogger("gumroad_client")

API_BASE = "https://api.gumroad.com/v2"


class GumroadClient:
    """Gumroad API v2 client. Read + update only — product creation is dashboard-only."""

    def __init__(self, access_token: Optional[str] = None):
        self.access_token = access_token or os.getenv("GUMROAD_ACCESS_TOKEN", "")
        if not self.access_token:
            logger.warning("GUMROAD_ACCESS_TOKEN not set — all calls will fail")

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        if not self.access_token:
            return {"success": False, "error": "GUMROAD_ACCESS_TOKEN not set"}
        url = f"{API_BASE}{path}"
        params = kwargs.pop("params", {}) or {}
        params["access_token"] = self.access_token
        try:
            r = httpx.request(method, url, params=params, timeout=30, **kwargs)
            if r.status_code >= 400:
                logger.error("Gumroad %s %s -> %d: %s", method, path, r.status_code, r.text[:200])
                return {"success": False, "error": f"HTTP {r.status_code}", "detail": r.text[:500]}
            data = r.json()
            if not data.get("success", True):
                logger.warning("Gumroad API success=false: %s", data.get("message", ""))
            return data
        except Exception as e:
            logger.error("Gumroad request failed: %s", e)
            return {"success": False, "error": str(e)}

    # ─── Products ──────────────────────────────────────────────────────────────

    def list_products(self) -> List[Dict[str, Any]]:
        resp = self._request("GET", "/products")
        return resp.get("products", []) if resp.get("success") else []

    def get_product(self, product_id: str) -> Dict[str, Any]:
        resp = self._request("GET", f"/products/{product_id}")
        return resp.get("product", {}) if resp.get("success") else resp

    def update_product(
        self,
        product_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        price_cents: Optional[int] = None,  # Gumroad uses cents (e.g. $19 = 1900)
        tags: Optional[List[str]] = None,
        custom_permalink: Optional[str] = None,
        published: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Update an existing product. Pass only fields you want to change."""
        body: Dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if price_cents is not None:
            body["price"] = price_cents
        if tags is not None:
            body["tags"] = ",".join(tags)
        if custom_permalink is not None:
            body["custom_permalink"] = custom_permalink
        if published is not None:
            body["published"] = "true" if published else "false"
        return self._request("PUT", f"/products/{product_id}", data=body)

    def enable_product(self, product_id: str) -> Dict[str, Any]:
        return self._request("PUT", f"/products/{product_id}/enable")

    def disable_product(self, product_id: str) -> Dict[str, Any]:
        return self._request("PUT", f"/products/{product_id}/disable")

    # ─── Sales / Revenue ───────────────────────────────────────────────────────

    def list_sales(
        self,
        product_id: Optional[str] = None,
        email: Optional[str] = None,
        after: Optional[str] = None,  # ISO date "2026-05-01"
        before: Optional[str] = None,
        page: int = 1,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"page": page}
        if product_id:
            params["product_id"] = product_id
        if email:
            params["email"] = email
        if after:
            params["after"] = after
        if before:
            params["before"] = before
        resp = self._request("GET", "/sales", params=params)
        return resp.get("sales", []) if resp.get("success") else []

    def get_sale(self, sale_id: str) -> Dict[str, Any]:
        resp = self._request("GET", f"/sales/{sale_id}")
        return resp.get("sale", {}) if resp.get("success") else resp

    # ─── Helper: update from listings_master.md row ────────────────────────────

    def sync_from_listing(
        self,
        product_id: str,
        name: str,
        description: str,
        price_usd: float,
        tags: List[str],
        custom_permalink: str,
    ) -> Dict[str, Any]:
        """Convenience: sync a single product from the listings_master format."""
        return self.update_product(
            product_id,
            name=name,
            description=description,
            price_cents=int(price_usd * 100),
            tags=tags,
            custom_permalink=custom_permalink,
            published=True,
        )


def _smoke_test():
    c = GumroadClient()
    if not c.access_token:
        print("Set GUMROAD_ACCESS_TOKEN in .env first")
        return
    products = c.list_products()
    print(f"Gumroad products: {len(products)}")
    for p in products[:5]:
        print(f"  - {p.get('name', '?')} (id={p.get('id', '?')}, ${p.get('price', 0) / 100:.2f})")


if __name__ == "__main__":
    _smoke_test()
