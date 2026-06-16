"""NarAI memory engine — public API surface.

The runtime implementation lives at ``backend/app/services/memory/`` to keep
Alembic, the ``users`` FK, and the existing pytest fixtures co-located. This
package re-exports that API under the locked Stage 0 namespace so consumers
import from ``services.narai.memory`` regardless of where the code currently
sits. When NarAI is lifted into its own deployable in Phase B, only this shim
moves; call-sites stay stable.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make ``app.*`` importable when the engine is consumed from outside backend/.
_BACKEND = Path(__file__).resolve().parents[3] / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.models.memory import EMBEDDING_DIMENSIONS, MEMORY_TYPES, Memory  # noqa: E402
from app.services.memory import (  # noqa: E402
    DEFAULT_K,
    MemoryStoreError,
    RECENCY_WEIGHT,
    RetrievedMemory,
    SIMILARITY_WEIGHT,
    add_memories_bulk,
    add_memory,
    count_memories,
    delete_memory,
    embed_many,
    embed_one,
    format_for_prompt,
    get_memory,
    search_memories,
)

__all__ = [
    "DEFAULT_K",
    "EMBEDDING_DIMENSIONS",
    "MEMORY_TYPES",
    "Memory",
    "MemoryStoreError",
    "RECENCY_WEIGHT",
    "RetrievedMemory",
    "SIMILARITY_WEIGHT",
    "add_memories_bulk",
    "add_memory",
    "count_memories",
    "delete_memory",
    "embed_many",
    "embed_one",
    "format_for_prompt",
    "get_memory",
    "search_memories",
]
