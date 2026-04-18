"""RAG pipeline — ingest PDF/MD/CSV/JSON/trade logs → chunk → embed → query.
Documents are stored in the same ChromaDB instance as memories, separate collection."""
import asyncio
import csv
import io
import json
import os
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils import embedding_functions
from langchain_text_splitters import RecursiveCharacterTextSplitter

ROOT = Path(__file__).parent.parent
_CHROMA_PATH = os.getenv("NARAI_CHROMA_PATH", str(ROOT / "data" / "chroma"))
_EMBED_MODEL = os.getenv("NARAI_EMBED_MODEL", "all-MiniLM-L6-v2")
_CHUNK_SIZE = int(os.getenv("NARAI_CHUNK_SIZE", "512"))
_CHUNK_OVERLAP = int(os.getenv("NARAI_CHUNK_OVERLAP", "64"))

_rag_collection: chromadb.Collection | None = None


def _get_rag_collection() -> chromadb.Collection:
    global _rag_collection
    if _rag_collection is None:
        client = chromadb.PersistentClient(path=_CHROMA_PATH)
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=_EMBED_MODEL
        )
        _rag_collection = client.get_or_create_collection(
            name="narai_rag",
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    return _rag_collection


_splitter = RecursiveCharacterTextSplitter(
    chunk_size=_CHUNK_SIZE,
    chunk_overlap=_CHUNK_OVERLAP,
)


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
    chunks = _splitter.split_text(raw)

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
    chunks = _splitter.split_text(text)
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
    col = _get_rag_collection()
    if col.count() == 0:
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
    return hits


def query_context(text: str, n: int = 5) -> str:
    """Return RAG hits formatted as a context string for prompts."""
    hits = query(text, n=n)
    if not hits:
        return ""
    lines = ["[RAG CONTEXT]"]
    for h in hits:
        lines.append(f"• [{h['source']}] {h['content'][:400]}")
    return "\n".join(lines)


def delete_source(source_label: str) -> None:
    col = _get_rag_collection()
    col.delete(where={"source": source_label})


async def aingest(path: str | Path, **kwargs: Any) -> int:
    return await asyncio.to_thread(ingest, path, **kwargs)


async def aquery(text: str, **kwargs: Any) -> list[dict]:
    return await asyncio.to_thread(query, text, **kwargs)
