"""document_search — let KAI query the user's INDEXED documents (the RAG
knowledge base) mid-conversation and get back cited excerpts.

This is the proposal's "Agent → search the vector DB → retrieve relevant
passages → answer with citations" step. Domain agents (medical, legal,
engineering, accounting, …) call it to GROUND answers in the user's own uploaded
references instead of model memory. Read-only; reuses services/rag (pgvector
top-k). Returns each passage with its source filename + chunk position so the
agent can cite it, and a relevance score (1 - cosine distance).
"""
from __future__ import annotations

from typing import Any

from app.services.tools.base import ToolContext, ToolError


class DocumentSearchTool:
    name = "document_search"
    description = (
        "Semantic search over the user's uploaded/indexed documents (their "
        "knowledge base). Returns the most relevant passages with their source "
        "filename + position so you can CITE them. Use this to ground answers "
        "in the user's own documents (papers, standards, manuals, contracts, "
        "policies) instead of relying on memory. Cite passages you use as "
        "[source: <filename> #<position>]. Returns no passages if nothing is "
        "indexed yet."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to look for — a question or topic.",
            },
            "k": {
                "type": "integer",
                "description": "Max passages to return. Default 5, max 12.",
            },
        },
        "required": ["query"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        query = (kwargs.get("query") or "").strip()
        if not query:
            raise ToolError("query is required")
        k = max(1, min(int(kwargs.get("k") or 5), 12))
        if getattr(ctx, "session", None) is None or getattr(ctx, "user_id", None) is None:
            raise ToolError("document_search needs an authenticated user session")
        try:
            from app.services import rag
            chunks = rag.retrieve(ctx.session, user_id=ctx.user_id, query=query, k=k)
        except Exception as e:
            raise ToolError(f"document search failed: {e}")
        passages = [
            {
                "source": c["filename"],
                "position": c["position"],
                "relevance": round(1.0 - float(c["distance"]), 3),
                "excerpt": c["content"],
            }
            for c in chunks
        ]
        return {
            "query": query,
            "count": len(passages),
            "passages": passages,
            "note": (
                "Cite each passage you use as [source: <filename> #<position>]."
                if passages
                else "No indexed documents matched — the user may not have uploaded any yet."
            ),
        }
