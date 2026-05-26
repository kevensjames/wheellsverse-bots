from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import decode_token
from app.database import get_db
from app.models.user import User


# auto_error=False so the dependency doesn't 401 when the header is absent —
# the cookie path can still satisfy the request. Swagger's "Authorize" button
# still works because the scheme is registered.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)

_CREDENTIALS_EXC = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    nai_access: str | None = Cookie(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Accept either Authorization: Bearer header OR the nai_access cookie.

    Header is preferred (API clients); cookie is the browser-UI path. If both
    are present the header wins — keeps API clients deterministic.
    """
    presented = token or nai_access
    if not presented:
        raise _CREDENTIALS_EXC
    try:
        payload = decode_token(presented)
    except JWTError:
        raise _CREDENTIALS_EXC

    if payload.get("type") != "access":
        raise _CREDENTIALS_EXC

    sub = payload.get("sub")
    if not sub:
        raise _CREDENTIALS_EXC

    try:
        user_id = UUID(sub)
    except (ValueError, TypeError):
        raise _CREDENTIALS_EXC

    user = db.get(User, user_id)
    if user is None:
        raise _CREDENTIALS_EXC
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user")
    return user


def get_current_active_verified_user(
    user: User = Depends(get_current_user),
) -> User:
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified")
    return user
