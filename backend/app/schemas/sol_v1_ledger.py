"""Sol v1 ledger schemas — payments, proofs, and payment profiles.

Money-free: `amount` is a recorded number, `method` is an external rail name,
`handle` is a phone/email/tag. No bank/routing/card fields anywhere.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sol_v1 import CycleOut

# ── requests ─────────────────────────────────────────────────────────────────


class MarkPaidRequest(BaseModel):
    method: Literal["zelle", "cashapp", "venmo", "cash", "other"]
    proof_image_url: str | None = Field(default=None, max_length=2048)


class ProofCreate(BaseModel):
    image_url: str = Field(min_length=1, max_length=2048)


class PaymentProfileUpsert(BaseModel):
    method: Literal["zelle", "cashapp", "venmo", "applepay", "cash"]
    handle: str = Field(min_length=1, max_length=128)
    is_default: bool = False


# ── responses ────────────────────────────────────────────────────────────────


class ProofOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    payment_id: UUID
    image_url: str
    uploaded_at: datetime


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cycle_id: UUID
    payer_id: UUID
    payee_id: UUID
    amount: Decimal
    method: str | None = None
    status: str
    payer_marked_at: datetime | None = None
    payee_confirmed_at: datetime | None = None
    created_at: datetime


class PaymentProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    method: str
    handle: str
    is_default: bool
    created_at: datetime


class PaymentDetail(BaseModel):
    payment: PaymentOut
    proofs: list[ProofOut]
    # How to pay this payment: the payee's external-rail handles.
    pay_to: list[PaymentProfileOut]


class CycleActivateOut(BaseModel):
    cycle: CycleOut
    payments: list[PaymentOut]


# ── reminders (Stage 4) ───────────────────────────────────────────────────────


class ReminderItem(BaseModel):
    payment_id: UUID
    cycle_id: UUID
    counterparty_id: UUID
    amount: Decimal
    status: str
    due_date: date
    # 'overdue' | 'due_today' | 'upcoming' | 'scheduled'
    kind: str
    # 'payer' (you owe) | 'payee' (owed to you)
    role: str


class RemindersOut(BaseModel):
    as_payer: list[ReminderItem]
    as_payee: list[ReminderItem]
