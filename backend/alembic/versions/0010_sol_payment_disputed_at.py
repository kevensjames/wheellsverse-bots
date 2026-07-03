"""sol v1 — add sol_payments.disputed_at (Stage 5 reputation hardening)

Revision ID: 0010_sol_payment_disputed_at
Revises: 0009_sol_payments_cycle_payer_uq
Create Date: 2026-07-03

Records the FIRST time a payment was disputed and is never cleared by a payer
re-mark. Reputation reads it so a member cannot game their trust score by
re-marking a disputed payment back to 'marked' (which would otherwise erase the
payee's non-receipt signal). Additive, nullable; no data change.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0010_sol_payment_disputed_at"
down_revision: Union[str, None] = "0009_sol_payments_cycle_payer_uq"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE sol_payments ADD COLUMN IF NOT EXISTS disputed_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE sol_payments DROP COLUMN IF EXISTS disputed_at")
