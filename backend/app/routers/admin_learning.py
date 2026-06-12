"""Continuous-learning admin endpoints — the operator's Learning tab.

Reads + feedback capture (admin-token only; low-risk):
  POST /admin/learning/feedback   record a 👍/👎 (+ note) on KAI's behavior
  GET  /admin/learning/feedback   recent feedback
  GET  /admin/learning/lessons    lessons (optional ?status=)
  GET  /admin/learning/stats      counts

Audited actions (KAI_SCOPE_LEARNING):
  POST /admin/learning/synthesize        feedback + failures + self-correction
                                         → PROPOSED lessons (LLM, v2); each
                                         tagged by source; destructive=False
                                         (proposing only)
  POST /admin/learning/lessons/{id}/activate   approve a lesson → it injects
                                         into KAI's prompt; destructive=True
  POST /admin/learning/lessons/{id}/dismiss    retire a lesson; destructive=True

Only 'activate' changes KAI's behavior, so it (and dismiss) require approved=true.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.admin import require_admin_token
from app.routers.admin_chat import OperatorNotConfigured, _resolve_operator_profile
from app.services.governance import PendingApproval, ScopeDenied, audited
from app.services.learning import storage, synthesize_lessons
from app.services.router import build_default_router

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/learning",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


# ─── reads + feedback capture ────────────────────────────────────────


class FeedbackRequest(BaseModel):
    rating: str                       # up / down
    target_type: str = "general"      # message / conversation / general
    target_id: str | None = None
    note: str = ""


@router.post("/feedback")
def learning_feedback(body: FeedbackRequest):
    try:
        fb = storage.record_feedback(
            rating=body.rating, target_type=body.target_type,
            target_id=body.target_id, note=body.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"feedback": fb.as_dict()}


@router.get("/feedback")
def learning_feedback_list(rating: str | None = None, limit: int = 50):
    rows = storage.list_feedback(rating=rating, limit=limit)
    return {"count": len(rows), "feedback": [r.as_dict() for r in rows]}


@router.get("/lessons")
def learning_lessons(status: str | None = None, limit: int = 100):
    rows = storage.list_lessons(status=status, limit=limit)
    return {"count": len(rows), "lessons": [r.as_dict() for r in rows]}


@router.get("/stats")
def learning_stats() -> dict[str, Any]:
    return storage.stats()


# ─── audited actions ─────────────────────────────────────────────────


class ApproveRequest(BaseModel):
    approved: bool = False


class SynthesizeRequest(BaseModel):
    max_lessons: int = 5
    prefer_local: bool = False
    include_failures: bool = True            # v2: also learn from tool/LLM errors
    include_self_correction: bool = True     # v2: also learn from critic-caught fixes
    approved: bool = False


@audited(scope="learning.synthesize", destructive=False)
def _audited_synthesize(
    *, max_lessons: int, prefer_local: bool, include_failures: bool,
    include_self_correction: bool, session: Session,
) -> dict[str, Any]:
    rt = build_default_router(session)
    prof = _resolve_operator_profile(session)
    return synthesize_lessons(
        router=rt, user_id=prof.id, max_lessons=max_lessons, prefer_local=prefer_local,
        include_failures=include_failures, include_self_correction=include_self_correction,
    )


@audited(scope="learning.activate", destructive=True)
def _audited_activate(*, lesson_id: int) -> dict[str, Any]:
    return {"lesson": storage.set_lesson_status(lesson_id, "active").as_dict()}


@audited(scope="learning.dismiss", destructive=True)
def _audited_dismiss(*, lesson_id: int) -> dict[str, Any]:
    return {"lesson": storage.set_lesson_status(lesson_id, "dismissed").as_dict()}


def _guard(fn, **kwargs):
    try:
        return fn(**kwargs)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except OperatorNotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/synthesize")
def learning_synthesize(body: SynthesizeRequest, session: Session = Depends(get_db)):
    return _guard(
        _audited_synthesize, max_lessons=body.max_lessons,
        prefer_local=body.prefer_local, include_failures=body.include_failures,
        include_self_correction=body.include_self_correction,
        session=session, approved=body.approved,
    )


@router.post("/lessons/{lesson_id}/activate")
def learning_activate(lesson_id: int, body: ApproveRequest):
    return _guard(_audited_activate, lesson_id=lesson_id, approved=body.approved)


@router.post("/lessons/{lesson_id}/dismiss")
def learning_dismiss(lesson_id: int, body: ApproveRequest):
    return _guard(_audited_dismiss, lesson_id=lesson_id, approved=body.approved)
