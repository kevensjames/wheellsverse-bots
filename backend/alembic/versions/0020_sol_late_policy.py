"""sol v1 — late policy: grace period + delinquency escalation [Stage 24]

Adds a configurable grace period (days after a contribution's due date before the
organizer is escalated about a delinquent member) to circles and their templates,
plus a 'member_delinquent' notification kind for that organizer alert.

Additive + backward-compatible:
  1. ADD COLUMN grace_period_days INT NOT NULL DEFAULT 0 to sol_groups and
     sol_circle_templates (every existing row gets 0 = escalate immediately) +
     a >= 0 CHECK on each.
  2. widen the sol_notifications kind CHECK to allow 'member_delinquent'.

NON-CUSTODIAL: grace_period_days governs WHEN a coordination alert fires; it moves
no money and touches no bank/card field. Delinquency is a recorded/derived signal.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0020_sol_late_policy"
down_revision: Union[str, None] = "0019_sol_dispute_resolution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KINDS = (
    "payment_due", "payment_overdue", "payment_marked", "payment_confirmed",
    "payment_disputed", "cycle_started", "payout_incoming", "circle_opening",
    "payment_resolved", "member_delinquent",
)


def upgrade() -> None:
    for table in ("sol_groups", "sol_circle_templates"):
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS grace_period_days "
            f"INTEGER NOT NULL DEFAULT 0"
        )
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_grace_check")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_grace_check "
            f"CHECK (grace_period_days >= 0)"
        )
    kinds = ", ".join(f"'{k}'" for k in _KINDS)
    op.execute("ALTER TABLE sol_notifications DROP CONSTRAINT IF EXISTS sol_notifications_kind_check")
    op.execute(
        f"ALTER TABLE sol_notifications ADD CONSTRAINT sol_notifications_kind_check "
        f"CHECK (kind IN ({kinds}))"
    )


def downgrade() -> None:
    old_kinds = ", ".join(f"'{k}'" for k in _KINDS if k != "member_delinquent")
    op.execute("UPDATE sol_notifications SET kind='payment_overdue' WHERE kind='member_delinquent'")
    op.execute("ALTER TABLE sol_notifications DROP CONSTRAINT IF EXISTS sol_notifications_kind_check")
    op.execute(
        f"ALTER TABLE sol_notifications ADD CONSTRAINT sol_notifications_kind_check "
        f"CHECK (kind IN ({old_kinds}))"
    )
    for table in ("sol_groups", "sol_circle_templates"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {table}_grace_check")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS grace_period_days")
