#!/usr/bin/env python3
"""
core/etsy_client.py
─────────────────────────────────────────────────────────────────────────────
WheellsVerse Etsy Open API v3 Client

Etsy Open API v3: https://openapi.etsy.com/v3/
Docs:             https://developer.etsy.com/documentation/

Auth: OAuth 2.0 with PKCE — required for any shop-write action.
  1. etsy.com/developers/your-account → register app → get keystring
  2. Set ETSY_KEYSTRING and ETSY_SHARED_SECRET in .env
  3. Run /api/etsy/oauth-url to start install flow
  4. After approval, token saved to data/etsy_token.json

What this client does:
  • get_user()                      — fetch authenticated user info
  • get_shops()                     — list shops you own
  • create_draft_listing(...)       — create a digital-product draft listing
  • upload_listing_image(...)       — attach image to listing
  • upload_digital_file(...)        — attach the downloadable file
  • publish_listing(...)            — flip draft to active (LIVE on Etsy)
  • list_listings(...)              — list your own shop's listings

.env keys:
  ETSY_KEYSTRING       — app keystring from developer.etsy.com
  ETSY_SHARED_SECRET   — shared secret
  ETSY_REDIRECT_URI    — your OAuth callback URL
  ETSY_SHOP_ID         — your shop ID (cached after first auth)
─────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
TOKEN_FILE = DATA_DIR / "etsy_token.json"

logger = logging.getLogger("etsy_client")

API_BASE = "https://openapi.etsy.com/v3"
OAUTH_BASE = "https://www.etsy.com/oauth/connect"


def _load_token() -> Dict[str, Any]:
    if TOKEN_FILE.exists():
        try:
            return json.loads(TOKEN_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_token(data: Dict[str, Any]) -> None:
    TOKEN_FILE.write_text(json.dumps(data, indent=2))


class EtsyClient:
    """Etsy Open API v3 client — focused on digital-product listings."""

    def __init__(self):
        self.keystring = os.getenv("ETSY_KEYSTRING", "")
        self.shared_secret = os.getenv("ETSY_SHARED_SECRET", "")
        self.shop_id = os.getenv("ETSY_SHOP_ID", "")
        self._token_data = _load_token()
        if not self.keystring:
            logger.warning("ETSY_KEYSTRING not set — all calls will fail")

    @property
    def access_token(self) -> str:
        return self._token_data.get("access_token", "")

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.keystring,
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        if not self.keystring or not self.access_token:
            return {"error": "Etsy not authenticated — run OAuth install flow"}
        url = f"{API_BASE}{path}"
        try:
            r = httpx.request(method, url, headers=self._headers, timeout=30, **kwargs)
            if r.status_code == 401:
                logger.warning("Etsy 401 — token expired, refresh required")
            if r.status_code >= 400:
                logger.error("Etsy %s %s -> %d: %s", method, path, r.status_code, r.text[:200])
                return {"error": f"HTTP {r.status_code}", "detail": r.text[:500]}
            return r.json() if r.text else {}
        except Exception as e:
            logger.error("Etsy request failed: %s", e)
            return {"error": str(e)}

    # ─── OAuth helpers (used by /api/etsy/* routes) ────────────────────────────

    def get_auth_url(self, redirect_uri: str, scopes: List[str], state: str, code_challenge: str) -> str:
        """Build the OAuth authorization URL. PKCE code_challenge is required by Etsy."""
        import urllib.parse
        params = {
            "response_type": "code",
            "client_id": self.keystring,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{OAUTH_BASE}?{urllib.parse.urlencode(params)}"

    def exchange_code(self, code: str, redirect_uri: str, code_verifier: str) -> Dict[str, Any]:
        """Exchange OAuth code for access token (PKCE flow)."""
        try:
            r = httpx.post(
                "https://api.etsy.com/v3/public/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.keystring,
                    "redirect_uri": redirect_uri,
                    "code": code,
                    "code_verifier": code_verifier,
                },
                timeout=15,
            )
            data = r.json()
            if "access_token" in data:
                _save_token(data)
                self._token_data = data
            return data
        except Exception as e:
            return {"error": str(e)}

    # ─── User + Shop ───────────────────────────────────────────────────────────

    def get_user(self) -> Dict[str, Any]:
        return self._request("GET", "/application/users/me")

    def get_shops(self) -> List[Dict[str, Any]]:
        user = self.get_user()
        uid = user.get("user_id")
        if not uid:
            return []
        resp = self._request("GET", f"/application/users/{uid}/shops")
        return [resp] if "shop_id" in resp else []

    # ─── Listings ──────────────────────────────────────────────────────────────

    def create_draft_listing(
        self,
        title: str,
        description: str,
        price_usd: float,
        quantity: int = 999,
        tags: Optional[List[str]] = None,
        taxonomy_id: int = 76,  # 76 = Paper & Party Supplies > Stationery > Other
        is_digital: bool = True,
    ) -> Dict[str, Any]:
        """Create a draft listing for a digital product. Tags max 13, each ≤20 chars."""
        if not self.shop_id:
            return {"error": "ETSY_SHOP_ID not set — call get_shops() and cache it"}
        body = {
            "quantity": quantity,
            "title": title[:140],
            "description": description,
            "price": float(price_usd),
            "who_made": "i_did",
            "when_made": "made_to_order",
            "taxonomy_id": taxonomy_id,
            "type": "download" if is_digital else "physical",
            "is_supply": False,
            "shipping_profile_id": None,  # digital listings don't need one
            "tags": (tags or [])[:13],
        }
        return self._request(
            "POST",
            f"/application/shops/{self.shop_id}/listings",
            json=body,
        )

    def upload_listing_image(self, listing_id: int, image_path: str, rank: int = 1) -> Dict[str, Any]:
        """Attach an image to a listing. Etsy expects multipart/form-data here."""
        if not self.shop_id:
            return {"error": "ETSY_SHOP_ID not set"}
        try:
            with open(image_path, "rb") as f:
                files = {"image": (Path(image_path).name, f, "image/jpeg")}
                r = httpx.post(
                    f"{API_BASE}/application/shops/{self.shop_id}/listings/{listing_id}/images",
                    headers={
                        "x-api-key": self.keystring,
                        "Authorization": f"Bearer {self.access_token}",
                    },
                    files=files,
                    data={"rank": rank},
                    timeout=60,
                )
            return r.json() if r.status_code < 400 else {"error": r.text[:500]}
        except Exception as e:
            return {"error": str(e)}

    def upload_digital_file(self, listing_id: int, file_path: str, name: str = "") -> Dict[str, Any]:
        """Attach a downloadable digital file (PDF, ZIP, etc.) to a digital listing."""
        if not self.shop_id:
            return {"error": "ETSY_SHOP_ID not set"}
        try:
            with open(file_path, "rb") as f:
                files = {"file": (name or Path(file_path).name, f, "application/octet-stream")}
                r = httpx.post(
                    f"{API_BASE}/application/shops/{self.shop_id}/listings/{listing_id}/files",
                    headers={
                        "x-api-key": self.keystring,
                        "Authorization": f"Bearer {self.access_token}",
                    },
                    files=files,
                    timeout=120,
                )
            return r.json() if r.status_code < 400 else {"error": r.text[:500]}
        except Exception as e:
            return {"error": str(e)}

    def publish_listing(self, listing_id: int) -> Dict[str, Any]:
        """Flip a draft listing to active (LIVE on Etsy)."""
        return self._request(
            "PATCH",
            f"/application/shops/{self.shop_id}/listings/{listing_id}",
            json={"state": "active"},
        )

    def list_listings(self, state: str = "active", limit: int = 25) -> List[Dict[str, Any]]:
        if not self.shop_id:
            return []
        resp = self._request(
            "GET",
            f"/application/shops/{self.shop_id}/listings/{state}?limit={limit}",
        )
        return resp.get("results", []) if isinstance(resp, dict) else []


def _smoke_test():
    c = EtsyClient()
    if not c.access_token:
        print("Etsy OAuth not completed — run /api/etsy/oauth-url to install")
        return
    user = c.get_user()
    print(f"Etsy user: {user.get('login_name', user)}")


if __name__ == "__main__":
    _smoke_test()
