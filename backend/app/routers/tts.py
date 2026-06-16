"""Text-to-speech endpoint — KAI's "read response aloud" button.

Tier gate matches /kai/transcribe: paid plans only (pro/max/ultra).
Voice was on the v1 'not in this release' list — closing the loop
means both input AND output are voice-capable for paying users.

POST /kai/tts
  body: { "text": "..." }
  returns: audio/wav body
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.supabase_jwt import UserPrincipal
from app.models.profile import Profile
from app.services import tts

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/kai", tags=["voice"])

_PAID_TIERS = {"pro", "max", "ultra"}


def _require_paid(db: Session, user_id) -> Profile:
    profile = db.get(Profile, user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    tier = (profile.tier or "free").lower()
    if tier not in _PAID_TIERS:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Voice output requires a paid plan",
                "current_tier": tier,
                "upgrade_url": "/kai-ui/pricing.html",
            },
        )
    return profile


class TTSRequest(BaseModel):
    text: str


@router.post("/tts")
def synthesize_speech(
    body: TTSRequest,
    user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_paid(db, user.id)

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text cannot be empty")

    try:
        wav_bytes, mime = tts.synthesize(text)
    except tts.TTSError as e:
        logger.error("tts synthesis failed: %s", e)
        raise HTTPException(status_code=502, detail=f"tts error: {e}")

    return Response(content=wav_bytes, media_type=mime)
