"""sol v1 — non-custodial ROSCA coordinator data model (Stage 1)

Revision ID: 0007_sol_v1_data_model
Revises: 0006_add_kai_api_keys
Create Date: 2026-07-02

Creates the sol_* tables. Sol never holds member money — these tables only
record and coordinate member-to-member payments made outside the app. All
user_id/organizer_id/payer_id/payee_id columns FK to profiles(id) (the
canonical Supabase user table). Namespaced sol_* for minimal blast radius.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0007_sol_v1_data_model"
down_revision: Union[str, None] = "0006_add_kai_api_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sol_groups (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            organizer_id         UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            name                 TEXT NOT NULL,
            contribution_amount  NUMERIC(12,2) NOT NULL,
            frequency            TEXT NOT NULL CHECK (frequency IN ('weekly','biweekly','monthly')),
            member_limit         INTEGER NOT NULL CHECK (member_limit >= 2),
            status               TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','locked','complete')),
            invite_code          TEXT NOT NULL UNIQUE,
            locked_at            TIMESTAMPTZ,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_sol_groups_organizer_id ON sol_groups (organizer_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sol_memberships (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id          UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            group_id         UUID NOT NULL REFERENCES sol_groups(id) ON DELETE CASCADE,
            payout_position  INTEGER,
            role             TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('organizer','member')),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT sol_memberships_user_group_uq UNIQUE (user_id, group_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_sol_memberships_group_id ON sol_memberships (group_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sol_memberships_user_id ON sol_memberships (user_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sol_cycles (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            group_id                 UUID NOT NULL REFERENCES sol_groups(id) ON DELETE CASCADE,
            cycle_number             INTEGER NOT NULL,
            recipient_membership_id  UUID REFERENCES sol_memberships(id) ON DELETE SET NULL,
            due_date                 DATE NOT NULL,
            status                   TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','complete')),
            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT sol_cycles_group_number_uq UNIQUE (group_id, cycle_number)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_sol_cycles_group_id ON sol_cycles (group_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sol_payments (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            cycle_id            UUID NOT NULL REFERENCES sol_cycles(id) ON DELETE CASCADE,
            payer_id            UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            payee_id            UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            amount              NUMERIC(12,2) NOT NULL,
            method              TEXT NOT NULL CHECK (method IN ('zelle','cashapp','venmo','cash','other')),
            payer_marked_at     TIMESTAMPTZ,
            payee_confirmed_at  TIMESTAMPTZ,
            status              TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','marked','confirmed','disputed','late')),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT sol_payments_distinct_parties_check CHECK (payer_id <> payee_id)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_sol_payments_cycle_id ON sol_payments (cycle_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sol_payments_payer_id ON sol_payments (payer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_sol_payments_payee_id ON sol_payments (payee_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sol_payment_profiles (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            method      TEXT NOT NULL CHECK (method IN ('zelle','cashapp','venmo','applepay','cash')),
            handle      TEXT NOT NULL,
            is_default  BOOLEAN NOT NULL DEFAULT FALSE,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT sol_payment_profiles_user_method_uq UNIQUE (user_id, method)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sol_payment_profiles_user_id ON sol_payment_profiles (user_id)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sol_payment_proofs (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            payment_id   UUID NOT NULL REFERENCES sol_payments(id) ON DELETE CASCADE,
            image_url    TEXT NOT NULL,
            uploaded_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_sol_payment_proofs_payment_id ON sol_payment_proofs (payment_id)"
    )


def downgrade() -> None:
    # Drop in reverse-dependency order.
    op.execute("DROP TABLE IF EXISTS sol_payment_proofs")
    op.execute("DROP TABLE IF EXISTS sol_payment_profiles")
    op.execute("DROP TABLE IF EXISTS sol_payments")
    op.execute("DROP TABLE IF EXISTS sol_cycles")
    op.execute("DROP TABLE IF EXISTS sol_memberships")
    op.execute("DROP TABLE IF EXISTS sol_groups")
