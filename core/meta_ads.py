#!/usr/bin/env python3
"""
core/meta_ads.py
─────────────────────────────────────────────────────────────────────────────
Thin Meta Marketing API (Graph) wrapper for the Toodle Ads Agent, and the
reads of the daily numbers board (core/board/connectors/meta_sync.py).

This is a different surface from core/facebook.py, which posts organic
content to a Page. Creating ads needs a User Access Token with
`ads_management` + `ads_read` scopes and admin access to an Ad Account.
Reading spend needs only `ads_read` and access to the Ad Account: the board
uses a system-user token for that (META_INSIGHTS_TOKEN), and no Page.

Endpoints in scope (Graph v26.0 by default):
  POST /act_{ad_account_id}/adimages         — upload creative
  POST /act_{ad_account_id}/campaigns        — create campaign (PAUSED)
  POST /act_{ad_account_id}/adsets           — create adset (PAUSED)
  POST /act_{ad_account_id}/adcreatives      — create creative
  POST /act_{ad_account_id}/ads              — create ad (PAUSED)
  GET  /{node_id}                            — verify status
  GET  /act_{ad_account_id}                  — the account's currency and time zone (account_info)
  GET  /act_{ad_account_id}/insights         — spend per campaign per day (daily_insights)

All write methods print structured logs and return the JSON Graph payload.
Status is always PAUSED for safety; the caller (scripts/meta_first_ad.py)
intentionally does NOT activate. The user reviews in Ads Manager and flips
it to ACTIVE manually.

Every read (GET) sends the token in an Authorization: Bearer header, so the
token is not part of any URL. Only when Meta does not take it from the header
(code 190 or 2500) does that client send it as the access_token parameter
instead. With an app secret, a read also sends appsecret_proof. A read is
retried on Meta's rate-limit codes and on transient errors (3 times at most,
never more than 30 seconds apart), and fails with a MetaAdsError that carries
Meta's code, subcode and fbtrace_id. Its message and payload never carry the
token or the app secret: Meta's own words are kept with them hidden.

Env vars
  META_ACCESS_TOKEN      — User Access Token (ads_management + ads_read)
  AD_ACCOUNT_ID          — numeric (no "act_" prefix)
  PAGE_ID                — numeric Facebook Page ID (creating ads only)
  META_GRAPH_VERSION     — default "v26.0". In November 2026 Meta serves ads
                           calls on v25.0 and v26.0 only; v19.0 to v24.0 are
                           retired for the Marketing API.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlsplit

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("meta_ads")

DEFAULT_VERSION = "v26.0"
GRAPH_BASE = "https://graph.facebook.com"

# ── reads ──
READ_TIMEOUT = 90.0        # seconds: a synchronous Insights read can be slow
READ_RETRIES = 3           # retries of one read, on rate limiting or a transient error
MAX_WAIT = 30.0            # seconds: the longest wait before a retry
_THROTTLE_WAITS = (5.0, 15.0, 30.0)
_TRANSIENT_WAITS = (2.0, 8.0, 30.0)
# Meta's rate-limit codes: the app (4), a user (17), a Page (32), an API's own
# limit (613) and the business use cases (80000 ads_insights to 80014).
THROTTLE_CODES = frozenset({4, 17, 32, 613, *range(80000, 80015)})
ACCOUNT_FIELDS = ("id", "account_id", "name", "currency", "timezone_name", "account_status")
INSIGHTS_FIELDS = ("campaign_id", "campaign_name", "spend", "impressions", "inline_link_clicks", "actions",
                   "account_currency", "date_start", "date_stop")
INSIGHTS_PAGE_SIZE = 200
INSIGHTS_MAX_PAGES = 500
# Rate-limit figures Meta sends with an answer: numbers and ids, never a secret.
USAGE_HEADERS = ("x-business-use-case-usage", "x-ad-account-usage", "x-app-usage",
                 "x-fb-ads-insights-throttle")
_SECRET_PARAMS = frozenset({"access_token", "appsecret_proof"})
VERSION_RE = re.compile(r"v[0-9]{1,3}\.[0-9]{1,2}")
_RUN_RE = re.compile(r"[A-Za-z0-9_\-+/=]{8,}")
_TRACE_RE = re.compile(r"[A-Za-z0-9_\-]{1,64}")

# Tests mount a fake requests adapter here; None means the real network.
_adapter: Optional[Any] = None
_sleep = time.sleep


def _scrub(text: Any, secrets: tuple = (), longest: int = 300) -> str:
    """Meta's words, safe to keep: one printable line, cut short, with each
    secret, any piece of one 8 characters or longer, and any run of 24 or more
    token-like characters replaced by [hidden]."""
    keep = [s for s in secrets if s]
    out = " ".join(str(text or "").split())
    for secret in keep:
        out = out.replace(secret, "[hidden]")

    def hide(m: "re.Match") -> str:
        run = m.group(0)
        return "[hidden]" if len(run) >= 24 or any(run in s for s in keep) else run

    out = "".join(c for c in _RUN_RE.sub(hide, out) if c.isprintable())
    return out if len(out) <= longest else out[:longest - 3] + "..."


def _code(value: Any) -> Optional[int]:
    """One of Meta's error codes: a whole number, or digits in a string."""
    if isinstance(value, str) and re.fullmatch(r"-?[0-9]{1,9}", value.strip()):
        value = int(value)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _seconds(value: Any) -> Optional[float]:
    """A Retry-After header in seconds, when it is a plain number."""
    try:
        seconds = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return seconds if 0 <= seconds < 86400 else None


