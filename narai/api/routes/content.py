"""Content API routes — unified content generator."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from narai.api.auth import require_auth
from narai.core.content import ContentBrief, generate
from narai.core.content.generator import list_formats

rt = APIRouter(tags=["content"])


class ContentRequest(BaseModel):
    kind: str = Field(..., description="blog|newsletter|twitter|linkedin|email_drip|video_script|podcast_outline")
    topic: str
    audience: str = "entrepreneurs"
    tone: str = "direct, confident"
    goals: list[str] = []
    keywords: list[str] = []
    notes: str = ""
    use_memory: bool = True
    use_rag: bool = True


@rt.post("/content/generate")
async def content_generate(req: ContentRequest, _=Depends(require_auth)) -> dict:
    try:
        brief = ContentBrief(**req.model_dump())
        result = await generate(brief)
        return {"ok": True, "result": result.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"generation failed: {e}")


@rt.get("/content/formats")
async def content_formats(_=Depends(require_auth)) -> dict:
    return {"ok": True, "formats": list_formats()}


# Batch: generate multiple formats from one topic (e.g. blog + twitter + linkedin)
class BatchRequest(BaseModel):
    topic: str
    kinds: list[str]
    audience: str = "entrepreneurs"
    tone: str = "direct, confident"
    keywords: list[str] = []


@rt.post("/content/batch")
async def content_batch(req: BatchRequest, _=Depends(require_auth)) -> dict:
    results = []
    errors = []
    for kind in req.kinds:
        try:
            brief = ContentBrief(
                kind=kind, topic=req.topic, audience=req.audience,
                tone=req.tone, keywords=req.keywords,
            )
            r = await generate(brief)
            results.append(r.to_dict())
        except Exception as e:
            errors.append({"kind": kind, "error": str(e)})
    return {"ok": True, "results": results, "errors": errors}
