"""sol v1 — template waitlist + circle_opening notification kind [Stage 18]

Revision ID: 0018_sol_waitlist
Revises: 0017_sol_circle_templates
Create Date: 2026-07-04

Users can WAIT on a circle template; when the creator spawns a new instance the
waitlisted users are notified (an in-app 'circle_opening' nudge with the invite
code) so they can join. Additive: a new table + one widened CHECK.

NON-CUSTODIAL: a waitlist entry + a notification carry no money.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0018_sol_waitlist"
down_revision: Union[str, None] = "0017_sol_circle_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# sol_notifications kinds after adding circle_opening (Stage 18).
_KINDS = (
    "payment_due", "payment_overdue", "payment_marked", "payment_confirmed",
    "payment_disputed", "cycle_started", "payout_incoming", "circle_opening",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sol_waitlist (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            template_id UUID NOT NULL REFERENCES sol_circle_templates(id) ON DELETE CASCADE,
            user_id     UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT sol_waitlist_template_user_uq UNIQUE (template_id, user_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS sol_waitlist_template_idx ON sol_waitlist (template_id)"
    )
    # widen the notification kind CHECK to allow 'circle_opening'
    kinds = ", ".join(f"'{k}'" for k in _KINDS)
    op.execute("ALTER TABLE sol_notifications DROP CONSTRAINT IF EXISTS sol_notifications_kind_check")
    op.execute(
        f"ALTER TABLE sol_notifications ADD CONSTRAINT sol_notifications_kind_check "
        f"CHECK (kind IN ({kinds}))"
    )


def downgrade() -> None:
    # revert the CHECK (map any circle_opening rows out first)
    old = ", ".join(
        f"'{k}'" for k in _KINDS if k != "circle_opening"
    )
    op.execute("UPDATE sol_notifications SET kind='cycle_started' WHERE kind='circle_opening'")
    op.execute("ALTER TABLE sol_notifications DROP CONSTRAINT IF EXISTS sol_notifications_kind_check")
    op.execute(
        f"ALTER TABLE sol_notifications ADD CONSTRAINT sol_notifications_kind_check "
        f"CHECK (kind IN ({old}))"
    )
    op.execute("DROP TABLE IF EXISTS sol_waitlist")
