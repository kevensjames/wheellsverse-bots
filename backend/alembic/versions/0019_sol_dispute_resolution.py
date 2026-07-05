"""sol v1 — dispute resolution: waive + resolution audit [Stage 21]

A disputed payment used to have no terminal exit — the only way out was the payer
re-marking, so ONE unresolved dispute stranded its cycle (then the whole group) in
a non-terminal state forever. This adds a terminal 'waived' status (an organizer
write-off) plus a resolution audit (note / who / when) so a frozen cycle can close.

Additive + backward-compatible:
  1. widen the sol_payments status CHECK to allow 'waived' (DROP + re-ADD; no
     existing row can violate — the value is new).
  2. ADD three nullable columns to sol_payments: resolution_note, resolved_by,
     resolved_at (no table rewrite; existing rows get NULL).
  3. widen the sol_notifications kind CHECK to allow 'payment_resolved'.

NON-CUSTODIAL: 'waived' is a recorded forgiveness DECISION and the audit columns
store only text + a user id + a timestamp. No money, bank, or card field is added
and no funds move — Sol still only coordinates payments members make each other.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0019_sol_dispute_resolution"
down_revision: Union[str, None] = "0018_sol_waitlist"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# sol_payments statuses after adding 'waived' (Stage 21).
_STATUSES = ("pending", "marked", "confirmed", "disputed", "late", "waived")
# sol_notifications kinds after adding 'payment_resolved' (Stage 21).
_KINDS = (
    "payment_due", "payment_overdue", "payment_marked", "payment_confirmed",
    "payment_disputed", "cycle_started", "payout_incoming", "circle_opening",
    "payment_resolved",
)


def upgrade() -> None:
    # 1. widen the payment status CHECK to allow 'waived'
    statuses = ", ".join(f"'{s}'" for s in _STATUSES)
    op.execute("ALTER TABLE sol_payments DROP CONSTRAINT IF EXISTS sol_payments_status_check")
    op.execute(
        f"ALTER TABLE sol_payments ADD CONSTRAINT sol_payments_status_check "
        f"CHECK (status IN ({statuses}))"
    )
    # 2. resolution audit columns (all nullable; NULL for every existing row)
    op.execute("ALTER TABLE sol_payments ADD COLUMN IF NOT EXISTS resolution_note VARCHAR(500)")
    op.execute(
        "ALTER TABLE sol_payments ADD COLUMN IF NOT EXISTS resolved_by UUID "
        "REFERENCES profiles(id) ON DELETE SET NULL"
    )
    op.execute("ALTER TABLE sol_payments ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ")
    # 3. widen the notification kind CHECK to allow 'payment_resolved'
    kinds = ", ".join(f"'{k}'" for k in _KINDS)
    op.execute("ALTER TABLE sol_notifications DROP CONSTRAINT IF EXISTS sol_notifications_kind_check")
    op.execute(
        f"ALTER TABLE sol_notifications ADD CONSTRAINT sol_notifications_kind_check "
        f"CHECK (kind IN ({kinds}))"
    )


def downgrade() -> None:
    # NOTE: this is a schema-only reversion (Alembic convention). It maps any
    # 'waived' rows back to 'disputed'; it does NOT re-open cycles/groups that a
    # waive may have completed (application-derived state is not reconstructed on
    # downgrade). Downgrade is an emergency operation — re-examine affected cycles
    # if you run it after any payment was waived.
    # revert the notification kind CHECK (map any payment_resolved rows out first)
    old_kinds = ", ".join(f"'{k}'" for k in _KINDS if k != "payment_resolved")
    op.execute("UPDATE sol_notifications SET kind='payment_disputed' WHERE kind='payment_resolved'")
    op.execute("ALTER TABLE sol_notifications DROP CONSTRAINT IF EXISTS sol_notifications_kind_check")
    op.execute(
        f"ALTER TABLE sol_notifications ADD CONSTRAINT sol_notifications_kind_check "
        f"CHECK (kind IN ({old_kinds}))"
    )
    # drop the resolution audit columns
    op.execute("ALTER TABLE sol_payments DROP COLUMN IF EXISTS resolved_at")
    op.execute("ALTER TABLE sol_payments DROP COLUMN IF EXISTS resolved_by")
    op.execute("ALTER TABLE sol_payments DROP COLUMN IF EXISTS resolution_note")
    # revert the payment status CHECK (map any 'waived' rows back to 'disputed'
    # so the narrower constraint can be re-applied)
    old_statuses = ", ".join(f"'{s}'" for s in _STATUSES if s != "waived")
    op.execute("UPDATE sol_payments SET status='disputed' WHERE status='waived'")
    op.execute("ALTER TABLE sol_payments DROP CONSTRAINT IF EXISTS sol_payments_status_check")
    op.execute(
        f"ALTER TABLE sol_payments ADD CONSTRAINT sol_payments_status_check "
        f"CHECK (status IN ({old_statuses}))"
    )
