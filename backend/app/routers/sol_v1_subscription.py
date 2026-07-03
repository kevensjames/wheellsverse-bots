"""Sol v1 — member subscription API (Connect Stage B: $9.99/mo SaaS fee).

  GET  /sol/v1/subscription           the member's subscription status
  POST /sol/v1/subscription/checkout  a Stripe Checkout URL to start it
  POST /sol/v1/subscription/refresh    re-sync status from Stripe
  POST /sol/v1/subscription/portal     Stripe billing portal (manage/cancel)

This is Sol's software fee on its own Stripe account — separate from member
ROSCA money. Access suspension (SOL_REQUIRE_SUBSCRIPTION) is off by default.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.supabase_jwt import UserPrincipal, get_current_user
from app.schemas.sol_v1_subscription import CheckoutOut, PortalOut, SubscriptionStatusOut
from app.services.sol_v1 import subscription
from app.services.sol_v1.lifecycle import SolError

router = APIRouter(prefix="/sol/v1", tags=["sol-v1", "sol-subscription"])


def _raise(err: SolError):
    raise HTTPException(status_code=err.status_code, detail=err.detail)


@router.get("/subscription", response_model=SubscriptionStatusOut)
def get_status(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubscriptionStatusOut:
    return SubscriptionStatusOut.model_validate(subscription.status(db, user_id=current.id))


@router.post("/subscription/checkout", response_model=CheckoutOut)
def checkout(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CheckoutOut:
    try:
        url = subscription.create_checkout(db, user_id=current.id, email=current.email)
    except SolError as e:
        _raise(e)
    return CheckoutOut(url=url)


@router.post("/subscription/refresh", response_model=SubscriptionStatusOut)
def refresh(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SubscriptionStatusOut:
    try:
        subscription.refresh(db, user_id=current.id)
    except SolError as e:
        _raise(e)
    return SubscriptionStatusOut.model_validate(subscription.status(db, user_id=current.id))


@router.post("/subscription/portal", response_model=PortalOut)
def portal(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PortalOut:
    try:
        url = subscription.portal_link(db, user_id=current.id)
    except SolError as e:
        _raise(e)
    return PortalOut(url=url)
