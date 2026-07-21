"""CodeSearchProvider — KAI-owned seam for semantic code search.

The agent/tools/indexer depend only on this interface; the concrete
implementation (PgVectorCodeSearchProvider) lives behind it on KAI's existing
pgvector store, so the backend can be swapped without touching callers.

Design mirrors app/services/router/adapters/base.py:Adapter and
app/services/tools/base.py:Tool (Protocol + dataclasses).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.services.tools.base import ToolContext  # carries user_id (+ session)


@dataclass(slots=True)
class RepoRef:
    """A repo to index: a stable id + one or more root dirs (each must resolve
    under a tenant-allowlisted root — see walker/config)."""
    repo_id: str
    roots: list[str]


@dataclass(slots=True)
class CodeChunk:
    """One AST-aligned (or fallback) code fragment, post-redaction, ready to embed."""
    path: str          # repo-relative path
    lang: str
    symbol: str | None  # def/class/function name if known, else None
    start_line: int    # 1-indexed, inclusive
    end_line: int
    content: str
    content_sha: str   # sha256 of content — idempotency + change detection


@dataclass(slots=True)
class CodeHit:
    """A retrieved chunk with provenance for citation."""
    path: str
    lang: str
    symbol: str | None
    start_line: int
    end_line: int
    content: str
    similarity: float


@dataclass(slots=True)
class IndexResult:
    repo_id: str
    chunks_indexed: int = 0
    files_scanned: int = 0
    files_skipped: int = 0
    secrets_dropped: int = 0
    redactions: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "repo_id": self.repo_id,
            "chunks_indexed": self.chunks_indexed,
            "files_scanned": self.files_scanned,
            "files_skipped": self.files_skipped,
            "secrets_dropped": self.secrets_dropped,
            "redactions": self.redactions,
            "errors": self.errors[:20],
        }


@runtime_checkable
class CodeSearchProvider(Protocol):
    def index_repo(self, ctx: ToolContext, repo: RepoRef) -> IndexResult: ...

    def search(
        self,
        ctx: ToolContext,
        query: str,
        k: int = 8,
        *,
        repo_id: str | None = None,
        lang: str | None = None,
    ) -> list[CodeHit]: ...

    def delete_repo(self, ctx: ToolContext, repo_id: str) -> int: ...
