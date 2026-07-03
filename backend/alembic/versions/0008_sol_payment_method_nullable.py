"""sol v1 — make sol_payments.method nullable (Stage 3 ledger)

Revision ID: 0008_sol_payment_method_nullable
Revises: 0007_sol_v1_data_model
Create Date: 2026-07-02

Stage 3 materializes one sol_payments row per expected member-to-member payment
when a cycle is activated — before anyone has paid. At that point the rail
(zelle/cashapp/venmo/cash/other) is unknown; the payer chooses it when they mark
paid. So `method` must be nullable. The CHECK (method IN (...)) is unaffected —
a NULL satisfies a SQL CHECK; only non-NULL values are constrained.

Non-custodial: this changes nothing about what is stored — still no bank,
routing, card, or balance data. Just relaxes a NOT NULL.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0008_sol_payment_method_nullable"
down_revision: Union[str, None] = "0007_sol_v1_data_model"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE sol_payments ALTER COLUMN method DROP NOT NULL")


def downgrade() -> None:
    # Backfill any NULLs (materialized-but-unpaid rows) to 'other' so the
    # NOT NULL can be restored without failing on existing data.
    op.execute("UPDATE sol_payments SET method = 'other' WHERE method IS NULL")
    op.execute("ALTER TABLE sol_payments ALTER COLUMN method SET NOT NULL")
