"""Supabase Auth wrapper (Path X).

Why this exists: Stage 6 originally reinvented self-managed JWT auth against
a `public.users` table that does not exist in prod. Prod uses canonical
Supabase Auth: `auth.users` is the identity table, an `on_auth_user_created`
trigger mirrors rows into `public.profiles`, and every app table FKs to
`profiles.id`. This module is the thin layer that lets our FastAPI signup/
login/refresh handlers talk to that real system instead of the fictional one.

Three calls, two keys:
- ``create_user(email, password, full_name)`` — admin signup. Uses the
  **secret key**. Server-only — never call from a browser. The trigger
  populates ``profiles`` automatically.
- ``password_login(email, password)`` — password grant via ``/auth/v1/token``.
  Uses the **publishable key** (anon-level). Proxied through the backend so
  we can set HttpOnly cookies on the response.
- ``refresh_token(refresh)`` — refresh grant. Same endpoint, ``grant_type=
  refresh_token``. Publishable key.

Error handling: Supabase returns granular errors (email_exists,
weak_password, etc.). We collapse them to short generic strings so the
client surface doesn't leak Supabase implementation detail or aid
enumeration. The full error body is logged at WARNING level for debugging.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from supabase import Client, create_client

from app.config import settings

logger = logging.getLogger(__name__)


_admin: Client | None = None


def _config_or_raise() -> None:
    """Bail loudly at import-time use if env isn't wired — prevents the
    Stage 6 'silent default that never works in prod' failure mode."""
    if not settings.SUPABASE_URL or not settings.SUPABASE_SECRET_KEY:
        raise RuntimeError(
            "SUPABASE_URL / SUPABASE_SECRET_KEY missing — see Path X setup docs."
        )


def admin_client() -> Client:
    """Lazy singleton. Service-role bypasses all RLS — never expose."""
    global _admin
    if _admin is None:
        _config_or_raise()
        _admin = create_client(settings.SUPABASE_URL, settings.SUPABASE_SECRET_KEY)
    return _admin


class AuthError(Exception):
    """Generic auth failure. Detail is safe to surface to the client."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def create_user(email: str, password: str, full_name: str | None = None) -> dict[str, Any]:
    """Create an auth.users row. Trigger handle_new_user fills profiles.

    `email_confirm=True` skips the confirmation-email round-trip so the new
    account is immediately usable. When email verification UX is added
    later, flip this to False and wire the verify flow.
    """
    user_metadata: dict[str, Any] = {}
    if full_name:
        # `handle_new_user()` reads raw_user_meta_data->>'full_name'
        # to populate profiles.name. Match that exact key.
        user_metadata["full_name"] = full_name

    try:
        resp = admin_client().auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,
                "user_metadata": user_metadata,
            }
        )
    except Exception as e:
        # Extract a structured detail from supabase-py's AuthApiError if present.
        # The .code / .message fields are the Supabase-server categorisation
        # (e.g. "weak_password", "email_address_invalid", "email_exists") —
        # safe to surface and helpful for the client to act on.
        raw = str(e)
        code = getattr(e, "code", None) or ""
        message = getattr(e, "message", None) or ""
        msg_l = (raw + " " + code + " " + message).lower()
        logger.warning(
            "Supabase create_user failed for %s: type=%s code=%r message=%r raw=%s",
            email, type(e).__name__, code, message, raw[:200],
        )
        if any(t in msg_l for t in ("already", "registered", "exists")):
            raise AuthError("email already registered", status_code=409)
        if "weak_password" in msg_l or "password" in msg_l:
            raise AuthError("password too weak", status_code=400)
        if "email_address_invalid" in msg_l or "invalid_email" in msg_l:
            raise AuthError("email address rejected by auth provider", status_code=400)
        if "signup" in msg_l and "disabled" in msg_l:
            raise AuthError("signups are disabled in supabase auth settings", status_code=503)
        # Generic fallback — include exception class + supabase code if any
        # (not the raw text). Class name + code are safe; they tell us
        # "AuthRetryableError" vs "ConnectionError" vs "AuthApiError(weak_password)"
        # without leaking credentials or server internals.
        cls_name = type(e).__name__
        if code:
            detail = f"signup failed ({cls_name}: {code})"
        else:
            detail = f"signup failed ({cls_name})"
        raise AuthError(detail, status_code=400)

    # supabase-py 2.x returns a `UserResponse` object with `.user`. Older
    # paths returned dicts. Handle both without the operator-precedence trap
    # that previously yielded `user=None` for every successful call.
    if hasattr(resp, "user"):
        user = resp.user
    elif isinstance(resp, dict):
        user = resp.get("user")
    else:
        user = None

    if user is None:
        logger.warning(
            "Supabase create_user returned no user; resp type=%s repr=%s",
            type(resp).__name__, repr(resp)[:200],
        )
        raise AuthError("signup failed (no user in response)", status_code=400)
    return {"id": str(user.id), "email": user.email}


