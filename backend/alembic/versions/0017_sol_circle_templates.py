"""sol v1 — circle templates + instance/round links [Stage 17]

Revision ID: 0017_sol_circle_templates
Revises: 0016_sol_notifications
Create Date: 2026-07-04

Adds the template/instance/round layer ADDITIVELY — the working SolGroup model is
untouched in behavior:
  - sol_circle_templates: a reusable blueprint (amount/frequency/size/rules). A
    template SPAWNS instances.
  - sol_groups gains three NULLABLE/defaulted columns so existing groups are
    unaffected:
      template_id       -> the template this group is an instance of (NULL = a
                           standalone group, i.e. the pre-Stage-17 behavior)
      round_number      -> which round within the same cohort (default 1)
      previous_group_id -> the prior round's group (round chaining; NULL for round 1)

NON-CUSTODIAL: blueprints + links only; no money, no bank data. Additive.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0017_sol_circle_templates"
down_revision: Union[str, None] = "0016_sol_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FREQ = ("weekly", "biweekly", "monthly")
_VIS = ("public", "private", "invite_only")


def upgrade() -> None:
    freq = ", ".join(f"'{v}'" for v in _FREQ)
    vis = ", ".join(f"'{v}'" for v in _VIS)
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS sol_circle_templates (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            creator_id          UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            name                TEXT NOT NULL,
            contribution_amount NUMERIC(12, 2) NOT NULL,
            frequency           TEXT NOT NULL,
            member_limit        INTEGER NOT NULL,
            visibility          TEXT NOT NULL DEFAULT 'invite_only',
            active              BOOLEAN NOT NULL DEFAULT true,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT sol_circle_templates_frequency_check CHECK (frequency IN ({freq})),
            CONSTRAINT sol_circle_templates_visibility_check CHECK (visibility IN ({vis})),
            CONSTRAINT sol_circle_templates_member_limit_check CHECK (member_limit >= 2)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS sol_circle_templates_creator_idx "
        "ON sol_circle_templates (creator_id)"
    )
    # Additive links on sol_groups — all nullable/defaulted (existing rows keep
    # template_id=NULL, round_number=1, previous_group_id=NULL).
    op.execute(
        "ALTER TABLE sol_groups ADD COLUMN IF NOT EXISTS template_id UUID "
        "REFERENCES sol_circle_templates(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE sol_groups ADD COLUMN IF NOT EXISTS round_number INTEGER NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE sol_groups ADD COLUMN IF NOT EXISTS previous_group_id UUID "
        "REFERENCES sol_groups(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS sol_groups_template_idx ON sol_groups (template_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS sol_groups_template_idx")
    op.execute("ALTER TABLE sol_groups DROP COLUMN IF EXISTS previous_group_id")
    op.execute("ALTER TABLE sol_groups DROP COLUMN IF EXISTS round_number")
    op.execute("ALTER TABLE sol_groups DROP COLUMN IF EXISTS template_id")
    op.execute("DROP TABLE IF EXISTS sol_circle_templates")
