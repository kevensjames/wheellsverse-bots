"""Multi-user JWT auth via Supabase. Email/password login route delegates to
Supabase auth, then mints a NarAI-signed JWT with the real user UUID as `sub`.
"""
import logging
import os

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

log = logging.getLogger("narai.auth")

_SECRET = os.getenv("NARAI_JWT_SECRET", "change-me-in-production-narai-2026")
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
