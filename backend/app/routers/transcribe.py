"""Voice → text endpoint for KAI chat.

Frontend records audio via MediaRecorder (browser API), POSTs the
blob here, we forward to OpenAI's hosted Whisper API and return text.

Why hosted Whisper, not local:
  - Local Whisper needs PyTorch + a ~1.5GB model + CPU/GPU compute.
    On the Mac mini, real-time-ish transcription would compete with
    the daemon's request-serving CPU budget.
  - Hosted Whisper is $0.006/minute. A 30-second voice prompt = $0.003.
    Cheaper than the embedding cost of the resulting text in most cases.
  - Same API key (OPENAI_API_KEY) we already use everywhere else.

Tier gate: paid plans (pro/max/ultra). Voice was on the landing's
'not in v1' list — this closes that gap for paid users.
"""
from __future__ import annotations

import io
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.supabase_jwt import UserPrincipal
from app.models.profile import Profile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/kai", tags=["voice"])

_PAID_TIERS = {"pro", "max", "ultra"}
MAX_AUDIO_BYTES = 25 * 1024 * 1024   # OpenAI Whisper hard limit


def _require_paid(db: Session, user_id) -> Profile:
    profile = db.get(Profile, user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    tier = (profile.tier or "free").lower()
    if tier not in _PAID_TIERS:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Voice input requires a paid plan",
                "current_tier": tier,
                "upgrade_url": "/kai-ui/pricing.html",
            },
        )
    return profile


def _transcribe_blocking(api_key: str, bio: "io.BytesIO") -> str:
    """The synchronous OpenAI Whisper call — run in a threadpool so it doesn't
    block the event loop (PERF-F6)."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    result = client.audio.transcriptions.create(
        model="whisper-1", file=bio, response_format="text",
    )
    # whisper-1 with response_format=text returns a plain string
    return str(result).strip() if result else ""


@router.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload an audio blob (webm/m4a/mp3/wav) → return transcribed text."""
    _require_paid(db, user.id)

    if not settings.OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="OpenAI not configured")

    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="empty audio")
    if len(raw) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"audio too large ({len(raw):,} bytes); max {MAX_AUDIO_BYTES:,}",
        )

    # OpenAI SDK wants a file-like object with a name (it infers MIME from ext)
    fname = file.filename or "audio.webm"
    bio = io.BytesIO(raw)
    bio.name = fname

    try:
        text = await run_in_threadpool(
            _transcribe_blocking, settings.OPENAI_API_KEY, bio
        )
    except Exception as e:
        logger.exception("whisper transcription failed")
        raise HTTPException(status_code=502, detail=f"transcription error: {e}")

    if not text:
        return {"text": "", "note": "no speech detected"}
    return {"text": text}