def _usage(headers: Any) -> Dict[str, str]:
    out = {}
    for name in USAGE_HEADERS:
        value = headers.get(name)
        if value:
            out[name] = "".join(c for c in str(value) if c.isprintable())[:300]
    return out


def _as_day(value: Any) -> date:
    """A calendar day: a date, or YYYY-MM-DD."""
    if isinstance(value, datetime):
        raise TypeError("a day is a date, not a datetime")
    if isinstance(value, date):
        return value
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return date.fromisoformat(value)
    raise ValueError("a day is a date or YYYY-MM-DD")


class MetaAdsError(RuntimeError):
    """Raised when the Graph API returns an error payload.

    A read (GET) also fills Meta's error fields: code and subcode, error_type,
    is_transient, fbtrace_id (for Meta's support), the rate-limit headers
    (numbers, never a secret), retry_after, and meta_message: Meta's own words
    with the token and the app secret hidden. network is True when Meta could
    not be reached at all. A read's message and payload never carry the token,
    the app secret or a URL's query string."""

    def __init__(self, message: str, payload: Any = None, status_code: int = 0, *,
                 code: Optional[int] = None, subcode: Optional[int] = None,
                 error_type: Optional[str] = None, is_transient: bool = False,
                 fbtrace_id: Optional[str] = None, headers: Optional[Dict[str, str]] = None,
                 meta_message: str = "", network: bool = False, retry_after: Optional[float] = None):
        super().__init__(message)
        self.payload = payload
        self.status_code = status_code
        self.code = code
        self.subcode = subcode
        self.error_type = error_type
        self.is_transient = is_transient
        self.fbtrace_id = fbtrace_id
        self.headers = headers or {}
        self.meta_message = meta_message
        self.network = network
        self.retry_after = retry_after
        self.retries = 0            # how many times the read was tried again before it gave up

    @property
    def throttled(self) -> bool:
        """Meta is rate limiting the app, the ad account or a business use case."""
        return self.code in THROTTLE_CODES or self.status_code == 429

    @property
    def too_much_data(self) -> bool:
        """The read asked for too much at once: a shorter date range may work."""
        return ((self.code == 100 and self.subcode == 1504018)
                or (self.code == 1 and "reduce the amount of data" in self.meta_message.lower()))

    @property
    def transient(self) -> bool:
        """Worth trying again as it is: no answer, or an error Meta calls temporary."""
        return (self.network or self.is_transient or self.code in (1, 2)
                or (self.code is None and self.status_code >= 500))


