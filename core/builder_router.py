#!/usr/bin/env python3
"""
core/builder_router.py
─────────────────────────────────────────────────────────────────────────────
Visual Bot Builder API.

GET  /api/builder/templates     — list templates
POST /api/builder/create        — build + save bot from template
POST /api/builder/preview       — generate code preview (no save)
─────────────────────────────────────────────────────────────────────────────
"""

from typing import Dict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from core.bot_builder import build_from_template, get_templates, preview_from_template

router = APIRouter(prefix="/api/builder", tags=["builder"])


class BuildRequest(BaseModel):
    template_id: str
    config: Dict
    bot_name: str


class PreviewRequest(BaseModel):
    template_id: str
    config: Dict
    bot_name: str = "preview_bot"


@router.get("/templates")
def builder_templates():
    return {"templates": get_templates()}


@router.post("/create")
def builder_create(req: BuildRequest):
    if not req.bot_name.strip():
        raise HTTPException(status_code=400, detail="bot_name required")
    try:
        result = build_from_template(req.template_id, req.config, req.bot_name.strip())
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/preview")
def builder_preview(req: PreviewRequest):
    try:
        code = preview_from_template(req.template_id, req.config, req.bot_name)
        return {"code": code}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
