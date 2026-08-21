"""Multi-user JWT auth via Supabase. Email/password login route delegates to
Supabase auth, then mints a NarAI-signed JWT with the real user UUID as `sub`.
"""
import logging
import os
import sys

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

log = logging.getLogger("narai.auth")

# Insecure default values that must not be used in production
_INSECURE_DEFAULTS = {
    "change-me-in-production-narai-2026",
    "change-me-to-a-random-256-bit-string",
}


def _get_jwt_secret() -> str:
    """Get JWT secret from environment with security validation.
    
    Fails fast if the secret is missing or set to a known insecure default.
    This prevents authentication bypass vulnerabilities in misconfigured deployments.
    """
    secret = os.getenv("NARAI_JWT_SECRET", "").strip()
    
    if not secret:
        log.critical(
            "NARAI_JWT_SECRET environment variable is not set. "
            "The application cannot start without a secure JWT secret. "
            "Generate a random secret: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
        sys.exit(1)
    
    if secret in _INSECURE_DEFAULTS:
        log.critical(
            f"NARAI_JWT_SECRET is set to an insecure default value. "
            f"This creates an authentication bypass vulnerability. "
            f"Generate a random secret: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
        sys.exit(1)
    
    if len(secret) < 32:
        log.critical(
            f"NARAI_JWT_SECRET is too short ({len(secret)} characters). "
            f"Use at least 32 characters for adequate security. "
            f"Generate a random secret: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
        sys.exit(1)
    
    return secret


_SECRET = _get_jwt_secret()
_ALGORITHM = "HS256"
_TTL_HOURS = int(os.getenv("NARAI_JWT_TTL_HOURS", "72"))

_bearer = HTTPBearer(auto_error=True)


def sign_in_with_supabase(email: str, password: str) -> str | None:
    """Validate email+password against Supabase auth. Returns the user UUID
    on success, None on failure. Errors are logged, never propagated."""
    try:
        from core.narai_user import get_supabase
        sb = get_supabase()
        res = sb.auth.sign_in_with_password({"email": email, "password": password})
        if res and getattr(res, "user", None):
            return res.user.id
        return None
    except Exception as e:
        log.warning(f"supabase sign-in failed for {email}: {e}")
        return None


def create_token(user_id: str) -> str:
    """Mint a NarAI-signed JWT with the given user UUID as `sub`."""
    import jwt  # PyJWT — pure Python, no compiled extensions
    expire = datetime.now(timezone.utc) + timedelta(hours=_TTL_HOURS)
    return jwt.encode({"sub": user_id, "exp": expire}, _SECRET, algorithm=_ALGORITHM)


def require_auth(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    import jwt  # PyJWT
    try:
        payload = jwt.decode(creds.credentials, _SECRET, algorithms=[_ALGORITHM])
        return payload["sub"]
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
