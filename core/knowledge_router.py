#!/usr/bin/env python3
"""
core/knowledge_router.py
─────────────────────────────────────────────────────────────────────────────
Knowledge Base API.

POST   /api/kb/documents       — upload text / PDF / URL
GET    /api/kb/documents        — list documents
DELETE /api/kb/documents/{id}  — delete document
POST   /api/kb/search           — semantic search
GET    /api/kb/status           — doc count + embedding availability
─────────────────────────────────────────────────────────────────────────────
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.knowledge import (
    add_document, delete_document, format_for_context,
    get_document, get_status, list_documents, search,
)

logger = logging.getLogger("knowledge_router")
router = APIRouter(prefix="/api/kb", tags=["knowledge"])


class AddDocRequest(BaseModel):
    title: str
    content: Optional[str] = None
    url: Optional[str] = None
    source: str = ""
    tags: str = ""


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    format_context: bool = False


@router.post("/documents")
async def kb_add_document(req: AddDocRequest):
    """Add a text document or URL to the knowledge base."""
    content = req.content or ""

    if req.url and not content:
        # Fetch URL content
        try:
            from core.search_engine import fetch_page
            content = fetch_page(req.url)
            if not content:
                raise HTTPException(status_code=400, detail="Could not fetch URL content")
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"URL fetch failed: {e}")

    if not content.strip():
        raise HTTPException(status_code=400, detail="No content provided")

    doc_id = add_document(
        title=req.title.strip(),
        content=content,
        source=req.source or req.url or "",
        tags=req.tags,
    )
    return {"doc_id": doc_id, "title": req.title, "chars": len(content)}


@router.post("/documents/upload")
async def kb_upload_file(request: Request):
    """Upload a file (text/PDF/DOCX) to the knowledge base."""
    try:
        form = await request.form()
        file_obj = form.get("file")
        title = form.get("title", "")
        tags = form.get("tags", "")

        if not file_obj:
            raise HTTPException(status_code=400, detail="No file provided")

        filename = getattr(file_obj, "filename", "upload")
        data = await file_obj.read()

        if not title:
            title = filename

        # Extract text
        content = ""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext == "pdf":
            try:
                import io
                import PyPDF2
                reader = PyPDF2.PdfReader(io.BytesIO(data))
                content = "\n\n".join(p.extract_text() or "" for p in reader.pages[:50])
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"PDF read failed: {e}")
        elif ext in ("docx",):
            try:
                import docx
                import io
                doc = docx.Document(io.BytesIO(data))
                content = "\n\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except Exception as e:
                raise HTTPException(status_code=400, detail=f"DOCX read failed: {e}")
        else:
            content = data.decode("utf-8", errors="replace")

        if not content.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from file")

        doc_id = add_document(title=title, content=content, source=filename, tags=tags)
        return {"doc_id": doc_id, "title": title, "chars": len(content), "filename": filename}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/documents")
def kb_list_documents():
    """List all documents in the knowledge base."""
    return {"documents": list_documents()}


@router.get("/documents/{doc_id}")
def kb_get_document(doc_id: str):
    doc = get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.delete("/documents/{doc_id}")
def kb_delete_document(doc_id: str):
    delete_document(doc_id)
    return {"deleted": True, "doc_id": doc_id}


@router.post("/search")
def kb_search(req: SearchRequest):
    """Semantic search over the knowledge base."""
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    results = search(req.query, top_k=max(1, min(req.top_k, 20)))
    response = {"results": results, "found": len(results), "query": req.query}
    if req.format_context:
        response["context"] = format_for_context(results)
    return response


@router.get("/status")
def kb_status():
    """Knowledge base stats and embedding availability."""
    return get_status()
