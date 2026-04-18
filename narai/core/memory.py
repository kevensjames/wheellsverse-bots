"""Long-term vector memory backed by ChromaDB (local, no server needed).
Each memory entry is embedded and stored; recall uses semantic similarity."""
from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import chromadb
from chromadb.utils import embedding_functions

ROOT = Path(__file__).parent.parent
_DEFAULT_CHROMA_PATH = str(ROOT / "data" / "chroma")

_client: Optional[Any] = None
_collection: Optional[Any] = None
_current_path: Optional[str] = None


def _make_ef() -> Any:
    model = os.getenv("NARAI_EMBED_MODEL", "all-MiniLM-L6-v2")
    try:
        return embedding_functions.SentenceTransformerEmbeddingFunction(model_name=model)
    except Exception:
        return embedding_functions.DefaultEmbeddingFunction()


def _get_collection() -> Any:
    global _client, _collection, _current_path
    # Re-init when path changes (supports test isolation via monkeypatch)
    path = os.getenv("NARAI_CHROMA_PATH", _DEFAULT_CHROMA_PATH)
    if _collection is None or path != _current_path:
        _current_path = path
        _client = chromadb.PersistentClient(path=path)
        _collection = _client.get_or_create_collection(
            name="narai_memory",
            embedding_function=_make_ef(),
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def _key_to_id(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:32]


# ── Public API ────────────────────────────────────────────────────────────────

def remember(
    key: str,
    content: str,
    tags: list[str] | None = None,
    source: str | None = None,
) -> str:
    """Store or update a memory entry. Returns the chroma ID."""
    col = _get_collection()
    chroma_id = _key_to_id(key)
    metadata = {
        "key": key,
        "tags": ",".join(tags or []),
        "source": source or "",
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }
    col.upsert(ids=[chroma_id], documents=[content], metadatas=[metadata])
    return chroma_id


def recall(query: str, n: int = 5, tag_filter: str | None = None) -> list[dict]:
    """Semantic search over memories. Returns list of {key, content, tags, score}."""
    col = _get_collection()
    where = {"tags": {"$contains": tag_filter}} if tag_filter else None
    try:
        results = col.query(
            query_texts=[query],
            n_results=min(n, col.count() or 1),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        return []

    entries = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        entries.append({
            "key": meta.get("key", ""),
            "content": doc,
            "tags": [t for t in meta.get("tags", "").split(",") if t],
            "source": meta.get("source", ""),
            "saved_at": meta.get("saved_at", ""),
            "score": round(1 - dist, 4),  # cosine distance → similarity
        })
    return entries


def forget(key: str) -> bool:
    """Remove a memory entry by key. Returns True if deleted."""
    col = _get_collection()
    chroma_id = _key_to_id(key)
    try:
        col.delete(ids=[chroma_id])
        return True
    except Exception:
        return False


def count() -> int:
    return _get_collection().count()


def recall_context(query: str, n: int = 5) -> str:
    """Return recalled memories formatted as a context string for prompts."""
    entries = recall(query, n=n)
    if not entries:
        return ""
    lines = ["[MEMORY CONTEXT]"]
    for e in entries:
        lines.append(f"• [{e['key']}] {e['content'][:300]}")
    return "\n".join(lines)


async def aremember(key: str, content: str, **kwargs: Any) -> str:
    return await asyncio.to_thread(remember, key, content, **kwargs)


async def arecall(query: str, n: int = 5, **kwargs: Any) -> list[dict]:
    return await asyncio.to_thread(recall, query, n, **kwargs)


async def aforget(key: str) -> bool:
    return await asyncio.to_thread(forget, key)
