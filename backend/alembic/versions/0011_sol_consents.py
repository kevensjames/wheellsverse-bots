"""sol v1 — sol_consents (Stage 7 legal disclosure surface)

Revision ID: 0011_sol_consents
Revises: 0010_sol_payment_disputed_at
Create Date: 2026-07-03

Records a member's acceptance of a versioned disclosure (the non-custodial terms
+ risk disclosure). One row per (user, document, version). The create/join gate
reads this to require acceptance before a member can coordinate money.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0011_sol_consents"
down_revision: Union[str, None] = "0010_sol_payment_disputed_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS sol_consents (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            document_key  TEXT NOT NULL,
            version       TEXT NOT NULL,
            accepted_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT sol_consents_user_doc_version_uq UNIQUE (user_id, document_key, version)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_sol_consents_user_id ON sol_consents (user_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sol_consents")
