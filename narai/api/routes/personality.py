"""Personality selection routes (Week 4-B).

  GET  /personalities         — list all 6 archetypes (slug/name/description)
  GET  /personalities/me      — the current user's selection
  POST /personalities/select  — set the current user's selection
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from narai.api.auth import require_auth
from narai.api.dependencies.personality import (
    get_user_personality,
    set_user_personality,
)
from narai.core.personalities import (
    DEFAULT_PERSONALITY_SLUG,
    PERSONALITIES,
    list_personalities,
)


logger = logging.getLogger("narai.routes.personality")

rt = APIRouter(prefix="/personalities", tags=["personalities"])


class SelectRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=32)


class SelectResponse(BaseModel):
    slug: str
    name: str


@rt.get("")
def list_all(_: str = Depends(require_auth)) -> dict:
    """Return all available personality presets. Auth-gated so anonymous
    callers don't enumerate; the data itself isn't sensitive."""
    return {
        "personalities": list_personalities(),
        "default": DEFAULT_PERSONALITY_SLUG,
    }


@rt.get("/me")
def current(slug: str = Depends(get_user_personality)) -> dict:
    """Return the authenticated user's current personality selection.
    Falls back to the default slug if none is set or column is missing."""
    p = PERSONALITIES[slug]
    return {"slug": p.slug, "name": p.name, "description": p.description}


@rt.post("/select", response_model=SelectResponse)
def select(
    body: SelectRequest,
    user_id: str = Depends(require_auth),
) -> SelectResponse:
    """Update the authenticated user's personality. 400 on unknown slug;
    503 if persistence fails (column not yet migrated, DB error)."""
    if body.slug not in PERSONALITIES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown personality slug {body.slug!r}; "
                f"valid slugs: {list(PERSONALITIES.keys())}"
            ),
        )
    ok = set_user_personality(user_id, body.slug)
    if not ok:
        raise HTTPException(
            status_code=503,
            detail=(
                "couldn't persist personality selection — the "
                "profiles.personality column may not be migrated yet. "
                "Retry after the Week 4-B SQL migration is applied."
            ),
        )
    p = PERSONALITIES[body.slug]
    return SelectResponse(slug=p.slug, name=p.name)
