"""Shared tool types. Canonical (OpenAI-style) format used internally."""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.orm import Session


@dataclass(slots=True)
class ToolContext:
    """Passed to every tool's execute(). Extend as new context emerges."""
    user_id: uuid.UUID
    session: Session
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    # Per-request authorization for side-effecting (writes=True) tools. Default
    # deny: the LLM tool loop cannot make external changes (SaaS writes, CRM
    # creates, paid generation, MCP fs/git) unless the OPERATOR set this True for
    # the request. User-facing chat never sets it, so users can't trigger writes
    # on the operator's shared third-party accounts. See ToolRegistry.execute.
    allow_writes: bool = False


@dataclass(slots=True)
class ToolCall:
    """LLM's request to invoke a tool. Canonical (OpenAI-style) format."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ToolResult:
    """Result of executing a tool. JSON-serializable."""
    call_id: str
    name: str
    output: dict[str, Any] | str
    is_error: bool = False

    def as_content(self) -> str:
        if isinstance(self.output, str):
            return self.output
        return json.dumps(self.output, default=str)


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the function's args

    def execute(self, ctx: ToolContext, **kwargs) -> dict[str, Any]: ...


class ToolError(Exception):
    """Raised by tools for user-facing failures. Caught by the registry and
    returned as a ToolResult(is_error=True)."""


class ToolLoopExceededError(RuntimeError):
    """Tool loop hit max_iters without producing a final response."""
