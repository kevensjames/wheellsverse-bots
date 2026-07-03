"""sol v1 — sol_notifications (durable in-app inbox) [Stage 8: notifications]

Revision ID: 0016_sol_notifications
Revises: 0015_sol_payment_method_stripe
Create Date: 2026-07-03

Members currently receive NOTHING — the reminder scan only builds an operator
Telegram digest. This adds a durable, per-member in-app inbox so the daily
due/overdue sweep (and later ledger events) actually reach members.

NON-CUSTODIAL: notifications only carry text + a deep-link; no money, no bank
data. `dedup_key` (UNIQUE per user) makes emission idempotent — the daily scan
re-runs without ever creating a second copy of the same nudge. Additive.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0016_sol_notifications"
down_revision: Union[str, None] = "0015_sol_payment_method_stripe"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KINDS = (
    "payment_due",
    "payment_overdue",
    "payment_marked",
    "payment_confirmed",
    "payment_disputed",
    "cycle_started",
    "payout_incoming",
)


def upgrade() -> None:
    kinds = ", ".join(f"'{k}'" for k in _KINDS)
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS sol_notifications (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            kind          TEXT NOT NULL,
            title         TEXT NOT NULL,
            body          TEXT NOT NULL,
            link          TEXT,
            payment_id    UUID REFERENCES sol_payments(id) ON DELETE SET NULL,
            dedup_key     TEXT NOT NULL,
            read_at       TIMESTAMPTZ,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT sol_notifications_kind_check CHECK (kind IN ({kinds})),
            CONSTRAINT sol_notifications_user_dedup_uq UNIQUE (user_id, dedup_key)
        )
        """
    )
    # Drives unread-count + the member's newest-first list (partial-ish: the
    # common query filters by user then reads read_at).
    op.execute(
        "CREATE INDEX IF NOT EXISTS sol_notifications_user_created_idx "
        "ON sol_notifications (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS sol_notifications_user_unread_idx "
        "ON sol_notifications (user_id) WHERE read_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sol_notifications")
