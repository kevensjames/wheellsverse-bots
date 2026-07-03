"""sol v1 — sol_stripe_payments (Connect Stage C: destination-charge settlement)

Revision ID: 0014_sol_stripe_payments
Revises: 0013_sol_member_subscriptions
Create Date: 2026-07-03

Links a ledger payment (sol_payments) to its Stripe destination charge. NON-
CUSTODIAL: destination_account_id (NOT NULL) is the recipient's connected
account — the charge's transfer_data.destination — so funds settle directly
into the recipient's account and Sol's platform balance is never touched.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0014_sol_stripe_payments"
down_revision: Union[str, None] = "0013_sol_member_subscriptions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sol_stripe_payments (
            id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            payment_id                  UUID NOT NULL REFERENCES sol_payments(id) ON DELETE CASCADE,
            payer_id                    UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            destination_account_id      TEXT NOT NULL,
            amount                      NUMERIC(12,2) NOT NULL,
            stripe_checkout_session_id  TEXT,
            stripe_payment_intent_id    TEXT,
            status                      TEXT NOT NULL DEFAULT 'pending',
            created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT sol_stripe_payments_payment_uq UNIQUE (payment_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_sol_stripe_payments_pi ON sol_stripe_payments (stripe_payment_intent_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sol_stripe_payments")
