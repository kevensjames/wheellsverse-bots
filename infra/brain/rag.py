"""RAG pipeline — ingest PDF/MD/CSV/JSON/trade logs → chunk → embed → query.
Documents are stored in the same ChromaDB instance as memories, separate collection.

RAG is intentionally global — shared knowledge base across all users.
If per-user uploads land later, add user_id filter then."""
from __future__ import annotations

import asyncio
import csv
import json
import os
from pathlib import Path
from typing import Any, Optional

import chromadb
from chromadb.utils import embedding_functions

# Brain modules now live at infra/brain/, but persistent Chroma data
# continues to live at narai/data/chroma so existing RAG collections keep
# working without migration. Override with NARAI_CHROMA_PATH env if desired.
ROOT = Path(__file__).resolve().parents[2] / "narai"
_DEFAULT_CHROMA_PATH = str(ROOT / "data" / "chroma")
_CHUNK_SIZE = int(os.getenv("NARAI_CHUNK_SIZE", "512"))
_CHUNK_OVERLAP = int(os.getenv("NARAI_CHUNK_OVERLAP", "64"))

_rag_collection: Optional[Any] = None
_current_rag_path: Optional[str] = None


def _split_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Simple sliding-window text splitter — no external dependency."""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        # Try to break at a sentence boundary within the last 20% of the chunk
        boundary = text.rfind(". ", start + int(chunk_size * 0.8), end)
        if boundary != -1:
            end = boundary + 1
        chunks.append(text[start:end].strip())
        start = end - overlap
    return [c for c in chunks if c]


def _make_ef() -> Any:
    model = os.getenv("NARAI_EMBED_MODEL", "all-MiniLM-L6-v2")
    try:
        return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model)
    except Exception:
        return embedding_functions.DefaultEmbeddingFunction()


def _get_rag_collection() -> Any:
    global _rag_collection, _current_rag_path
    path = os.getenv("NARAI_CHROMA_PATH", _DEFAULT_CHROMA_PATH)
    if _rag_collection is None or path != _current_rag_path:
        _current_rag_path = path
        client = chromadb.PersistentClient(path=path)
        try:
            _rag_collection = client.get_or_create_collection(
                name="narai_rag",
                embedding_function=_make_ef(),
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            if "embedding function" not in str(e).lower():
                raise
            try:
                client.delete_collection("narai_rag")
            except Exception:
                pass
            _rag_collection = client.get_or_create_collection(
                name="narai_rag",
                embedding_function=_make_ef(),
                metadata={"hnsw:space": "cosine"},
            )
    return _rag_collection




# ── Loaders ───────────────────────────────────────────────────────────────────

def _load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _load_pdf(path: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _load_csv(path: Path) -> str:
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(" | ".join(f"{k}: {v}" for k, v in row.items()))
    return "\n".join(rows)


def _load_json(path: Path) -> str:
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return "\n".join(json.dumps(item, default=str) for item in data)
    return json.dumps(data, indent=2, default=str)


_LOADERS = {
    ".pdf": _load_pdf,
    ".md": _load_text,
    ".txt": _load_text,
    ".csv": _load_csv,
    ".json": _load_json,
}


def _load_file(path: Path) -> str:
    loader = _LOADERS.get(path.suffix.lower())
    if loader is None:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    return loader(path)


# ── Ingest ────────────────────────────────────────────────────────────────────

def ingest(path: str | Path, source_label: str | None = None) -> int:
    """Ingest a file into the RAG collection. Returns number of chunks stored."""
    path = Path(path)
    label = source_label or path.name
    raw = _load_file(path)
    chunks = _split_text(raw)

    col = _get_rag_collection()
    ids = [f"{label}::chunk::{i}" for i in range(len(chunks))]
    metadatas = [{"source": label, "chunk": i, "file_type": path.suffix.lstrip(".")}
                 for i in range(len(chunks))]

    # upsert in batches of 100 to avoid memory spikes
    for start in range(0, len(chunks), 100):
        batch_ids = ids[start:start + 100]
        batch_docs = chunks[start:start + 100]
        batch_meta = metadatas[start:start + 100]
        col.upsert(ids=batch_ids, documents=batch_docs, metadatas=batch_meta)

    return len(chunks)


def ingest_text(text: str, source_label: str, file_type: str = "text") -> int:
    """Ingest raw text directly (e.g., trade log string)."""
    chunks = _split_text(text)
    col = _get_rag_collection()
    ids = [f"{source_label}::chunk::{i}" for i in range(len(chunks))]
    metadatas = [{"source": source_label, "chunk": i, "file_type": file_type}
                 for i in range(len(chunks))]
    for start in range(0, len(chunks), 100):
        col.upsert(
            ids=ids[start:start + 100],
            documents=chunks[start:start + 100],
            metadatas=metadatas[start:start + 100],
        )
    return len(chunks)


# ── Query ─────────────────────────────────────────────────────────────────────

def query(text: str, n: int = 5, source_filter: str | None = None) -> list[dict]:
    """Semantic search over ingested documents."""
    import time as _time
    # Telemetry — context-bound, optional, never throws into the hot path.
    try:
        from .telemetry import (
            EVENT_RAG_HIT,
            EVENT_RAG_MISS,
            EVENT_RAG_QUERY,
            get_current_telemetry,
        )
        _tel = get_current_telemetry()
    except Exception:
        _tel = None

    _t0 = _time.perf_counter()
    col = _get_rag_collection()
    if col.count() == 0:
        if _tel is not None and _tel.enabled:
            _ms = (_time.perf_counter() - _t0) * 1000.0
            _tel.emit(EVENT_RAG_QUERY, query_len=len(text), n_requested=n,
                      hits=0, duration_ms=_ms, empty_collection=True)
            _tel.emit(EVENT_RAG_MISS, hits=0)
            _tel.record_latency("rag_query", _ms)
        return []
    where = {"source": source_filter} if source_filter else None
    try:
        results = col.query(
            query_texts=[text],
            n_results=min(n, col.count()),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        if _tel is not None and _tel.enabled:
            _ms = (_time.perf_counter() - _t0) * 1000.0
            _tel.emit(EVENT_RAG_QUERY, query_len=len(text), n_requested=n,
                      hits=0, duration_ms=_ms, error=True)
            _tel.emit(EVENT_RAG_MISS, hits=0)
            _tel.record_latency("rag_query", _ms)
        return []

    hits = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        hits.append({
            "content": doc,
            "source": meta.get("source", ""),
            "chunk": meta.get("chunk", 0),
            "file_type": meta.get("file_type", ""),
            "score": round(1 - dist, 4),
        })

    if _tel is not None and _tel.enabled:
        _ms = (_time.perf_counter() - _t0) * 1000.0
        _tel.emit(EVENT_RAG_QUERY, query_len=len(text), n_requested=n,
                  hits=len(hits), duration_ms=_ms,
                  source_filter=source_filter or None)
        _tel.emit(EVENT_RAG_HIT if hits else EVENT_RAG_MISS, hits=len(hits))
        _tel.record_latency("rag_query", _ms)

    return hits


def format_query(hits: list[dict]) -> str:
    """Format pre-fetched RAG hits as a context string for prompts.
    Used by chat.py which already has hits from rag.aquery() and just needs
    the formatting half of query_context()."""
    if not hits:
        return ""
    lines = ["[RAG CONTEXT]"]
    for h in hits:
        lines.append(f"• [{h.get('source', '?')}] {h.get('content', '')[:400]}")
    return "\n".join(lines)


def query_context(text: str, n: int = 5) -> str:
    """Return RAG hits formatted as a context string for prompts."""
    return format_query(query(text, n=n))


def delete_source(source_label: str) -> None:
    col = _get_rag_collection()
    col.delete(where={"source": source_label})


async def aingest(path: str | Path, **kwargs: Any) -> int:
    return await asyncio.to_thread(ingest, path, **kwargs)


async def aquery(text: str, **kwargs: Any) -> list[dict]:
    return await asyncio.to_thread(query, text, **kwargs)
