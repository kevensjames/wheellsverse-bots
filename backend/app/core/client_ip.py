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
    """The caller's credential, read in the SAME precedence the guarded endpoints
    AUTHENTICATE with, so the rate-limit bucket tracks the real principal and
    can't be rotated out from under the limit.

    `get_current_user` (POST /chat) is cookie-first with an Authorization-bearer
    fallback; `get_user_for_stream` (GET /chat/stream) reads ONLY the cookie or
    the `?token` query param and never the bearer header. This function is
    cookie -> query-token -> bearer to match: a caller authenticated by cookie
    keys on the (stable) cookie, so rotating an *unvalidated* bearer header can't
    mint fresh buckets and slip the per-user cap. Bearer is the key only when it
    is actually the credential (pure API clients with no cookie/query token)."""
    tok = request.cookies.get(ACCESS_COOKIE)
    if tok:
        return tok
    tok = request.query_params.get("token")
    if tok:
        return tok
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


def user_or_ip_key(request: Request) -> str:
    """Per-user key for authenticated endpoints; per-IP fallback for anonymous.
    Uses a hash of the token (never the plaintext) so one user's quota is
    isolated from another's without decoding/validating the JWT in the limiter."""
    tok = _token_from(request)
    if tok:
        return "u:" + hashlib.sha256(tok.encode("utf-8")).hexdigest()[:24]
    return "ip:" + client_ip(request)
