#!/usr/bin/env python3
"""
core/knowledge.py
─────────────────────────────────────────────────────────────────────────────
Local RAG knowledge base using sentence-transformers + SQLite.

Documents are chunked, embedded, and stored as numpy float32 blobs.
Search uses cosine similarity — no external vector DB needed.

Requires: sentence-transformers>=2.7.0  (pip install sentence-transformers)
Falls back gracefully to keyword search if library not installed.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import struct
import uuid
from datetime import datetime
from typing import Dict, List, Optional

from core.chat_db import _get_conn, _lock

logger = logging.getLogger("knowledge")

CHUNK_SIZE = 400      # characters per chunk (approx 100 tokens)
CHUNK_OVERLAP = 80
MAX_CHUNKS_PER_DOC = 100

# ─── Lazy model loading ───────────────────────────────────────────────────────

_embed_model = None
_embed_available = None


def _get_embed_model():
    global _embed_model, _embed_available
    if _embed_available is False:
        return None
    if _embed_model is not None:
        return _embed_model
    try:
        from sentence_transformers import SentenceTransformer
        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
        _embed_available = True
        logger.info("[knowledge] Loaded all-MiniLM-L6-v2 embedding model")
        return _embed_model
    except Exception as e:
        logger.warning(f"[knowledge] sentence-transformers not available ({e}), using keyword fallback")
        _embed_available = False
        return None


# ─── Embedding utils ──────────────────────────────────────────────────────────

def _encode(text: str) -> Optional[bytes]:
    model = _get_embed_model()
    if model is None:
        return None
    vec = model.encode(text, normalize_embeddings=True)
    # Pack as float32 blob
    return struct.pack(f"{len(vec)}f", *vec.tolist())


def _decode(blob: bytes) -> Optional[List[float]]:
    if not blob:
        return None
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    # Vectors are normalized so dot product = cosine similarity
    return dot


# ─── Chunking ─────────────────────────────────────────────────────────────────

def _chunk_text(text: str) -> List[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())
        if len(chunks) >= MAX_CHUNKS_PER_DOC:
            break
        start += CHUNK_SIZE - CHUNK_OVERLAP
    return chunks


# ─── Document operations ──────────────────────────────────────────────────────

def add_document(title: str, content: str, source: str = "", tags: str = "") -> str:
    """
    Add a document to the knowledge base.
    Chunks and embeds the content.
    Returns the document ID.
    """
    doc_id = str(uuid.uuid4())
    chunks = _chunk_text(content)
    num_chunks = len(chunks)

    # Store the full doc + first chunk embedding (representative)
    first_emb = _encode(content[:1000]) if content else None

    conn = _get_conn()
    now = datetime.utcnow().isoformat()
    with _lock:
        conn.execute(
            "INSERT INTO knowledge_docs(id,title,content,source,embedding,created_at,tags,chunks) VALUES(?,?,?,?,?,?,?,?)",
            (doc_id, title, content[:50000], source, first_emb, now, tags, num_chunks)
        )
        conn.commit()

    logger.info(f"[knowledge] Added doc '{title}' ({num_chunks} chunks)")
    return doc_id


def delete_document(doc_id: str) -> bool:
    conn = _get_conn()
    with _lock:
        conn.execute("DELETE FROM knowledge_docs WHERE id=?", (doc_id,))
        conn.commit()
    return True


def list_documents() -> List[Dict]:
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT id,title,source,tags,chunks,created_at FROM knowledge_docs ORDER BY created_at DESC"
        ).fetchall()
    return [
        {"id": r[0], "title": r[1], "source": r[2], "tags": r[3], "chunks": r[4], "created_at": r[5]}
        for r in rows
    ]


def get_document(doc_id: str) -> Optional[Dict]:
    conn = _get_conn()
    with _lock:
        row = conn.execute(
            "SELECT id,title,content,source,tags,chunks,created_at FROM knowledge_docs WHERE id=?", (doc_id,)
        ).fetchone()
    if not row:
        return None
    return {"id": row[0], "title": row[1], "content": row[2], "source": row[3],
            "tags": row[4], "chunks": row[5], "created_at": row[6]}


# ─── Search ───────────────────────────────────────────────────────────────────

def search(query: str, top_k: int = 5) -> List[Dict]:
    """
    Search the knowledge base.
    Uses cosine similarity if embeddings available, otherwise keyword matching.
    Returns list of {doc_id, title, chunk, score, source}.
    """
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT id,title,content,source,embedding,tags FROM knowledge_docs"
        ).fetchall()

    if not rows:
        return []

    model = _get_embed_model()

    if model is not None:
        # Vector search
        query_vec = _decode(_encode(query))
        results = []
        for doc_id, title, content, source, emb_blob, tags in rows:
            if not emb_blob:
                continue
            doc_vec = _decode(emb_blob)
            if doc_vec is None:
                continue
            score = _cosine(query_vec, doc_vec)
            # Find best matching chunk
            chunks = _chunk_text(content)
            best_chunk = chunks[0] if chunks else content[:400]
            best_score = score
            for ch in chunks[:20]:
                ch_vec = _decode(_encode(ch))
                if ch_vec:
                    s = _cosine(query_vec, ch_vec)
                    if s > best_score:
                        best_score = s
                        best_chunk = ch
            results.append({"doc_id": doc_id, "title": title, "chunk": best_chunk,
                             "score": best_score, "source": source})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    else:
        # Keyword fallback
        ql = query.lower().split()
        results = []
        for doc_id, title, content, source, _, tags in rows:
            text_lower = (title + " " + content + " " + tags).lower()
            score = sum(1 for w in ql if w in text_lower) / max(len(ql), 1)
            if score > 0:
                # Find first matching chunk
                chunks = _chunk_text(content)
                best_chunk = next(
                    (ch for ch in chunks if any(w in ch.lower() for w in ql)),
                    chunks[0] if chunks else content[:400]
                )
                results.append({"doc_id": doc_id, "title": title, "chunk": best_chunk,
                                 "score": score, "source": source})
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]


def format_for_context(results: List[Dict]) -> str:
    """Format search results as a system-context string."""
    if not results:
        return ""
    lines = ["[Knowledge Base Results]\n"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. **{r['title']}**")
        if r.get("source"):
            lines.append(f"   Source: {r['source']}")
        lines.append(f"   {r['chunk']}\n")
    lines.append("Use the above context to inform your answer. Cite the document title.")
    return "\n".join(lines)


def get_status() -> Dict:
    conn = _get_conn()
    with _lock:
        doc_count = conn.execute("SELECT COUNT(*) FROM knowledge_docs").fetchone()[0]
        total_chunks = conn.execute("SELECT SUM(chunks) FROM knowledge_docs").fetchone()[0] or 0
    return {
        "doc_count": doc_count,
        "total_chunks": total_chunks,
        "embeddings_available": _get_embed_model() is not None,
    }
