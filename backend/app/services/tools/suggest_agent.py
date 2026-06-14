"""suggest_agent — the super-router as a tool: recommend the best domain expert
agent (preset) for a question. Returns the preset id + confidence + reason
(preset_id is null for ordinary general chat). KAI can call it to route a
request to the right specialist; a client/dashboard can call it to auto-select
the preset. Builds its own router from the session, like verify_claim.
"""
from __future__ import annotations

from typing import Any

from app.services.tools.base import ToolContext, ToolError


class SuggestAgentTool:
    name = "suggest_agent"
    description = (
        "Recommend the best expert agent (preset) to handle a question — e.g. "
        "medical_research, legal_research, engineering, accounting, finance, "
        "research, swe, marketing. Returns {preset_id, confidence, reason}; "
        "preset_id is null when no specialist clearly fits (general chat). Use "
        "to route a request to the right specialist."
    )
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The user's question/request to route.",
            },
        },
        "required": ["question"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        question = (kwargs.get("question") or "").strip()
        if not question:
            raise ToolError("question is required")
        if getattr(ctx, "session", None) is None or getattr(ctx, "user_id", None) is None:
            raise ToolError("suggest_agent needs an authenticated user session")
        try:
            from app.services import agent_router
            from app.services.router import build_default_router
            rt = build_default_router(ctx.session)
            out = agent_router.classify_domain(router=rt, user_id=ctx.user_id, question=question)
        except Exception as e:
            raise ToolError(f"routing failed: {e}")
        return {
            "preset_id": out["preset_id"],
            "confidence": out["confidence"],
            "reason": out.get("reason", ""),
        }
