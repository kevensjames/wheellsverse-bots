"""KAI continuous learning (v1: feedback → lessons → operator-approved injection).

The closed loop the roadmap's learning system needs, scoped to one session:
capture explicit feedback (👍/👎 + notes), synthesize PROPOSED lessons from it,
and — once the operator APPROVES a lesson (→ active) — inject it into KAI's
system prompt so behavior actually improves. Gated by KAI_SCOPE_LEARNING;
activation is @audited (KAI changes its own guidance only with approval).

  storage    — feedback + lessons CRUD (SQLite sidecar)
  synthesis  — feedback → proposed lessons via the LLM
  injection  — active lessons → system-prompt preamble (loop closes here)
"""
from app.services.learning.storage import (  # noqa: F401
    LEARNING_DB_PATH,
    LESSON_STATUSES,
    RATINGS,
    Feedback,
    Lesson,
    add_lesson,
    get_lesson,
    list_feedback,
    list_lessons,
    record_feedback,
    set_lesson_status,
    stats,
)
from app.services.learning.synthesis import synthesize_lessons  # noqa: F401
from app.services.learning.injection import active_lessons_preamble  # noqa: F401

__all__ = [
    "LEARNING_DB_PATH",
    "LESSON_STATUSES",
    "RATINGS",
    "Feedback",
    "Lesson",
    "active_lessons_preamble",
    "add_lesson",
    "get_lesson",
    "list_feedback",
    "list_lessons",
    "record_feedback",
    "set_lesson_status",
    "stats",
    "synthesize_lessons",
]
