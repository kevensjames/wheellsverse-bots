#!/usr/bin/env python3
"""
core/meta_ads.py
─────────────────────────────────────────────────────────────────────────────
Thin Meta Marketing API (Graph) wrapper for the Toodle Ads Agent.

This is a different surface from core/facebook.py, which posts organic
content to a Page. The Marketing API needs a User Access Token with
`ads_management` + `ads_read` scopes and admin access to an Ad Account.

Endpoints in scope (Graph v19.0 by default):
  POST /act_{ad_account_id}/adimages         — upload creative
  POST /act_{ad_account_id}/campaigns        — create campaign (PAUSED)
  POST /act_{ad_account_id}/adsets           — create adset (PAUSED)
  POST /act_{ad_account_id}/adcreatives      — create creative
  POST /act_{ad_account_id}/ads              — create ad (PAUSED)
  GET  /{node_id}                            — verify status

All write methods print structured logs and return the JSON Graph payload.
Status is always PAUSED for safety; the caller (scripts/meta_first_ad.py)
intentionally does NOT activate. The user reviews in Ads Manager and flips
it to ACTIVE manually.

Env vars
  META_ACCESS_TOKEN      — User Access Token (ads_management + ads_read)
  AD_ACCOUNT_ID          — numeric (no "act_" prefix)
  PAGE_ID                — numeric Facebook Page ID
  META_GRAPH_VERSION     — default "v19.0"
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("meta_ads")

DEFAULT_VERSION = "v19.0"
GRAPH_BASE = "https://graph.facebook.com"


class MetaAdsError(RuntimeError):
    """Raised when the Graph API returns an error payload."""

    def __init__(self, message: str, payload: Any = None, status_code: int = 0):
        super().__init__(message)
        self.payload = payload
        self.status_code = status_code


class MetaAdsClient:
    """Minimal Marketing API client. One token, one ad account."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        ad_account_id: Optional[str] = None,
        page_id: Optional[str] = None,
        version: Optional[str] = None,
    ):
        self.access_token = access_token or os.getenv("META_ACCESS_TOKEN", "")
        ad_acc = ad_account_id or os.getenv("AD_ACCOUNT_ID") or os.getenv("FB_AD_ACCOUNT_ID", "")
        self.ad_account_id = ad_acc.replace("act_", "")  # accept either form
        self.page_id = page_id or os.getenv("PAGE_ID") or os.getenv("FACEBOOK_PAGE_ID", "")
        self.version = version or os.getenv("META_GRAPH_VERSION", DEFAULT_VERSION)

    # ── Plumbing ──────────────────────────────────────────────────────────────

    @property
    def base(self) -> str:
        return f"{GRAPH_BASE}/{self.version}"

    @property
    def acct(self) -> str:
        return f"act_{self.ad_account_id}"

    def is_configured(self) -> bool:
        return bool(self.access_token and self.ad_account_id and self.page_id)

    def _post(self, path: str, *, data: Optional[Dict[str, Any]] = None,
              files: Optional[Dict] = None) -> Dict:
        url = f"{self.base}{path}"
        payload = {"access_token": self.access_token, **(data or {})}
        logger.info("[meta_ads POST] %s data_keys=%s files=%s",
                    url, sorted(payload.keys()), bool(files))
        r = requests.post(url, data=payload, files=files, timeout=60)
        return self._handle(r, "POST", url)

    def _get(self, node_id: str, *, fields: Optional[str] = None) -> Dict:
        url = f"{self.base}/{node_id}"
        params: Dict[str, Any] = {"access_token": self.access_token}
        if fields:
            params["fields"] = fields
        logger.info("[meta_ads GET] %s fields=%s", url, fields)
        r = requests.get(url, params=params, timeout=30)
        return self._handle(r, "GET", url)

    @staticmethod
    def _handle(r: requests.Response, method: str, url: str) -> Dict:
        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text}
        if not r.ok or "error" in data:
            err = (data.get("error") or {}).get("message", data)
            logger.error("[meta_ads ERR] %s %s status=%s err=%s", method, url, r.status_code, err)
            raise MetaAdsError(
                f"{method} {url} → {r.status_code}: {err}",
                payload=data, status_code=r.status_code,
            )
        return data

    # ── Step 1 — Upload image ────────────────────────────────────────────────

    def upload_image(self, image_path: str) -> str:
        """POST /act_{id}/adimages → returns image_hash."""
        p = Path(image_path)
        if not p.exists():
            raise FileNotFoundError(f"creative image not found: {image_path}")

        with p.open("rb") as f:
            data = self._post(
                f"/{self.acct}/adimages",
                files={"source": (p.name, f, "image/jpeg" if p.suffix.lower() in {".jpg", ".jpeg"} else "image/png")},
            )

        # Response shape: {"images": {"<filename>": {"hash": "...", "url": "..."}}}
        images = data.get("images") or {}
        if not images:
            raise MetaAdsError("upload_image: no images in response", payload=data)
        # Take the first image entry regardless of filename key
        first = next(iter(images.values()))
        image_hash = first.get("hash")
        if not image_hash:
            raise MetaAdsError("upload_image: no hash in response", payload=data)
        logger.info("[meta_ads] uploaded image hash=%s", image_hash)
        return image_hash

    # ── Step 2 — Campaign ────────────────────────────────────────────────────

    def create_campaign(
        self,
        name: str,
        *,
        objective: str = "OUTCOME_TRAFFIC",
        special_ad_categories: Optional[List[str]] = None,
        status: str = "PAUSED",
    ) -> str:
        import json as _json
        # Meta requires special_ad_categories to be present even when empty
        # (form-encoded Python lists get dropped — must send as a JSON string)
        # AND when budget lives on the adset, requires explicit
        # is_adset_budget_sharing_enabled boolean.
        data = self._post(
            f"/{self.acct}/campaigns",
            data={
                "name": name,
                "objective": objective,
                "status": status,
                "special_ad_categories": _json.dumps(special_ad_categories or []),
                "is_adset_budget_sharing_enabled": "false",
            },
        )
        campaign_id = data.get("id")
        if not campaign_id:
            raise MetaAdsError("create_campaign: no id in response", payload=data)
        return campaign_id

    # ── Step 3 — Ad set ──────────────────────────────────────────────────────

    def create_adset(
        self,
        name: str,
        *,
        campaign_id: str,
        daily_budget_cents: int = 500,            # $5.00
        billing_event: str = "IMPRESSIONS",
        optimization_goal: str = "LINK_CLICKS",
        bid_strategy: str = "LOWEST_COST_WITHOUT_CAP",
        targeting: Optional[Dict[str, Any]] = None,
        status: str = "PAUSED",
        start_time: Optional[str] = None,         # ISO 8601, e.g. "2026-05-22T20:00:00-0700"
    ) -> str:
        import json as _json
        target = targeting or {
            "geo_locations": {"countries": ["US"]},
            "age_min": 25,
            "age_max": 55,
        }
        # Meta now requires explicit Advantage+ targeting opt-in/out.
        # 0 = keep our manual targeting, 1 = let Meta expand the audience.
        target.setdefault("targeting_automation", {"advantage_audience": 0})
        payload: Dict[str, Any] = {
            "name": name,
            "campaign_id": campaign_id,
            "daily_budget": str(daily_budget_cents),
            "billing_event": billing_event,
            "optimization_goal": optimization_goal,
            "bid_strategy": bid_strategy,
            "targeting": _json.dumps(target),  # Graph API expects targeting as JSON string in form-encoded body
            "status": status,
        }
        if start_time:
            payload["start_time"] = start_time

        data = self._post(f"/{self.acct}/adsets", data=payload)
        adset_id = data.get("id")
        if not adset_id:
            raise MetaAdsError("create_adset: no id in response", payload=data)
        return adset_id

    # ── Step 4 — Ad creative ─────────────────────────────────────────────────

    def create_creative(
        self,
        name: str,
        *,
        message: str,
        link_url: str,
        image_hash: str,
        call_to_action: str = "LEARN_MORE",
        page_id: Optional[str] = None,
    ) -> str:
        import json as _json
        pid = page_id or self.page_id
        if not pid:
            raise MetaAdsError("create_creative: PAGE_ID not configured")
        link_data = {
            "message": message,
            "link": link_url,
            "image_hash": image_hash,
            "call_to_action": {"type": call_to_action, "value": {"link": link_url}},
        }
        story_spec = {"page_id": pid, "link_data": link_data}

        data = self._post(
            f"/{self.acct}/adcreatives",
            data={
                "name": name,
                "object_story_spec": _json.dumps(story_spec),
            },
        )
        creative_id = data.get("id")
        if not creative_id:
            raise MetaAdsError("create_creative: no id in response", payload=data)
        return creative_id

    # ── Step 5 — Ad ──────────────────────────────────────────────────────────

    def create_ad(
        self,
        name: str,
        *,
        adset_id: str,
        creative_id: str,
        status: str = "PAUSED",
    ) -> str:
        import json as _json
        data = self._post(
            f"/{self.acct}/ads",
            data={
                "name": name,
                "adset_id": adset_id,
                "creative": _json.dumps({"creative_id": creative_id}),
                "status": status,
            },
        )
        ad_id = data.get("id")
        if not ad_id:
            raise MetaAdsError("create_ad: no id in response", payload=data)
        return ad_id

    # ── Verification ─────────────────────────────────────────────────────────

    def get_node(self, node_id: str, fields: str = "id,name,status,effective_status") -> Dict:
        return self._get(node_id, fields=fields)


_client: Optional[MetaAdsClient] = None


def get_meta_ads() -> MetaAdsClient:
    global _client
    if _client is None:
        _client = MetaAdsClient()
    return _client
