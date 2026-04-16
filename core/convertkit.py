#!/usr/bin/env python3
"""
core/convertkit.py
─────────────────────────────────────────────────────────────────────────────
ConvertKit (Kit) API v4 integration.

Revenue model: 30% RECURRING commission on every paid subscriber you refer.
One subscriber who stays 12 months = 12 commissions.

Credentials needed in .env:
  CONVERTKIT_API_KEY     — Settings → Developer → API Keys
  CONVERTKIT_API_SECRET  — same page
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("convertkit")

BASE = "https://api.convertkit.com/v3"


class ConvertKitClient:

    def __init__(self):
        self.api_key = os.getenv("CONVERTKIT_API_KEY", "")
        self.api_secret = os.getenv("CONVERTKIT_API_SECRET", "")
        self.affiliate_url = os.getenv("AFFILIATE_CONVERTKIT_URL", "")

    def _get(self, path: str, params: dict = None) -> Dict:
        p = {"api_secret": self.api_secret, **(params or {})}
        r = requests.get(f"{BASE}{path}", params=p, timeout=15)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict = None) -> Dict:
        payload = {"api_secret": self.api_secret, **(body or {})}
        r = requests.post(f"{BASE}{path}", json=payload, timeout=15)
        r.raise_for_status()
        return r.json()

    # ── Subscribers ────────────────────────────────────────────────────────────

    def add_subscriber(self, email: str, first_name: str = "",
                       tags: List[str] = None, fields: Dict = None) -> Dict:
        """Add / update a subscriber."""
        body: Dict = {"email": email}
        if first_name:
            body["first_name"] = first_name
        if fields:
            body["fields"] = fields
        result = self._post("/subscribers", body)
        if tags:
            sub_id = result.get("subscriber", {}).get("id")
            if sub_id:
                self.add_tags(sub_id, tags)
        logger.info(f"Subscriber added: {email}")
        return result

    def list_subscribers(self, page: int = 1) -> Dict:
        return self._get("/subscribers", {"page": page})

    def get_subscriber_count(self) -> int:
        data = self._get("/subscribers")
        return data.get("total_subscribers", 0)

    # ── Tags ───────────────────────────────────────────────────────────────────

    def list_tags(self) -> List[Dict]:
        return self._get("/tags").get("tags", [])

    def create_tag(self, name: str) -> Dict:
        return self._post("/tags", {"tag": {"name": name}})

    def add_tags(self, subscriber_id: int, tags: List[str]):
        for tag_name in tags:
            # Find or create tag
            existing = {t["name"]: t["id"] for t in self.list_tags()}
            tag_id = existing.get(tag_name)
            if not tag_id:
                t = self.create_tag(tag_name)
                tag_id = t.get("id") or t.get("tag", {}).get("id")
            if tag_id:
                self._post(f"/tags/{tag_id}/subscribe", {"subscriber": {"id": subscriber_id}})

    # ── Sequences / Automations ────────────────────────────────────────────────

    def list_sequences(self) -> List[Dict]:
        return self._get("/sequences").get("courses", [])

    def add_to_sequence(self, email: str, sequence_id: int) -> Dict:
        return self._post(f"/sequences/{sequence_id}/subscribe", {"email": email})

    # ── Broadcasts (one-off emails) ────────────────────────────────────────────

    def list_broadcasts(self) -> List[Dict]:
        return self._get("/broadcasts").get("broadcasts", [])

    def create_broadcast(self, subject: str, content: str,
                         description: str = "") -> Dict:
        """Create a draft broadcast email. Returns draft even if send address unconfirmed."""
        import requests as _req
        body = {
            "api_secret": self.api_secret,
            "subject": subject,
            "content": content,
            "description": description or subject,
        }
        r = _req.post(f"{BASE}/broadcasts", json=body, timeout=15)
        if r.status_code == 422:
            msg = r.json().get("message", "")
            if "saved as a draft" in msg or "send address" in msg:
                logger.info(f"Broadcast saved as draft (confirm send address in ConvertKit): {subject}")
                return {"broadcast": {"id": None}, "status": "draft", "message": msg}
            r.raise_for_status()
        r.raise_for_status()
        logger.info(f"Broadcast created: {subject}")
        return r.json()

    def send_broadcast(self, broadcast_id: int) -> Dict:
        """Send a draft broadcast to all subscribers immediately."""
        result = self._post(f"/broadcasts/{broadcast_id}/send", {})
        logger.info(f"Broadcast {broadcast_id} sent")
        return result

    # ── Forms ──────────────────────────────────────────────────────────────────

    def list_forms(self) -> List[Dict]:
        return self._get("/forms").get("forms", [])

    def subscribe_to_form(self, form_id: int, email: str,
                          first_name: str = "") -> Dict:
        body: Dict = {"email": email}
        if first_name:
            body["first_name"] = first_name
        return self._post(f"/forms/{form_id}/subscribe", body)

    # ── Status ─────────────────────────────────────────────────────────────────

    def is_connected(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def get_status(self) -> Dict:
        connected = self.is_connected()
        subscriber_count = 0
        if connected:
            try:
                subscriber_count = self.get_subscriber_count()
            except Exception:
                pass
        return {
            "connected": connected,
            "api_key": self.api_key[:8] + "..." if self.api_key else "",
            "subscriber_count": subscriber_count,
            "affiliate_url": self.affiliate_url,
        }


_client: Optional[ConvertKitClient] = None


def get_convertkit() -> ConvertKitClient:
    global _client
    if _client is None:
        _client = ConvertKitClient()
    return _client
