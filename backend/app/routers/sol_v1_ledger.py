"""Sol v1 ledger API — double-confirmed member payments + payment profiles.

Second router on the /sol/v1 prefix (lifecycle is the first). Every route is
JWT-authed; the acting identity is always the token principal (`current.id`),
never a body field, so no one can act as another member.

NON-CUSTODIAL: these endpoints record and reconcile member-to-member payments
made OUTSIDE the app. Sol never moves money.
"""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.rate_limit import limiter
from app.database import get_db
from app.dependencies.supabase_jwt import UserPrincipal, get_current_user
from app.schemas.sol_v1 import CycleOut
from app.schemas.sol_v1_ledger import (
    CycleActivateOut,
    MarkPaidRequest,
    PaymentDetail,
    PaymentOut,
    PaymentProfileOut,
    PaymentProfileUpsert,
    ProofCreate,
    ProofOut,
    ResolvePaymentRequest,
)
from app.services.sol_v1 import ledger
from app.services.sol_v1.lifecycle import SolError

router = APIRouter(prefix="/sol/v1", tags=["sol-v1", "sol-ledger"])


def _raise(err: SolError):
    raise HTTPException(status_code=err.status_code, detail=err.detail)


# ── cycle activation ──────────────────────────────────────────────────────────


@router.post("/cycles/{cycle_id}/activate", response_model=CycleActivateOut)
@limiter.limit("30/minute")
def activate_cycle(
    cycle_id: UUID,
    request: Request,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CycleActivateOut:
    try:
        cycle, payments = ledger.activate_cycle(db, cycle_id=cycle_id, actor_id=current.id)
    except SolError as e:
        _raise(e)
    return CycleActivateOut(
        cycle=CycleOut.model_validate(cycle),
        payments=[PaymentOut.model_validate(p) for p in payments],
    )


# ── payments ──────────────────────────────────────────────────────────────────


@router.get("/payments", response_model=list[PaymentOut])
def my_payments(
    role: Literal["payer", "payee", "all"] = Query("all"),
    payment_status: str | None = Query(None, alias="status"),
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PaymentOut]:
    try:
        payments = ledger.list_payments(
            db, user_id=current.id, role=role, status=payment_status
        )
    except SolError as e:
        _raise(e)
    return [PaymentOut.model_validate(p) for p in payments]


@router.get("/payments/{payment_id}", response_model=PaymentDetail)
def payment_detail(
    payment_id: UUID,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentDetail:
    try:
        payment, proofs, pay_to, organizer_id = ledger.get_payment_detail(
            db, payment_id=payment_id, user_id=current.id
        )
    except SolError as e:
        _raise(e)
    disputed = payment.status == "disputed"
    return PaymentDetail(
        payment=PaymentOut.model_validate(payment),
        proofs=[ProofOut.model_validate(pr) for pr in proofs],
        pay_to=[PaymentProfileOut.model_validate(pp) for pp in pay_to],
        # who may act on a disputed payment, computed server-side so the SPA
        # never has to guess (and never shows a button that would 403)
        can_withdraw=disputed and current.id == payment.payee_id,
        can_waive=disputed and current.id == organizer_id,
    )


@router.post("/payments/{payment_id}/mark", response_model=PaymentOut)
@limiter.limit("30/minute")
def mark_paid(
    payment_id: UUID,
    request: Request,
    body: MarkPaidRequest,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOut:
    try:
        payment = ledger.mark_paid(
            db,
            payment_id=payment_id,
            actor_id=current.id,
            method=body.method,
            proof_image_url=body.proof_image_url,
        )
    except SolError as e:
        _raise(e)
    return PaymentOut.model_validate(payment)


@router.post("/payments/{payment_id}/confirm", response_model=PaymentOut)
@limiter.limit("30/minute")
def confirm_received(
    payment_id: UUID,
    request: Request,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOut:
    try:
        payment = ledger.confirm_received(db, payment_id=payment_id, actor_id=current.id)
    except SolError as e:
        _raise(e)
    return PaymentOut.model_validate(payment)


@router.post("/payments/{payment_id}/dispute", response_model=PaymentOut)
@limiter.limit("30/minute")
def dispute(
    payment_id: UUID,
    request: Request,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOut:
    try:
        payment = ledger.dispute(db, payment_id=payment_id, actor_id=current.id)
    except SolError as e:
        _raise(e)
    return PaymentOut.model_validate(payment)


@router.post("/payments/{payment_id}/dispute/withdraw", response_model=PaymentOut)
@limiter.limit("30/minute")
def withdraw_dispute(
    payment_id: UUID,
    request: Request,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOut:
    """PAYEE retracts a mistaken dispute → the payment returns to 'marked'."""
    try:
        payment = ledger.withdraw_dispute(db, payment_id=payment_id, actor_id=current.id)
    except SolError as e:
        _raise(e)
    return PaymentOut.model_validate(payment)


@router.post("/payments/{payment_id}/resolve", response_model=PaymentOut)
@limiter.limit("30/minute")
def resolve_payment(
    payment_id: UUID,
    request: Request,
    body: ResolvePaymentRequest,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOut:
    """ORGANIZER resolves a disputed payment. This stage supports outcome='waive'
    (a terminal write-off that unfreezes a stranded cycle). No money moves."""
    if body.outcome != "waive":
        raise HTTPException(status_code=400, detail=f"unsupported outcome {body.outcome!r}")
    try:
        payment = ledger.waive_dispute(
            db, payment_id=payment_id, actor_id=current.id, note=body.note
        )
    except SolError as e:
        _raise(e)
    return PaymentOut.model_validate(payment)


@router.post(
    "/payments/{payment_id}/proofs",
    response_model=ProofOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("20/minute")
def add_proof(
    payment_id: UUID,
    request: Request,
    body: ProofCreate,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProofOut:
    try:
        proof = ledger.add_proof(
            db, payment_id=payment_id, actor_id=current.id, image_url=body.image_url
        )
    except SolError as e:
        _raise(e)
    return ProofOut.model_validate(proof)


# ── payment profiles ──────────────────────────────────────────────────────────


@router.get("/payment-profiles", response_model=list[PaymentProfileOut])
def my_payment_profiles(
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PaymentProfileOut]:
    profiles = ledger.list_payment_profiles(db, user_id=current.id)
    return [PaymentProfileOut.model_validate(p) for p in profiles]


@router.put("/payment-profiles", response_model=PaymentProfileOut)
@limiter.limit("20/minute")
def upsert_payment_profile(
    request: Request,
    body: PaymentProfileUpsert,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentProfileOut:
    try:
        profile = ledger.upsert_payment_profile(
            db,
            user_id=current.id,
            method=body.method,
            handle=body.handle,
            is_default=body.is_default,
        )
    except SolError as e:
        _raise(e)
    return PaymentProfileOut.model_validate(profile)


@router.delete("/payment-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
def delete_payment_profile(
    profile_id: UUID,
    request: Request,
    current: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    try:
        ledger.delete_payment_profile(db, user_id=current.id, profile_id=profile_id)
    except SolError as e:
        _raise(e)