def password_login(email: str, password: str) -> dict[str, Any]:
    """Password grant. Returns Supabase access + refresh tokens.

    We hit the REST endpoint directly (rather than supabase-py's
    auth.sign_in_with_password) so we control the failure mode and don't
    pull the session into the supabase-py global Auth client.
    """
    _config_or_raise()
    if not settings.SUPABASE_PUBLISHABLE_KEY:
        raise RuntimeError("SUPABASE_PUBLISHABLE_KEY missing")

    try:
        r = httpx.post(
            f"{settings.SUPABASE_URL}/auth/v1/token",
            params={"grant_type": "password"},
            headers={
                "apikey": settings.SUPABASE_PUBLISHABLE_KEY,
                "Content-Type": "application/json",
            },
            json={"email": email, "password": password},
            timeout=15.0,
        )
    except httpx.HTTPError as e:
        logger.warning("Supabase password grant network error: %s", e)
        raise AuthError("login failed", status_code=502)

    if r.status_code != 200:
        # Generic message — same for bad password, unknown email, unverified
        # email. Prevents enumeration.
        logger.info(
            "Supabase password grant rejected for %s (status=%d body=%s)",
            email, r.status_code, r.text[:200],
        )
        raise AuthError("invalid email or password", status_code=401)

    data = r.json()
    user = data.get("user") or {}
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_in": data.get("expires_in", 3600),
        "user_id": user.get("id"),
        "user_email": user.get("email"),
    }


def refresh_session(refresh: str) -> dict[str, Any]:
    """Refresh-token grant. Same shape as password_login."""
    _config_or_raise()
    if not settings.SUPABASE_PUBLISHABLE_KEY:
        raise RuntimeError("SUPABASE_PUBLISHABLE_KEY missing")

    try:
        r = httpx.post(
            f"{settings.SUPABASE_URL}/auth/v1/token",
            params={"grant_type": "refresh_token"},
            headers={
                "apikey": settings.SUPABASE_PUBLISHABLE_KEY,
                "Content-Type": "application/json",
            },
            json={"refresh_token": refresh},
            timeout=15.0,
        )
    except httpx.HTTPError as e:
        logger.warning("Supabase refresh grant network error: %s", e)
        raise AuthError("refresh failed", status_code=502)

    if r.status_code != 200:
        logger.info(
            "Supabase refresh grant rejected (status=%d body=%s)",
            r.status_code, r.text[:200],
        )
        raise AuthError("invalid refresh token", status_code=401)

    data = r.json()
    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_in": data.get("expires_in", 3600),
    }


def delete_user(user_id: str) -> None:
    """Admin-only. Cascades through profiles + chat tables via FK ON DELETE."""
    try:
        admin_client().auth.admin.delete_user(user_id)
    except Exception as e:
        logger.warning("Supabase delete_user failed for %s: %s", user_id, e)
        raise AuthError("delete failed", status_code=400)
