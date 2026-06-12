"""KG query tool — lets KAI (via the tool loop) query the knowledge graph
from inside a chat turn.

Three actions, exposed as one tool with an `action` parameter:
  search    — find entities matching a label substring (+ optional type)
  neighbors — list edges adjacent to a named entity
  triples   — BFS traversal from an entity, returning textual triples

We picked one-tool-many-actions over three-tools so the LLM doesn't have
to learn the difference between three nearly-identical names. The
`action` enum is small and self-documenting via the description.
"""
from __future__ import annotations

import logging
from typing import Any

from app.services.kg import find_entities, neighbors, traverse
from app.services.tools.base import ToolContext, ToolError

logger = logging.getLogger(__name__)


class KGQueryTool:
    name = "kg_query"
    description = (
        "Query KAI's knowledge graph — a store of facts the operator has "
        "taught KAI about their world (e.g. 'Jhon owns KAI', 'KAI uses "
        "Stripe', 'Stripe depends_on STRIPE_WEBHOOK_SECRET'). Pick one "
        "action:\n"
        "  search    — list entities whose label matches a substring "
        "(use first when you don't know the exact label).\n"
        "  neighbors — list edges adjacent to a specific entity (use to "
        "see what an entity 'owns', 'uses', 'depends_on', etc.).\n"
        "  triples   — multi-hop BFS from an entity, returning ('A', "
        "'relation', 'B') strings (use to explore a subgraph)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "neighbors", "triples"],
                "description": "Which query to run.",
            },
            "query": {
                "type": "string",
                "description": (
                    "search: label substring to find entities matching. "
                    "neighbors/triples: exact (case-insensitive) entity "
                    "label to start from."
                ),
            },
            "type": {
                "type": "string",
                "description": (
                    "search only — optional type filter "
                    "(person/product/company/service/concept/event/other)."
                ),
            },
            "direction": {
                "type": "string",
                "enum": ["out", "in", "both"],
                "description": (
                    "neighbors only — out: edges where this entity is "
                    "source; in: where it's destination; both: both. "
                    "Default 'out'."
                ),
            },
            "relation": {
                "type": "string",
                "description": (
                    "neighbors only — optional relation filter "
                    "(e.g. 'owns', 'uses', 'depends_on')."
                ),
            },
            "max_depth": {
                "type": "integer",
                "description": (
                    "triples only — how many hops to BFS. Default 2. "
                    "Hard cap 5."
                ),
            },
            "limit": {
                "type": "integer",
                "description": "Max rows to return. Default 25.",
            },
        },
        "required": ["action", "query"],
    }

    def execute(self, ctx: ToolContext, **kwargs: Any) -> dict[str, Any]:
        action = (kwargs.get("action") or "").strip().lower()
        query = (kwargs.get("query") or "").strip()
        limit = int(kwargs.get("limit") or 25)

        if not action:
            raise ToolError("action is required")
        if not query:
            raise ToolError("query is required")

        if action == "search":
            rows = find_entities(
                label_contains=query,
                type=kwargs.get("type"),
                limit=limit,
            )
            return {
                "action": "search",
                "count": len(rows),
                "entities": [
                    {
                        "label": e.label,
                        "type": e.type,
                        "attributes": e.attributes,
                    }
                    for e in rows
                ],
            }

        if action == "neighbors":
            edges = neighbors(
                query,
                direction=(kwargs.get("direction") or "out").lower(),
                relation=kwargs.get("relation"),
                limit=limit,
            )
            return {
                "action": "neighbors",
                "entity": query,
                "count": len(edges),
                "edges": [
                    {
                        "src": e.src.label,
                        "relation": e.relation,
                        "dst": e.dst.label,
                        "attributes": e.attributes,
                    }
                    for e in edges
                ],
            }

        if action == "triples":
            edges = traverse(
                query,
                max_depth=int(kwargs.get("max_depth") or 2),
                max_edges=limit,
            )
            return {
                "action": "triples",
                "start": query,
                "count": len(edges),
                "triples": [
                    " — ".join(e.as_triple()) for e in edges
                ],
            }

        raise ToolError(f"unknown action {action!r}; use search|neighbors|triples")
