"""Shared types for the router and adapters."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Intent(str, Enum):
    CODE = "code"
    REALTIME = "realtime"
    GENERAL = "general"


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(slots=True)
class Message:
    role: Role
    content: str

    def as_dict(self) -> dict[str, str]:
        return {"role": self.role.value, "content": self.content}


@dataclass(slots=True)
class ToolCallSpec:
    """Canonical (OpenAI-style) tool-call request returned by an adapter."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class CompletionResult:
    """Unified result from any adapter."""
    content: str
    adapter: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: int
    finish_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[ToolCallSpec] = field(default_factory=list)


def to_message_dicts(messages: list[Message] | list[dict]) -> list[dict]:
    """Normalize a mixed list of Message / dict into plain dicts."""
    out: list[dict] = []
    for m in messages:
        if isinstance(m, Message):
            out.append(m.as_dict())
        else:
            out.append(m)
    return out
