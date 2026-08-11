"""add kai_swe_tasks table for the autonomous SWE agent (persistence layer)

Revision ID: 0008_add_kai_swe_tasks
Revises: 0007_add_kai_code_chunks
Create Date: 2026-07-21

Backs the operator-approved autonomous SWE loop: one row per task, carrying
state across the three separate operator requests (create+plan /
approve-plan+execute / approve-push). Single-operator model — deliberately NO
user_id / RLS (the SWE admin surface is one shared-token operator on a non-prod
runner; a per-tenant credential store is a documented follow-up, not this MVP).

NOTE: if the sibling fix/kai-code-intelligence branch (which also introduces a
0007) merges first, renumber this to 0008 and rechain down_revision AT MERGE
TIME — do not guess now. The CHECK + columns here MUST stay in sync with
app/models/swe_task.py, which is the source of truth for the TEST schema
(conftest builds tables via Base.metadata.create_all, not alembic).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0008_add_kai_swe_tasks"
down_revision: Union[str, None] = "0007_add_kai_code_chunks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS kai_swe_tasks (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            task_id           VARCHAR(200) NOT NULL UNIQUE,
            goal              TEXT NOT NULL,
            source_dir        TEXT NOT NULL,
            image             TEXT,
            policy            JSONB NOT NULL DEFAULT '{}'::jsonb,
            status            VARCHAR(24) NOT NULL DEFAULT 'awaiting_plan_approval',
            plan              JSONB,
            patch             TEXT,
            patch_sha256      VARCHAR(64),
            review_branch     TEXT,
            plan_approved_by  TEXT,
            plan_approved_at  TIMESTAMPTZ,
            push_approved_by  TEXT,
            push_approved_at  TIMESTAMPTZ,
            attempts          INTEGER NOT NULL DEFAULT 0,
            tokens_used       INTEGER NOT NULL DEFAULT 0,
            cost_usd          NUMERIC(10,4) NOT NULL DEFAULT 0,
            exit_code         INTEGER,
            stdout            TEXT,
            stderr            TEXT,
            timed_out         BOOLEAN NOT NULL DEFAULT FALSE,
            artifacts         JSONB NOT NULL DEFAULT '{}'::jsonb,
            error             TEXT,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_kai_swe_tasks_status CHECK (status IN (
                'awaiting_plan_approval', 'plan_approved', 'executing',
                'awaiting_push_approval', 'pushing', 'pushed',
                'rejected', 'failed', 'expired'
            ))
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_kai_swe_tasks_status ON kai_swe_tasks (status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS kai_swe_tasks")