def _retry_wait(e: MetaAdsError, attempt: int) -> Optional[float]:
    """Seconds to wait before trying a failed read again, or None when trying
    again cannot help: a request for too much data, a refused token, a missing
    permission or any other error Meta does not call temporary."""
    if e.too_much_data:
        return None
    if e.throttled:
        waits = _THROTTLE_WAITS
    elif e.transient:
        waits = _TRANSIENT_WAITS
    else:
        return None
    wait = e.retry_after if e.retry_after is not None else waits[min(attempt, len(waits) - 1)]
    return min(max(wait, 0.0), MAX_WAIT)


def _next_cursor(paging: Any) -> Optional[str]:
    """The cursor of the next page, or None after the last one. Meta sends a
    cursor even on the last page; only `next` says there is more. The `next`
    link is never requested or kept, because it can carry the token: its
    `after` value is read from it only when `cursors.after` is missing."""
    if not isinstance(paging, dict) or not paging.get("next"):
        return None
    cursors = paging.get("cursors")
    after = cursors.get("after") if isinstance(cursors, dict) else None
    if not after:
        found = parse_qs(urlsplit(str(paging["next"])).query).get("after")
        after = found[0] if found else None
    if not isinstance(after, str) or not after:
        raise MetaAdsError("Meta said there is another page of insights but gave no cursor for it")
    return after


