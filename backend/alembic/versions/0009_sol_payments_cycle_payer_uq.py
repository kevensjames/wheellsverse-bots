"""sol v1 — UNIQUE(cycle_id, payer_id) on sol_payments (Stage 3 hardening)

Revision ID: 0009_sol_payments_cycle_payer_uq
Revises: 0008_sol_payment_method_nullable
Create Date: 2026-07-02

A payer owes at most one payment per cycle. This constraint is a hard DB
backstop against duplicate cycle activation ever materializing a second set of
payment rows (the service also locks the cycle row, but belt + suspenders on a
money-coordination ledger). Additive; no data change.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0009_sol_payments_cycle_payer_uq"
down_revision: Union[str, None] = "0008_sol_payment_method_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE sol_payments "
        "ADD CONSTRAINT sol_payments_cycle_payer_uq UNIQUE (cycle_id, payer_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE sol_payments DROP CONSTRAINT IF EXISTS sol_payments_cycle_payer_uq")
