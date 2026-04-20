"""Research API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from narai.api.auth import require_auth
from narai.core.research import ResearchBrief, research

rt = APIRouter(tags=["research"])


class ResearchRequest(BaseModel):
    query: str
    max_sources: int = 6
    ingest_to_rag: bool = True
    rag_label: str = ""


@rt.post("/research")
async def research_run(req: ResearchRequest, _=Depends(require_auth)) -> dict:
    try:
        result = await research(ResearchBrief(**req.model_dump()))
        return {"ok": True, "result": result.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
