"""Knowledge Graph MVP — SQLite-backed entity + relation store for KAI.

What this is: a structured store of facts KAI has learned about your world.
Each fact is a triple `(entity, relation, entity)` plus attributes. Think:
    (Jhon, owns, KAI)
    (KAI, uses, Stripe)
    (Stripe, depends_on, STRIPE_WEBHOOK_SECRET)

Why SQLite (defer Neo4j):
  - Zero infra: file at `data/kg/kg.db`, ships with the daemon
  - Adjacency lists in SQL are good enough for the operator's volume
  - Upgrade path to Neo4j later if traversal becomes the bottleneck
  - Backups are `cp` of one file; no service to manage

What this enables (downstream):
  - The `kg_query` tool: KAI can answer "what depends on X?" by traversal
  - Memory injection: when the operator mentions "Stripe" in a prompt,
    KAI surfaces relevant edges + entities as context
  - Operator dashboard: see what KAI has learned

Public API:
    from app.services.kg import (
        add_entity, add_edge, find_entities, neighbors,
        traverse, all_relations,
    )
"""
from app.services.kg.storage import (
    Edge,
    Entity,
    add_edge,
    add_entity,
    all_relations,
    find_entities,
    neighbors,
    traverse,
)

__all__ = [
    "Edge",
    "Entity",
    "add_edge",
    "add_entity",
    "all_relations",
    "find_entities",
    "neighbors",
    "traverse",
]
