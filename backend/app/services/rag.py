"""RAG v2: chunk + embed at upload, retrieve top-k at query time.

Pipeline
--------
upload (services/documents.py:upload)
  → extract text (PDF/TXT/MD)
  → store full text in kai_documents (unchanged from v1)
  → THIS module: split into ~800-char chunks (200-char overlap)
                 embed each chunk via OpenAI text-embedding-3-small
                 INSERT INTO kai_doc_chunks (..., embedding)

retrieval (services/rag.retrieve)
  → embed the user query
  → SELECT chunks ORDER BY embedding <=> query LIMIT k
    (only the user's own doc_id space, RLS-style enforced by the WHERE)

Cost
----
text-embedding-3-small: $0.02 per 1M tokens (~$0.0001 per 50-page doc).
Per query: one embed (~$0.000001). Negligible.

Failure model
-------------
Embedding errors during upload are LOGGED + the chunk is stored with
embedding=NULL. We skip those chunks at retrieval time. A failed embed
doesn't fail the upload.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Sequence

from sqlalchemy import text as sqltext
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Tuneables. Conservative defaults; revisit when we have real usage.
CHUNK_CHARS = 800        # ~200 tokens per chunk
CHUNK_OVERLAP = 200      # share 25% with neighbors for boundary coverage
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
EMBED_BATCH = 96         # OpenAI accepts up to 2048 inputs/request


# ── Chunking ──────────────────────────────────────────────────────────────


def split_into_chunks(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Sliding-window character chunks. Boundary-agnostic — we don't try to
    split on sentence/paragraph because the embedder handles partial-context
    fragments fine. Overlap covers boundary loss."""
    if not text:
        return []
    chunks: list[str] = []
    step = max(1, size - overlap)
    i = 0
    while i < len(text):
        chunk = text[i : i + size].strip()
        if chunk:
            chunks.append(chunk)
        if i + size >= len(text):
            break
        i += step
    return chunks


# ── Embedding ─────────────────────────────────────────────────────────────


def _embed_batch(texts: Sequence[str]) -> list[list[float] | None]:
    """Call OpenAI embeddings. Returns one vector per input (or None on failure)."""
    if not texts:
        return []
    import urllib.request, urllib.error
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        logger.warning("OPENAI_API_KEY missing — skipping embeddings")
        return [None] * len(texts)
    body = json.dumps({"model": EMBED_MODEL, "input": list(texts)}).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/embeddings",
        data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        logger.warning("OpenAI embeddings HTTP %s: %s", e.code, e.read()[:300])
        return [None] * len(texts)
    except Exception as e:
        logger.warning("OpenAI embeddings call failed: %s", e)
        return [None] * len(texts)
    data = payload.get("data") or []
    # Sort by index to be paranoid about order
    by_idx = {d["index"]: d["embedding"] for d in data}
    return [by_idx.get(i) for i in range(len(texts))]


# ── Index a document ──────────────────────────────────────────────────────


def index_document(db: Session, doc_id: uuid.UUID, user_id: uuid.UUID, text: str) -> int:
    """Chunk + embed + insert. Returns number of chunks indexed.

    Called by documents.upload() after the doc is persisted. Safe to call
    multiple times (no dedup) — but in practice the upload flow only calls
    it once per doc.
    """
    chunks = split_into_chunks(text)
    if not chunks:
        return 0

    total = 0
    for start in range(0, len(chunks), EMBED_BATCH):
        batch = chunks[start : start + EMBED_BATCH]
        embeddings = _embed_batch(batch)
        for offset, (chunk_text, vec) in enumerate(zip(batch, embeddings)):
            pos = start + offset
            # pgvector accepts a string literal like '[0.1,0.2,...]'
            vec_str = None
            if vec is not None and len(vec) == EMBED_DIM:
                vec_str = "[" + ",".join(repr(round(float(v), 6)) for v in vec) + "]"
            db.execute(
                sqltext(
                    """
                    INSERT INTO kai_doc_chunks
                        (doc_id, user_id, position, content, embedding)
                    VALUES
                        (:doc_id, :user_id, :position, :content,
                         CAST(:embedding AS vector))
                    """
                ),
                {
                    "doc_id": str(doc_id),
                    "user_id": str(user_id),
                    "position": pos,
                    "content": chunk_text,
                    "embedding": vec_str,
                },
            )
            total += 1
        db.commit()  # commit each batch so a later batch failure preserves prior work
    return total


# ── Retrieve top-k for a query ────────────────────────────────────────────


def retrieve(
    db: Session,
    user_id: uuid.UUID,
    query: str,
    k: int = 5,
    doc_id: uuid.UUID | None = None,
) -> list[dict]:
    """Return top-k chunks most similar to the query (cosine distance).

    Scoped to the user's own chunks. If doc_id is given, scoped further to
    that one document (use when user picks a specific doc from the dropdown).
    Returns [] if embedding fails or no chunks indexed.
    """
    if not query.strip():
        return []
    vecs = _embed_batch([query])
    if not vecs or vecs[0] is None:
        return []
    q_vec = vecs[0]
    vec_str = "[" + ",".join(repr(round(float(v), 6)) for v in q_vec) + "]"

    where_doc = "AND c.doc_id = :doc_id" if doc_id else ""
    sql = sqltext(f"""
        SELECT
          c.id, c.doc_id, c.position, c.content,
          d.filename,
          (c.embedding <=> CAST(:q AS vector)) AS dist
        FROM kai_doc_chunks c
        JOIN kai_documents d ON d.id = c.doc_id
        WHERE c.user_id = :user_id
          AND c.embedding IS NOT NULL
          {where_doc}
        ORDER BY c.embedding <=> CAST(:q AS vector)
        LIMIT :k
    """)
    params = {"user_id": str(user_id), "q": vec_str, "k": k}
    if doc_id:
        params["doc_id"] = str(doc_id)
    rows = db.execute(sql, params).fetchall()
    return [
        {
            "chunk_id": str(r[0]),
            "doc_id": str(r[1]),
            "position": int(r[2]),
            "content": r[3],
            "filename": r[4],
            "distance": float(r[5]),
        }
        for r in rows
    ]


def compose_context(chunks: list[dict], max_chars: int = 12_000) -> str:
    """Format retrieved chunks as a single context block to prepend to a
    chat message. Trims to max_chars to keep us safely under any model's
    context window."""
    if not chunks:
        return ""
    parts = []
    used = 0
    for c in chunks:
        snippet = (
            f"[From \"{c['filename']}\", chunk #{c['position']}]\n{c['content']}\n"
        )
        if used + len(snippet) > max_chars:
            break
        parts.append(snippet)
        used += len(snippet)
    if not parts:
        return ""
    return (
        "Reference excerpts from your uploaded documents:\n"
        "---\n" + "\n---\n".join(parts) + "\n---\n"
    )
