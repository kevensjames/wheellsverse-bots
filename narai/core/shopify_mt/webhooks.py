"""
Shopify webhook helpers — HMAC verification + mandatory topic registration.

Required Shopify webhooks for App Store approval:
  - app/uninstalled
  - customers/data_request  (GDPR)
  - customers/redact        (GDPR)
  - shop/redact             (GDPR)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import urllib.request
from typing import Iterable

log = logging.getLogger("shopify_mt.webhooks")

SHOPIFY_API_SECRET = os.getenv("SHOPIFY_API_SECRET", "")
APP_URL = os.getenv("APP_URL", "https://app.wheellsverse.com").rstrip("/")

MANDATORY_TOPICS: tuple[str, ...] = (
    "app/uninstalled",
    "customers/data_request",
    "customers/redact",
    "shop/redact",
)


def verify_hmac(raw_body: bytes, hmac_header: str) -> bool:
    """Verify Shopify's X-Shopify-Hmac-Sha256 header against raw request body."""
    if not hmac_header or not SHOPIFY_API_SECRET:
        return False
    digest = hmac.new(SHOPIFY_API_SECRET.encode(), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, hmac_header)


def register_mandatory_webhooks(shop: str, access_token: str,
                                 topics: Iterable[str] = MANDATORY_TOPICS) -> dict[str, bool]:
    """Register the GDPR + uninstall webhooks on a freshly installed merchant."""
    results: dict[str, bool] = {}
    for topic in topics:
        endpoint = f"{APP_URL}/shopify/webhook/{topic.replace('/', '_')}"
        payload = json.dumps({
            "webhook": {"topic": topic, "address": endpoint, "format": "json"}
        }).encode()
        req = urllib.request.Request(
            f"https://{shop}/admin/api/2026-04/webhooks.json",
            data=payload, method="POST",
            headers={
                "X-Shopify-Access-Token": access_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                r.read()
                results[topic] = True
        except Exception as e:
            log.warning(f"[webhooks] register {topic} for {shop} failed: {e}")
            results[topic] = False
    return results
