"""add kai_api_keys table for /v1/chat/completions OpenAI-compatible endpoint

Revision ID: 0006_add_kai_api_keys
Revises: 0005_stage4_enhance_conv_msg
Create Date: 2026-06-04

Lets paid KAI users issue API keys from /account/api-keys and use KAI as
a drop-in OpenAI replacement (Authorization: Bearer kai_xxx).

Tier gating happens at request time against profiles.tier — no FK or
trigger here, just a runtime check. If a user downgrades to free, all
their keys 401 on next use without DB cleanup.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0006_add_kai_api_keys"
down_revision: Union[str, None] = "0005_stage4_enhance_conv_msg"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kai_api_keys (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            key_hash      TEXT NOT NULL UNIQUE,
            prefix        TEXT NOT NULL,
            label         TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_used_at  TIMESTAMPTZ,
            revoked_at    TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kai_api_keys_user_id ON kai_api_keys (user_id)"
    )
    # key_hash already UNIQUE via constraint, but a named index helps Postgres
    # use index-only scans for the lookup path.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_kai_api_keys_key_hash ON kai_api_keys (key_hash)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kai_api_keys")
