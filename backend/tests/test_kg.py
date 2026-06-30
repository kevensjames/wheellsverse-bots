"""Knowledge Graph storage + query tool + admin endpoint tests."""
from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services import kg
from app.services.kg import storage as kg_storage
from app.services.tools.base import ToolContext, ToolError
from app.services.tools.kg_query import KGQueryTool


ADMIN_HEADERS = {"X-Admin-Token": settings.admin_token}


@pytest.fixture(autouse=True)
def _isolated_kg_db(tmp_path, monkeypatch):
    """Per-test SQLite file so tests don't pollute each other (or the real db)."""
    db = tmp_path / "kg.db"
    monkeypatch.setattr(kg_storage, "KG_DB_PATH", db)
    yield db


# ─── entities ───────────────────────────────────────────────────────


def test_add_entity_creates_then_retrieves():
    e = kg.add_entity("Jhon", "person", {"role": "operator"})
    assert e.id > 0
    assert e.label == "Jhon"
    assert e.type == "person"
    assert e.attributes == {"role": "operator"}

    found = kg.find_entities(label_contains="jhon")  # case-insensitive
    assert len(found) == 1
    assert found[0].label == "Jhon"


def test_add_entity_empty_label_raises():
    with pytest.raises(ValueError):
        kg.add_entity("   ", "person")


def test_add_entity_upserts_by_label_case_insensitive():
    a = kg.add_entity("KAI", "product", {"version": 1})
    b = kg.add_entity("kai", "service", {"version": 2})
    # Same row, merged attributes; type stays whatever it was first set to
    assert a.id == b.id
    assert b.attributes == {"version": 2}


# ─── edges ──────────────────────────────────────────────────────────


def test_add_edge_creates_both_entities_if_missing():
    edge = kg.add_edge("Jhon", "owns", "KAI", src_type="person", dst_type="product")
    assert edge.src.label == "Jhon"
    assert edge.dst.label == "KAI"
    assert edge.relation == "owns"
    assert edge.as_triple() == ("Jhon", "owns", "KAI")


def test_add_edge_dedupes_same_triple():
    e1 = kg.add_edge("A", "uses", "B")
    e2 = kg.add_edge("A", "uses", "B", attributes={"note": "second time"})
    assert e1.id == e2.id
    # Second add merged attributes onto the first edge
    assert e2.attributes == {"note": "second time"}


def test_add_edge_normalizes_relation():
    """Spaces become underscores so 'depends on' and 'depends_on' are equivalent."""
    e1 = kg.add_edge("A", "depends on", "B")
    e2 = kg.add_edge("A", "DEPENDS_ON", "B")
    assert e1.id == e2.id
    assert e1.relation == "depends_on"


def test_add_edge_empty_relation_raises():
    with pytest.raises(ValueError):
        kg.add_edge("A", "  ", "B")


# ─── neighbors ──────────────────────────────────────────────────────


def test_neighbors_out():
    kg.add_edge("Jhon", "owns", "KAI")
    kg.add_edge("Jhon", "owns", "Toodle")
    kg.add_edge("KAI", "uses", "Stripe")
    out = kg.neighbors("Jhon", direction="out")
    targets = {e.dst.label for e in out}
    assert targets == {"KAI", "Toodle"}


def test_neighbors_in():
    kg.add_edge("Jhon", "owns", "KAI")
    kg.add_edge("Jhonette", "owns", "KAI")
    in_edges = kg.neighbors("KAI", direction="in")
    sources = {e.src.label for e in in_edges}
    assert sources == {"Jhon", "Jhonette"}


def test_neighbors_both_combines():
    kg.add_edge("A", "uses", "B")
    kg.add_edge("C", "owns", "A")
    all_e = kg.neighbors("A", direction="both")
    # 1 outgoing + 1 incoming
    assert len(all_e) == 2


def test_neighbors_relation_filter():
    kg.add_edge("A", "owns", "B")
    kg.add_edge("A", "uses", "C")
    only_owns = kg.neighbors("A", relation="owns")
    assert len(only_owns) == 1
    assert only_owns[0].dst.label == "B"


def test_neighbors_unknown_entity_empty():
    assert kg.neighbors("does-not-exist") == []


def test_neighbors_invalid_direction_raises():
    with pytest.raises(ValueError):
        kg.neighbors("X", direction="sideways")


# ─── traversal ──────────────────────────────────────────────────────


def test_traverse_walks_max_depth():
    kg.add_edge("A", "uses", "B")
    kg.add_edge("B", "uses", "C")
    kg.add_edge("C", "uses", "D")
    edges = kg.traverse("A", max_depth=2)
    # depth 1: A→B  depth 2: B→C  (C→D is depth 3, beyond cap)
    triples = [e.as_triple() for e in edges]
    assert ("A", "uses", "B") in triples
    assert ("B", "uses", "C") in triples
    assert ("C", "uses", "D") not in triples


def test_traverse_handles_cycle_without_infinite_loop():
    kg.add_edge("A", "uses", "B")
    kg.add_edge("B", "uses", "A")  # cycle back
    edges = kg.traverse("A", max_depth=5)
    # Both edges visited exactly once, no explosion
    assert len(edges) == 2


def test_traverse_respects_max_edges_cap():
    for i in range(20):
        kg.add_edge("Hub", "links", f"Node{i}")
    edges = kg.traverse("Hub", max_depth=1, max_edges=5)
    assert len(edges) == 5


def test_traverse_unknown_start_empty():
    assert kg.traverse("nobody") == []


