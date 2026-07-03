"""Sol v1 legal/consent schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field


class LegalStatusOut(BaseModel):
    document_key: str
    version: str
    title: str
    url: str
    accepted: bool


class AcceptRequest(BaseModel):
    version: str = Field(min_length=1, max_length=64)
