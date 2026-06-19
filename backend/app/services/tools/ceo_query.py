from __future__ import annotations
from typing import Any
from app.services.tools.base import ToolContext, ToolError
from app.services.ceo import store


class CeoQueryTool:
    name = "ceo_query"
    description = (
        "Read KAI's own CEO state (READ-ONLY). action='board' → the company "
        "goal, latest KPI snapshot, and recent executive decisions. "
        "action='decisions' → recent decisions only. The operator runs the "
        "company from the CEO dashboard tab; this tool only reports."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["board", "decisions"]},
            "limit": {"type": "integer", "description": "decisions only — max rows (default 20)"},
        },
        "required": ["action"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        action = (kwargs.get("action") or "").strip().lower()
        if action == "board":
            return {"company": store.get_company(), "snapshot": store.latest_snapshot(),
                    "decisions": store.list_decisions(limit=10)}
        if action == "decisions":
            return {"decisions": store.list_decisions(limit=int(kwargs.get("limit") or 20))}
        raise ToolError("action must be 'board' or 'decisions'")
