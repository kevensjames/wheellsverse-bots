"""Memory + RAG management routes."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from narai.api.auth import require_auth
from narai.core import memory, rag

rt = APIRouter(prefix="/memory", tags=["memory"])


class MemoryIn(BaseModel):
    key: str
    content: str
    tags: list[str] = []
    source: str | None = None


class RecallQuery(BaseModel):
    query: str
    n: int = 5
    tag_filter: str | None = None


@rt.post("")
async def store(item: MemoryIn, _: str = Depends(require_auth)) -> dict:
    chroma_id = await memory.aremember(item.key, item.content, tags=item.tags, source=item.source)
    return {"chroma_id": chroma_id, "key": item.key}


@rt.post("/recall")
async def recall(req: RecallQuery, _: str = Depends(require_auth)) -> list[dict]:
    return await memory.arecall(req.query, n=req.n, tag_filter=req.tag_filter)


@rt.delete("/{key}")
async def forget(key: str, _: str = Depends(require_auth)) -> dict:
    deleted = await memory.aforget(key)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory key not found")
    return {"deleted": key}


@rt.get("/count")
async def mem_count(_: str = Depends(require_auth)) -> dict:
    return {"memories": memory.count(), "rag_documents": rag._get_rag_collection().count()}


# ── RAG routes ────────────────────────────────────────────────────────────────

rag_rt = APIRouter(prefix="/rag", tags=["rag"])


@rag_rt.post("/ingest/text")
async def ingest_text_endpoint(
    source: str,
    text: str,
    _: str = Depends(require_auth),
) -> dict:
    chunks = rag.ingest_text(text, source_label=source)
    return {"source": source, "chunks": chunks}


@rag_rt.post("/ingest/file")
async def ingest_file(
    file: UploadFile,
    _: str = Depends(require_auth),
) -> dict:
    import tempfile
    from pathlib import Path

    suffix = Path(file.filename or "file.txt").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    chunks = await rag.aingest(tmp_path, source_label=file.filename)
    Path(tmp_path).unlink(missing_ok=True)
    return {"filename": file.filename, "chunks": chunks}


@rag_rt.post("/query")
async def rag_query(
    query: str,
    n: int = 5,
    _: str = Depends(require_auth),
) -> list[dict]:
    return await rag.aquery(query, n=n)
