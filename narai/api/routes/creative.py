"""Creative API routes — music/video briefs, image prompts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from narai.api.auth import require_auth
from narai.core.creative import image_prompts, music_brief, video_brief

rt = APIRouter(tags=["creative"])


class MusicRequest(BaseModel):
    concept: str
    vibe: str = "cinematic, melodic"
    duration_sec: int = 60


class VideoRequest(BaseModel):
    concept: str
    platform: str = "tiktok"
    duration_sec: int = 30


class ImageRequest(BaseModel):
    concept: str
    n: int = 4
    style: str = "cinematic"


@rt.post("/creative/music")
async def creative_music(req: MusicRequest, _=Depends(require_auth)) -> dict:
    try:
        return {"ok": True, "result": await music_brief(**req.model_dump())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@rt.post("/creative/video")
async def creative_video(req: VideoRequest, _=Depends(require_auth)) -> dict:
    try:
        return {"ok": True, "result": await video_brief(**req.model_dump())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@rt.post("/creative/images")
async def creative_images(req: ImageRequest, _=Depends(require_auth)) -> dict:
    try:
        return {"ok": True, "result": await image_prompts(**req.model_dump())}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
