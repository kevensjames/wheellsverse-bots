"""Self-service document library for KAI users (RAG v1).

Paid-only — same gate as /v1/chat/completions etc. Pro tier is fine
(uploads cost ~nothing to store; future v2 embeddings will cost a tiny
amount per upload but won't gate by tier for uploads).

Endpoints
---------
  POST   /account/documents               multipart/form-data file upload
  GET    /account/documents               list user's library
  GET    /account/documents/{id}/text     return the extracted text
  DELETE /account/documents/{id}          remove
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.supabase_jwt import UserPrincipal
from app.models.profile import Profile
from app.services import documents

router = APIRouter(prefix="/account/documents", tags=["documents"])

_PAID_TIERS = {"pro", "max", "ultra"}


def _require_paid(db: Session, user_id: uuid.UUID) -> Profile:
    profile = db.get(Profile, user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="profile not found")
    tier = (profile.tier or "free").lower()
    if tier not in _PAID_TIERS:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Document uploads require a paid plan",
                "current_tier": tier,
                "upgrade_url": "/kai-ui/pricing.html",
            },
        )
    return profile


class DocumentOut(BaseModel):
    id: uuid.UUID
    filename: str
    mime_type: str
    text_len: int
    created_at: str


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_doc(
    file: UploadFile = File(...),
    user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentOut:
    _require_paid(db, user.id)
    raw = await file.read()
    try:
        row = documents.upload(
            db,
            user_id=user.id,
            filename=file.filename or "untitled",
            mime_type=file.content_type or "",
            data=raw,
        )
    except documents.DocumentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return DocumentOut(
        id=row.id,
        filename=row.filename,
        mime_type=row.mime_type,
        text_len=row.text_len,
        created_at=row.created_at.isoformat(),
    )


@router.get("", response_model=list[DocumentOut])
def list_documents(
    user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentOut]:
    _require_paid(db, user.id)
    rows = documents.list_user(db, user.id)
    return [
        DocumentOut(
            id=r.id,
            filename=r.filename,
            mime_type=r.mime_type,
            text_len=r.text_len,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


@router.get("/{doc_id}/text")
def get_text(
    doc_id: uuid.UUID,
    user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_paid(db, user.id)
    row = documents.get_for_user(db, user.id, doc_id)
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")
    return {"id": str(row.id), "filename": row.filename, "text": row.full_text}


@router.get("/{doc_id}/retrieve")
def retrieve_chunks(
    doc_id: uuid.UUID,
    q: str,
    k: int = 5,
    user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """RAG v2: top-k chunks from this doc most relevant to query string q.

    Used by chat.js when a doc is attached AND the doc is large enough that
    full-text injection would blow the context window. Falls back to full
    text if no chunks were indexed (failed embedding, etc.)."""
    _require_paid(db, user.id)
    row = documents.get_for_user(db, user.id, doc_id)
    if row is None:
        raise HTTPException(status_code=404, detail="document not found")
    from app.services import rag
    chunks = rag.retrieve(db, user_id=user.id, query=q, k=k, doc_id=doc_id)
    return {
        "doc_id": str(doc_id),
        "filename": row.filename,
        "query": q,
        "chunks": chunks,
        "context": rag.compose_context(chunks),
    }


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_doc(
    doc_id: uuid.UUID,
    user: UserPrincipal = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_paid(db, user.id)
    ok = documents.delete(db, user.id, doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail="document not found")
    return None
