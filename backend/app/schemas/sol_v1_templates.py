"""Sol v1 template schemas (Stage 17 — template / instance / round).

Money-free: contribution_amount is a recorded number; a template holds no money.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.sol_v1 import GroupOut


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    contribution_amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    frequency: Literal["weekly", "biweekly", "monthly"]
    member_limit: int = Field(ge=2, le=100)
    visibility: Literal["public", "private", "invite_only"] = "invite_only"


class SpawnRequest(BaseModel):
    # optional override for the instance's display name (defaults to the template's)
    name: str | None = Field(default=None, max_length=120)


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    creator_id: UUID
    name: str
    contribution_amount: Decimal
    frequency: str
    member_limit: int
    visibility: str
    active: bool
    created_at: datetime


class TemplateDetail(BaseModel):
    template: TemplateOut
    # every group spawned from this template (each an "instance")
    instances: list[GroupOut]
