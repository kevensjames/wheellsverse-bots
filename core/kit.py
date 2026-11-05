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
  - Paged reads (list_tags_page, list_tag_subscribers): one page per call;
               pass pagination.end_cursor back as `after` while
               pagination.has_next_page is true.

Env vars
  KIT_API_KEY     — from Kit → Settings → Advanced → API Keys (v4 key)
  KIT_API_BASE    — defaults to https://api.kit.com/v4
  KIT_DRY_RUN     — "true" / "1" → log every intended write call, do NOT
                    send it to Kit. Returns synthesised responses with
                    "_dry_run": true so callers can verify wiring. Reads
                    always go to Kit.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("kit")

DEFAULT_BASE = "https://api.kit.com/v4"
# Kit allows an API key 120 requests per rolling 60 seconds (2 a second on
# average), shared by every process that uses the key. 4 a second is a burst
# ceiling, not a sustained rate: a caller that reads many pages also handles 429.
DEFAULT_RATE_LIMIT_PER_SEC = 4
MAX_PER_PAGE = 1000      # the largest page Kit documents for its v4 list endpoints
SUBSCRIBER_STATES = ("active", "inactive", "bounced", "complained", "cancelled")
_DAY_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _is_truthy(val: Optional[str]) -> bool:
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


def _ymd(value) -> str:
    """A day for Kit's date filters, YYYY-MM-DD: from a date, a datetime (its
    own calendar day) or a YYYY-MM-DD string."""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and _DAY_RE.fullmatch(value.strip()):
        return value.strip()
    raise ValueError("a Kit date filter is a date or YYYY-MM-DD")


def _page_size(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_PER_PAGE:
        raise ValueError(f"per_page must be a whole number from 1 to {MAX_PER_PAGE}")
    return value


def _kit_id(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("a Kit id is a positive whole number")
    return value


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
            # The type only: an exception's text can repeat details of the request.
            logger.error("[kit NET] %s %s failed: %s", method, url, type(e).__name__)
            return {"error": f"request failed ({type(e).__name__})", "status": 0}

        try:
            data = r.json()
        except ValueError:
            data = {"raw": r.text}
        if not isinstance(data, dict):      # Kit answers JSON objects; anything else is kept, not indexed
            data = {"raw": data}

        self._log_call(method, url, body, status=r.status_code, ok=r.ok, dry=False)
        data["status"] = r.status_code
        retry_after = r.headers.get("Retry-After")
        if retry_after is not None:         # for a caller that waits before trying again
            data["_retry_after"] = retry_after
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

    def list_tags_page(self, *, after: Optional[str] = None, per_page: int = MAX_PER_PAGE) -> Dict:
        """GET /v4/tags, one page: {"tags": [{"id", "name", "created_at"}],
        "pagination": {"has_next_page", "end_cursor", ...}, "status": 200}.
        Unlike list_tags(), which reads the first page only and answers []
        on any failure, this returns the whole answer, so a caller can page
        through every tag and tell a failure from "no tags". A bad argument
        raises ValueError before any request. A failure at Kit or on the way
        never raises: it comes back as {"error" or "errors": ..., "status": n}
        (status 0: no key, or Kit could not be reached)."""
        params: Dict[str, Any] = {"per_page": _page_size(per_page)}
        if after:
            params["after"] = after
        return self._request("GET", "/tags", params=params)

    def list_tag_subscribers(self, tag_id: int, *, tagged_after=None, tagged_before=None,
                             after: Optional[str] = None, per_page: int = MAX_PER_PAGE,
                             status: str = "all", include_total_count: bool = False) -> Dict:
        """GET /v4/tags/{tag_id}/subscribers, one page of the subscribers who
        hold the tag now: {"subscribers": [{"id", "email_address", "state",
        "created_at", "tagged_at", ...}], "pagination": {...}, "status": 200}.
        tagged_at is when this tag was applied to that subscriber (UTC).

        status "all", the default here, also lists people who have
        unsubscribed since (state "cancelled") or not yet confirmed
        ("inactive"); Kit's own default is "active" only. tagged_after and
        tagged_before filter on tagged_at and take a day (a date or
        YYYY-MM-DD). Kit does not document whether they are inclusive, or in
        which time zone a day starts, so pad them and check tagged_at
        yourself. A read: it reaches Kit even with KIT_DRY_RUN on. A bad
        argument raises ValueError before any request; a failure at Kit or on
        the way comes back as {"error" or "errors": ..., "status": n}."""
        if status not in ("all", *SUBSCRIBER_STATES):
            raise ValueError("status must be all, " + ", ".join(SUBSCRIBER_STATES))
        params: Dict[str, Any] = {"status": status, "per_page": _page_size(per_page)}
        if tagged_after is not None:
            params["tagged_after"] = _ymd(tagged_after)
        if tagged_before is not None:
            params["tagged_before"] = _ymd(tagged_before)
        if after:
            params["after"] = after
        if include_total_count:
            params["include_total_count"] = "true"     # lower case: requests would send Python's "True"
        return self._request("GET", f"/tags/{_kit_id(tag_id)}/subscribers", params=params)

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

    def list_sequence_emails(self, sequence_id: int) -> List[Dict]:
        data = self._request("GET", f"/sequences/{sequence_id}/emails")
        return data.get("emails", []) if isinstance(data.get("emails"), list) else []

    def create_sequence_email(
        self,
        sequence_id: int,
        *,
        subject: str,
        delay_value: int,
        delay_unit: str = "days",      # "days" or "hours"
        content: Optional[str] = None,
        preview_text: Optional[str] = None,
        position: Optional[int] = None,
        published: bool = False,
        send_days: Optional[List[str]] = None,
    ) -> Dict:
        """POST /v4/sequences/{sequence_id}/emails — adds one email to the sequence."""
        if delay_unit not in {"days", "hours"}:
            raise ValueError(f"delay_unit must be 'days' or 'hours', got {delay_unit!r}")
        body: Dict[str, Any] = {
            "subject": subject,
            "delay_value": int(delay_value),
            "delay_unit": delay_unit,
            "published": published,
        }
        if content is not None:
            body["content"] = content
        if preview_text is not None:
            body["preview_text"] = preview_text
        if position is not None:
            body["position"] = int(position)
        if send_days:
            body["send_days"] = send_days
        return self._request(
            "POST", f"/sequences/{sequence_id}/emails",
            body=body, writes=True,
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
