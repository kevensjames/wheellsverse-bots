"""Learning query tool — lets KAI report what it has learned from feedback,
from inside a chat turn. READ-ONLY (recording feedback / activating lessons go
through the operator's audited endpoints).

Actions:
  lessons  — list lessons (optional status: proposed/active/dismissed)
  feedback — recent thumbs up/down + notes
  stats    — counts (feedback by rating, lessons by status, active lessons)
  review   — auto-tuning: which active lessons appear to be helping vs which
             should be reviewed for retirement (correlational)
"""
from __future__ import annotations

from typing import Any

from app.services.learning import evaluate_lessons, storage
from app.services.tools.base import ToolContext, ToolError


class LearningQueryTool:
    name = "learning_query"
    description = (
        "Query what KAI has learned from user feedback. READ-ONLY. Pick one:\n"
        "  lessons  — list lessons KAI has distilled (filter by status: "
        "active = currently applied, proposed = awaiting operator approval, "
        "dismissed).\n"
        "  feedback — recent thumbs up/down the operator gave, with notes.\n"
        "  stats    — counts: feedback by rating, lessons by status.\n"
        "  review   — effectiveness check: which active lessons seem to help "
        "vs should be reviewed for retirement (correlational, not causal)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["lessons", "feedback", "stats", "review"],
                "description": "Which query to run.",
            },
            "status": {
                "type": "string",
                "enum": ["proposed", "active", "dismissed"],
                "description": "lessons only — optional status filter.",
            },
            "rating": {
                "type": "string",
                "enum": ["up", "down"],
                "description": "feedback only — optional rating filter.",
            },
            "limit": {"type": "integer", "description": "Max rows. Default 25."},
        },
        "required": ["action"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        action = (kwargs.get("action") or "").strip().lower()
        limit = int(kwargs.get("limit") or 25)
        if action == "lessons":
            rows = storage.list_lessons(status=kwargs.get("status"), limit=limit)
            return {
                "action": "lessons", "count": len(rows),
                "lessons": [
                    {"id": r.id, "text": r.text, "status": r.status, "source": r.source}
                    for r in rows
                ],
            }
        if action == "feedback":
            rows = storage.list_feedback(rating=kwargs.get("rating"), limit=limit)
            return {
                "action": "feedback", "count": len(rows),
                "feedback": [
                    {"rating": r.rating, "note": r.note, "target_type": r.target_type}
                    for r in rows
                ],
            }
        if action == "stats":
            return {"action": "stats", **storage.stats()}
        if action == "review":
            return {"action": "review", **evaluate_lessons()}
        raise ToolError(f"unknown action {action!r}; use lessons|feedback|stats|review")
