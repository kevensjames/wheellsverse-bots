#!/usr/bin/env python3
"""
core/gsc.py
─────────────────────────────────────────────────────────────────────────────
Google Search Console API integration.

Setup (one-time):
  1. Go to console.cloud.google.com → New project → Enable "Search Console API"
  2. IAM & Admin → Service Accounts → Create → Download JSON key
  3. In GSC: Settings → Users and permissions → Add user (service account email)
     with "Full" permission
  4. Add to .env:
       GSC_SERVICE_ACCOUNT_FILE=/path/to/service-account.json
       GSC_PROPERTY_URL=https://wheellsverse-bots.pages.dev/

Returns top queries, impressions, clicks, CTR, and average position.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("gsc")


class GSCClient:

    def __init__(self):
        self.service_account_file = os.getenv("GSC_SERVICE_ACCOUNT_FILE", "")
        self.property_url = os.getenv(
            "GSC_PROPERTY_URL",
            "https://wheellsverse-bots.pages.dev/"
        )
        self._service = None

    def is_connected(self) -> bool:
        if not self.service_account_file:
            return False
        return Path(self.service_account_file).exists()

    def _get_service(self):
        if self._service is None:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build

            creds = service_account.Credentials.from_service_account_file(
                self.service_account_file,
                scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
            )
            self._service = build("searchconsole", "v1", credentials=creds)
        return self._service

    def get_top_queries(self, days: int = 28, limit: int = 25) -> List[Dict]:
        """Return top search queries with impressions, clicks, CTR, position."""
        svc = self._get_service()
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        resp = svc.searchanalytics().query(
            siteUrl=self.property_url,
            body={
                "startDate": start,
                "endDate": end,
                "dimensions": ["query"],
                "rowLimit": limit,
                "orderBy": [{"fieldName": "impressions", "sortOrder": "DESCENDING"}],
            },
        ).execute()

        rows = resp.get("rows", [])
        return [
            {
                "query": r["keys"][0],
                "impressions": r.get("impressions", 0),
                "clicks": r.get("clicks", 0),
                "ctr": round(r.get("ctr", 0) * 100, 2),
                "position": round(r.get("position", 0), 1),
            }
            for r in rows
        ]

    def get_top_pages(self, days: int = 28, limit: int = 20) -> List[Dict]:
        """Return top pages by impressions."""
        svc = self._get_service()
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        resp = svc.searchanalytics().query(
            siteUrl=self.property_url,
            body={
                "startDate": start,
                "endDate": end,
                "dimensions": ["page"],
                "rowLimit": limit,
                "orderBy": [{"fieldName": "impressions", "sortOrder": "DESCENDING"}],
            },
        ).execute()

        rows = resp.get("rows", [])
        return [
            {
                "page": r["keys"][0],
                "impressions": r.get("impressions", 0),
                "clicks": r.get("clicks", 0),
                "ctr": round(r.get("ctr", 0) * 100, 2),
                "position": round(r.get("position", 0), 1),
            }
            for r in rows
        ]

    def get_summary(self, days: int = 28) -> Dict:
        """Overall summary: total impressions, clicks, avg CTR, avg position."""
        svc = self._get_service()
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        resp = svc.searchanalytics().query(
            siteUrl=self.property_url,
            body={"startDate": start, "endDate": end, "dimensions": []},
        ).execute()

        rows = resp.get("rows", [{}])
        r = rows[0] if rows else {}
        return {
            "impressions": int(r.get("impressions", 0)),
            "clicks": int(r.get("clicks", 0)),
            "ctr": round(r.get("ctr", 0) * 100, 2),
            "position": round(r.get("position", 0), 1),
            "period_days": days,
        }

    def submit_sitemap(self, sitemap_url: str = "") -> Dict:
        """Submit or refresh a sitemap."""
        svc = self._get_service()
        url = sitemap_url or f"{self.property_url}sitemap.xml"
        svc.sitemaps().submit(siteUrl=self.property_url, feedpath=url).execute()
        logger.info(f"Sitemap submitted: {url}")
        return {"status": "submitted", "url": url}

    def get_status(self) -> Dict:
        connected = self.is_connected()
        result: Dict = {
            "connected": connected,
            "property_url": self.property_url,
            "service_account_file": self.service_account_file or "not set",
        }
        if not connected:
            result["setup_steps"] = [
                "1. console.cloud.google.com → Enable 'Search Console API'",
                "2. IAM → Service Accounts → Create → Download JSON key",
                "3. GSC dashboard → Settings → Users → Add service account email (Full access)",
                "4. .env: GSC_SERVICE_ACCOUNT_FILE=/path/to/key.json",
                "5. .env: GSC_PROPERTY_URL=https://wheellsverse-bots.pages.dev/",
            ]
        return result


_client: Optional[GSCClient] = None


def get_gsc() -> GSCClient:
    global _client
    if _client is None:
        _client = GSCClient()
    return _client
