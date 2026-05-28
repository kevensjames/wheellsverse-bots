"""Supabase JWT validator (Path X).

Verifies tokens issued by ``auth.users``-based Supabase Auth. The project is
on the **asymmetric** signing scheme (ES256 over P-256), so validation:

1. Fetches the JWKS at ``${SUPABASE_URL}/auth/v1/.well-known/jwks.json``
   (public endpoint, no auth required).
2. Caches the public keys in-process (PyJWKClient handles this).
3. Verifies signature + ``exp`` + ``iat`` + ``aud="authenticated"``.

The decoded payload's ``sub`` claim is the auth.users.id — which equals
profiles.id — which is what every chat table FKs to. That's the whole
unblock: we now persist against an id that actually exists.

Why PyJWT + PyJWKClient (not jose): jose ships JWK utilities but not a
caching JWKS client. PyJWT's PyJWKClient does both. We were already on
PyJWT for the cryptography backend; this just uses the rest of it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

import jwt
from jwt import PyJWKClient, PyJWKClientError
from fastapi import Cookie, Depends, Header, HTTPException, Query, status

from app.config import settings

logger = logging.getLogger(__name__)


_jwks_client: PyJWKClient | None = None


def _get_jwks_client() -> PyJWKClient:
    """Lazy + cached. PyJWKClient itself caches keys, so the singleton just
    avoids re-instantiating the HTTP fetcher per request."""
    global _jwks_client
    if _jwks_client is None:
        if not settings.SUPABASE_URL:
            raise RuntimeError("SUPABASE_URL missing — Path X JWT validation needs it")
        _jwks_client = PyJWKClient(
            f"{settings.SUPABASE_URL}/auth/v1/.well-known/jwks.json",
            # PyJWKClient defaults: lru cache size=16, requests timeout=30s.
        )
    return _jwks_client


@dataclass(frozen=True)
class UserPrincipal:
    """Authenticated identity passed to route handlers.

    Mirrors what we used to read off the SQLAlchemy User model — but the id
    is now a real ``profiles.id`` (== ``auth.users.id``), and the row really
    exists. ``email`` is included because some endpoints want it without
    re-joining; ``role`` distinguishes ``authenticated`` from ``service_role``.
    """

    id: UUID
    email: str | None
    role: str


_INVALID = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials",
)


def decode_supabase_jwt(token: str) -> dict:
    """Verify + return the JWT claims. Raises HTTPException(401) on any failure."""
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience="authenticated",
            # leeway 0 = enforce exp/iat strictly. Increase only with operator sign-off.
        )
    except (PyJWKClientError, jwt.InvalidTokenError) as e:
        # Don't leak the specific reason — same response for expired vs malformed
        # vs wrong-audience. Helps with timing-attack hardening too.
        logger.info("JWT verification rejected: %s", type(e).__name__)
        raise _INVALID
    return payload


def _principal_from_payload(payload: dict) -> UserPrincipal:
    sub = payload.get("sub")
    if not sub:
        raise _INVALID
    try:
        uid = UUID(sub)
    except (ValueError, TypeError):
        raise _INVALID
    return UserPrincipal(
        id=uid,
        email=payload.get("email"),
        role=payload.get("role", "authenticated"),
    )


# ── FastAPI dependencies ──────────────────────────────────────────────


def get_current_user(
    nai_access: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
) -> UserPrincipal:
    """Cookie-first, then Authorization: Bearer.

    Replaces the Stage 6 dependency that decoded a self-managed JWT and
    looked up a User row. The new principal needs no DB round-trip — the
    Supabase JWT already carries id, email, role.
    """
    token = nai_access
    if not token and authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() == "bearer" and value:
            token = value.strip()
    if not token:
        raise _INVALID
    return _principal_from_payload(decode_supabase_jwt(token))


def get_user_for_stream(
    nai_access: str | None = Cookie(default=None),
    token: str | None = Query(default=None, min_length=10),
) -> UserPrincipal:
    """SSE endpoint: cookie preferred, ?token= legacy fallback (still
    deprecated, kept until UI sessions cycle)."""
    presented = nai_access
    if not presented and token:
        logger.warning("SSE auth used deprecated ?token= query param")
        presented = token
    if not presented:
        raise _INVALID
    return _principal_from_payload(decode_supabase_jwt(presented))
