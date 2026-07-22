"""Persistence for autonomous SWE tasks (kai_swe_tasks).

Single source of truth for task state across the three SEPARATE operator
requests (create+plan / approve-plan+execute / approve-push). Two invariants:

  * Idempotent create — INSERT ... ON CONFLICT (task_id) DO NOTHING; a repeat
    of the same task_id returns the EXISTING row unchanged (opt-in: pass a
    stable task_id, else a random one disables idempotency).
  * Conditional transitions — every state change is
    `UPDATE ... WHERE status = :from RETURNING id`; zero rows updated means the
    task was not in the expected state (already advanced, terminal, or missing)
    and raises IllegalTransition, which the router surfaces as HTTP 409. This
    closes double-approve / approve-after-reject races with no lock table.

No background worker, lease, or sweeper — execution is synchronous-in-request.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# Kept in sync with app.models.swe_task.SWE_TASK_STATES and the CHECK constraint.
STATES: tuple[str, ...] = (
    "awaiting_plan_approval", "plan_approved", "executing",
    "awaiting_push_approval", "pushing", "pushed",
    "rejected", "failed", "expired",
)
TERMINAL: frozenset[str] = frozenset({"pushed", "rejected", "failed", "expired"})

# Columns that hold JSONB and therefore need an explicit cast on write.
_JSONB_COLS: frozenset[str] = frozenset({"plan", "policy", "artifacts"})


class IllegalTransition(Exception):
    """A conditional UPDATE matched zero rows — the task was not in the expected
    `from` state (already advanced, terminal, or nonexistent)."""


def get_task(db: Session, *, task_id: str) -> dict[str, Any] | None:
    row = db.execute(
        text("SELECT * FROM kai_swe_tasks WHERE task_id = :task_id"),
        {"task_id": task_id},
    ).mappings().first()
    return dict(row) if row is not None else None


def create_task(
    db: Session,
    *,
    task_id: str,
    goal: str,
    source_dir: str,
    image: str | None = None,
    policy: dict[str, Any] | None = None,
    plan: list[dict] | None = None,
) -> dict[str, Any]:
    """Insert a task idempotently. Lands in 'awaiting_plan_approval'. If task_id
    already exists, the existing row wins and is returned unchanged (the INSERT
    is a no-op). `plan` (LLM-only, no exec) may be attached at creation; Gate 1
    reviews it before any container runs."""
    db.execute(
        text(
            """
            INSERT INTO kai_swe_tasks (task_id, goal, source_dir, image, policy, plan, status)
            VALUES (:task_id, :goal, :source_dir, :image,
                    CAST(:policy AS JSONB), CAST(:plan AS JSONB), 'awaiting_plan_approval')
            ON CONFLICT (task_id) DO NOTHING
            """
        ),
        {
            "task_id": task_id,
            "goal": goal,
            "source_dir": source_dir,
            "image": image,
            "policy": json.dumps(policy or {}),
            "plan": json.dumps(plan) if plan is not None else None,
        },
    )
    db.commit()
    existing = get_task(db, task_id=task_id)
    if existing is None:  # pragma: no cover - defensive; the row must exist post-commit
        raise RuntimeError(f"kai_swe_tasks row for {task_id!r} vanished after insert")
    return existing


def transition(
    db: Session,
    *,
    task_id: str,
    from_status: str,
    to_status: str,
    touch: tuple[str, ...] = (),
    **fields: Any,
) -> dict[str, Any]:
    """Atomically move `task_id` from `from_status` to `to_status`, optionally
    setting extra columns (`fields`) and stamping columns in `touch` to NOW().
    Always bumps updated_at. Raises IllegalTransition if the row was not in
    `from_status` (zero rows updated)."""
    if to_status not in STATES:
        raise ValueError(f"unknown target status: {to_status!r}")

    sets = ["status = :to_status", "updated_at = NOW()"]
    params: dict[str, Any] = {
        "task_id": task_id, "from_status": from_status, "to_status": to_status,
    }
    for col in touch:
        sets.append(f"{col} = NOW()")
    for col, val in fields.items():
        if col in _JSONB_COLS:
            sets.append(f"{col} = CAST(:{col} AS JSONB)")
            params[col] = val if isinstance(val, str) else json.dumps(val)
        else:
            sets.append(f"{col} = :{col}")
            params[col] = val

    row = db.execute(
        text(
            f"UPDATE kai_swe_tasks SET {', '.join(sets)} "
            f"WHERE task_id = :task_id AND status = :from_status RETURNING id"
        ),
        params,
    ).first()
    if row is None:
        db.rollback()
        raise IllegalTransition(
            f"task {task_id!r} not in expected state {from_status!r}"
        )
    db.commit()
    result = get_task(db, task_id=task_id)
    assert result is not None  # updated row must exist
    return result
