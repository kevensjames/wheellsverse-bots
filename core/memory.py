#!/usr/bin/env python3
"""
core/memory.py
─────────────────────────────────────────────────────────────────────────────
Memory System — stores outputs, decisions, and context per project.

Storage: JSON (default) + optional OpenAI vector embeddings for semantic search.

Structure:
  memory/
    global.json           ← cross-project context
    projects/
      wheellsverse.json   ← per-project memory
      client_1.json
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent.parent
MEMORY_DIR = ROOT / "memory"

logger = logging.getLogger("memory")


class MemoryEntry:
    """A single memory record."""

    def __init__(
        self,
        key: str,
        content: str,
        source: str = "",
        tags: Optional[List[str]] = None,
        project: str = "global",
        metadata: Optional[Dict] = None,
    ):
        self.key = key
        self.content = content
        self.source = source
        self.tags = tags or []
        self.project = project
        self.metadata = metadata or {}
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.access_count = 0

    def to_dict(self) -> Dict:
        return {
            "key": self.key,
            "content": self.content,
            "source": self.source,
            "tags": self.tags,
            "project": self.project,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
        }

    @classmethod
    def from_dict(cls, d: Dict) -> "MemoryEntry":
        e = cls(
            key=d["key"],
            content=d.get("content", ""),
            source=d.get("source", ""),
            tags=d.get("tags", []),
            project=d.get("project", "global"),
            metadata=d.get("metadata", {}),
        )
        e.created_at = d.get("created_at", e.created_at)
        e.updated_at = d.get("updated_at", e.updated_at)
        e.access_count = d.get("access_count", 0)
        return e


class MemoryStore:
    """
    JSON-backed memory store with keyword search.
    Optional: semantic search via OpenAI embeddings (set USE_EMBEDDINGS=true in .env).
    """

    MAX_ENTRIES = 2000

    def __init__(self, project: str = "global"):
        self.project = project
        self._entries: Dict[str, MemoryEntry] = {}
        self._lock = threading.Lock()
        self._path = self._get_path(project)
        self._load()

    @staticmethod
    def _get_path(project: str) -> Path:
        if project == "global":
            return MEMORY_DIR / "global.json"
        return MEMORY_DIR / "projects" / f"{project}.json"

    def _load(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                for key, d in data.items():
                    self._entries[key] = MemoryEntry.from_dict(d)
                logger.debug(f"Memory loaded: {len(self._entries)} entries [{self.project}]")
            except Exception as e:
                logger.warning(f"Memory load error [{self.project}]: {e}")

    def _save(self):
        try:
            data = {k: v.to_dict() for k, v in self._entries.items()}
            self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Memory save error: {e}")

    # ─── Core operations ──────────────────────────────────────────────────────

    def save(
        self,
        key: str,
        content: str,
        source: str = "",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict] = None,
    ) -> MemoryEntry:
        """Save or update a memory entry."""
        with self._lock:
            if key in self._entries:
                entry = self._entries[key]
                entry.content = content
                entry.updated_at = datetime.now().isoformat()
                if tags:
                    entry.tags = list(set(entry.tags + tags))
                if metadata:
                    entry.metadata.update(metadata)
            else:
                # Evict oldest if at capacity
                if len(self._entries) >= self.MAX_ENTRIES:
                    oldest = sorted(
                        self._entries.items(),
                        key=lambda x: x[1].updated_at
                    )[:50]
                    for k, _ in oldest:
                        del self._entries[k]

                entry = MemoryEntry(
                    key=key,
                    content=content,
                    source=source,
                    tags=tags or [],
                    project=self.project,
                    metadata=metadata or {},
                )
                self._entries[key] = entry

            self._save()
            return entry

    def retrieve(self, key: str) -> Optional[MemoryEntry]:
        """Get a specific memory by key."""
        with self._lock:
            entry = self._entries.get(key)
            if entry:
                entry.access_count += 1
            return entry

    def search(self, query: str, limit: int = 10, tags: Optional[List[str]] = None) -> List[Dict]:
        """
        Keyword search across memory entries.
        Optionally filter by tags.
        If OPENAI_API_KEY is set and USE_EMBEDDINGS=true, uses vector similarity.
        """
        if os.getenv("USE_EMBEDDINGS", "").lower() == "true":
            return self._semantic_search(query, limit, tags)
        return self._keyword_search(query, limit, tags)

    def _keyword_search(self, query: str, limit: int, tags: Optional[List[str]]) -> List[Dict]:
        query_lower = query.lower()
        query_words = set(re.split(r"\W+", query_lower))

        results = []
        with self._lock:
            for entry in self._entries.values():
                # Tag filter
                if tags and not any(t in entry.tags for t in tags):
                    continue
                # Score: word overlap in content + key + source
                text = f"{entry.key} {entry.content} {entry.source} {' '.join(entry.tags)}".lower()
                text_words = set(re.split(r"\W+", text))
                score = len(query_words & text_words) / max(len(query_words), 1)
                if score > 0:
                    results.append((score, entry))

        results.sort(key=lambda x: x[0], reverse=True)
        return [
            {**e.to_dict(), "relevance": round(s, 3)}
            for s, e in results[:limit]
        ]

    def _semantic_search(self, query: str, limit: int, tags: Optional[List[str]]) -> List[Dict]:
        """Vector similarity search using OpenAI embeddings."""
        try:
            from openai import OpenAI
            import numpy as np

            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

            # Embed query
            q_resp = client.embeddings.create(model="text-embedding-3-small", input=query)
            q_vec = q_resp.data[0].embedding

            results = []
            with self._lock:
                for entry in self._entries.values():
                    if tags and not any(t in entry.tags for t in tags):
                        continue
                    cached_emb = entry.metadata.get("embedding")
                    if not cached_emb:
                        # Embed on demand
                        try:
                            r = client.embeddings.create(
                                model="text-embedding-3-small",
                                input=entry.content[:2000]
                            )
                            cached_emb = r.data[0].embedding
                            entry.metadata["embedding"] = cached_emb
                        except Exception:
                            continue

                    # Cosine similarity
                    a, b = np.array(q_vec), np.array(cached_emb)
                    score = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
                    results.append((score, entry))

            results.sort(key=lambda x: x[0], reverse=True)
            return [
                {**e.to_dict(), "relevance": round(s, 3)}
                for s, e in results[:limit]
            ]
        except Exception as e:
            logger.error(f"Semantic search failed, falling back to keyword: {e}")
            return self._keyword_search(query, limit, tags)

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._entries:
                del self._entries[key]
                self._save()
                return True
            return False

    def list_all(self, limit: int = 100) -> List[Dict]:
        with self._lock:
            entries = sorted(
                self._entries.values(),
                key=lambda e: e.updated_at,
                reverse=True
            )[:limit]
            return [e.to_dict() for e in entries]

    def get_stats(self) -> Dict:
        with self._lock:
            sources = {}
            for e in self._entries.values():
                sources[e.source] = sources.get(e.source, 0) + 1
            return {
                "total_entries": len(self._entries),
                "project": self.project,
                "top_sources": dict(sorted(sources.items(), key=lambda x: x[1], reverse=True)[:10]),
            }

    def save_bot_output(self, bot_name: str, category: str, content: str, topic: str = ""):
        """Convenience: save a bot's output to memory."""
        key = f"output:{bot_name}:{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.save(
            key=key,
            content=content[:3000],  # truncate for memory
            source=bot_name,
            tags=[category, bot_name, "output"] + ([topic] if topic else []),
            metadata={"bot": bot_name, "category": category, "topic": topic},
        )
        return key

    def save_decision(self, decision: Dict):
        """Store a decision engine decision."""
        key = f"decision:{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.save(
            key=key,
            content=json.dumps(decision),
            source="decision_engine",
            tags=["decision", decision.get("action_type", "")],
            metadata=decision,
        )


