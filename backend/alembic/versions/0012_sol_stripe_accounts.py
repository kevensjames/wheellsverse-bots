"""sol v1 — sol_stripe_accounts (Connect rail: member connected accounts)

Revision ID: 0012_sol_stripe_accounts
Revises: 0011_sol_consents
Create Date: 2026-07-03

Each member's own Stripe Connect (Express) account for the Stripe rail. The
account belongs to the member; Sol never holds their funds (contributions
settle directly into the recipient's connected account via destination charges).
We store only the account id + Stripe's capability flags — no bank details.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0012_sol_stripe_accounts"
down_revision: Union[str, None] = "0011_sol_consents"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sol_stripe_accounts (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id            UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            stripe_account_id  TEXT NOT NULL,
            charges_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
            payouts_enabled    BOOLEAN NOT NULL DEFAULT FALSE,
            details_submitted  BOOLEAN NOT NULL DEFAULT FALSE,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT sol_stripe_accounts_user_uq UNIQUE (user_id),
            CONSTRAINT sol_stripe_accounts_acct_uq UNIQUE (stripe_account_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sol_stripe_accounts")
