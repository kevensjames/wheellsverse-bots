"""KAI continuous learning (v2: feedback + failures + self-correction → lessons
→ operator-approved injection).

The closed loop the roadmap's learning system needs, scoped to one session:
capture signals about KAI's behavior, synthesize PROPOSED lessons from them,
and — once the operator APPROVES a lesson (→ active) — inject it into KAI's
system prompt so behavior actually improves. Gated by KAI_SCOPE_LEARNING;
activation is @audited (KAI changes its own guidance only with approval).

  storage    — feedback + lessons CRUD (SQLite sidecar)
  synthesis  — feedback + tool/LLM failures + self-correction events → proposed
               lessons via the LLM (v2: 3 signals, each tagged by source)
  injection  — active lessons → system-prompt preamble (loop closes here)
  tuning     — measure active-lesson effectiveness (before/after down-rate) →
               propose retirement; operator approves the dismiss (loop tightens)
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
from app.services.learning.tuning import evaluate_lessons  # noqa: F401

__all__ = [
    "LEARNING_DB_PATH",
    "LESSON_STATUSES",
    "RATINGS",
    "Feedback",
    "Lesson",
    "active_lessons_preamble",
    "add_lesson",
    "evaluate_lessons",
    "get_lesson",
    "list_feedback",
    "list_lessons",
    "record_feedback",
    "set_lesson_status",
    "stats",
    "synthesize_lessons",
]
