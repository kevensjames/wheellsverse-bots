"""Small helpers the board shares with the rest of the app.

  * client_ip:  the visitor's address for the /go click limit (core/api.py).
  * usable_url: the check on SUPABASE_URL before the ledger calls it
                (core/board/ledger.py).

The board has no sign-in of its own: the owner check is production's
(api_key_middleware and verify_api_key in core/api.py).
"""
from __future__ import annotations

import httpx
from fastapi import Request


def usable_url(url: str) -> bool:
    """An http(s) URL with a host and a valid port. A copy-paste can leave an
    invisible character or a bad port in it, and httpx then fails every call."""
    try:
        parsed = httpx.URL(url)
        port = parsed.port
    except (httpx.InvalidURL, ValueError, TypeError):
        return False
    return (parsed.scheme in ("http", "https") and bool(parsed.host)
            and not any(c.isspace() for c in url) and (port is None or 0 < port < 65536))


def client_ip(request: Request) -> str:
    """Cloudflare's CF-Connecting-IP, else the first X-Forwarded-For hop (as the
    API rate limiter in core/api.py reads it), else the socket peer. It keys the
    /go click limit only (core/click_tracker.allow_click); it is never stored."""
    ip = (request.headers.get("cf-connecting-ip") or "").strip()
    if not ip:
        ip = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if not ip and request.client:
        ip = request.client.host
    return ip[:64] or "unknown"
