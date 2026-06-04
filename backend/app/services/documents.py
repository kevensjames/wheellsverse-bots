"""Document upload + library service for RAG v1.

Supported input formats (v1):
  - text/plain
  - text/markdown
  - application/pdf  (extracted via PyPDF2)

We extract text at upload time, never re-parse the original. Storage is
just the extracted text + the original filename for display. We DON'T
store the raw PDF bytes — that would 5–20× the storage cost for zero
value (we can't re-extract a different shape from the same PDF).

Limits (v1):
  - max file size 5 MB before extraction
  - max extracted text 200_000 chars after extraction (~50 pages)
  - per-user document quota 50

Future v2 adds chunk-level embeddings + retrieval; today's flow prepends
the full text to a chat message that explicitly references the doc.
"""
from __future__ import annotations

import io
import logging
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.document import KaiDocument

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 5 * 1024 * 1024       # 5 MB raw
MAX_TEXT_CHARS = 200_000               # ~50 pages
MAX_DOCS_PER_USER = 50


class DocumentError(ValueError):
    """User-facing error: surfaces directly to API 4xx response."""


def _extract_pdf(data: bytes) -> str:
    try:
        from PyPDF2 import PdfReader
    except ImportError as e:  # pragma: no cover — should be in venv
        raise DocumentError("PDF support not installed on server") from e
    try:
        reader = PdfReader(io.BytesIO(data))
        parts = []
        for page in reader.pages:
            t = page.extract_text() or ""
            if t.strip():
                parts.append(t.strip())
        return "\n\n".join(parts)
    except Exception as e:
        raise DocumentError(f"could not parse PDF: {e}") from e


def _extract_text(data: bytes) -> str:
    # Best-effort decode — try UTF-8 first, then latin-1 as fallback.
    for enc in ("utf-8", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise DocumentError("could not decode text file (not UTF-8 or latin-1)")


def upload(
    db: Session,
    user_id: uuid.UUID,
    filename: str,
    mime_type: str,
    data: bytes,
) -> KaiDocument:
    """Extract text from data + persist. Returns the row.

    Raises DocumentError on any user-visible failure (too big, bad PDF,
    bad encoding, quota exceeded). The caller maps to HTTPException(400/413).
    """
    if not filename or not filename.strip():
        raise DocumentError("filename required")
    if len(data) > MAX_FILE_BYTES:
        raise DocumentError(
            f"file too large ({len(data):,} bytes); max {MAX_FILE_BYTES:,}"
        )
    if not data:
        raise DocumentError("empty file")

    mime = (mime_type or "").lower().strip()
    if mime == "application/pdf" or filename.lower().endswith(".pdf"):
        text = _extract_pdf(data)
        mime = "application/pdf"
    elif mime.startswith("text/") or filename.lower().endswith((".txt", ".md", ".markdown")):
        text = _extract_text(data)
        if not mime:
            mime = "text/plain"
    else:
        raise DocumentError(
            f"unsupported file type {mime!r}; v1 supports PDF + text + markdown"
        )

    text = (text or "").strip()
    if not text:
        raise DocumentError("no extractable text in file")
    if len(text) > MAX_TEXT_CHARS:
        # Truncate rather than reject — most over-limit docs are slightly over
        text = text[:MAX_TEXT_CHARS]
        logger.warning("document truncated to %d chars (was over limit)", MAX_TEXT_CHARS)

    # Quota check
    current = db.query(KaiDocument).filter(KaiDocument.user_id == user_id).count()
    if current >= MAX_DOCS_PER_USER:
        raise DocumentError(
            f"document quota reached ({MAX_DOCS_PER_USER}); delete one first"
        )

    row = KaiDocument(
        user_id=user_id,
        filename=filename.strip()[:200],  # cap display name
        mime_type=mime,
        text_len=len(text),
        full_text=text,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_user(db: Session, user_id: uuid.UUID) -> list[KaiDocument]:
    return (
        db.query(KaiDocument)
        .filter(KaiDocument.user_id == user_id)
        .order_by(KaiDocument.created_at.desc())
        .all()
    )


def get_for_user(
    db: Session, user_id: uuid.UUID, doc_id: uuid.UUID
) -> Optional[KaiDocument]:
    return (
        db.query(KaiDocument)
        .filter(KaiDocument.id == doc_id, KaiDocument.user_id == user_id)
        .first()
    )


def delete(db: Session, user_id: uuid.UUID, doc_id: uuid.UUID) -> bool:
    row = get_for_user(db, user_id, doc_id)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True
