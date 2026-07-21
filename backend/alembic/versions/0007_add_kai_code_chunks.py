"""add kai_code_chunks table (code intelligence)

Revision ID: 0007_add_kai_code_chunks
Revises: 0006_add_kai_api_keys
Create Date: 2026-07-21

Native semantic code search on pgvector. Tenant isolation is enforced at the app
layer (WHERE user_id in every query); the RLS policy here is defense-in-depth for
any least-privilege / non-owner DB role (it becomes active under FORCE ROW LEVEL
SECURITY + a per-request ``SET app.user_id`` — a follow-up wiring step).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0007_add_kai_code_chunks"
down_revision: Union[str, None] = "0006_add_kai_api_keys"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    op.create_table(
        "kai_code_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("repo_id", sa.String(length=200), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("lang", sa.String(length=40), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=True),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_sha", sa.String(length=64), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.UniqueConstraint("user_id", "repo_id", "path", "content_sha",
                            name="uq_kai_code_chunks_ident"),
    )
    op.create_index("ix_kai_code_chunks_user_repo", "kai_code_chunks",
                    ["user_id", "repo_id"])
    op.execute(
        "CREATE INDEX ix_kai_code_chunks_embedding "
        "ON kai_code_chunks USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100);"
    )
    op.execute("ALTER TABLE kai_code_chunks ENABLE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY kai_code_chunks_tenant ON kai_code_chunks "
        "USING (user_id = current_setting('app.user_id', true)::uuid);"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS kai_code_chunks_tenant ON kai_code_chunks;")
    op.execute("ALTER TABLE kai_code_chunks DISABLE ROW LEVEL SECURITY;")
    op.drop_index("ix_kai_code_chunks_embedding", table_name="kai_code_chunks")
    op.drop_index("ix_kai_code_chunks_user_repo", table_name="kai_code_chunks")
    op.drop_table("kai_code_chunks")
