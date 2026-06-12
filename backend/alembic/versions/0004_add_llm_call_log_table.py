"""add llm_call_log table

Revision ID: 0004_add_llm_call_log_table
Revises: 0003_add_memories_table
Create Date: 2026-05-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004_add_llm_call_log_table"
down_revision: Union[str, None] = "0003_add_memories_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "llm_call_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("adapter", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cost_usd",
            sa.Numeric(10, 6),
            nullable=False,
            server_default="0",
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "success", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )
    op.create_index(
        "ix_llm_call_log_user_id_created_at",
        "llm_call_log",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_llm_call_log_adapter_created_at",
        "llm_call_log",
        ["adapter", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_llm_call_log_created_at",
        "llm_call_log",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_llm_call_log_created_at", table_name="llm_call_log")
    op.drop_index("ix_llm_call_log_adapter_created_at", table_name="llm_call_log")
    op.drop_index("ix_llm_call_log_user_id_created_at", table_name="llm_call_log")
    op.drop_table("llm_call_log")
