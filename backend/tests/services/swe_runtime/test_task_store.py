"""kai_swe_tasks persistence — idempotent create, atomic conditional transitions,
CHECK-guarded status. Uses the shared db_session fixture (create_all schema)."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.services.swe_runtime import task_store
from app.services.swe_runtime.task_store import IllegalTransition


def _create(db, task_id="t1"):
    return task_store.create_task(
        db, task_id=task_id, goal="fix the bug", source_dir="/repo",
        image="python:3.11-slim", policy={"image": "python:3.11-slim"},
        plan=[{"n": 1, "command": "pytest", "rationale": "repro"}],
    )


def test_create_lands_awaiting_plan_approval(db_session):
    row = _create(db_session)
    assert row["status"] == "awaiting_plan_approval"
    assert row["task_id"] == "t1"
    assert row["goal"] == "fix the bug"
    assert row["plan"] == [{"n": 1, "command": "pytest", "rationale": "repro"}]
    assert row["attempts"] == 0


def test_create_is_idempotent_on_task_id(db_session):
    first = _create(db_session)
    # Re-create with the SAME task_id but different content — must be a no-op
    # that returns the ORIGINAL row (not a duplicate, not an overwrite).
    again = task_store.create_task(
        db_session, task_id="t1", goal="DIFFERENT", source_dir="/other",
        policy={}, plan=None,
    )
    assert again["id"] == first["id"]
    assert again["goal"] == "fix the bug"       # unchanged
    count = db_session.execute(
        text("SELECT COUNT(*) FROM kai_swe_tasks WHERE task_id = 't1'")
    ).scalar()
    assert count == 1


def test_transition_happy_path(db_session):
    _create(db_session)
    row = task_store.transition(
        db_session, task_id="t1",
        from_status="awaiting_plan_approval", to_status="plan_approved",
        touch=("plan_approved_at",), plan_approved_by="operator@kai",
    )
    assert row["status"] == "plan_approved"
    assert row["plan_approved_by"] == "operator@kai"
    assert row["plan_approved_at"] is not None


def test_illegal_transition_raises_and_leaves_row_unchanged(db_session):
    _create(db_session)
    # The task is in awaiting_plan_approval, NOT awaiting_push_approval, so a
    # push transition must be refused (zero rows) and the row left untouched.
    with pytest.raises(IllegalTransition):
        task_store.transition(
            db_session, task_id="t1",
            from_status="awaiting_push_approval", to_status="pushing",
        )
    assert task_store.get_task(db_session, task_id="t1")["status"] == "awaiting_plan_approval"


def test_double_approve_is_blocked(db_session):
    _create(db_session)
    task_store.transition(
        db_session, task_id="t1",
        from_status="awaiting_plan_approval", to_status="plan_approved",
    )
    # A second approval from the original state must fail — the row already moved.
    with pytest.raises(IllegalTransition):
        task_store.transition(
            db_session, task_id="t1",
            from_status="awaiting_plan_approval", to_status="plan_approved",
        )


def test_transition_sets_jsonb_and_text_fields(db_session):
    _create(db_session)
    task_store.transition(
        db_session, task_id="t1",
        from_status="awaiting_plan_approval", to_status="plan_approved",
    )
    row = task_store.transition(
        db_session, task_id="t1",
        from_status="plan_approved", to_status="awaiting_push_approval",
        patch="--- a\n+++ b\n", patch_sha256="deadbeef",
        artifacts={"lib.py": "def add(): ..."},
    )
    assert row["patch"].startswith("--- a")
    assert row["patch_sha256"] == "deadbeef"
    assert row["artifacts"] == {"lib.py": "def add(): ..."}


def test_check_constraint_rejects_unknown_status(db_session):
    _create(db_session)
    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE kai_swe_tasks SET status = 'bogus' WHERE task_id = 't1'")
        )
        db_session.commit()
    db_session.rollback()


def test_unknown_target_status_rejected_before_db(db_session):
    _create(db_session)
    with pytest.raises(ValueError):
        task_store.transition(
            db_session, task_id="t1",
            from_status="awaiting_plan_approval", to_status="not_a_state",
        )
