"""sol v1 — allow method='stripe' on sol_payments (Connect Stage C)

Revision ID: 0015_sol_payment_method_stripe
Revises: 0014_sol_stripe_payments
Create Date: 2026-07-03

A payment settled via the Stripe rail records method='stripe'. Widen the
method CHECK to include it. Additive; no data change.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0015_sol_payment_method_stripe"
down_revision: Union[str, None] = "0014_sol_stripe_payments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE sol_payments DROP CONSTRAINT IF EXISTS sol_payments_method_check")
    op.execute(
        "ALTER TABLE sol_payments ADD CONSTRAINT sol_payments_method_check "
        "CHECK (method IN ('zelle','cashapp','venmo','cash','other','stripe'))"
    )


def downgrade() -> None:
    # Revert to the pre-stripe set (map any 'stripe' rows to 'other' first).
    op.execute("UPDATE sol_payments SET method='other' WHERE method='stripe'")
    op.execute("ALTER TABLE sol_payments DROP CONSTRAINT IF EXISTS sol_payments_method_check")
    op.execute(
        "ALTER TABLE sol_payments ADD CONSTRAINT sol_payments_method_check "
        "CHECK (method IN ('zelle','cashapp','venmo','cash','other'))"
    )
