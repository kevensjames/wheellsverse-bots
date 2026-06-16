"""Memory tool. `action=search` recalls memories; `action=save` adds one."""
from __future__ import annotations

from typing import Any

from app.services.memory.retrieval import search_memories
from app.services.memory.store import add_memory
from app.services.tools.base import ToolContext, ToolError

VALID_TYPES = ("fact", "event", "preference", "note")


class MemoryTool:
    name = "memory_tool"
    description = (
        "Read or write the user's persistent memory. "
        "Use 'search' to recall facts you may have stored from past conversations. "
        "Use 'save' when the user shares something worth remembering long-term "
        "(facts, preferences, important events). Do NOT save passing chitchat."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "save"],
                "description": "search = recall existing memories. save = store a new one.",
            },
            "query": {
                "type": "string",
                "description": "For action=search: the recall query. Ignored for save.",
            },
            "content": {
                "type": "string",
                "description": "For action=save: the fact/preference/event to remember. Ignored for search.",
            },
            "memory_type": {
                "type": "string",
                "enum": list(VALID_TYPES),
                "description": "For action=save: the kind of memory. Defaults to 'note'.",
            },
            "k": {
                "type": "integer",
                "description": "For action=search: max number of results. Defaults to 5, capped at 10.",
            },
        },
        "required": ["action"],
    }

    def execute(self, ctx: ToolContext, **kwargs) -> dict[str, Any]:
        action = kwargs.get("action")
        if action not in ("search", "save"):
            raise ToolError(f"action must be 'search' or 'save', got {action!r}")
        if action == "search":
            return self._search(ctx, kwargs)
        return self._save(ctx, kwargs)

    @staticmethod
    def _search(ctx: ToolContext, kwargs: dict) -> dict[str, Any]:
        query = (kwargs.get("query") or "").strip()
        if not query:
            raise ToolError("search requires non-empty 'query'")
        k = max(1, min(int(kwargs.get("k") or 5), 10))

        results = search_memories(ctx.session, user_id=ctx.user_id, query=query, k=k)
        return {
            "memories": [
                {
                    "content": r.content,
                    "type": r.memory_type,
                    "score": round(r.score, 3),
                }
                for r in results
            ],
            "count": len(results),
        }

    @staticmethod
    def _save(ctx: ToolContext, kwargs: dict) -> dict[str, Any]:
        content = (kwargs.get("content") or "").strip()
        if not content:
            raise ToolError("save requires non-empty 'content'")
        memory_type = kwargs.get("memory_type") or "note"
        if memory_type not in VALID_TYPES:
            raise ToolError(f"memory_type must be one of {VALID_TYPES}")

        memory = add_memory(
            ctx.session,
            user_id=ctx.user_id,
            content=content,
            memory_type=memory_type,
        )
        ctx.session.commit()
        return {
            "saved": True,
            "id": str(memory.id),
            "type": memory_type,
            "content": content,
        }
