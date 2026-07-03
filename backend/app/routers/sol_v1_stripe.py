"""Sol v1 — Stripe Connect API (Connect Stage A: onboarding).

  GET  /sol/v1/stripe/account          the member's connect status (DB read)
  POST /sol/v1/stripe/account/onboard  a Stripe-hosted onboarding link
  POST /sol/v1/stripe/account/refresh  re-sync capability flags from Stripe

Sandbox-locked: the onboard/refresh operations refuse to run against a live key
unless live use is approved (see services/sol_v1/stripe_connect._guard).
Non-custodial: the connected account belongs to the member; Sol never holds funds.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.supabase_jwt import UserPrincipal, get_current_user
from app.schemas.sol_v1_stripe import ConnectStatusOut, OnboardingLinkOut
from app.services.sol_v1 import stripe_connect
from app.services.sol_v1.lifecycle import SolError

router = APIRouter(prefix="/sol/v1", tags=["sol-v1", "sol-stripe"])


def _raise(err: SolError):
    raise HTTPException(status_code=err.status_code, detail=err.detail)


@router.get("/stripe/account", response_model=ConnectStatusOut)
def stripe_account(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConnectStatusOut:
    return ConnectStatusOut.model_validate(stripe_connect.account_status(db, user_id=current.id))


@router.post("/stripe/account/onboard", response_model=OnboardingLinkOut)
def stripe_onboard(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> OnboardingLinkOut:
    try:
        url = stripe_connect.onboarding_link(db, user_id=current.id, email=current.email)
    except SolError as e:
        _raise(e)
    return OnboardingLinkOut(url=url)


@router.post("/stripe/account/refresh", response_model=ConnectStatusOut)
def stripe_refresh(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ConnectStatusOut:
    try:
        stripe_connect.refresh_status(db, user_id=current.id)
    except SolError as e:
        _raise(e)
    return ConnectStatusOut.model_validate(stripe_connect.account_status(db, user_id=current.id))
