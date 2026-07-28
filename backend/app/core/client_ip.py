"""Client-IP + rate-limit keying that is safe behind the Cloudflare tunnel.

`slowapi`'s default `get_remote_address` keys on the socket peer. The tunnel
terminates on loopback, so EVERY request appears to come from 127.0.0.1 — the
`5/minute` signup limit becomes one global bucket shared by all users, and
per-attacker limiting is impossible.

`client_ip` trusts a forwarded client-IP header (CF-Connecting-IP, then the
first X-Forwarded-For hop) ONLY when the socket peer is a trusted local proxy
(loopback/private = the tunnel). A directly-reachable origin must NOT trust those
headers — they're spoofable — so it keys on the socket address. This mirrors the
already-reviewed admin throttle logic (dependencies/admin.py).

`user_or_ip_key` keys authenticated endpoints (chat) by the caller's token so
users get independent quotas and can't consume each other's; anonymous callers
fall back to the client IP.

Storage note: the shipped uvicorn runs --workers 1, so the in-memory limiter is
authoritative. A multi-worker / multi-host deployment MUST set the limiter's
storage_uri to Redis (see core/rate_limit.py) or the per-key counts fragment.
"""
from __future__ import annotations

import hashlib
import ipaddress

from starlette.requests import Request

from app.dependencies.cookie_auth import ACCESS_COOKIE


def _is_trusted_peer(host: str | None) -> bool:
    if not host:
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private


def client_ip(request: Request | None) -> str:
    """The real client IP for rate-limit keying (see module docstring)."""
    if request is None:
        return "unknown"
    peer = getattr(getattr(request, "client", None), "host", None)
    if _is_trusted_peer(peer):
        headers = getattr(request, "headers", {}) or {}
        cf = headers.get("cf-connecting-ip")
        if cf:
            return cf.strip()
        xff = headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
    return peer or "unknown"


def _token_from(request: Request) -> str:
    """The caller's credential, from wherever this deployment carries it:
    Authorization bearer (API/JSON clients), the `token` query param, or the
    access cookie (EventSource streaming can't set headers)."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.query_params.get("token")
            or request.cookies.get(ACCESS_COOKIE)
            or "")


def user_or_ip_key(request: Request) -> str:
    """Per-user key for authenticated endpoints; per-IP fallback for anonymous.
    Uses a hash of the token (never the plaintext) so one user's quota is
    isolated from another's without decoding/validating the JWT in the limiter."""
    tok = _token_from(request)
    if tok:
        return "u:" + hashlib.sha256(tok.encode("utf-8")).hexdigest()[:24]
    return "ip:" + client_ip(request)
