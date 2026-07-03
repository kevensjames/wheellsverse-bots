"""sol v1 — sol_member_subscriptions (Connect Stage B: $9.99/mo SaaS fee)

Revision ID: 0013_sol_member_subscriptions
Revises: 0012_sol_stripe_accounts
Create Date: 2026-07-03

The member's platform subscription (Stripe Billing on Sol's own account). This
is Sol's software revenue, entirely separate from member ROSCA money. Status
mirrors Stripe; 'active'/'trialing' mean the member has platform access.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0013_sol_member_subscriptions"
down_revision: Union[str, None] = "0012_sol_stripe_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sol_member_subscriptions (
            id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                 UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            stripe_customer_id      TEXT,
            stripe_subscription_id  TEXT,
            status                  TEXT NOT NULL DEFAULT 'none',
            current_period_end      TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT sol_member_subscriptions_user_uq UNIQUE (user_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sol_member_subscriptions")
