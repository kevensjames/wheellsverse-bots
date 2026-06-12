"""failure_lookup tool — lets KAI explicitly check for similar past
failures before attempting a risky action.

Auto-injected past failures already land in the system prompt for every
chat turn via memory_injection. This tool is for when KAI wants to LOOK
DEEPER — e.g. before running a deploy, before calling a tool that has
broken before, before promising the user an outcome.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.failure_memory import find_recent_similar, list_recent
from app.services.tools.base import ToolContext, ToolError

logger = logging.getLogger(__name__)


class FailureLookupTool:
    name = "failure_lookup"
    description = (
        "Check KAI's failure log for past actions that broke. Use BEFORE "
        "attempting an action that you think might fail (deploys, "
        "configuration changes, tool calls with side effects). Two modes:\n"
        "  similar — find failures whose prompt overlaps with your query\n"
        "             (use when you have a description of the action)\n"
        "  recent  — list the most recent failures regardless of similarity\n"
        "             (use when surveying what's been going wrong lately)"
    )
    parameters = {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "enum": ["similar", "recent"],
                "description": "similar (Jaccard match) or recent (newest first).",
            },
            "query": {
                "type": "string",
                "description": (
                    "similar: prompt to match against. recent: ignored."
                ),
            },
            "tool_name": {
                "type": "string",
                "description": (
                    "recent only — filter to failures from this specific tool."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max rows to return. Default 5.",
            },
        },
        "required": ["mode"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        mode = (kwargs.get("mode") or "").strip().lower()
        limit = int(kwargs.get("limit") or 5)
        if mode not in ("similar", "recent"):
            raise ToolError(f"mode must be 'similar' or 'recent', got {mode!r}")

        if mode == "similar":
            query = (kwargs.get("query") or "").strip()
            if not query:
                raise ToolError("mode=similar requires a non-empty query")
            failures = find_recent_similar(query, k=limit)
        else:
            failures = list_recent(
                limit=limit,
                tool_name=kwargs.get("tool_name") or None,
            )

        return {
            "mode": mode,
            "count": len(failures),
            "failures": [
                {
                    "when": f.ts[:19],
                    "prompt": f.prompt,
                    "category": f.category,
                    "tool": f.tool_name,
                    "detail": f.detail,
                    "score": round(f.similarity_score, 3) if mode == "similar" else None,
                }
                for f in failures
            ],
        }
