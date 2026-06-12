"""Knowledge Graph storage — SQLite over a single .db file.

Schema:
  entities:
    id          INTEGER PK
    label       TEXT    NOT NULL UNIQUE — canonical name ("Jhon", "KAI", "Stripe")
    type        TEXT    NOT NULL       — bucket: person / product / company / service / concept / event / other
    attributes  TEXT (JSON)            — free-form props
    created_at  TEXT                   — ISO-8601 UTC
    updated_at  TEXT                   — ISO-8601 UTC

  edges:
    id          INTEGER PK
    src_id      INTEGER NOT NULL  → entities(id)
    dst_id      INTEGER NOT NULL  → entities(id)
    relation    TEXT    NOT NULL  ("owns" / "uses" / "depends_on" / ...)
    attributes  TEXT (JSON)
    created_at  TEXT
    UNIQUE(src_id, dst_id, relation)  — same triple = same edge

Indexes on src_id / dst_id / relation for the two traversal patterns
(forward neighbors + backward neighbors).

Concurrency: SQLite serializes writes within one connection. The daemon
is single-process / single-worker so one connection is enough. We open
fresh connections per call (cheap with WAL); if call rate becomes a
bottleneck, switch to a connection pool.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

# Repo root = .../wheellsverse_bots/. Walk up from this file:
# backend/app/services/kg/storage.py → backend/app/services/kg → backend/app/services → backend/app → backend → REPO
_REPO_ROOT = Path(__file__).resolve().parents[4]

KG_DB_PATH = Path(
    os.environ.get("KAI_KG_DB_PATH", str(_REPO_ROOT / "data" / "kg" / "kg.db"))
)
KG_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


# ─── data models ─────────────────────────────────────────────────────


@dataclass(slots=True)
class Entity:
    id: int
    label: str
    type: str
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


@dataclass(slots=True)
class Edge:
    id: int
    src: Entity
    dst: Entity
    relation: str
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None

    def as_triple(self) -> tuple[str, str, str]:
        """Cheap textual form: ('Jhon', 'owns', 'KAI'). Useful for
        dumping to the LLM context."""
        return (self.src.label, self.relation, self.dst.label)


# ─── schema bootstrap ────────────────────────────────────────────────


_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    type        TEXT    NOT NULL,
    attributes  TEXT    NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type);

CREATE TABLE IF NOT EXISTS edges (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    src_id      INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    dst_id      INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relation    TEXT    NOT NULL,
    attributes  TEXT    NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL,
    UNIQUE(src_id, dst_id, relation)
);

CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextlib.contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    """Open a connection with WAL + foreign keys enabled. Auto-commits on
    successful exit, rolls back on exception."""
    c = sqlite3.connect(str(KG_DB_PATH), isolation_level=None)  # autocommit, explicit txn
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        c.executescript(_SCHEMA)
        yield c
    finally:
        c.close()


# ─── write side ──────────────────────────────────────────────────────


def add_entity(
    label: str,
    type: str,
    attributes: dict[str, Any] | None = None,
) -> Entity:
    """Upsert an entity by label (case-insensitive). Returns the resulting
    row. If an entity with this label already exists, type stays whatever
    it was first set to and attributes are MERGED (incoming overrides)."""
    label = (label or "").strip()
    type = (type or "other").strip().lower()
    if not label:
        raise ValueError("entity label cannot be empty")
    attrs = attributes or {}
    now = _now()
    with _conn() as c:
        existing = c.execute(
            "SELECT id, label, type, attributes, created_at, updated_at "
            "FROM entities WHERE label = ?",
            (label,),
        ).fetchone()
        if existing is not None:
            merged = json.loads(existing["attributes"])
            merged.update(attrs)
            c.execute(
                "UPDATE entities SET attributes = ?, updated_at = ? WHERE id = ?",
                (json.dumps(merged, default=str), now, existing["id"]),
            )
            return Entity(
                id=existing["id"], label=existing["label"], type=existing["type"],
                attributes=merged, created_at=existing["created_at"], updated_at=now,
            )
        cur = c.execute(
            "INSERT INTO entities (label, type, attributes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (label, type, json.dumps(attrs, default=str), now, now),
        )
        eid = cur.lastrowid
        return Entity(
            id=eid, label=label, type=type, attributes=attrs,
            created_at=now, updated_at=now,
        )


def add_edge(
    src_label: str,
    relation: str,
    dst_label: str,
    *,
    src_type: str = "other",
    dst_type: str = "other",
    attributes: dict[str, Any] | None = None,
) -> Edge:
    """Add a triple (src --relation--> dst). Both entities are upserted
    by label first. If the edge already exists, attributes are merged."""
    relation = (relation or "").strip().lower().replace(" ", "_")
    if not relation:
        raise ValueError("relation cannot be empty")
    src = add_entity(src_label, src_type)
    dst = add_entity(dst_label, dst_type)
    attrs = attributes or {}
    now = _now()
    with _conn() as c:
        existing = c.execute(
            "SELECT id, attributes FROM edges "
            "WHERE src_id = ? AND dst_id = ? AND relation = ?",
            (src.id, dst.id, relation),
        ).fetchone()
        if existing is not None:
            merged = json.loads(existing["attributes"])
            merged.update(attrs)
            c.execute(
                "UPDATE edges SET attributes = ? WHERE id = ?",
                (json.dumps(merged, default=str), existing["id"]),
            )
            return Edge(
                id=existing["id"], src=src, dst=dst, relation=relation,
                attributes=merged, created_at=now,
            )
        cur = c.execute(
            "INSERT INTO edges (src_id, dst_id, relation, attributes, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (src.id, dst.id, relation, json.dumps(attrs, default=str), now),
        )
        return Edge(
            id=cur.lastrowid, src=src, dst=dst, relation=relation,
            attributes=attrs, created_at=now,
        )


# ─── read side ───────────────────────────────────────────────────────


def find_entities(
    *,
    label_contains: str | None = None,
    type: str | None = None,
    limit: int = 50,
) -> list[Entity]:
    """Search entities by label substring + optional type filter.

    Both filters are optional. With nothing set, returns the most-recently
    updated entities first, capped at `limit`.
    """
    where: list[str] = []
    params: list[Any] = []
    if label_contains:
        where.append("label LIKE ?")
        params.append(f"%{label_contains.strip()}%")
    if type:
        where.append("type = ?")
        params.append(type.strip().lower())
    sql = (
        "SELECT id, label, type, attributes, created_at, updated_at "
        "FROM entities"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))

    out: list[Entity] = []
    with _conn() as c:
        for row in c.execute(sql, tuple(params)):
            out.append(_row_to_entity(row))
    return out


def neighbors(
    label: str,
    *,
    direction: str = "out",
    relation: str | None = None,
    limit: int = 50,
) -> list[Edge]:
    """Edges adjacent to the entity matching `label` (exact, case-insensitive).

    direction: "out" → edges where this entity is the source.
               "in"  → edges where this entity is the destination.
               "both"→ both directions (output not deduped).
    relation:  optional filter on the edge's relation.
    """
    label = (label or "").strip()
    if not label:
        return []
    if direction not in ("out", "in", "both"):
        raise ValueError(f"direction must be out|in|both, got {direction!r}")
    out: list[Edge] = []
    with _conn() as c:
        ent = c.execute(
            "SELECT id, label, type, attributes, created_at, updated_at "
            "FROM entities WHERE label = ?",
            (label,),
        ).fetchone()
        if ent is None:
            return []
        eid = ent["id"]

        if direction in ("out", "both"):
            for row in _query_edges(c, src_id=eid, relation=relation, limit=limit):
                out.append(row)
        if direction in ("in", "both"):
            for row in _query_edges(c, dst_id=eid, relation=relation, limit=limit):
                out.append(row)
    return out[:limit]


def traverse(
    start_label: str,
    *,
    max_depth: int = 2,
    max_edges: int = 50,
) -> list[Edge]:
    """BFS from start_label outward up to max_depth hops.

    Returns the edges visited in BFS order, capped at max_edges. Visited
    entities are tracked so cycles don't blow up the budget.
    """
    start_label = (start_label or "").strip()
    if not start_label:
        return []
    max_depth = max(1, min(int(max_depth), 5))
    max_edges = max(1, min(int(max_edges), 500))

    seen_entities: set[int] = set()
    seen_edges: set[int] = set()
    out: list[Edge] = []
    with _conn() as c:
        start = c.execute(
            "SELECT id FROM entities WHERE label = ?",
            (start_label,),
        ).fetchone()
        if start is None:
            return []
        frontier = [start["id"]]
        seen_entities.add(start["id"])

        for _depth in range(max_depth):
            next_frontier: list[int] = []
            for eid in frontier:
                if len(out) >= max_edges:
                    return out
                for edge in _query_edges(c, src_id=eid, relation=None, limit=max_edges):
                    if edge.id in seen_edges:
                        continue
                    seen_edges.add(edge.id)
                    out.append(edge)
                    if len(out) >= max_edges:
                        return out
                    if edge.dst.id not in seen_entities:
                        seen_entities.add(edge.dst.id)
                        next_frontier.append(edge.dst.id)
            frontier = next_frontier
            if not frontier:
                break
    return out


def all_relations() -> list[tuple[str, int]]:
    """Distinct edge relations with their counts. Useful for the admin
    panel to show what relations the KG knows about."""
    with _conn() as c:
        return [
            (r["relation"], r["n"])
            for r in c.execute(
                "SELECT relation, COUNT(*) AS n FROM edges GROUP BY relation "
                "ORDER BY n DESC"
            )
        ]


# ─── helpers ─────────────────────────────────────────────────────────


def _query_edges(
    c: sqlite3.Connection,
    *,
    src_id: int | None = None,
    dst_id: int | None = None,
    relation: str | None,
    limit: int,
) -> Iterator[Edge]:
    where: list[str] = []
    params: list[Any] = []
    if src_id is not None:
        where.append("e.src_id = ?")
        params.append(src_id)
    if dst_id is not None:
        where.append("e.dst_id = ?")
        params.append(dst_id)
    if relation:
        where.append("e.relation = ?")
        params.append(relation.strip().lower())
    sql = """
        SELECT
            e.id           AS edge_id,
            e.relation     AS relation,
            e.attributes   AS edge_attrs,
            e.created_at   AS edge_created,
            s.id           AS s_id, s.label AS s_label, s.type AS s_type,
            s.attributes   AS s_attrs, s.created_at AS s_created, s.updated_at AS s_updated,
            d.id           AS d_id, d.label AS d_label, d.type AS d_type,
            d.attributes   AS d_attrs, d.created_at AS d_created, d.updated_at AS d_updated
        FROM edges AS e
        JOIN entities AS s ON s.id = e.src_id
        JOIN entities AS d ON d.id = e.dst_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY e.id DESC LIMIT ?"
    params.append(limit)

    for row in c.execute(sql, tuple(params)):
        yield Edge(
            id=row["edge_id"],
            src=Entity(
                id=row["s_id"], label=row["s_label"], type=row["s_type"],
                attributes=json.loads(row["s_attrs"]),
                created_at=row["s_created"], updated_at=row["s_updated"],
            ),
            dst=Entity(
                id=row["d_id"], label=row["d_label"], type=row["d_type"],
                attributes=json.loads(row["d_attrs"]),
                created_at=row["d_created"], updated_at=row["d_updated"],
            ),
            relation=row["relation"],
            attributes=json.loads(row["edge_attrs"]),
            created_at=row["edge_created"],
        )


def _row_to_entity(row: sqlite3.Row) -> Entity:
    return Entity(
        id=row["id"], label=row["label"], type=row["type"],
        attributes=json.loads(row["attributes"]),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )
