"""Sol — non-custodial ROSCA coordinator (Stage 1: data model).

Sol coordinates rotating savings circles. It NEVER accepts, holds, routes, or
transfers member money — members pay each other directly, outside the app
(Zelle / CashApp / Venmo / cash). These tables only *record* and *coordinate*:
amounts are plain recorded numbers, payment "methods" are external rails, and
`sol_payment_profiles.handle` stores a phone / email / cashtag ONLY — never a
bank account or routing number.

All tables are namespaced `sol_*` to keep blast radius minimal inside the shared
schema. `user_id` FKs point at the canonical user table, `profiles(id)` (UUID).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# ── Enumerated string domains (kept as CHECK constraints, not PG enums, so new
#    values are a one-line migration and never a type-alter dance) ─────────────
FREQUENCIES = ("weekly", "biweekly", "monthly")
GROUP_STATUSES = ("open", "locked", "complete")
MEMBERSHIP_ROLES = ("organizer", "member")
CYCLE_STATUSES = ("pending", "active", "complete")
PAYMENT_METHODS = ("zelle", "cashapp", "venmo", "cash", "other")
PAYMENT_STATUSES = ("pending", "marked", "confirmed", "disputed", "late")
# Payment-profile methods add applepay; exclude "other" (a handle needs a rail).
PROFILE_METHODS = ("zelle", "cashapp", "venmo", "applepay", "cash")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


class SolGroup(Base):
    """A savings circle. `contribution_amount` is a recorded number only."""

    __tablename__ = "sol_groups"
    __table_args__ = (
        CheckConstraint(_in("frequency", FREQUENCIES), name="sol_groups_frequency_check"),
        CheckConstraint(_in("status", GROUP_STATUSES), name="sol_groups_status_check"),
        CheckConstraint("member_limit >= 2", name="sol_groups_member_limit_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # The member who created + is billed for the group (Stripe SaaS sub, not
    # member money). Also has an 'organizer' membership row.
    organizer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    contribution_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    frequency: Mapped[str] = mapped_column(Text, nullable=False)
    member_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    # Random token for "join via link"; set at create, used in Stage 2.
    invite_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class SolMembership(Base):
    """A user's seat in a group + their place in the payout rotation."""

    __tablename__ = "sol_memberships"
    __table_args__ = (
        UniqueConstraint("user_id", "group_id", name="sol_memberships_user_group_uq"),
        CheckConstraint(_in("role", MEMBERSHIP_ROLES), name="sol_memberships_role_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sol_groups.id", ondelete="CASCADE"), nullable=False
    )
    # NULL until the group is locked and the rotation is assigned.
    payout_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    role: Mapped[str] = mapped_column(Text, nullable=False, server_default="member")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SolCycle(Base):
    """One period of the rotation: the recipient receives everyone else's pay."""

    __tablename__ = "sol_cycles"
    __table_args__ = (
        UniqueConstraint("group_id", "cycle_number", name="sol_cycles_group_number_uq"),
        CheckConstraint(_in("status", CYCLE_STATUSES), name="sol_cycles_status_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sol_groups.id", ondelete="CASCADE"), nullable=False
    )
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # The membership receiving the pool this cycle (set when calendar is generated).
    recipient_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sol_memberships.id", ondelete="SET NULL"),
        nullable=True,
    )
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SolPayment(Base):
    """A recorded member-to-member payment for a cycle. No money moves through Sol.

    Double-confirmation: payer marks paid (`payer_marked_at`) → payee confirms
    (`payee_confirmed_at`) → status 'confirmed'. `disputed` flags a conflict.
    """

    __tablename__ = "sol_payments"
    __table_args__ = (
        CheckConstraint(_in("method", PAYMENT_METHODS), name="sol_payments_method_check"),
        CheckConstraint(_in("status", PAYMENT_STATUSES), name="sol_payments_status_check"),
        CheckConstraint("payer_id <> payee_id", name="sol_payments_distinct_parties_check"),
        # One payment per (cycle, payer): DB backstop so a duplicate cycle
        # activation can never materialize a second set of payment rows.
        UniqueConstraint("cycle_id", "payer_id", name="sol_payments_cycle_payer_uq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sol_cycles.id", ondelete="CASCADE"), nullable=False
    )
    payer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    payee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # NULL until the payer actually marks paid and picks the rail they used
    # (rows are materialized at cycle activation, before any payment happens).
    # The method CHECK still constrains non-NULL values to PAYMENT_METHODS.
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    payer_marked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payee_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SolPaymentProfile(Base):
    """How a member wants to be paid: an external-rail handle ONLY.

    HARD RULE: `handle` is a phone / email / cashtag — never a bank account or
    routing number. Sol never sees or stores bank credentials (non-custodial).
    """

    __tablename__ = "sol_payment_profiles"
    __table_args__ = (
        CheckConstraint(_in("method", PROFILE_METHODS), name="sol_payment_profiles_method_check"),
        UniqueConstraint("user_id", "method", name="sol_payment_profiles_user_method_uq"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False
    )
    method: Mapped[str] = mapped_column(Text, nullable=False)
    handle: Mapped[str] = mapped_column(Text, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SolPaymentProof(Base):
    """Optional screenshot a payer attaches when marking paid; payee reviews it."""

    __tablename__ = "sol_payment_proofs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sol_payments.id", ondelete="CASCADE"), nullable=False
    )
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
