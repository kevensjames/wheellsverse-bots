"""infra.brain.tools.schema — JSON-schema bridge for LLM tool planning.

A :class:`Tool` may carry an optional JSON-schema dict on its ``schema``
field. :class:`ToolSchema` is the LLM-facing combined view (name +
description + input_schema) used by :class:`BrainClient`'s tool-calling
loop to advertise tools to the model and to render the tool catalog into
the system prompt.

Tools without a schema are *executable* but not *planner-visible* — the
LLM tool loop will not advertise them. This is intentional: lets us keep
internal/admin tools out of the planner's view by simply not adding a
schema.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .registry import Tool


@dataclass(frozen=True)
class ToolSchema:
    """LLM-facing description of a tool.

    Fields
    ------
    name:
        Stable identifier — must match :attr:`Tool.name` exactly so that the
        executor can look it up after the LLM emits a call.
    description:
        Short prose description shown to the planning LLM. Should describe
        *when* to use the tool, not how to call it (the schema covers that).
    input_schema:
        JSON Schema (Draft 7 / OpenAPI 3 compatible) describing the
        ``input`` dict the tool's ``run`` function expects. By convention
        the top-level type is ``"object"`` with ``properties`` + ``required``.
    """

    name: str
    description: str
    input_schema: dict

    @classmethod
    def from_tool(cls, tool: "Tool") -> Optional["ToolSchema"]:
        """Lift a :class:`Tool` into a :class:`ToolSchema`. Returns ``None``
        if the tool exposes no schema (i.e. is not planner-visible)."""
        if tool.schema is None:
            return None
        return cls(
            name=tool.name,
            description=tool.description,
            input_schema=tool.schema,
        )

    def to_dict(self) -> dict:
        """Serialize for transmission to model APIs that accept native
        tool schemas (e.g. Anthropic ``tools=[{name, description, input_schema}]``)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def to_prompt_block(self) -> str:
        """Render as a single Markdown bullet for the tool-use system prompt."""
        # Compact, deterministic rendering — keep the order stable so prompt
        # caches don't churn between requests.
        import json

        params = self.input_schema.get("properties", {}) or {}
        required = set(self.input_schema.get("required", []) or [])
        if params:
            param_lines: list[str] = []
            for key in sorted(params):
                spec = params[key] or {}
                kind = spec.get("type", "any")
                req_marker = "" if key in required else "?"
                desc = spec.get("description")
                line = f"  - {key}{req_marker}: {kind}"
                if desc:
                    line += f" — {desc}"
                param_lines.append(line)
            params_block = "\n".join(param_lines)
        else:
            params_block = "  (no parameters)"

        return (
            f"- **{self.name}** — {self.description}\n"
            f"{params_block}\n"
            f"  schema: {json.dumps(self.input_schema, sort_keys=True)}"
        )


__all__ = ["ToolSchema"]
