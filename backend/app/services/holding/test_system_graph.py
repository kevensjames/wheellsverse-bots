"""§56 HoldingSystemGraph guard — dynamic-from-real-registries, zero fabricated topology, bounded view.
Run (from backend/):
    python3 -m app.services.holding.test_system_graph
"""
from app.services.holding.system_graph import build_graph, SystemGraph, EdgeType, _ROOT_ID


def run() -> bool:
    res = []

    def ck(n, ok):
        res.append(bool(ok))
        print(f"  [{'PASS' if ok else 'FAIL'}] {n}")

    # ── 1. built from the REAL registries (11 entities + capabilities + missions), no DB needed ──────
    # entities + hierarchy are pure; capabilities from the pure capability registry; missions/workers
    # are injected here so the core test is DB-free + deterministic (real build also fail-opens, tested below).
    from app.services.holding import registry as reg
    fake_missions = [
        {"mission_id": "ms-1", "objective": "reduce SOL deploy drift", "company": "sol", "origin": "PROBLEM",
         "authority_level": "A0_OBSERVE"},
        {"mission_id": "ms-2", "objective": "holding-wide vendor cost review", "company": "holding",
         "origin": "PROACTIVE", "authority_level": "A0_OBSERVE"},
    ]
    g = build_graph(sources={"missions": lambda: fake_missions, "workers": lambda: []})

    ents = [n for n in g.nodes() if n["type"] in ("holding", "LLC", "company", "product", "project")]
    ck("entity nodes derive from the real registry (== all_entities count)", len(ents) == len(reg.all_entities()))
    caps = [n for n in g.nodes() if n["type"] == "capability"]
    ck("capability nodes present (from capability registry, AVAILABLE)", len(caps) >= 1)
    miss = [n for n in g.nodes() if n["type"] == "mission"]
    ck("mission nodes present (== injected missions)", len(miss) == 2)

    # ── 2. EVERY node + edge carries provenance; endpoints of every edge are real nodes (no dangling) ─
    ck("every node has non-empty provenance", all(n["provenance"] for n in g.nodes()))
    ck("every edge has non-empty provenance", all(e["provenance"] for e in g.edges()))
    node_ids = {n["id"] for n in g.nodes()}
    ck("no edge references a non-existent node (no fabricated topology)",
       all(e["src"] in node_ids and e["dst"] in node_ids for e in g.edges()))

    # ── 3. §14 hierarchy owned_by edges present + correct (child → parent) ────────────────────────────
    owned = [e for e in g.edges() if e["rel"] == EdgeType.OWNED_BY.value]
    ck("owned_by hierarchy edges present", len(owned) >= len(reg.hierarchy_edges()))
    ck("sol owned_by solcircle (real multi-level chain)",
       any(e["src"] == "entity:sol" and e["dst"] == "entity:solcircle" for e in owned))
    ck("solcircle owned_by wheellsverse_holdings (root)",
       any(e["src"] == "entity:solcircle" and e["dst"] == f"entity:{_ROOT_ID}" for e in owned))
    ck("root entity has no owned_by (it is the parent)",
       not any(e["src"] == f"entity:{_ROOT_ID}" for e in owned))

    # ── 4. an edge is emitted ONLY with real evidence — a fabricated hierarchy edge is DROPPED ────────
    g2 = build_graph(sources={
        "hierarchy": lambda: [{"parent": "ghost_parent", "child": "sol", "relation": "owns"},
                              {"parent": _ROOT_ID, "child": "kai", "relation": "owns"}],
        "missions": lambda: [], "workers": lambda: []})
    o2 = [e for e in g2.edges() if e["rel"] == EdgeType.OWNED_BY.value]
    ck("edge to a non-registry parent (ghost_parent) is NOT created", not any("ghost" in e["dst"] for e in o2))
    ck("real edge among registry entities (kai owned_by root) IS created",
       any(e["src"] == "entity:kai" and e["dst"] == f"entity:{_ROOT_ID}" for e in o2))

    # add_edge itself refuses a dangling endpoint
    g3 = SystemGraph()
    g3.add_node("a", node_type="x", label="A", provenance="t")
    ck("add_edge refuses an edge to a missing node", g3.add_edge("a", EdgeType.USES, "missing", provenance="t") is False)
    ck("add_edge refuses a self-loop", g3.add_edge("a", EdgeType.USES, "a", provenance="t") is False)

    # ── 5. real edge TYPES carry real evidence: deployed_as / uses / monitored_by / supports ─────────
    rels = {e["rel"] for e in g.edges()}
    ck("deployed_as edges exist (registry.deployment/domains)", EdgeType.DEPLOYED_AS.value in rels)
    ck("uses edges exist (registry.integrations → vendor)", EdgeType.USES.value in rels)
    ck("supports edges exist (capabilities/missions → entity)", EdgeType.SUPPORTS.value in rels)
    # kai carries a 'prod observability monitor' integration → monitored_by, not a plain vendor
    ck("monitored_by edge from the real monitor integration on kai",
       any(e["rel"] == EdgeType.MONITORED_BY.value and e["src"] == "entity:kai" for e in g.edges()))
    # mission→company supports edge is real (ms-1 → sol); holding-level mission → root
    ck("mission supports its company (ms-1 → sol)",
       any(e["src"] == "mission:ms-1" and e["dst"] == "entity:sol"
           and e["rel"] == EdgeType.SUPPORTS.value for e in g.edges()))
    ck("holding-level mission supports the root (ms-2 → holdings)",
       any(e["src"] == "mission:ms-2" and e["dst"] == f"entity:{_ROOT_ID}" for e in g.edges()))
    # NOT fabricated: no calls/depends_on/blocked_by without a structured source
    ck("no fabricated calls/depends_on/blocked_by edges",
       not (rels & {EdgeType.CALLS.value, EdgeType.DEPENDS_ON.value, EdgeType.BLOCKED_BY.value}))

    # ── 6. bounded view — overview is selective (not a giant dump), focused view respects the cap ─────
    ov = g.view()
    ck("overview view returns only entity nodes (selective, not the full graph)",
       len(ov["nodes"]) <= len(g.nodes()) and all(
           n["type"] in ("holding", "LLC", "company", "product", "project") for n in ov["nodes"]))
    ck("overview view carries owned_by edges + a summary", ov["summary"]["nodes_total"] == len(g.nodes())
       and all(e["rel"] == EdgeType.OWNED_BY.value for e in ov["edges"]))
    small = g.view(max_nodes=3)
    ck("overview honours max_nodes cap + flags truncation", len(small["nodes"]) == 3 and small["truncated"] is True)

    nb = g.view(focus=f"entity:{_ROOT_ID}", depth=1, max_nodes=5)
    ck("focused neighborhood is bounded by max_nodes", len(nb["nodes"]) <= 5)
    ck("focused neighborhood edges stay within the returned nodes",
       all(e["src"] in {n["id"] for n in nb["nodes"]} and e["dst"] in {n["id"] for n in nb["nodes"]}
           for e in nb["edges"]))
    ck("view of an unknown node fails closed (empty, no crash)",
       g.view(focus="entity:nope")["nodes"] == [])

    # ── 7. deterministic / no-LLM — identical build → identical summary ──────────────────────────────
    a = build_graph(sources={"missions": lambda: fake_missions, "workers": lambda: []}).summary()
    b = build_graph(sources={"missions": lambda: fake_missions, "workers": lambda: []}).summary()
    ck("build is deterministic (identical summary across runs)", a == b)

    # ── 8. fail-open — a source that raises contributes nothing, never crashes the build ─────────────
    def boom():
        raise RuntimeError("subsystem down")
    g4 = build_graph(sources={"missions": boom, "workers": boom})
    ck("a raising source is fail-open (build still yields the registry entities)",
       len([n for n in g4.nodes() if n["type"] in ("holding", "LLC", "company", "product", "project")])
       == len(reg.all_entities()))

    # ── 9. real default build (missions/workers hit the DB → fail-open to [] if absent) ──────────────
    gd = build_graph()   # exercises the real default sources end to end
    ck("real default build produces the registry entities + capabilities",
       len([n for n in gd.nodes() if n["type"] == "capability"]) >= 1
       and len([n for n in gd.nodes() if n["type"] in ("holding", "LLC", "company", "product", "project")])
       == len(reg.all_entities()))

    n, ok = len(res), sum(res)
    print(f"\nHOLDING SYSTEM GRAPH TESTS: {ok}/{n} —", "PASS" if ok == n else "FAIL")
    return ok == n


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