# ─── Multi-project store manager ──────────────────────────────────────────────

class MemoryManager:
    """Manages memory stores across multiple projects."""

    def __init__(self):
        self._stores: Dict[str, MemoryStore] = {}
        self._global = self._get_store("global")

    def _get_store(self, project: str) -> MemoryStore:
        if project not in self._stores:
            self._stores[project] = MemoryStore(project)
        return self._stores[project]

    def save(self, key: str, content: str, project: str = "global", **kwargs) -> MemoryEntry:
        return self._get_store(project).save(key, content, **kwargs)

    def retrieve(self, key: str, project: str = "global") -> Optional[MemoryEntry]:
        return self._get_store(project).retrieve(key)

    def search(self, query: str, project: str = "global", limit: int = 10, **kwargs) -> List[Dict]:
        return self._get_store(project).search(query, limit, **kwargs)

    def list_all(self, project: str = "global", limit: int = 100) -> List[Dict]:
        return self._get_store(project).list_all(limit)

    def get_stats(self, project: str = "global") -> Dict:
        return self._get_store(project).get_stats()

    def save_decision(self, decision: Dict):
        """Delegate to the global store's save_decision."""
        self._global.save_decision(decision)

    def list_projects(self) -> List[str]:
        """List all projects that have memory stores."""
        projects = ["global"]
        proj_dir = MEMORY_DIR / "projects"
        if proj_dir.exists():
            projects += [p.stem for p in proj_dir.glob("*.json")]
        return list(set(projects))

    @property
    def global_store(self) -> MemoryStore:
        return self._global


# Singleton
_memory_manager: Optional[MemoryManager] = None


def get_memory() -> MemoryManager:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
