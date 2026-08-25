/* KAI Adaptive Mission Nexus — Memory Constellation (Phase 9, §22)
 *
 * Pure UMD logic (browser + node), no DOM. The ONLY real graph in the system is the
 * App-B Knowledge Graph (SQLite entities+edges: directed, typed, named relations —
 * docs/KAI_MEMORY_SOURCES.md). This module models that graph and lays it out
 * deterministically. Everything else the platform calls "memory" is FLAT records
 * (no edges) — this module never invents edges between them.
 *
 * Hard honesty rules (D13), enforced + tested:
 *   - Edges carry NO weight (the KG has no weight column) → uniform rendering; a
 *     numeric in `attributes` stays there, never promoted to a thickness/score.
 *   - No fabricated similarity / co-occurrence / tag edges; an edge exists only where
 *     a real triple (src,relation,dst) does. buildEgoGraph drops edges with a missing
 *     endpoint rather than inventing a node.
 *   - No stored recency/importance → no recency-glow or importance-sizing.
 *   - entity_count from /stats is a ≤500 sample cap → `capped` flag, shown as "500+".
 *   - Layout is deterministic (degree-ranked, stable order) — no Math.random, no jitter.
 * Entity labels/attributes are operator-authored but still UNTRUSTED at render:
 *   untrusted:true, escaped via textContent/escapeHtml (a `<script>` label is inert).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.NexusMemory = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Entity type enum mirrors the KG (backend/app/services/kg): informal, 'other' fallback.
  const ENTITY_TYPES = ['person', 'product', 'company', 'service', 'concept', 'event', 'other'];
  const normType = (t) => { const s = String(t == null ? 'other' : t).toLowerCase(); return ENTITY_TYPES.indexOf(s) >= 0 ? s : 'other'; };

  const escapeHtml = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // KG labels are UNIQUE COLLATE NOCASE → canonical id is the lowercased label.
  const idOf = (label) => String(label == null ? '' : label).trim().toLowerCase();
  const normRelation = (r) => String(r == null ? 'related_to' : r).trim().toLowerCase().replace(/\s+/g, '_');
  const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

  function normalizeEntity(raw, opts) {
    raw = raw || {}; opts = opts || {};
    const label = raw.label != null ? String(raw.label) : String(raw.id != null ? raw.id : '');
    return {
      id: idOf(label),              // canonical (lowercased) — matches KG NOCASE uniqueness
      label,                         // display (original case), UNTRUSTED → textContent only
      type: normType(raw.type),
      attributes: (raw.attributes && typeof raw.attributes === 'object') ? raw.attributes : {},
      provenance: opts.provenance || raw.provenance || 'DERIVED',   // never silently REAL
      untrusted: true,
    };
  }

  // Edge = a real KG triple. NO weight (the KG stores none).
  function normalizeEdge(raw, opts) {
    raw = raw || {}; opts = opts || {};
    const src = idOf(raw.src != null ? raw.src : raw.source);
    const dst = idOf(raw.dst != null ? raw.dst : raw.target);
    const relation = normRelation(raw.relation);
    return {
      edge_id: raw.edge_id != null ? raw.edge_id : (src + '|' + relation + '|' + dst),
      src, dst, relation,
      src_label: raw.src != null ? String(raw.src) : src,
      dst_label: raw.dst != null ? String(raw.dst) : dst,
      attributes: (raw.attributes && typeof raw.attributes === 'object') ? raw.attributes : {},
      provenance: opts.provenance || raw.provenance || 'DERIVED',
      untrusted: true,
    };
  }

  function dedupeEntities(list) {
    const by = new Map();
    for (const e of (list || [])) if (!by.has(e.id)) by.set(e.id, e);
    return [...by.values()];
  }
  // Dedupe by the real KG uniqueness key (src,relation,dst).
  function dedupeEdges(list) {
    const by = new Map();
    for (const e of (list || [])) { const k = e.src + '|' + e.relation + '|' + e.dst; if (!by.has(k)) by.set(k, e); }
    return [...by.values()];
  }

  // Assemble the drawable graph: dedupe, then keep ONLY edges whose BOTH endpoints are
  // present as nodes. Missing-endpoint edges are DROPPED (never fabricate a node/edge).
  function buildEgoGraph(entities, edges) {
    const nodes = dedupeEntities(entities);
    const present = new Set(nodes.map((n) => n.id));
    const kept = dedupeEdges(edges).filter((e) => present.has(e.src) && present.has(e.dst) && e.src !== e.dst);
    return { nodes, edges: kept };
  }

  // Deterministic layout: center = seed (if present) else highest-degree; others on
  // concentric rings ordered by degree then id. No randomness, no physics.
  function layoutGraph(nodes, edges, seedId) {
    const deg = {};
    for (const n of nodes) deg[n.id] = 0;
    for (const e of edges) { if (deg[e.src] != null) deg[e.src]++; if (deg[e.dst] != null) deg[e.dst]++; }
    const byRank = nodes.slice().sort((a, b) => (deg[b.id] - deg[a.id]) || cmp(a.id, b.id));
    const center = (seedId && nodes.some((n) => n.id === seedId)) ? seedId : (byRank[0] ? byRank[0].id : null);
    const pos = {};
    if (center) pos[center] = { x: 50, y: 50 };
    const others = byRank.filter((n) => n.id !== center);
    const perRing = 8;
    others.forEach((n, i) => {
      const ring = Math.floor(i / perRing);
      const inRing = i % perRing;
      const countInRing = Math.min(perRing, others.length - ring * perRing);
      const r = 22 + ring * 15;
      const ang = (inRing / countInRing) * Math.PI * 2 - Math.PI / 2 + ring * 0.55;   // offset rings so they don't align
      pos[n.id] = { x: 50 + Math.cos(ang) * r, y: 50 + Math.sin(ang) * r * 0.82 };
    });
    return pos;
  }

  function neighborsOf(id, edges) {
    id = idOf(id);
    const out = [], incoming = [];
    for (const e of (edges || [])) { if (e.src === id) out.push(e); else if (e.dst === id) incoming.push(e); }
    return { out, in: incoming, degree: out.length + incoming.length };
  }

  // Header/summary. entity_count may be a ≤500 sample cap from /stats → carry `capped`.
  function summarize(nodes, edges, statsCap) {
    nodes = nodes || []; edges = edges || [];
    const byType = {}, byRelation = {};
    for (const n of nodes) byType[n.type] = (byType[n.type] || 0) + 1;
    for (const e of edges) byRelation[e.relation] = (byRelation[e.relation] || 0) + 1;
    return {
      entityCount: nodes.length,          // DRAWN nodes (the ego sample, bounded)
      edgeCount: edges.length,
      relationTypes: Object.keys(byRelation).length,
      byType, byRelation,
      // capped reflects the /stats ≤500 sample-cap SIGNAL — NOT the drawn sample size.
      // The ego-graph is bounded well under 500, so a size check would be dead code.
      capped: !!statsCap,
    };
  }

  return {
    ENTITY_TYPES, normType, escapeHtml, idOf, normRelation,
    normalizeEntity, normalizeEdge, dedupeEntities, dedupeEdges,
    buildEgoGraph, layoutGraph, neighborsOf, summarize,
  };
});
