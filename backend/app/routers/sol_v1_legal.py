"""Sol v1 legal API — the current disclosure + recorded consent.

  GET  /sol/v1/legal/current   the current terms + whether the caller accepted
  POST /sol/v1/legal/accept    record the caller's acceptance of the current terms

The create/join routes gate on this (server-enforced); the app also checks it up
front to show the consent screen.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.database import get_db
from app.dependencies.supabase_jwt import UserPrincipal, get_current_user
from app.schemas.sol_v1_legal import AcceptRequest, LegalStatusOut
from app.services.sol_v1 import disclosures
from app.services.sol_v1.lifecycle import SolError

router = APIRouter(prefix="/sol/v1", tags=["sol-v1", "sol-legal"])


@router.get("/legal/current", response_model=LegalStatusOut)
def current_terms(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LegalStatusOut:
    return LegalStatusOut.model_validate(disclosures.consent_status(db, user_id=current.id))


@router.post("/legal/accept", response_model=LegalStatusOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
def accept_terms(
    request: Request,
    body: AcceptRequest,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LegalStatusOut:
    try:
        disclosures.record_consent(
            db, user_id=current.id,
            document_key=disclosures.CURRENT["document_key"], version=body.version,
        )
    except SolError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    return LegalStatusOut.model_validate(disclosures.consent_status(db, user_id=current.id))
