"""Single-user JWT auth. Password stored as bcrypt hash in .env (NARAI_PASSWORD_HASH).
To generate: python -c "from passlib.hash import bcrypt; print(bcrypt.hash('yourpassword'))"
"""
import os

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_SECRET = os.getenv("NARAI_JWT_SECRET", "change-me-in-production-narai-2026")
_ALGORITHM = "HS256"
_TTL_HOURS = int(os.getenv("NARAI_JWT_TTL_HOURS", "72"))
_PASSWORD_HASH = os.getenv("NARAI_PASSWORD_HASH", "")

_bearer = HTTPBearer(auto_error=True)


def verify_password(plain: str) -> bool:
    import bcrypt as _bcrypt  # lazy — module loads even if bcrypt wheel is absent at import time
    if not _PASSWORD_HASH:
        raise EnvironmentError("NARAI_PASSWORD_HASH not set")
    return _bcrypt.checkpw(plain.encode(), _PASSWORD_HASH.encode())


def create_token() -> str:
    from jose import jwt  # lazy — module loads even if jose wheel is absent at import time
    expire = datetime.now(timezone.utc) + timedelta(hours=_TTL_HOURS)
    return jwt.encode({"sub": "owner", "exp": expire}, _SECRET, algorithm=_ALGORITHM)


def require_auth(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> str:
    from jose import JWTError, jwt  # lazy
    try:
        payload = jwt.decode(creds.credentials, _SECRET, algorithms=[_ALGORITHM])
        return payload["sub"]
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
