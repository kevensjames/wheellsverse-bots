"""stage 4: extend conversations + messages for NAI tool-loop bookkeeping

Revision ID: 0005_stage4_enhance_conv_msg
Revises: 0004_add_llm_call_log_table
Create Date: 2026-05-19

The conversations + messages tables already exist on Supabase with real
production data (29 + 98 rows from prior NarAI v1 work). Stage 4 only
adds columns — no destructive changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005_stage4_enhance_conv_msg"
down_revision: Union[str, None] = "0004_add_llm_call_log_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Conversations: add metadata jsonb
    op.execute(
        "ALTER TABLE conversations "
        "ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb"
    )

    # Messages: add tool-loop + audit columns
    op.execute(
        "ALTER TABLE messages "
        "ADD COLUMN IF NOT EXISTS tool_calls JSONB, "
        "ADD COLUMN IF NOT EXISTS tool_call_id VARCHAR(100), "
        "ADD COLUMN IF NOT EXISTS tool_name VARCHAR(100), "
        "ADD COLUMN IF NOT EXISTS adapter VARCHAR(50), "
        "ADD COLUMN IF NOT EXISTS cost_usd NUMERIC(10, 6), "
        "ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb"
    )

    # role CHECK constraint — existing rows ('user', 'assistant') satisfy it
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'ck_messages_role'
                  AND conrelid = 'public.messages'::regclass
            ) THEN
                ALTER TABLE messages
                    ADD CONSTRAINT ck_messages_role
                    CHECK (role IN ('user', 'assistant', 'system', 'tool'));
            END IF;
        END $$;
        """
    )

    # Chronological per-conversation index
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_messages_conv_created "
        "ON messages (conversation_id, created_at ASC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_messages_conv_created")
    op.execute(
        "ALTER TABLE messages DROP CONSTRAINT IF EXISTS ck_messages_role"
    )
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS metadata")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS cost_usd")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS adapter")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS tool_name")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS tool_call_id")
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS tool_calls")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS metadata")
