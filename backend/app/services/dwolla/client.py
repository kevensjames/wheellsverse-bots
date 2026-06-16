"""DwollaClient — stdlib-only (urllib) Dwolla API v2 client.

Mirrors the twenty_crm tool's posture: read env directly, fail-soft, raise a
single user-facing error type (DwollaError). Token is cached per (key, env)
module-side and refreshed before expiry.

Why stdlib only: the daemon already ships urllib; adding the `dwollav2` SDK
would pull a requests/transitive tree into a money path we want to keep small
and auditable. The API is a thin HAL+JSON REST surface — easy to call directly.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# HAL media type — Dwolla is strict: requests whose Accept it doesn't recognise
# EXACTLY get 406 "InvalidVersion: Missing or invalid API version". The version
# token is `vnd.dwolla.v1` — NOT `vnd.dhs.dwolla.v1` (a common stale value that
# 406s). Verified live against sandbox 2026-06-16. Send on every request.
_HAL = "application/vnd.dwolla.v1.hal+json"
_TIMEOUT = 25
_HOSTS = {
    "sandbox": "https://api-sandbox.dwolla.com",
    "production": "https://api.dwolla.com",
}
# Identifying UA — good hygiene + avoids generic-urllib blocks at the edge.
_UA = "KAI-Sol/1.0 (+https://wheellsverse.com)"

# Module-level token cache: {(key, env): (access_token, expires_at_epoch)}.
# Shared across DwollaClient instances so per-call tool execution doesn't
# re-auth every time. Refreshed when within 60s of expiry.
_TOKEN_CACHE: dict[tuple[str, str], tuple[str, float]] = {}


class DwollaError(Exception):
    """User-facing Dwolla failure (auth, HTTP error, misconfig)."""


class DwollaProductionLocked(DwollaError):
    """Refused to operate against the production host without an explicit
    DWOLLA_ALLOW_PRODUCTION=1 opt-in. The sandbox-lock safety latch."""


def _env() -> str:
    return (os.environ.get("DWOLLA_ENV") or "sandbox").strip().lower()


def _creds() -> tuple[str, str]:
    key = (os.environ.get("DWOLLA_KEY") or "").strip()
    secret = (os.environ.get("DWOLLA_SECRET") or "").strip()
    if not key or not secret:
        raise DwollaError("Dwolla is not configured — set DWOLLA_KEY + DWOLLA_SECRET")
    return key, secret


def is_configured() -> bool:
    return bool((os.environ.get("DWOLLA_KEY") or "").strip()
                and (os.environ.get("DWOLLA_SECRET") or "").strip())


class DwollaClient:
    """Thin Dwolla v2 client. Construct cheaply per request; token is cached."""

    def __init__(self) -> None:
        self.env = _env()
        if self.env not in _HOSTS:
            raise DwollaError(f"DWOLLA_ENV must be one of {sorted(_HOSTS)} (got {self.env!r})")
        # SANDBOX-LOCK: production requires a deliberate, separate opt-in so a
        # stray DWOLLA_ENV flip can't silently start touching real bank money.
        if self.env == "production" and not _truthy("DWOLLA_ALLOW_PRODUCTION"):
            raise DwollaProductionLocked(
                "Refusing production Dwolla: set DWOLLA_ALLOW_PRODUCTION=1 to authorize "
                "real money movement (and ensure the facilitator agreement + compliance "
                "sign-off are in place)."
            )
        self.base = _HOSTS[self.env]

    # ── auth ────────────────────────────────────────────────────────────
    def _token(self) -> str:
        key, secret = _creds()
        ck = (key, self.env)
        cached = _TOKEN_CACHE.get(ck)
        if cached and cached[1] - 60 > time.time():
            return cached[0]
        basic = base64.b64encode(f"{key}:{secret}".encode()).decode()
        req = urllib.request.Request(
            f"{self.base}/token",
            data=b"grant_type=client_credentials",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": _UA,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                tok = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise DwollaError(f"Dwolla auth {e.code}: {_body(e)}")
        except Exception as e:  # noqa: BLE001 — surface as a single error type
            raise DwollaError(f"Dwolla auth failed: {e}")
        access = tok.get("access_token")
        if not access:
            raise DwollaError("Dwolla auth returned no access_token")
        _TOKEN_CACHE[ck] = (access, time.time() + int(tok.get("expires_in", 3600)))
        return access

    # ── low-level request ───────────────────────────────────────────────
    def _request(self, method: str, url: str, body: dict | None = None) -> dict[str, Any]:
        if not url.startswith(self.base):
            # Dwolla returns absolute hrefs in _links; only follow our own host.
            if url.startswith("http"):
                raise DwollaError(f"refusing off-host Dwolla URL: {url}")
            url = f"{self.base}/{url.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {self._token()}",
            "Accept": _HAL,
            "User-Agent": _UA,
        }
        payload = None
        if body is not None:
            payload = json.dumps(body).encode()
            headers["Content-Type"] = _HAL
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
                # 201s (creates) often have an empty body + a Location header.
                location = r.headers.get("Location")
                raw = r.read()
                data = json.loads(raw) if raw else {}
                if location and "location" not in data:
                    data["location"] = location
                return data
        except urllib.error.HTTPError as e:
            raise DwollaError(f"Dwolla {method} {e.code}: {_body(e)}")
        except Exception as e:  # noqa: BLE001
            raise DwollaError(f"Dwolla request failed: {e}")

    # ── reads (used by the read-only KAI tool) ──────────────────────────
    def _account_href(self) -> str:
        """The account resource href from the API root (cached per instance)."""
        if not getattr(self, "_acct_href", None):
            root = self._request("GET", "/")
            self._acct_href = (root.get("_links", {}).get("account", {}) or {}).get("href", "")
            if not self._acct_href:
                raise DwollaError("Dwolla root returned no account link")
        return self._acct_href

    def get_account(self) -> dict[str, Any]:
        # The API root is GET "/" (NOT "/root"); it returns _links.account.
        return self._request("GET", self._account_href())

    def list_customers(self, limit: int = 25, offset: int = 0) -> dict[str, Any]:
        limit = max(1, min(int(limit), 200))
        return self._request("GET", f"/customers?limit={limit}&offset={max(0, int(offset))}")

    def get_customer(self, customer_id: str) -> dict[str, Any]:
        return self._request("GET", f"/customers/{customer_id}")

    def list_funding_sources(self, customer_id: str) -> dict[str, Any]:
        return self._request("GET", f"/customers/{customer_id}/funding-sources")

    def list_transfers(self, customer_id: str | None = None, limit: int = 25) -> dict[str, Any]:
        # Top-level GET /transfers is POST-only (create). Transfer LISTS are
        # scoped to a customer or the account.
        limit = max(1, min(int(limit), 200))
        if customer_id:
            return self._request("GET", f"/customers/{customer_id}/transfers?limit={limit}")
        return self._request("GET", f"{self._account_href()}/transfers?limit={limit}")

    def get_transfer(self, transfer_id: str) -> dict[str, Any]:
        return self._request("GET", f"/transfers/{transfer_id}")

    # ── writes (NOT exposed to the LLM tool; called by audited service fns) ─
    def create_customer(self, customer: dict[str, Any]) -> dict[str, Any]:
        """Create a Customer (verified/receive-only/business per `type`)."""
        return self._request("POST", "/customers", body=customer)

    def create_funding_source(self, customer_id: str, source: dict[str, Any]) -> dict[str, Any]:
        """Attach a bank account to a customer (e.g. {plaidToken, name})."""
        return self._request("POST", f"/customers/{customer_id}/funding-sources", body=source)

    def create_transfer(self, source_href: str, dest_href: str, value: str,
                         currency: str = "USD", metadata: dict | None = None) -> dict[str, Any]:
        """Initiate an ACH transfer. MONEY MOVEMENT — callers must route through
        the @audited service wrapper, never invoke this directly from the model."""
        body: dict[str, Any] = {
            "_links": {"source": {"href": source_href}, "destination": {"href": dest_href}},
            "amount": {"currency": currency, "value": _money(value)},
        }
        if metadata:
            body["metadata"] = metadata
        return self._request("POST", "/transfers", body=body)


def verify_webhook(body: bytes, signature_header: str | None,
                   secret: str | None = None) -> bool:
    """Constant-time HMAC-SHA256 verification of a Dwolla webhook.

    Dwolla signs the raw request body with your webhook subscription secret and
    sends the hex digest in `X-Request-Signature-SHA-256`. Reject anything that
    doesn't match — an unverified webhook must never drive a money state change.
    """
    secret = secret if secret is not None else (os.environ.get("DWOLLA_WEBHOOK_SECRET") or "")
    if not secret or not signature_header:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header.strip())


# ── helpers ─────────────────────────────────────────────────────────────
def _truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _money(value: Any) -> str:
    """Normalise an amount to Dwolla's 2-dp decimal string. Rejects junk so a
    bad amount fails loudly here, not as a half-formed transfer."""
    try:
        v = round(float(value), 2)
    except (TypeError, ValueError):
        raise DwollaError(f"invalid transfer amount: {value!r}")
    if v <= 0:
        raise DwollaError("transfer amount must be positive")
    return f"{v:.2f}"


def _body(e: urllib.error.HTTPError) -> str:
    try:
        return e.read().decode()[:400]
    except Exception:  # noqa: BLE001
        return e.reason or str(e)
