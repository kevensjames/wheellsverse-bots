"""Cookie helpers — issuance + clearing (Path X).

The validation half of this module moved to ``app/dependencies/supabase_jwt.py``
when Path X swapped the fictional self-managed JWT for real Supabase tokens.
What's left here is just the response-cookie plumbing — set on signup/login/
refresh, clear on logout.

HttpOnly + SameSite=Lax + Secure-in-prod is unchanged from Stage 6. The
cookie *value* is now a Supabase JWT (ES256), but the cookie *contract*
(name, path, lifetime) stays the same — the UI doesn't need to know.

Cookie lifetimes track Supabase defaults (60-min access, 30-day refresh)
rather than the legacy Stage 6 ACCESS_TOKEN_EXPIRE_MINUTES / REFRESH_TOKEN_
EXPIRE_DAYS — those settings are now meaningless for user auth, kept only
so existing .env files don't blow up at startup.
"""
from __future__ import annotations

from fastapi import Response

from app.config import settings


ACCESS_COOKIE = "nai_access"
REFRESH_COOKIE = "nai_refresh"

# Supabase access tokens default to 60min; refresh to 30 days. Match those so
# the cookie expiry tracks the JWT's actual validity.
_ACCESS_COOKIE_SECONDS = 60 * 60
_REFRESH_COOKIE_SECONDS = 30 * 86400


def _cookie_secure() -> bool:
    """Cookies must be HTTPS-only in prod; localhost dev can't use HTTPS."""
    return settings.APP_ENV.lower() not in ("development", "dev", "local", "test")


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Attach HttpOnly cookies to the outgoing response."""
    secure = _cookie_secure()
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=access_token,
        max_age=_ACCESS_COOKIE_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        max_age=_REFRESH_COOKIE_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        # Refresh cookie only goes to /auth/* — narrows blast radius if leaked.
        path="/auth",
    )


def clear_auth_cookies(response: Response) -> None:
    """Drop both cookies (logout)."""
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/auth")
