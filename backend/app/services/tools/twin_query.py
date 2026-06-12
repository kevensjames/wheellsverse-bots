"""Twin query tool — lets KAI consult the operator self-model from inside a
chat turn (e.g. to answer 'what would the operator want here?'). READ-ONLY;
curating the profile / drafting / activating go through the audited endpoints.

Actions:
  profile — active operator-profile entries (optional section filter)
  drafts  — recent drafts KAI wrote in the operator's voice
  stats   — counts (active entries by section, drafts)
"""
from __future__ import annotations

from typing import Any

from app.services.tools.base import ToolContext, ToolError
from app.services.twin import storage


class TwinQueryTool:
    name = "twin_query"
    description = (
        "Consult KAI's model of the OPERATOR (the principal). READ-ONLY. Pick:\n"
        "  profile — the operator's active self-model entries (identity, voice, "
        "values, preferences, goals). Use to tailor a reply or reason about "
        "what the operator would want.\n"
        "  drafts  — recent text KAI drafted in the operator's voice.\n"
        "  stats   — counts of active profile entries + drafts."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["profile", "drafts", "stats"],
                "description": "Which query to run.",
            },
            "section": {
                "type": "string",
                "enum": ["identity", "voice", "values", "preferences", "goals"],
                "description": "profile only — optional section filter.",
            },
            "limit": {"type": "integer", "description": "Max rows. Default 50."},
        },
        "required": ["action"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        action = (kwargs.get("action") or "").strip().lower()
        limit = int(kwargs.get("limit") or 50)
        if action == "profile":
            rows = storage.list_entries(
                section=kwargs.get("section"), status="active", limit=limit
            )
            return {
                "action": "profile", "count": len(rows),
                "entries": [{"section": e.section, "text": e.text} for e in rows],
            }
        if action == "drafts":
            rows = storage.list_drafts(limit=limit)
            return {
                "action": "drafts", "count": len(rows),
                "drafts": [{"task": d.task, "content": d.content} for d in rows],
            }
        if action == "stats":
            return {"action": "stats", **storage.stats()}
        raise ToolError(f"unknown action {action!r}; use profile|drafts|stats")
