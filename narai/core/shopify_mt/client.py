"""
Stateless Shopify Admin client — scoped to ONE merchant per instance.

Unlike the singleton in core/narai_shopify_engine.py (which reads YOUR store
creds from env), this client takes (shop_domain, access_token) explicitly.
Use it when acting on another merchant's store.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Optional

log = logging.getLogger("shopify_mt.client")

API_VERSION = "2026-04"


class ShopifyAPIError(Exception):
    def __init__(self, status: int, message: str):
        self.status = status
        self.message = message
        super().__init__(f"HTTP {status}: {message}")


class ShopifyAdminClient:
    def __init__(self, shop_domain: str, access_token: str):
        self.shop = shop_domain
        self.token = access_token
        self.base = f"https://{shop_domain}/admin/api/{API_VERSION}"

    def _request(self, method: str, endpoint: str, data: Optional[dict] = None) -> dict:
        url = f"{self.base}/{endpoint.lstrip('/')}"
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(url, data=body, method=method, headers={
            "X-Shopify-Access-Token": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")[:500]
            raise ShopifyAPIError(e.code, body_text) from None

    # ── Convenience wrappers ──────────────────────────────────────────────────

    def create_product(self, product: dict) -> dict:
        return self._request("POST", "products.json", {"product": product}).get("product", {})

    def update_product(self, product_id: int, patch: dict) -> dict:
        patch["id"] = product_id
        return self._request("PUT", f"products/{product_id}.json", {"product": patch}).get("product", {})

    def delete_product(self, product_id: int) -> None:
        self._request("DELETE", f"products/{product_id}.json")

    def attach_image(self, product_id: int, src: str, alt: str = "", position: int = 1) -> dict:
        return self._request("POST", f"products/{product_id}/images.json", {
            "image": {"src": src, "alt": alt, "position": position}
        }).get("image", {})

    def get_product(self, product_id: int) -> dict:
        return self._request("GET", f"products/{product_id}.json").get("product", {})

    def get_shop(self) -> dict:
        return self._request("GET", "shop.json").get("shop", {})
