"""KAI Capability Fabric — the capability relationship graph (§17, §60, §61).

A typed directed graph over capability ids. The Brain uses it to resolve dependencies
(REQUIRES closure), avoid running conflicting capabilities together (CONFLICTS_WITH),
choose among interchangeable ones (ALTERNATIVE_TO), and pick a fallback when one fails
(FALLBACK_FOR). Symmetric relations (CONFLICTS_WITH / ALTERNATIVE_TO) are stored both ways
so a query from either side is consistent.

Pure stdlib; testable as a plain ``python3`` script.
"""
from __future__ import annotations

from enum import Enum


class Relation(str, Enum):
    REQUIRES = "REQUIRES"
    HELPS = "HELPS"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    FALLBACK_FOR = "FALLBACK_FOR"
    ALTERNATIVE_TO = "ALTERNATIVE_TO"
    PRODUCES = "PRODUCES"
    CONSUMES = "CONSUMES"


_SYMMETRIC = {Relation.CONFLICTS_WITH, Relation.ALTERNATIVE_TO}


class CapabilityGraph:
    def __init__(self) -> None:
        # relation -> {src -> set(dst)}
        self._edges: dict[Relation, dict[str, set[str]]] = {r: {} for r in Relation}

    def add(self, src: str, relation: Relation, dst: str) -> None:
        self._edges[relation].setdefault(src, set()).add(dst)
        if relation in _SYMMETRIC:
            self._edges[relation].setdefault(dst, set()).add(src)

    def related(self, src: str, relation: Relation) -> set[str]:
        return set(self._edges[relation].get(src, set()))

    # ── dependency resolution (§60) — transitive REQUIRES with cycle protection ──
    def requires_closure(self, cap_id: str) -> list[str]:
        """All capabilities that must be present, in dependency-first order.

        Raises ValueError on a dependency cycle (a cascading runtime surprise must fail
        at plan time, not at activation time).
        """
        order: list[str] = []
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(node: str) -> None:
            if node in done:
                return
            if node in visiting:
                raise ValueError(f"dependency cycle through {node!r}")
            visiting.add(node)
            for dep in sorted(self._edges[Relation.REQUIRES].get(node, set())):
                visit(dep)
            visiting.discard(node)
            done.add(node)
            if node != cap_id:
                order.append(node)

        visit(cap_id)
        return order

    def conflicts_with(self, cap_id: str) -> set[str]:
        return self.related(cap_id, Relation.CONFLICTS_WITH)

    def alternatives(self, cap_id: str) -> set[str]:
        return self.related(cap_id, Relation.ALTERNATIVE_TO)

    def fallbacks_for(self, cap_id: str) -> set[str]:
        """Capabilities declared FALLBACK_FOR cap_id (use when cap_id is unavailable/failed)."""
        return {src for src, dsts in self._edges[Relation.FALLBACK_FOR].items() if cap_id in dsts}

    def any_conflict(self, cap_ids: list[str]) -> tuple[str, str] | None:
        """Return the first conflicting pair in a proposed set, or None (§61)."""
        s = set(cap_ids)
        for cid in cap_ids:
            clash = self.conflicts_with(cid) & s
            if clash:
                return (cid, sorted(clash)[0])
        return None
