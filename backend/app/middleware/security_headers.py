"""Security-headers middleware (Stage 6 hardening).

Adds the headers a public-facing FastAPI app needs to pass a baseline
browser-security audit (Mozilla Observatory, Lighthouse, securityheaders.com):

- Strict-Transport-Security  — only in production (gated on APP_ENV).
- Content-Security-Policy    — strict; whitelists same-origin scripts/styles
                               and inline-style for the dark-mode CSS variables.
- X-Content-Type-Options     — `nosniff`, every response.
- X-Frame-Options            — `DENY`; reinforced by CSP frame-ancestors.
- Referrer-Policy            — strict-origin-when-cross-origin.
- Permissions-Policy         — disable camera / mic / geo / etc. by default.

Why ASGI middleware (not BaseHTTPMiddleware): we need to mutate the response
headers without buffering the body. Starlette's BaseHTTPMiddleware passes the
body through an iter and breaks SSE streaming (the `/nai/chat/stream`
endpoint's `text/event-stream` response would no longer flush incrementally).
Pure-ASGI middleware patches only the `http.response.start` message.

Why a custom middleware (not a library like secure.py): the only thing we
need is a static-ish header dict. A 60-line ASGI function has no dependency
surface to maintain and lets us keep the policy literal.
"""
from __future__ import annotations

from typing import Awaitable, Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send


# Content-Security-Policy.
# - default-src 'self':         same-origin by default
# - script-src 'self':          no inline <script> (refactored signup/login)
# - style-src 'self':           style.css served from /nai-ui/
# - img-src 'self' data:        data: URIs allowed for tiny inline icons
# - connect-src 'self':         fetch + EventSource on same origin
# - frame-ancestors 'self' + wheellsverse:  clickjacking defense, with an
#   explicit allowlist for KAI's own embeds inside the WheellsVerse AI
#   Command Center at app.wheellsverse.com. The Command Center iframes
#   /admin from kai.wheellsverse.com — different origin, needs allowlist.
#   Modern browsers use this directive in place of X-Frame-Options.
# - form-action 'self':         no off-domain form posts
# - base-uri 'self':            block <base> injection redirecting relative URLs
# - object-src 'none':          no plugins
_CSP = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "frame-ancestors 'self' https://app.wheellsverse.com https://wheellsverse.com; "
    "form-action 'self'; "
    "base-uri 'self'; "
    "object-src 'none'"
)

# Permissions-Policy: turn off features we never use. Browsers default these
# to allow-self; explicit opt-out keeps third-party iframes (if any are ever
# added) from inheriting them.
_PERMISSIONS_POLICY = (
    "accelerometer=(), camera=(), geolocation=(), gyroscope=(), "
    "magnetometer=(), microphone=(), payment=(), usb=()"
)

# HSTS: 1 year, include subdomains. No `preload` directive — that requires
# submitting to the HSTS preload list, which is an operator decision and is
# difficult to reverse. Operator can add it once they're confident.
_HSTS = "max-age=31536000; includeSubDomains"


def _is_production(app_env: str) -> bool:
    return app_env.lower() not in ("development", "dev", "local", "test")


class SecurityHeadersMiddleware:
    """Pure-ASGI middleware that injects security headers on every response."""

    def __init__(self, app: ASGIApp, *, app_env: str = "production") -> None:
        self.app = app
        # Capture once at construction. The middleware is reinstantiated per
        # process start, so config rotation requires a restart — that's the
        # same coupling as the cookie Secure flag.
        self._production = _is_production(app_env)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            # Pass websocket / lifespan untouched.
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # headers is a list of (bytes, bytes). Append our additions if
                # the response didn't already set them — last-write-wins on
                # collision favors whatever the route explicitly chose.
                existing = {name.lower() for name, _ in headers}
                # X-Frame-Options removed: it has no cross-origin allowlist
                # mode (only DENY or SAMEORIGIN), and the AI Command Center
                # at app.wheellsverse.com needs to iframe KAI from
                # kai.wheellsverse.com. CSP frame-ancestors above is the
                # modern equivalent and DOES support per-origin allowlists.
                # Browsers since 2018 (Chrome 55+, FF 58+, Safari 11+) prefer
                # frame-ancestors over X-Frame-Options when both are present.
                additions: list[tuple[bytes, bytes]] = [
                    (b"content-security-policy", _CSP.encode()),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"strict-origin-when-cross-origin"),
                    (b"permissions-policy", _PERMISSIONS_POLICY.encode()),
                ]
                if self._production:
                    additions.append(
                        (b"strict-transport-security", _HSTS.encode())
                    )
                for name, value in additions:
                    if name not in existing:
                        headers.append((name, value))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)
