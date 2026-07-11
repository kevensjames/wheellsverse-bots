"""Admin auth: shared-secret header, constant-time compared, brute-force throttled.

Stage 11 replaces this with real `admin_users` table auth. Until then the whole
admin surface (journals, persona, relationship, Sol money admin) rests on one
shared token, so this module hardens that gate:

- **Constant-time compare** (``hmac.compare_digest``) so the token can't be
  recovered via response-timing.
- **Per-client failed-attempt throttle** so the token can't be brute-forced
  unthrottled over the public tunnel. A VALID token is always honoured (the
  check runs first), so an operator who fat-fingers the token can't lock
  *themselves* out — only wrong tokens accrue toward the limit. Off in dev/test
  (the threat is production-facing, and a shared TestClient IP would trip it).

The companion ``config.Settings`` boot-guard refuses to start in production on a
weak/absent token, so this gate always defends a strong secret in prod.

In-memory state is fine for the single-worker uvicorn we ship (see
``core/rate_limit.py``); a multi-worker/multi-host deployment should back the
counter with Redis instead.
"""
from __future__ import annotations

import hmac
import ipaddress
import threading
import time

from fastapi import Header, HTTPException, Request, status

from app.config import settings

# Brute-force throttle: more than N failed attempts per client per window → 429.
_WINDOW_SECONDS = 300
_MAX_FAILURES = 10
_NON_PROD_ENVS = frozenset({"development", "dev", "local", "test", "testing", "ci"})

_lock = threading.Lock()
_failures: dict[str, list[float]] = {}  # client key -> monotonic timestamps


def _throttle_enabled() -> bool:
    """Only throttle in production-like envs. Dev/test are exempt so local runs
    stay frictionless and the shared-IP test suite can't trip the limit."""
    return (settings.APP_ENV or "").strip().lower() not in _NON_PROD_ENVS


def _is_trusted_peer(host: str | None) -> bool:
    """Whether the direct socket peer is a trusted local reverse proxy. The
    Cloudflare tunnel terminates on loopback, so only then is a forwarded
    client-IP header (CF-Connecting-IP / X-Forwarded-For) authentic. A
    directly-reachable origin must NOT trust those headers — they're spoofable."""
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def _client_key(request: Request | None) -> str:
    """Identify the caller for throttling. Trust CF-Connecting-IP / the first
    X-Forwarded-For hop ONLY when the socket peer is a trusted local proxy
    (the tunnel); otherwise key on the socket address so a spoofed/rotated
    forwarding header can't evade the limit."""
    if request is None:
        return "unknown"
    client = getattr(request, "client", None)
    peer = getattr(client, "host", None)
    if _is_trusted_peer(peer):
        headers = getattr(request, "headers", {}) or {}
        cf = headers.get("cf-connecting-ip")
        if cf:
            return cf.strip()
        xff = headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return peer or "unknown"


def _count_recent_failures(key: str, now: float) -> int:
    """Prune expired failures for ``key`` and return the live count. Caller holds
    the lock."""
    live = [t for t in _failures.get(key, ()) if now - t < _WINDOW_SECONDS]
    if live:
        _failures[key] = live
    else:
        _failures.pop(key, None)
    return len(live)


def _reset_throttle() -> None:
    """Clear all throttle state. For tests."""
    with _lock:
        _failures.clear()


def require_admin_token(
    request: Request = None,  # injected by FastAPI; default lets unit tests pass one
    x_admin_token: str | None = Header(default=None),
) -> None:
    """Gate an admin route on the shared secret. A correct token always passes
    (and clears the client's failure streak). A missing/incorrect token records
    a failure and returns 403 — or 429 once the client exceeds the budget."""
    expected = settings.admin_token
    ok = (
        bool(x_admin_token)
        and bool(expected)
        and hmac.compare_digest(x_admin_token.encode("utf-8"), expected.encode("utf-8"))
    )
    if not _throttle_enabled():
        if ok:
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin token required")

    key = _client_key(request)
    now = time.monotonic()
    if ok:
        with _lock:
            _failures.pop(key, None)  # valid token clears the streak — no self-lockout
        return

    with _lock:
        _failures.setdefault(key, []).append(now)
        count = _count_recent_failures(key, now)
    if count > _MAX_FAILURES:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed admin auth attempts; try again later.",
            headers={"Retry-After": str(_WINDOW_SECONDS)},
        )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin token required",
    )
