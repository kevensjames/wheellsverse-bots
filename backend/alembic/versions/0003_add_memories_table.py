"""add memories table

Revision ID: 0003_add_memories_table
Revises: 0002_stripe_customer_id
Create Date: 2026-05-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from pgvector.sqlalchemy import Vector


revision: str = "0003_add_memories_table"
down_revision: Union[str, None] = "0002_stripe_customer_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    op.create_table(
        "memories",
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
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "memory_type",
            sa.String(length=20),
            nullable=False,
            server_default="note",
        ),
        sa.Column("embedding", Vector(1536), nullable=False),
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
        sa.Column(
            "last_used_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.CheckConstraint(
            "memory_type IN ('fact', 'event', 'preference', 'note')",
            name="ck_memories_memory_type",
        ),
    )

    op.create_index(
        "ix_memories_user_id_created_at",
        "memories",
        ["user_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_memories_memory_type",
        "memories",
        ["memory_type"],
    )
    op.execute(
        "CREATE INDEX ix_memories_embedding "
        "ON memories USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100);"
    )


def downgrade() -> None:
    op.drop_index("ix_memories_embedding", table_name="memories")
    op.drop_index("ix_memories_memory_type", table_name="memories")
    op.drop_index("ix_memories_user_id_created_at", table_name="memories")
    op.drop_table("memories")
