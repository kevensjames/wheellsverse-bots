"""infra.brain — canonical AI brain.

Modules:
  router      — multi-model LLM router (litellm) with fast/deep tiers
  memory      — three-layer memory: facts (SQLite), episodes (Chroma), patterns
  rag         — RAG ingest + query over Chroma
  tiers       — tier classifier (fast vs deep)
  resilience  — retry + circuit breakers (tenacity / pybreaker)
  skills      — .md skill-pack loader (packs in skills/)

Heavy optional deps (chromadb, litellm, tenacity) are imported lazily so light
callers can use parts of the brain without the full dep tree installed.
"""
try:
    from .memory import MemoryStore, Fact, Episode  # noqa: F401
except ImportError:
    pass

__all__ = ["MemoryStore", "Fact", "Episode"]
