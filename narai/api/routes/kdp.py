"""KDP API routes — metadata optimizer, royalty projector."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from narai.api.auth import require_auth
from narai.core.kdp import optimize_metadata, project_royalties

rt = APIRouter(tags=["kdp"])


class MetadataRequest(BaseModel):
    topic: str
    genre: str = "self-help"
    target_reader: str = "entrepreneurs"
    existing_title: str = ""


class RoyaltyRequest(BaseModel):
    price: float
    format: str = "ebook"
    pages: int = 200
    file_size_mb: float = 2.0
    monthly_units: int = 10


@rt.post("/kdp/metadata")
async def kdp_metadata(req: MetadataRequest, _=Depends(require_auth)) -> dict:
    try:
        return {"ok": True, **(await optimize_metadata(**req.model_dump()))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@rt.post("/kdp/royalties")
async def kdp_royalties(req: RoyaltyRequest, _=Depends(require_auth)) -> dict:
    try:
        return {"ok": True, "projection": project_royalties(**req.model_dump())}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
