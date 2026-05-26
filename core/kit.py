#!/usr/bin/env python3
"""
core/kit.py
─────────────────────────────────────────────────────────────────────────────
Kit (formerly ConvertKit) API v4 client.

Base URL : https://api.kit.com/v4
Auth     : X-Kit-Api-Key: <KIT_API_KEY>

Coexists with core/convertkit.py (which uses the legacy v3 api.convertkit.com
endpoint set + api_secret-in-body auth). Use this module for any new code; the
v3 module is kept only for backward compatibility with existing lead-capture
flows already in production.

Endpoint shapes verified against developers.kit.com/api-reference/* on
2026-05-22. Notable v4 differences vs v3:
  - Subscriber upsert is by email_address (not email).
  - Tagging:   POST /v4/tags/{tag_id}/subscribers/{subscriber_id}  body: {}
  - Sequence:  POST /v4/sequences/{sequence_id}/subscribers/{subscriber_id}
               body: {}   (subscriber MUST already exist)

Env vars
  KIT_API_KEY     — from Kit → Settings → Advanced → API Keys (v4 key)
  KIT_API_BASE    — defaults to https://api.kit.com/v4
  KIT_DRY_RUN     — "true" / "1" → log every intended write call, do NOT
                    send it to Kit. Returns synthesised responses with
                    "_dry_run": true so callers can verify wiring.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("kit")

DEFAULT_BASE = "https://api.kit.com/v4"
DEFAULT_RATE_LIMIT_PER_SEC = 4  # Kit's documented rate ceiling is higher; this is a courteous self-limit


def _is_truthy(val: Optional[str]) -> bool:
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


class KitClient:
    """Thin Kit v4 client with dry-run, rate-limit, and structured call logging."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        dry_run: Optional[bool] = None,
        rate_limit_per_sec: float = DEFAULT_RATE_LIMIT_PER_SEC,
    ):
        self.api_key = api_key or os.getenv("KIT_API_KEY", "")
        self.base_url = (base_url or os.getenv("KIT_API_BASE") or DEFAULT_BASE).rstrip("/")
        self.dry_run = _is_truthy(os.getenv("KIT_DRY_RUN")) if dry_run is None else dry_run
        self._rate_window = 1.0 / max(rate_limit_per_sec, 0.1)
        self._last_call = 0.0
        self._lock = Lock()

    # ── HTTP plumbing ─────────────────────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        return {"X-Kit-Api-Key": self.api_key, "Accept": "application/json"}

    def _throttle(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._rate_window - (now - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()

    def _log_call(self, method: str, url: str, body: Any, status: int, ok: bool, dry: bool) -> None:
        marker = "DRY" if dry else ("OK" if ok else "ERR")
        logger.info("[kit %s] %s %s status=%s body=%s", marker, method, url, status, body if body is not None else {})

    def _request(self, method: str, path: str, *, body: Any = None, params: Optional[Dict] = None,
                 writes: bool = False) -> Dict:
        if not self.api_key:
            return {"error": "KIT_API_KEY not set", "status": 0}

        url = f"{self.base_url}{path}"

        if writes and self.dry_run:
            self._log_call(method, url, body, status=0, ok=True, dry=True)
            return {"_dry_run": True, "method": method, "url": url, "body": body or {}, "status": 0}

        self._throttle()
        try:
            r = requests.request(
                method, url,
                headers=self._headers(),
                json=body if body is not None else None,
                params=params or None,
                timeout=15,
            )
        except requests.RequestException as e:
            logger.error("[kit NET] %s %s failed: %s", method, url, e)
            return {"error": str(e), "status": 0}

        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text}

        self._log_call(method, url, body, status=r.status_code, ok=r.ok, dry=False)
        data["status"] = r.status_code
        return data

    # ── Account ───────────────────────────────────────────────────────────────

    def get_account(self) -> Dict:
        return self._request("GET", "/account")

    def is_configured(self) -> bool:
        return bool(self.api_key)

    # ── Tags ──────────────────────────────────────────────────────────────────

    def list_tags(self) -> List[Dict]:
        data = self._request("GET", "/tags")
        return data.get("tags", []) if isinstance(data.get("tags"), list) else []

    def create_tag(self, name: str) -> Dict:
        return self._request("POST", "/tags", body={"name": name}, writes=True)

    def tag_subscriber(self, tag_id: int, subscriber_id: int) -> Dict:
        return self._request(
            "POST", f"/tags/{tag_id}/subscribers/{subscriber_id}",
            body={}, writes=True,
        )

    # ── Sequences ─────────────────────────────────────────────────────────────

    def list_sequences(self) -> List[Dict]:
        data = self._request("GET", "/sequences")
        return data.get("sequences", []) if isinstance(data.get("sequences"), list) else []

    def add_subscriber_to_sequence(self, sequence_id: int, subscriber_id: int) -> Dict:
        return self._request(
            "POST", f"/sequences/{sequence_id}/subscribers/{subscriber_id}",
            body={}, writes=True,
        )

    # ── Subscribers ───────────────────────────────────────────────────────────

    def upsert_subscriber(self, email_address: str, first_name: str = "",
                          fields: Optional[Dict] = None) -> Dict:
        body: Dict[str, Any] = {"email_address": email_address}
        if first_name:
            body["first_name"] = first_name
        if fields:
            body["fields"] = fields
        return self._request("POST", "/subscribers", body=body, writes=True)

    def get_subscriber(self, subscriber_id: int) -> Dict:
        return self._request("GET", f"/subscribers/{subscriber_id}")

    # ── Webhooks ──────────────────────────────────────────────────────────────

    def list_webhooks(self) -> List[Dict]:
        data = self._request("GET", "/webhooks")
        return data.get("webhooks", []) if isinstance(data.get("webhooks"), list) else []

    def create_webhook(self, target_url: str, event: Dict) -> Dict:
        """event: e.g. {"name": "subscriber.subscriber_activated"}"""
        return self._request(
            "POST", "/webhooks",
            body={"target_url": target_url, "event": event},
            writes=True,
        )


_client: Optional[KitClient] = None


def get_kit() -> KitClient:
    global _client
    if _client is None:
        _client = KitClient()
    return _client
