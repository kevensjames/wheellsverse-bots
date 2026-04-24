"""NarAI memory.

Two coexisting APIs:

1. Module-level vector API (`remember`, `recall`, `forget`, `aremember`, ...)
   — used by the existing chat route, backed by Chroma collection
   "narai_memory". Kept stable.

2. `MemoryStore` class — the Step 2 three-layer engine:
     * Facts (stable truths) → SQLite
     * Episodes (semantic recall of past turns) → Chroma collection
       "narai_episodes"
     * Patterns (behavior observations) → SQLite, filled in Step 7

Both APIs live in the same module so chat.py and future routes can import
from a single place.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

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
        try:
            _collection = _client.get_or_create_collection(
                name="narai_memory",
                embedding_function=_make_ef(),
                metadata={"hnsw:space": "cosine"},
            )
        except ValueError as e:
            if "embedding function" not in str(e).lower():
                raise
            _client.delete_collection("narai_memory")
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


def format_recall(entries: list[dict]) -> str:
    """Format already-fetched recall entries as a prompt context string."""
    if not entries:
        return ""
    lines = ["[MEMORY CONTEXT]"]
    for e in entries:
        lines.append(f"• [{e['key']}] {e['content'][:300]}")
    return "\n".join(lines)


def recall_context(query: str, n: int = 5) -> str:
    """Return recalled memories formatted as a context string for prompts."""
    return format_recall(recall(query, n=n))


async def aremember(key: str, content: str, **kwargs: Any) -> str:
    return await asyncio.to_thread(remember, key, content, **kwargs)


async def arecall(query: str, n: int = 5, **kwargs: Any) -> list[dict]:
    return await asyncio.to_thread(recall, query, n, **kwargs)


async def aforget(key: str) -> bool:
    return await asyncio.to_thread(forget, key)


# ── Step 2: Three-layer MemoryStore ──────────────────────────────────────────
# Facts (SQLite), Episodes (Chroma collection "narai_episodes"), Patterns
# (SQLite, reserved for Step 7). Separate from the module-level API above so
# the Step 1 chat wiring keeps working.

Category = Literal["goal", "preference", "identity", "project", "skill", "other"]
Source = Literal["explicit", "extracted", "inferred"]

_CATEGORY_ORDER = ["identity", "goal", "project", "preference", "skill", "other"]


@dataclass
class Fact:
    id: str
    user_id: str
    category: str
    content: str
    confidence: float
    created_at: str
    source: str


@dataclass
class Episode:
    id: str
    user_id: str
    content: str
    timestamp: str
    score: float = 0.0


@dataclass
class Pattern:
    id: str
    user_id: str
    pattern_type: str
    description: str
    observations_count: int
    last_seen: str


_MEMORY_STORE_SCHEMA = """
CREATE TABLE IF NOT EXISTS facts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    source TEXT DEFAULT 'explicit'
);
CREATE INDEX IF NOT EXISTS idx_user_cat ON facts(user_id, category);

