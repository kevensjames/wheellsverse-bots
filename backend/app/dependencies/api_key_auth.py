"""API-key authentication dependency for /v1/* endpoints.

Distinct from the cookie/JWT auth used on /kai/* (the SPA path) and
/account/* (key management UI). Drop-in OpenAI-compatible clients send:

    Authorization: Bearer kai_xxx...

We resolve the key to its owner, check tier-gate (must be paid), and
build a UserPrincipal so the downstream endpoint code is shape-identical
to cookie-auth handlers.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.supabase_jwt import UserPrincipal
from app.models.profile import Profile
from app.services import api_keys

logger = logging.getLogger(__name__)

_API_TIERS = {"max", "ultra"}  # Pro is web-only; API requires Max or Ultra.


def require_api_key_user(
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> UserPrincipal:
    """Resolve a `Authorization: Bearer kai_xxx` header to a UserPrincipal.

    Tier-gated: free users cannot use API keys even if they have a valid key
    (covers the downgrade case — they had Pro, issued keys, downgraded).
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing Authorization header (expected 'Bearer kai_...')",
            headers={"WWW-Authenticate": 'Bearer realm="kai"'},
        )
    plaintext = authorization.split(None, 1)[1].strip()
    key_row = api_keys.verify(db, plaintext)
    if key_row is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or revoked API key",
            headers={"WWW-Authenticate": 'Bearer realm="kai"'},
        )

    profile = db.get(Profile, key_row.user_id)
    if profile is None:
        # Cascade should have killed the key when profile deleted, but
        # defend in depth.
        raise HTTPException(status_code=401, detail="key owner not found")

    if (profile.tier or "free") not in _API_TIERS:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "API access requires a paid plan",
                "current_tier": profile.tier or "free",
                "upgrade_url": "https://kai.wheellsverse.com/kai-ui/pricing.html",
            },
        )

    return UserPrincipal(
        id=profile.id,
        email=profile.email,
        role="authenticated",
    )
