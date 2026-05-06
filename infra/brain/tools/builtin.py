"""infra.brain.tools.builtin — bundled demo tools.

These are mock implementations that are safe to ship: no network calls, no
side effects. They exist so the tool layer can be exercised end-to-end
without external dependencies. Production deployments should ``replace()``
them with real implementations against the same names.

The names match the policy whitelist in ``infra.brain.policy.SAFE_TOOLS``,
so registering these makes the NAI policy immediately useful.
"""
from __future__ import annotations

from typing import Any

from ..policy import CAPABILITY_NETWORK, CAPABILITY_READ_ONLY
from .registry import Tool, register


# ── Demo: web_search ─────────────────────────────────────────────────────────


async def _web_search(input: dict) -> dict:
    """Mock web-search: returns deterministic stub results.

    Input shape: ``{"query": str, "n": int (optional, default 3)}``.
    """
    query = str(input.get("query", "")).strip()
    if not query:
        raise ValueError("web_search requires a non-empty 'query'")
    n = max(1, min(int(input.get("n", 3)), 10))
    return {
        "query": query,
        "results": [
            {
                "title": f"Mock result {i + 1} for {query!r}",
                "url": f"https://example.com/search?q={query}&r={i + 1}",
                "snippet": f"This is a stub snippet #{i + 1} for the query {query!r}.",
            }
            for i in range(n)
        ],
    }


WEB_SEARCH_TOOL = Tool(
    name="web_search",
    description=(
        "Search the web for pages relevant to a query. Use when the answer "
        "depends on current public information you don't already know."
    ),
    run=_web_search,
    schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query, in plain natural language.",
            },
            "n": {
                "type": "integer",
                "description": "How many results to return (1–10).",
                "minimum": 1,
                "maximum": 10,
                "default": 3,
            },
        },
        "required": ["query"],
    },
    # Real web search would be (read_only, network); the mock is local-only
    # but we declare the *intended* capability set so policy gating exercises
    # the realistic path.
    capabilities=frozenset({CAPABILITY_READ_ONLY, CAPABILITY_NETWORK}),
)


# ── Registration helper ──────────────────────────────────────────────────────


def register_demo_tools() -> None:
    """Register every bundled demo tool in the default registry.

    Idempotent: if a tool is already registered it is replaced. Call this
    once at process start (or from tests) to make the demos available.
    """
    from .registry import default_registry
    reg = default_registry()
    reg.replace(WEB_SEARCH_TOOL)


__all__ = ["WEB_SEARCH_TOOL", "register_demo_tools"]
