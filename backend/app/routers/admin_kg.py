"""Knowledge Graph admin endpoints — read-side surface for the operator
dashboard.

Three endpoints, mirror the three query actions on the kg_query tool:
  GET /admin/kg/stats              entity + edge counts, distinct relations
  GET /admin/kg/search?q=...       entity search by label substring
  GET /admin/kg/neighbors?label=…  edges adjacent to an entity
  POST /admin/kg/add-edge          manually add a triple (operator
                                    teaches KAI directly)

The add-edge endpoint is the only write path; it's @audited as
destructive=True so the operator confirms before the daemon writes
to the KG.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.dependencies.admin import require_admin_token
from app.services.governance import PendingApproval, ScopeDenied, audited
from app.services.kg import (
    add_edge as _add_edge,
    all_relations,
    count_entities,
    find_entities,
    neighbors,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/kg",
    tags=["admin"],
    dependencies=[Depends(require_admin_token)],
)


@router.get("/stats")
def kg_stats() -> dict[str, Any]:
    """Cheap counters for the admin panel header. Doesn't dump the graph."""
    relations = all_relations()
    return {
        "entity_count": count_entities(),  # exact COUNT(*), no longer capped at 500
        "relation_count_distinct": len(relations),
        "edge_count_by_relation": [
            {"relation": r, "count": n} for r, n in relations
        ],
    }


@router.get("/search")
def kg_search(q: str = "", type: str | None = None, limit: int = 50):
    rows = find_entities(label_contains=q or None, type=type, limit=limit)
    return {
        "query": q,
        "type": type,
        "count": len(rows),
        "entities": [
            {
                "label": e.label,
                "type": e.type,
                "attributes": e.attributes,
                "updated_at": e.updated_at,
            }
            for e in rows
        ],
    }


@router.get("/neighbors")
def kg_neighbors(
    label: str,
    direction: str = "out",
    relation: str | None = None,
    limit: int = 50,
):
    try:
        edges = neighbors(label, direction=direction, relation=relation, limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "entity": label,
        "direction": direction,
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


class AddEdgeRequest(BaseModel):
    src: str
    relation: str
    dst: str
    src_type: str = "other"
    dst_type: str = "other"
    attributes: dict[str, Any] | None = None
    approved: bool = False   # required for the @audited destructive guard


@audited(scope="kg.add_edge", destructive=True)
def _audited_add_edge(payload: AddEdgeRequest):
    edge = _add_edge(
        src_label=payload.src,
        relation=payload.relation,
        dst_label=payload.dst,
        src_type=payload.src_type,
        dst_type=payload.dst_type,
        attributes=payload.attributes,
    )
    return {
        "edge_id": edge.id,
        "triple": list(edge.as_triple()),
    }


@router.post("/add-edge")
def kg_add_edge(body: AddEdgeRequest):
    """Operator manually teaches KAI a triple. Goes through @audited with
    destructive=True; the caller must include approved=true to actually
    apply the write."""
    try:
        return _audited_add_edge(body, approved=body.approved)
    except ScopeDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    except PendingApproval as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
