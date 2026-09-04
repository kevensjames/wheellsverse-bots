"""§56 HoldingSystemGraph — a DYNAMIC typed graph of the holding, built from REAL registries.

This is NOT the hardcoded 8-node topology `kai-nexus-systems.js` renders, and NOT a second
capability graph. It is the §56 holding-level graph over companies/apps/deployments/vendors/
monitors/capabilities/missions/workers, assembled LIVE from the already-authoritative sources
(holding.registry, its §14 hierarchy_edges, the capability registry, holding.mission, holding.status).

Reuse (CONSOLIDATION, not a parallel graph): this mirrors the typed-directed-graph + cycle-safe
traversal PATTERN of `capability/graph.py` (CapabilityGraph). It does not import/duplicate that
graph — that one is the §17 capability-relationship graph keyed on bare capability ids with a fixed
Relation enum; this one needs heterogeneous TYPED nodes carrying provenance. The capability↔capability
relationships stay in `capability/graph.py::seed_graph()`; they are NOT re-derived here.

Zero-fabrication (§0 #16-19 / §58): every node and every edge carries a `provenance` citing the real
source record. An edge is emitted ONLY where real evidence exists — a hierarchy edge whose parent is
not a real registry entity is dropped, never invented. The relation vocabulary (EdgeType) is the full
§56 set; build_graph() emits only the subset the registries actually evidence today (no calls/depends_on/
blocked_by are fabricated — they appear only when a structured source for them exists).

Injectable sources (like digital_twin), each wrapped fail-open: a subsystem that errors contributes
nothing, never a crash. Pure/no-LLM — a plain ``python3`` self-test (mirrors test_registry.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Callable

_ROOT_ID = "wheellsverse_holdings"
# entity_types that render as the graph's top-level "company/app" cards (for the bounded overview view)
_ENTITY_NODE_TYPES = {"holding", "LLC", "company", "product", "project"}


class EdgeType(str, Enum):
    """The §56 typed relation vocabulary. build_graph() emits only relations with real evidence."""
    OWNED_BY = "owned_by"          # child entity → parent entity (holding.registry.hierarchy_edges §14)
    DEPLOYED_AS = "deployed_as"    # entity → deployment / domain node (registry.deployment / .domains)
    USES = "uses"                  # entity → vendor node (registry.integrations)
    MONITORED_BY = "monitored_by"  # entity → monitor node (registry.integrations naming a monitor)
    SUPPORTS = "supports"          # capability/mission/worker → the entity it serves
    DEPENDS_ON = "depends_on"      # reserved — no structured holding-level source today (not fabricated)
    CALLS = "calls"                # reserved — no structured source today (not fabricated)
    BLOCKED_BY = "blocked_by"      # reserved — no structured source today (not fabricated)


@dataclass
class Node:
    id: str
    type: str
    label: str
    provenance: str
    attrs: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Edge:
    src: str
    rel: str
    dst: str
    provenance: str

    def as_dict(self) -> dict:
        return {"src": self.src, "rel": self.rel, "dst": self.dst, "provenance": self.provenance}


def _slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-") or "unknown"


def _vendor_base(s: str) -> str:
    """The vendor name without its parenthetical qualifier: 'OpenAI (prod)' → 'OpenAI'. Mild, honest
    normalization so the same vendor across entities (Stripe on sol + siteboost) merges to one node."""
    return (s or "").split("(", 1)[0].strip() or (s or "").strip()


class SystemGraph:
    """Typed directed graph of holding nodes + provenance-carrying edges. Single edge store (the list
    keeps each edge's provenance); neighbor lookups scan it — bounded at holding scale, no index needed."""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: list[Edge] = []
        self._edge_keys: set[tuple[str, str, str]] = set()

    # ── build primitives ──────────────────────────────────────────────────────────────────────────
    def add_node(self, node_id: str, *, node_type: str, label: str, provenance: str,
                 attrs: dict | None = None) -> None:
        """Idempotent: first write wins for the node; edges carry the per-source provenance that matters."""
        if not node_id or node_id in self._nodes:
            return
        self._nodes[node_id] = Node(id=node_id, type=node_type, label=label or node_id,
                                    provenance=provenance, attrs=attrs or {})

    def add_edge(self, src: str, rel: EdgeType | str, dst: str, *, provenance: str) -> bool:
        """Emit an edge ONLY if BOTH endpoints are real nodes (never a fabricated topology). Deduped.
        Returns True if an edge was added."""
        r = rel.value if isinstance(rel, EdgeType) else str(rel)
        if src not in self._nodes or dst not in self._nodes or src == dst:
            return False
        key = (src, r, dst)
        if key in self._edge_keys:
            return False
        self._edge_keys.add(key)
        self._edges.append(Edge(src=src, rel=r, dst=dst, provenance=provenance))
        return True

    # ── queries ───────────────────────────────────────────────────────────────────────────────────
    def nodes(self) -> list[dict]:
        return [n.as_dict() for n in self._nodes.values()]

    def edges(self) -> list[dict]:
        return [e.as_dict() for e in self._edges]

    def related(self, node_id: str, rel: EdgeType | str | None = None) -> list[str]:
        r = rel.value if isinstance(rel, EdgeType) else (str(rel) if rel is not None else None)
        return [e.dst for e in self._edges if e.src == node_id and (r is None or e.rel == r)]

    def summary(self) -> dict:
        nby: dict[str, int] = {}
        for n in self._nodes.values():
            nby[n.type] = nby.get(n.type, 0) + 1
        eby: dict[str, int] = {}
        for e in self._edges:
            eby[e.rel] = eby.get(e.rel, 0) + 1
        return {"nodes_total": len(self._nodes), "edges_total": len(self._edges),
                "nodes_by_type": dict(sorted(nby.items())), "edges_by_type": dict(sorted(eby.items()))}

    # ── §56 BOUNDED VIEW (selective — never a giant unreadable dump) ─────────────────────────────────
    def view(self, *, focus: str | None = None, depth: int = 1, max_nodes: int = 60,
             node_types: set[str] | None = None, edge_types: set[str] | None = None) -> dict:
        """No focus → a bounded STRUCTURAL overview: the entity nodes + the §14 owned_by hierarchy +
        type counts (not the full capability/mission fan-out). With a focus node → its cycle-safe
        neighborhood BFS to `depth`, capped at `max_nodes`. `truncated` says when the cap clipped it."""
        if focus is None:
            ents = [n for n in self._nodes.values() if n.type in _ENTITY_NODE_TYPES]
            kept = ents[:max_nodes]
            kept_ids = {n.id for n in kept}
            edges = [e for e in self._edges
                     if e.rel == EdgeType.OWNED_BY.value and e.src in kept_ids and e.dst in kept_ids]
            return {"focus": None, "scope": "overview",
                    "nodes": [n.as_dict() for n in kept], "edges": [e.as_dict() for e in edges],
                    "truncated": len(ents) > max_nodes, "summary": self.summary()}

        if focus not in self._nodes:
            return {"focus": focus, "scope": "neighborhood", "error": "unknown node",
                    "nodes": [], "edges": [], "truncated": False}

        et = edge_types
        edges = [e for e in self._edges if et is None or e.rel in et]
        visited: set[str] = {focus}          # cycle-safe (mirrors capability/graph.requires_closure guard)
        frontier: set[str] = {focus}
        for _ in range(max(0, depth)):        # expand ONLY from the current frontier — honours depth exactly
            nxt: set[str] = set()
            for e in edges:
                for a, b in ((e.src, e.dst), (e.dst, e.src)):
                    if a in frontier and b not in visited:
                        if len(visited) >= max_nodes:
                            continue             # cap reached — do not pull in new nodes
                        visited.add(b)
                        nxt.add(b)
            frontier = nxt
            if not frontier:
                break
        nodes = [self._nodes[n].as_dict() for n in visited
                 if node_types is None or self._nodes[n].type in node_types]
        node_ids = {n["id"] for n in nodes}
        # show every edge fully inside the returned neighborhood (dedup already guaranteed by add_edge)
        kept_edges = [e for e in edges if e.src in node_ids and e.dst in node_ids]
        return {"focus": focus, "scope": f"neighborhood(depth={depth})",
                "nodes": nodes, "edges": [e.as_dict() for e in kept_edges],
                "truncated": len(visited) >= max_nodes,
                "count": {"nodes": len(nodes), "edges": len(kept_edges)}}


# ── default live sources (fail-open, injectable — mirrors digital_twin._DEFAULT_SOURCES) ─────────────
def _src_entities() -> list:
    from app.services.holding import registry as reg
    return reg.all_entities()


def _src_hierarchy() -> list:
    from app.services.holding import registry as reg
    return reg.hierarchy_edges()


def _src_capabilities() -> list:
    """AVAILABLE (real, runnable) capabilities only — the operational shared resources, not the dormant
    126-entry discovery catalog. Bounded + honest."""
    from app.services.capability.seed import seed_registry
    from app.services.capability.manifest import Availability
    reg = seed_registry()
    return [{"id": m.id, "name": m.name} for m in reg.list(availability=Availability.AVAILABLE)]


def _src_missions() -> list:
    from app.services.holding.mission import list_missions
    return list_missions(limit=100)


def _src_workers() -> list:
    from app.services.holding.status import list_workers
    return list_workers()


_DEFAULT_SOURCES: dict[str, Callable] = {
    "entities": _src_entities, "hierarchy": _src_hierarchy, "capabilities": _src_capabilities,
    "missions": _src_missions, "workers": _src_workers,
}


def _safe(sources: dict, name: str, default: Any) -> Any:
    fn = sources.get(name)
    if fn is None:
        return default
    try:
        v = fn()
        return v if v is not None else default
    except Exception:            # a failing subsystem contributes nothing — never a crash, never a guess
        return default


def build_graph(sources: dict[str, Callable] | None = None) -> SystemGraph:
    """Assemble the §56 graph from real registries. Every node/edge carries provenance; an edge is
    emitted only where both endpoints are real nodes (add_edge enforces it). Fail-open per source."""
    src = {**_DEFAULT_SOURCES, **(sources or {})}
    g = SystemGraph()

    known: set[str] = set()
    for e in _safe(src, "entities", []):
        eid = getattr(e, "entity_id", None)
        if not eid:
            continue
        known.add(eid)
        etype = getattr(e, "entity_type", "unknown") or "unknown"
        g.add_node(f"entity:{eid}", node_type=etype, label=getattr(e, "brand_name", eid),
                   provenance="holding.registry",
                   attrs={"entity_id": eid, "entity_type": etype,
                          "status": getattr(e, "operational_status", "") or "",
                          "stage": getattr(e, "stage", "") or "",
                          "repository": getattr(e, "repository", "") or ""})
        # deployed_as → deployment node (per-entity freeform deployment fact)
        dep = getattr(e, "deployment", None)
        if dep:
            dn = f"deployment:{eid}"
            g.add_node(dn, node_type="deployment", label=dep, provenance=f"holding.registry:{eid}.deployment")
            g.add_edge(f"entity:{eid}", EdgeType.DEPLOYED_AS, dn, provenance=f"holding.registry:{eid}.deployment")
        # deployed_as → domain nodes (domains are clean shared identifiers)
        for d in (getattr(e, "domains", []) or []):
            dom = f"domain:{_slug(d)}"
            g.add_node(dom, node_type="domain", label=d, provenance=f"holding.registry:{eid}.domains")
            g.add_edge(f"entity:{eid}", EdgeType.DEPLOYED_AS, dom, provenance=f"holding.registry:{eid}.domains")
        # uses → vendor / monitored_by → monitor  (from integrations)
        for ig in (getattr(e, "integrations", []) or []):
            base = _vendor_base(ig)
            # ponytail: keyword classify — the integration string LITERALLY names a monitor, not a guess.
            if any(k in ig.lower() for k in ("monitor", "observability")):
                mn = f"monitor:{_slug(base)}"
                g.add_node(mn, node_type="monitor", label=base, provenance=f"holding.registry:{eid}.integrations")
                g.add_edge(f"entity:{eid}", EdgeType.MONITORED_BY, mn,
                           provenance=f"holding.registry:{eid}.integrations[{ig}]")
            else:
                vn = f"vendor:{_slug(base)}"
                g.add_node(vn, node_type="vendor", label=base, provenance=f"holding.registry:{eid}.integrations")
                g.add_edge(f"entity:{eid}", EdgeType.USES, vn,
                           provenance=f"holding.registry:{eid}.integrations[{ig}]")

    # §14 owned_by — child owned_by parent, ONLY between real registry entities (no fabricated node)
    for h in _safe(src, "hierarchy", []):
        parent, child = h.get("parent"), h.get("child")
        if parent in known and child in known:
            g.add_edge(f"entity:{child}", EdgeType.OWNED_BY, f"entity:{parent}",
                       provenance=f"holding.registry.hierarchy_edges({h.get('relation', 'owns')})")

    root = f"entity:{_ROOT_ID}" if _ROOT_ID in known else None

    # capabilities → supports holding root (available shared resources)
    for c in _safe(src, "capabilities", []):
        cid = c.get("id") if isinstance(c, dict) else getattr(c, "id", None)
        if not cid:
            continue
        cn = f"capability:{cid}"
        g.add_node(cn, node_type="capability", label=(c.get("name") if isinstance(c, dict) else cid) or cid,
                   provenance="capability.registry(AVAILABLE)")
        if root:
            g.add_edge(cn, EdgeType.SUPPORTS, root, provenance="capability.registry(AVAILABLE)")

    # missions → supports the company they serve (else holding-level → root)
    for m in _safe(src, "missions", []):
        mid = m.get("mission_id") if isinstance(m, dict) else None
        if not mid:
            continue
        mn = f"mission:{mid}"
        g.add_node(mn, node_type="mission", label=m.get("objective") or mid,
                   provenance=f"holding.mission:{mid}",
                   attrs={"origin": m.get("origin"), "company": m.get("company"),
                          "authority_level": m.get("authority_level")})
        comp = m.get("company")
        if comp and f"entity:{comp}" in g._nodes:
            g.add_edge(mn, EdgeType.SUPPORTS, f"entity:{comp}", provenance=f"holding.mission:{mid}.company")
        elif root:
            g.add_edge(mn, EdgeType.SUPPORTS, root, provenance=f"holding.mission:{mid}(holding-level)")

    # workers → supports holding root (work plane)
    for w in _safe(src, "workers", []):
        wid = w.get("worker_id") if isinstance(w, dict) else None
        if not wid:
            continue
        wn = f"worker:{_slug(wid)}"
        g.add_node(wn, node_type="worker", label=wid, provenance="holding.status.list_workers",
                   attrs={"online": w.get("online")})
        if root:
            g.add_edge(wn, EdgeType.SUPPORTS, root, provenance="holding.status.list_workers")

    return g


if __name__ == "__main__":
    from app.services.holding.test_system_graph import run
    raise SystemExit(0 if run() else 1)
