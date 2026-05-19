"""Request / response shapes for the NAI API."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10_000)
    conversation_id: uuid.UUID | None = None
    use_tools: bool = False
    prefer_local: bool = False
    max_tokens: int = Field(default=1024, ge=64, le=4096)


class MessageOut(BaseModel):
    # protected_namespaces=() silences Pydantic v2's "model_" warning — we
    # carry the real DB column name ``model_used`` through to the API.
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: uuid.UUID
    role: str
    content: str
    adapter: str | None = None
    model_used: str | None = None
    cost_usd: float | None = None
    created_at: datetime
    tool_calls: list[dict[str, Any]] | None = None
    tool_name: str | None = None


class ChatResponse(BaseModel):
    conversation_id: uuid.UUID
    message: MessageOut
    total_cost_usd: float  # sum of LLM call costs for this turn


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    message_count: int


class ConversationDetail(BaseModel):
    id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]