# ─── kg_query tool ──────────────────────────────────────────────────


def _ctx():
    return ToolContext(user_id=uuid.uuid4(), session=MagicMock())


def test_tool_search_action():
    kg.add_edge("Jhon", "owns", "KAI")
    out = KGQueryTool().execute(_ctx(), action="search", query="jhon")
    assert out["action"] == "search"
    assert out["count"] == 1
    assert out["entities"][0]["label"] == "Jhon"


def test_tool_neighbors_action():
    kg.add_edge("Jhon", "owns", "KAI")
    kg.add_edge("KAI", "uses", "Stripe")
    out = KGQueryTool().execute(_ctx(), action="neighbors", query="KAI", direction="both")
    assert out["entity"] == "KAI"
    relations = {e["relation"] for e in out["edges"]}
    assert relations == {"owns", "uses"}


def test_tool_triples_action():
    kg.add_edge("KAI", "uses", "Stripe")
    kg.add_edge("Stripe", "needs", "WebhookSecret")
    out = KGQueryTool().execute(_ctx(), action="triples", query="KAI", max_depth=2)
    assert any("KAI" in t and "Stripe" in t for t in out["triples"])
    assert any("Stripe" in t and "WebhookSecret" in t for t in out["triples"])


def test_tool_action_required():
    with pytest.raises(ToolError):
        KGQueryTool().execute(_ctx(), action="", query="x")


def test_tool_unknown_action():
    with pytest.raises(ToolError):
        KGQueryTool().execute(_ctx(), action="rotate", query="x")


# ─── admin endpoints ────────────────────────────────────────────────


def test_admin_kg_stats_requires_token(client):
    r = client.get("/admin/kg/stats")
    assert r.status_code == 403


def test_admin_kg_stats_empty(client):
    r = client.get("/admin/kg/stats", headers=ADMIN_HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["entity_count"] == 0
    assert body["edge_count_by_relation"] == []


def test_admin_kg_stats_populated(client):
    kg.add_edge("Jhon", "owns", "KAI")
    kg.add_edge("Jhon", "owns", "Toodle")
    kg.add_edge("KAI", "uses", "Stripe")
    r = client.get("/admin/kg/stats", headers=ADMIN_HEADERS)
    body = r.json()
    assert body["entity_count"] == 4
    rels = {row["relation"]: row["count"] for row in body["edge_count_by_relation"]}
    assert rels == {"owns": 2, "uses": 1}


def test_admin_kg_search(client):
    kg.add_entity("Jhon", "person")
    kg.add_entity("Jhonette", "person")
    kg.add_entity("KAI", "product")
    r = client.get("/admin/kg/search?q=jhon", headers=ADMIN_HEADERS)
    body = r.json()
    labels = {e["label"] for e in body["entities"]}
    assert labels == {"Jhon", "Jhonette"}


def test_admin_kg_neighbors(client):
    kg.add_edge("Jhon", "owns", "KAI")
    r = client.get(
        "/admin/kg/neighbors?label=Jhon&direction=out",
        headers=ADMIN_HEADERS,
    )
    body = r.json()
    assert body["edges"][0]["dst"] == "KAI"


# ─── add-edge (destructive) ─────────────────────────────────────────


def test_admin_kg_add_edge_requires_approval(client, monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_KG", "1")
    monkeypatch.setenv("KAI_SCOPE_KG_ADD_EDGE", "1")  # GOV-005: destructive needs its exact flag
    r = client.post(
        "/admin/kg/add-edge",
        headers=ADMIN_HEADERS,
        json={"src": "A", "relation": "uses", "dst": "B", "approved": False},
    )
    assert r.status_code == 409
    assert "approved" in r.json()["detail"].lower()


def test_admin_kg_add_edge_approved_writes(client, monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_KG", "1")
    monkeypatch.setenv("KAI_SCOPE_KG_ADD_EDGE", "1")  # GOV-005: destructive needs its exact flag
    # Isolate the audit log so this test doesn't pollute
    from app.services.governance import audit_log as _al
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False) as tf:
        monkeypatch.setattr(_al, "AUDIT_LOG_PATH", _al.Path(tf.name))
        r = client.post(
            "/admin/kg/add-edge",
            headers=ADMIN_HEADERS,
            json={
                "src": "Jhon", "relation": "owns", "dst": "KAI",
                "src_type": "person", "dst_type": "product",
                "approved": True,
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["triple"] == ["Jhon", "owns", "KAI"]


def test_admin_kg_add_edge_scope_off_403(client, monkeypatch):
    monkeypatch.delenv("KAI_SCOPE_KG", raising=False)
    monkeypatch.delenv("KAI_SCOPE_KG_ADD_EDGE", raising=False)
    r = client.post(
        "/admin/kg/add-edge",
        headers=ADMIN_HEADERS,
        json={"src": "A", "relation": "uses", "dst": "B", "approved": True},
    )
    assert r.status_code == 403


def test_admin_kg_add_edge_validates_input(client, monkeypatch):
    monkeypatch.setenv("KAI_SCOPE_KG", "1")
    monkeypatch.setenv("KAI_SCOPE_KG_ADD_EDGE", "1")  # GOV-005: destructive needs its exact flag
    # Empty relation
    r = client.post(
        "/admin/kg/add-edge",
        headers=ADMIN_HEADERS,
        json={"src": "A", "relation": "", "dst": "B", "approved": True},
    )
    assert r.status_code == 400
