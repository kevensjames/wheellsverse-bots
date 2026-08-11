"""ORM for kai_swe_tasks — persistence for the autonomous SWE agent.

Source of truth for the TEST schema: the harness builds tables via
Base.metadata.create_all (conftest engine fixture), not alembic. Keep the
columns + CHECK here in sync with alembic 0007_add_kai_swe_tasks.py (prod path).

One row per SWE task; state advances across three separate operator requests
(create+plan / approve-plan+execute / approve-push) via CONDITIONAL updates in
app.services.swe_runtime.task_store. Single-operator model — no user_id / RLS.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (Boolean, CheckConstraint, DateTime, Index, Integer,
                        Numeric, String, Text, func, text)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# The 9 reconciled states. Mirrored by ck_kai_swe_tasks_status (below + the
# migration) and by task_store.STATES — change all three together.
SWE_TASK_STATES: tuple[str, ...] = (
    "awaiting_plan_approval", "plan_approved", "executing",
    "awaiting_push_approval", "pushing", "pushed",
    "rejected", "failed", "expired",
)


class SweTaskRecord(Base):
    __tablename__ = "kai_swe_tasks"

    # server_default (not just the ORM-side default=) so raw-SQL inserts in
    # task_store get a DB-generated id — matches the migration's
    # `DEFAULT gen_random_uuid()` (needs the pgcrypto extension).
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True,
        server_default=text("gen_random_uuid()"), default=uuid.uuid4,
    )
    # Operator/brain handle AND the idempotency key (UNIQUE → ON CONFLICT).
    task_id: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    source_dir: Mapped[str] = mapped_column(Text, nullable=False)
    image: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Serialized SandboxPolicy.
    policy: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="awaiting_plan_approval"
    )
    # Brain's proposed steps (Gate 1 review payload).
    plan: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Produced unified diff (Gate 2 review payload).
    patch: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Binds a Gate-2 approval to the exact patch (blocks a post-approval swap).
    patch_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Server-computed kai/swe/<task_id>; a client can never supply it.
    review_branch: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    push_approved_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    push_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(10, 4), nullable=False, server_default="0"
    )
    # Last SandboxResult snapshot (full per-step trail lives in plan/artifacts).
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    timed_out: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    artifacts: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_plan_approval', 'plan_approved', 'executing', "
            "'awaiting_push_approval', 'pushing', 'pushed', "
            "'rejected', 'failed', 'expired')",
            name="ck_kai_swe_tasks_status",
        ),
        Index("ix_kai_swe_tasks_status", "status"),
    )

    def __repr__(self) -> str:
        return f"<SweTaskRecord task_id={self.task_id!r} status={self.status!r}>"
