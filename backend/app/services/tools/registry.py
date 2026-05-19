"""Tool registry. Knows every tool, exposes provider-specific schemas, executes."""
from __future__ import annotations

import logging
from typing import Any

from app.services.tools.base import Tool, ToolContext, ToolError, ToolResult

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"unknown tool {name!r}")
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    # --- Schema export ---

    def openai_schema(self) -> list[dict[str, Any]]:
        """OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def anthropic_schema(self) -> list[dict[str, Any]]:
        """Anthropic tool-use format."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in self._tools.values()
        ]

    # --- Execution ---

    def execute(
        self, name: str, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        try:
            tool = self.get(name)
        except KeyError as e:
            return ToolResult(
                call_id="", name=name, output={"error": str(e)}, is_error=True
            )

        try:
            output = tool.execute(ctx, **arguments)
            return ToolResult(call_id="", name=name, output=output, is_error=False)
        except ToolError as e:
            logger.warning("tool %s user error: %s", name, e)
            return ToolResult(
                call_id="", name=name, output={"error": str(e)}, is_error=True
            )
        except Exception as e:
            logger.exception("tool %s internal failure", name)
            return ToolResult(
                call_id="",
                name=name,
                output={"error": f"internal failure: {type(e).__name__}"},
                is_error=True,
            )
