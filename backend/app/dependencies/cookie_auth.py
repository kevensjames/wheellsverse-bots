"""Cookie-based auth for Stage 6 (public exposure).

Replaces the Stage 4 query-param token on /nai/chat/stream with HttpOnly cookies.
Browsers auto-send cookies on same-origin EventSource requests, and JS can't
read them — so the JWT no longer travels through the URL bar, browser history,
or referer headers.

Public API:
- ``set_auth_cookies(response, access, refresh)`` — call this in /auth/signup,
  /auth/login, /auth/refresh after issuing new tokens.
- ``clear_auth_cookies(response)`` — call this in /auth/logout.
- ``get_user_from_cookie`` — FastAPI dependency for endpoints that should
  accept cookie auth only (e.g. the SSE endpoint).
- ``get_user_from_cookie_or_bearer`` — fallback dependency for endpoints that
  must accept either cookie OR ``Authorization: Bearer`` (transitional, and
  for API clients that don't have cookies).

The Bearer path is still the canonical "machine" auth; the cookie path is for
browser-driven UIs (the /nai-ui pages).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, Response, status
from jose import JWTError
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import decode_token
from app.database import get_db
from app.models.user import User


ACCESS_COOKIE = "nai_access"
REFRESH_COOKIE = "nai_refresh"


def _cookie_secure() -> bool:
    """Cookies must be HTTPS-only in prod; localhost dev can't use HTTPS."""
    return settings.APP_ENV.lower() not in ("development", "dev", "local", "test")


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Attach HttpOnly cookies to the outgoing response.

    The access cookie matches ACCESS_TOKEN_EXPIRE_MINUTES; the refresh cookie
    matches REFRESH_TOKEN_EXPIRE_DAYS. Both are HttpOnly + SameSite=Lax. In
    production they're also Secure (HTTPS only).
    """
    secure = _cookie_secure()
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
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


_INVALID = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials",
)


def _user_from_access_token(token: str, db: Session) -> User:
    try:
        payload = decode_token(token)
    except JWTError:
        raise _INVALID
    if payload.get("type") != "access":
        raise _INVALID
    sub = payload.get("sub")
    if not sub:
        raise _INVALID
    try:
        user_id = UUID(sub)
    except (ValueError, TypeError):
        raise _INVALID
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _INVALID
    return user


def get_user_from_cookie(
    nai_access: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Cookie-only dependency. Use for SSE endpoints reachable from the UI."""
    if not nai_access:
        raise _INVALID
    return _user_from_access_token(nai_access, db)


def get_user_from_cookie_or_bearer(
    nai_access: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Accept either cookie OR Authorization: Bearer header.

    The cookie is preferred (UI flow); the header is the API-client fallback.
    """
    token: str | None = nai_access
    if not token and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            token = value.strip()
    if not token:
        raise _INVALID
    return _user_from_access_token(token, db)