class MetaAdsClient:
    """Minimal Marketing API client. One token, one ad account."""

    def __init__(
        self,
        access_token: Optional[str] = None,
        ad_account_id: Optional[str] = None,
        page_id: Optional[str] = None,
        version: Optional[str] = None,
        app_secret: Optional[str] = None,
    ):
        self.access_token = access_token or os.getenv("META_ACCESS_TOKEN", "")
        ad_acc = ad_account_id or os.getenv("AD_ACCOUNT_ID") or os.getenv("FB_AD_ACCOUNT_ID", "")
        self.ad_account_id = ad_acc.replace("act_", "")  # accept either form
        self.page_id = page_id or os.getenv("PAGE_ID") or os.getenv("FACEBOOK_PAGE_ID", "")
        self.version = version or os.getenv("META_GRAPH_VERSION", DEFAULT_VERSION)
        # Reads only. With an app secret, every read sends appsecret_proof.
        self.app_secret = app_secret or ""
        self._send_proof = bool(self.app_secret)
        self.proof_dropped = False          # Meta said the proof is not from this token's app
        self.token_sent_as = "header"       # "parameter" once Meta has not taken it from the header
        self.upgraded_to: Optional[str] = None   # set when Meta answered from another API version
        self.reads = 0                      # reads sent, retries included
        self._read_session: Optional[requests.Session] = None

    # ── Plumbing ──────────────────────────────────────────────────────────────

    @property
    def base(self) -> str:
        return f"{GRAPH_BASE}/{self.version}"

    @property
    def acct(self) -> str:
        return f"act_{self.ad_account_id}"

    def is_configured(self) -> bool:
        return bool(self.access_token and self.ad_account_id and self.page_id)

    def is_read_configured(self) -> bool:
        """Whether account_info and daily_insights can run: a token and an ad
        account. Reads need no Page."""
        return bool(self.access_token and self.ad_account_id)

    def close(self) -> None:
        if self._read_session is not None:
            self._read_session.close()
            self._read_session = None

    def _post(self, path: str, *, data: Optional[Dict[str, Any]] = None,
              files: Optional[Dict] = None) -> Dict:
        url = f"{self.base}{path}"
        payload = {"access_token": self.access_token, **(data or {})}
        logger.info("[meta_ads POST] %s data_keys=%s files=%s",
                    url, sorted(payload.keys()), bool(files))
        r = requests.post(url, data=payload, files=files, timeout=60)
        return self._handle(r, "POST", url)

    def _get(self, node_id: str, *, fields: Optional[str] = None,
             params: Optional[Dict[str, Any]] = None) -> Dict:
        """GET /{node_id} with `fields` and any other query parameters, through
        the read path (_read). The token never goes in `params`."""
        query = {k: v for k, v in (params or {}).items() if k not in _SECRET_PARAMS}
        if fields:
            query["fields"] = fields
        return self._read(f"/{node_id.lstrip('/')}", query)

    # ── Reads: the token in a header, retries, errors without secrets ────────

    def _session(self) -> requests.Session:
        if self._read_session is None:
            session = requests.Session()
            if _adapter is not None:
                session.mount("https://", _adapter)
            self._read_session = session
        return self._read_session

    def _read(self, path: str, params: Dict[str, Any]) -> Dict:
        """One GET of the Graph API. On a rate-limit code it waits 5, 15, then
        30 seconds, and on a transient error 2, 8, then 30 (or Meta's
        Retry-After, at most 30), and tries again 3 times at most. Raises
        MetaAdsError."""
        attempt = 0
        while True:
            try:
                return self._read_once(path, params)
            except MetaAdsError as e:
                if self._fall_back(e):
                    continue
                wait = _retry_wait(e, attempt)
                if wait is None:
                    raise
                if attempt >= READ_RETRIES:
                    e.retries = attempt
                    raise
                attempt += 1
                logger.warning("[meta_ads GET] %s: HTTP %s, code %s; retry %d of %d in %.0f s",
                               path, e.status_code, e.code, attempt, READ_RETRIES, wait)
                _sleep(wait)

    def _fall_back(self, e: MetaAdsError) -> bool:
        """Change how the next try signs in, at most once each: send the token as
        a parameter when Meta did not take it from the header (190 or 2500), and
        stop sending appsecret_proof when Meta says it is not valid (the app
        secret is another app's). True when the read should run again."""
        if self.token_sent_as == "header" and e.code in (190, 2500):
            self.token_sent_as = "parameter"
            logger.warning("[meta_ads] Meta did not take the token from the Authorization header "
                           "(code %s); sending it as a parameter", e.code)
            return True
        said = e.meta_message.lower()
        if self._send_proof and e.code == 100 and "appsecret_proof" in said and "invalid" in said:
            self._send_proof = False
            self.proof_dropped = True
            logger.warning("[meta_ads] Meta refused appsecret_proof: the app secret is not the token's "
                           "app's; reading without it")
            return True
        return False

    def _read_once(self, path: str, params: Dict[str, Any]) -> Dict:
        if not VERSION_RE.fullmatch(self.version or ""):
            raise MetaAdsError("META_GRAPH_VERSION must look like v26.0")
        query = {k: v for k, v in params.items() if v is not None and k not in _SECRET_PARAMS}
        headers = {"Accept": "application/json"}
        if self.token_sent_as == "header":
            headers["Authorization"] = f"Bearer {self.access_token}"
        else:
            query["access_token"] = self.access_token
        if self._send_proof:
            query["appsecret_proof"] = hmac.new(self.app_secret.encode(), self.access_token.encode(),
                                                hashlib.sha256).hexdigest()
        logger.info("[meta_ads GET] %s%s %s", self.base, path,
                    {k: v for k, v in query.items() if k not in _SECRET_PARAMS and k != "after"})
        self.reads += 1
        try:
            r = self._session().get(f"{self.base}{path}", params=query, headers=headers,
                                    timeout=READ_TIMEOUT, allow_redirects=False)
        except Exception as e:  # noqa: BLE001 — its text can hold the URL and its query string: never kept
            raise MetaAdsError(f"GET {path}: Meta could not be reached ({type(e).__name__})",
                               network=isinstance(e, requests.RequestException)) from None
        return self._handle_read(r, path)

    def _handle_read(self, r: requests.Response, path: str) -> Dict:
        served = str(r.headers.get("facebook-api-version") or "").strip()
        if VERSION_RE.fullmatch(served) and served != self.version:
            self.upgraded_to = served
        elif any("version-warning" in name.lower() for name in r.headers) and self.upgraded_to is None:
            self.upgraded_to = ""           # upgraded, to a version Meta did not name
        try:
            data = r.json(parse_float=Decimal)    # a number never passes through a float
        except ValueError:
            data = None
        error = data.get("error") if isinstance(data, dict) else None
        if r.status_code == 200 and isinstance(data, dict) and error is None:
            return data
        e = error if isinstance(error, dict) else {}
        secrets = (self.access_token, self.app_secret)
        code, subcode = _code(e.get("code")), _code(e.get("error_subcode"))
        said = _scrub(e.get("message"), secrets)
        if not e and r.status_code == 200:
            said = "the answer is not a JSON object"
        trace = e.get("fbtrace_id")
        trace = trace if (isinstance(trace, str) and _TRACE_RE.fullmatch(trace)
                          and not any(trace in s for s in secrets if s)) else None
        kind = e.get("type") if isinstance(e.get("type"), str) and re.fullmatch(r"[A-Za-z]{1,40}", e["type"]) else None
        transient = e.get("is_transient") is True
        message = f"GET {path}: HTTP {r.status_code}"
        if code is not None:
            message += f", code {code}" + (f"/{subcode}" if subcode is not None else "")
        if said:
            message += f": {said}"
        logger.warning("[meta_ads ERR] %s (fbtrace_id %s)", message, trace)
        raise MetaAdsError(
            message, status_code=r.status_code, code=code, subcode=subcode, error_type=kind,
            is_transient=transient, fbtrace_id=trace, headers=_usage(r.headers), meta_message=said,
            retry_after=_seconds(r.headers.get("retry-after")),
            payload={"error": {"message": said, "type": kind, "code": code, "error_subcode": subcode,
                               "is_transient": transient, "fbtrace_id": trace}})

    def _require_read(self) -> None:
        if not self.is_read_configured():
            raise MetaAdsError("reads need a token and an ad account id")
        if not re.fullmatch(r"[0-9]{1,30}", self.ad_account_id):
            raise MetaAdsError("the ad account id must be the account's number, with or without act_")

    # ── Reads for the board ──────────────────────────────────────────────────

    def account_info(self) -> Dict[str, Any]:
        """GET /act_{id}: the ad account's ACCOUNT_FIELDS as Meta gives them,
        None where Meta leaves one out. timezone_name is the IANA zone of the
        account's days, currency its ISO code, account_status a number (1
        active). Needs a token with ads_read and the ad account; no Page."""
        self._require_read()
        data = self._get(self.acct, fields=",".join(ACCOUNT_FIELDS))
        return {k: data.get(k) for k in ACCOUNT_FIELDS}

    def daily_insights(self, since: Any, until: Any) -> List[Dict[str, Any]]:
        """Each campaign's numbers for each day from `since` to `until` (dates,
        both included, in the ad account's own time zone), across every page:
        one dict per campaign and day, with INSIGHTS_FIELDS as Meta writes
        them (spend is a decimal string in the account's currency). Meta
        leaves out a campaign-day with no delivery. The read sends
        level=campaign, time_increment=1 and its own page size, and no
        filtering, which would hide paused, archived and deleted campaigns.
        When Meta says the range is too much at once, each half is read
        instead."""
        self._require_read()
        since, until = _as_day(since), _as_day(until)
        if since > until:
            raise ValueError("since is after until")
        try:
            return self._insights(since, until)
        except MetaAdsError as e:
            if not e.too_much_data or since == until:
                raise
        middle = since + (until - since) // 2
        logger.warning("[meta_ads] insights for %s to %s are too much at once; reading each half", since, until)
        return self.daily_insights(since, middle) + self.daily_insights(middle + timedelta(days=1), until)

    def _insights(self, since: date, until: date) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "level": "campaign",
            "time_increment": "1",
            "time_range": json.dumps({"since": since.isoformat(), "until": until.isoformat()},
                                     sort_keys=True, separators=(",", ":")),
            "fields": ",".join(INSIGHTS_FIELDS),
            "limit": str(INSIGHTS_PAGE_SIZE),
        }
        rows: List[Dict[str, Any]] = []
        cursors: set = set()
        for _ in range(INSIGHTS_MAX_PAGES):
            page = self._read(f"/{self.acct}/insights", params)
            data = page.get("data")
            if not isinstance(data, list) or not all(isinstance(row, dict) for row in data):
                raise MetaAdsError("Meta's insights answer has no list of rows")
            rows.extend(data)
            after = _next_cursor(page.get("paging"))
            if after is None:
                return rows
            if after in cursors:
                raise MetaAdsError("Meta's next-page cursor for insights came back, so the read stopped")
            cursors.add(after)
            params["after"] = after
        raise MetaAdsError(f"Meta's insights ran past {INSIGHTS_MAX_PAGES} pages, so the read stopped")

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
