"""Sol v1 — Stripe-rail contribution API (Connect Stage C: destination charges).

  POST /sol/v1/stripe/payments/{payment_id}/checkout   pay the recipient via Stripe
  POST /sol/v1/stripe/payments/{payment_id}/reconcile   re-check + settle if paid
  GET  /sol/v1/stripe/payments/{payment_id}             the Stripe charge status

Sandbox-locked. NON-CUSTODIAL: every charge is a destination charge to the
recipient's connected account; Sol's balance is never touched.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.supabase_jwt import UserPrincipal, get_current_user
from app.schemas.sol_v1_charges import ChargeCheckoutOut, ChargeStatusOut
from app.services.sol_v1 import stripe_charges
from app.services.sol_v1.lifecycle import SolError

router = APIRouter(prefix="/sol/v1", tags=["sol-v1", "sol-stripe"])


def _raise(err: SolError):
    raise HTTPException(status_code=err.status_code, detail=err.detail)


@router.post("/stripe/payments/{payment_id}/checkout", response_model=ChargeCheckoutOut)
def contribution_checkout(
    payment_id: UUID,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChargeCheckoutOut:
    try:
        url = stripe_charges.create_contribution_checkout(db, payment_id=payment_id, payer_id=current.id)
    except SolError as e:
        _raise(e)
    return ChargeCheckoutOut(url=url)


@router.post("/stripe/payments/{payment_id}/reconcile", response_model=ChargeStatusOut)
def contribution_reconcile(
    payment_id: UUID,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChargeStatusOut:
    try:
        data = stripe_charges.reconcile(db, payment_id=payment_id, actor_id=current.id)
    except SolError as e:
        _raise(e)
    return ChargeStatusOut.model_validate(data)


@router.get("/stripe/payments/{payment_id}", response_model=ChargeStatusOut)
def contribution_status(
    payment_id: UUID,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChargeStatusOut:
    try:
        data = stripe_charges.charge_status(db, payment_id=payment_id, actor_id=current.id)
    except SolError as e:
        _raise(e)
    return ChargeStatusOut.model_validate(data)
