"""infra.brain.agents.messages — typed messages for the agent runtime.

:class:`AgentMessage` is a small, mutable dataclass (per spec) that
formalises the four roles inside the runtime:

    "system"   — instructions the brain assembles for itself
    "planner"  — the JSON plan the planner produced
    "executor" — narration emitted by the executor between steps
    "tool"     — output (or error) from one tool invocation

Helper constructors keep the metadata shape stable so consumers (logs,
dashboards, replay tools) can rely on field names without a constants file.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AgentMessage:
    """One message in an agent transcript."""

    role: str
    content: str
    metadata: dict = field(default_factory=dict)


# ── Helpers ──────────────────────────────────────────────────────────────────


def format_plan_message(plan: dict) -> AgentMessage:
    """Wrap a planner-produced plan as an :class:`AgentMessage`.

    Metadata always carries ``step_count`` so a downstream reader can render
    a summary without parsing the body.
    """
    if not isinstance(plan, dict):
        raise TypeError("plan must be a dict")
    steps = plan.get("steps", [])
    return AgentMessage(
        role="planner",
        content=json.dumps(plan, indent=2, default=str, sort_keys=True),
        metadata={
            "step_count": len(steps) if isinstance(steps, list) else 0,
        },
    )


def format_tool_message(
    tool_name: str,
    result: Any = None,
    error: Optional[str] = None,
) -> AgentMessage:
    """Wrap a tool's outcome as an :class:`AgentMessage`.

    Truncates long bodies to 4000 chars to protect transcripts from
    runaway output. The full payload remains available in the executor's
    ``task.result["steps"]`` record.
    """
    ok = error is None
    if not ok:
        return AgentMessage(
            role="tool",
            content=str(error),
            metadata={"tool": tool_name, "ok": False},
        )
    try:
        body = json.dumps(result, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        body = repr(result)
    if len(body) > 4000:
        body = body[:4000] + " …[truncated]"
    return AgentMessage(
        role="tool",
        content=body,
        metadata={"tool": tool_name, "ok": True},
    )


__all__ = [
    "AgentMessage",
    "format_plan_message",
    "format_tool_message",
]