CREATE TABLE IF NOT EXISTS patterns (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    pattern_type TEXT NOT NULL,
    description TEXT NOT NULL,
    observations_count INTEGER DEFAULT 1,
    last_seen TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


# Default lives in narai/data/memory_store/ so it doesn't collide with the
# existing narai/data/narai.db (SQLAlchemy async) or narai/data/chroma/ (the
# module-level vector memory above).
_DEFAULT_MEMORY_STORE_DIR = str(ROOT / "data" / "memory_store")


class MemoryStore:
    """Three-layer memory: Facts (SQL) + Episodes (vector) + Patterns (SQL).

    Pass ``data_dir`` to override defaults (tests use ``tempfile.mkdtemp()``).
    """

    def __init__(self, data_dir: str | Path = _DEFAULT_MEMORY_STORE_DIR):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.db = sqlite3.connect(
            self.data_dir / "narai.db", check_same_thread=False
        )
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_MEMORY_STORE_SCHEMA)
        self.db.commit()

        self.chroma = chromadb.PersistentClient(path=str(self.data_dir / "chroma"))
        self.episodes = self.chroma.get_or_create_collection("narai_episodes")

    # ---------- Facts ----------

    def remember_fact(
        self,
        user_id: str,
        content: str,
        category: Category = "other",
        confidence: float = 1.0,
        source: Source = "explicit",
    ) -> Fact:
        fid = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        self.db.execute(
            "INSERT INTO facts "
            "(id, user_id, category, content, confidence, created_at, updated_at, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (fid, user_id, category, content, confidence, now, now, source),
        )
        self.db.commit()
        return Fact(fid, user_id, category, content, confidence, now, source)

    def recall_facts(
        self, user_id: str, category: Category | None = None
    ) -> list[Fact]:
        if category:
            rows = self.db.execute(
                "SELECT * FROM facts WHERE user_id = ? AND category = ? "
                "ORDER BY updated_at DESC",
                (user_id, category),
            ).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM facts WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,),
            ).fetchall()
        return [
            Fact(
                r["id"], r["user_id"], r["category"], r["content"],
                r["confidence"], r["created_at"], r["source"],
            )
            for r in rows
        ]

    def forget_fact(self, fact_id: str) -> None:
        self.db.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
        self.db.commit()

    # ---------- Episodes ----------

    def log_episode(self, user_id: str, content: str) -> Episode:
        eid = str(uuid.uuid4())
        ts = datetime.utcnow().isoformat()
        self.episodes.add(
            ids=[eid],
            documents=[content],
            metadatas=[{"user_id": user_id, "timestamp": ts}],
        )
        return Episode(eid, user_id, content, ts)

    def recall_episodes(
        self, user_id: str, query: str, k: int = 3
    ) -> list[Episode]:
        result = self.episodes.query(
            query_texts=[query],
            n_results=k,
            where={"user_id": user_id},
        )
        out: list[Episode] = []
        if not result.get("ids") or not result["ids"][0]:
            return out
        for i, eid in enumerate(result["ids"][0]):
            meta = result["metadatas"][0][i]
            doc = result["documents"][0][i]
            dist = (
                result["distances"][0][i]
                if result.get("distances") and result["distances"][0]
                else 0.0
            )
            out.append(
                Episode(eid, meta["user_id"], doc, meta["timestamp"], dist)
            )
        return out

    # ---------- Context builder ----------

    def get_context(self, user_id: str, query: str | None = None) -> str:
        """Return a formatted block ready to drop into build_system_prompt."""
        facts = self.recall_facts(user_id)
        if not facts and not query:
            return ""

        lines: list[str] = ["Known about this user:"]

        by_cat: dict[str, list[str]] = {}
        for f in facts:
            by_cat.setdefault(f.category, []).append(f.content)

        for cat in _CATEGORY_ORDER:
            items = by_cat.get(cat)
            if not items:
                continue
            lines.append(f"\n{cat.capitalize()}:")
            lines.extend(f"- {item}" for item in items)

        if query:
            eps = self.recall_episodes(user_id, query, k=3)
            if eps:
                lines.append("\nRecent context:")
                lines.extend(f"- {e.content}" for e in eps)

        return "\n".join(lines)

    # ---------- Patterns (Step 6 read, Step 7 write) ----------

    def get_patterns(self, user_id: str, limit: int = 3) -> list[Pattern]:
        rows = self.db.execute(
            "SELECT * FROM patterns WHERE user_id = ? "
            "ORDER BY observations_count DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [
            Pattern(
                r["id"], r["user_id"], r["pattern_type"],
                r["description"], r["observations_count"], r["last_seen"],
            )
            for r in rows
        ]

    def upsert_pattern(
        self,
        user_id: str,
        pattern_type: str,
        description: str,
        observations_count: int = 1,
    ) -> None:
        # Deterministic ID so same description always maps to the same row.
        pid = hashlib.sha256(f"{user_id}:{description}".encode()).hexdigest()[:32]
        now = datetime.utcnow().isoformat()
        self.db.execute(
            "INSERT INTO patterns (id, user_id, pattern_type, description, "
            "observations_count, last_seen) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "observations_count=excluded.observations_count, last_seen=excluded.last_seen",
            (pid, user_id, pattern_type, description, observations_count, now),
        )
        self.db.commit()

    def get_recent_episodes_raw(self, user_id: str, limit: int = 100) -> list[dict]:
        """All episodes for a user sorted newest-first (for pattern mining)."""
        try:
            result = self.episodes.get(
                where={"user_id": user_id},
                include=["documents", "metadatas"],
            )
        except Exception:
            return []
        ids = result.get("ids") or []
        if not ids:
            return []
        pairs = [
            {"content": doc, "timestamp": meta.get("timestamp", "")}
            for doc, meta in zip(result["documents"], result["metadatas"])
        ]
        pairs.sort(key=lambda x: x["timestamp"], reverse=True)
        return pairs[:limit]

    def close(self) -> None:
        self.db.close()
