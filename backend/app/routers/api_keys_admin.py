"""Self-service API key management for paid KAI users.

Cookie-auth (same as /kai/*). Frontend lives at /kai-ui/api-keys.html
which posts to these endpoints.

  POST   /account/api-keys           → create + return plaintext ONCE
  GET    /account/api-keys           → list active keys (no plaintext)
  DELETE /account/api-keys/{key_id}  → revoke
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.supabase_jwt import UserPrincipal
from app.models.profile import Profile
from app.services import api_keys

router = APIRouter(prefix="/account/api-keys", tags=["api-keys"])

_API_TIERS = {"max", "ultra"}  # Pro is web-only; API access starts at Max.


def _require_api_tier(db: Session, user_id: uuid.UUID) -> Profile:
    profile = db.get(Profile, user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    tier = (profile.tier or "free").lower()
    if tier not in _API_TIERS:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "API access starts at the Max tier",
                "current_tier": tier,
                "upgrade_url": "/kai-ui/pricing.html",
            },
        )
    return profile


class CreateKeyRequest(BaseModel):
    label: str | None = Field(default=None, max_length=80)


class CreateKeyResponse(BaseModel):
    id: uuid.UUID
    label: str | None
    prefix: str
    created_at: str
    # Only present on create — the plaintext is shown ONCE.
    key: str


class KeyListItem(BaseModel):
    id: uuid.UUID
    label: str | None
    prefix: str
    created_at: str
    last_used_at: str | None


@router.post("", response_model=CreateKeyResponse, status_code=status.HTTP_201_CREATED)
def create_api_key(
    body: CreateKeyRequest,
    user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CreateKeyResponse:
    _require_api_tier(db, user.id)
    row, plaintext = api_keys.issue(db, user.id, label=body.label)
    return CreateKeyResponse(
        id=row.id,
        label=row.label,
        prefix=row.prefix,
        created_at=row.created_at.isoformat(),
        key=plaintext,
    )


@router.get("", response_model=list[KeyListItem])
def list_api_keys(
    user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KeyListItem]:
    _require_api_tier(db, user.id)
    rows = api_keys.list_active(db, user.id)
    return [
        KeyListItem(
            id=r.id,
            label=r.label,
            prefix=r.prefix,
            created_at=r.created_at.isoformat(),
            last_used_at=r.last_used_at.isoformat() if r.last_used_at else None,
        )
        for r in rows
    ]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(
    key_id: uuid.UUID,
    user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_api_tier(db, user.id)
    ok = api_keys.revoke(db, user.id, key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="key not found")
    return None
