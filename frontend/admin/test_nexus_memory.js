/* Node tests for kai-nexus-memory.js — the KG constellation model.
 * Run: node test_nexus_memory.js   (no framework, assert-based) */
const assert = require('assert');
const M = require('./kai-nexus-memory.js');

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

// ── normalize: types, provenance, untrusted, NO weight ───────────────────────
test('entity type normalizes to the KG enum; unknown → other', () => {
  assert.strictEqual(M.normalizeEntity({ label: 'Jhon', type: 'person' }).type, 'person');
  assert.strictEqual(M.normalizeEntity({ label: 'X', type: 'wizard' }).type, 'other');
  assert.strictEqual(M.normalizeEntity({ label: 'Y' }).type, 'other');
});
test('provenance defaults to DERIVED, never silently REAL; untrusted:true', () => {
  const e = M.normalizeEntity({ label: 'Stripe', type: 'service' });
  assert.strictEqual(e.provenance, 'DERIVED');
  assert.strictEqual(e.untrusted, true);
  const g = M.normalizeEntity({ label: 'Stripe' }, { provenance: 'REAL' });
  assert.strictEqual(g.provenance, 'REAL');
});
test('edges carry NO weight; a numeric in attributes stays in attributes', () => {
  const e = M.normalizeEdge({ src: 'KAI', relation: 'uses', dst: 'Stripe', attributes: { confidence: 0.9 } });
  assert.strictEqual('weight' in e, false);
  assert.strictEqual(e.attributes.confidence, 0.9);   // preserved as data, NOT promoted to weight
  assert.strictEqual(e.relation, 'uses');
});
test('relation is normalized (lowercase, spaces→underscore) like the KG', () => {
  assert.strictEqual(M.normalizeEdge({ src: 'A', relation: 'Depends On', dst: 'B' }).relation, 'depends_on');
});

// ── canonical ids (KG is COLLATE NOCASE) ─────────────────────────────────────
test('entity id is the lowercased label (matches KG NOCASE uniqueness)', () => {
  assert.strictEqual(M.normalizeEntity({ label: 'Stripe' }).id, 'stripe');
  assert.strictEqual(M.idOf('  KAI  '), 'kai');
});
test('dedupeEntities merges case-variant labels; dedupeEdges by (src,relation,dst)', () => {
  const nodes = M.dedupeEntities([M.normalizeEntity({ label: 'Stripe' }), M.normalizeEntity({ label: 'stripe' })]);
  assert.strictEqual(nodes.length, 1);
  const edges = M.dedupeEdges([
    M.normalizeEdge({ src: 'KAI', relation: 'uses', dst: 'Stripe' }),
    M.normalizeEdge({ src: 'kai', relation: 'uses', dst: 'stripe' }),
    M.normalizeEdge({ src: 'KAI', relation: 'owns', dst: 'Stripe' }),
  ]);
  assert.strictEqual(edges.length, 2);   // uses (deduped) + owns
});

// ── buildEgoGraph: never invent nodes/edges ──────────────────────────────────
test('buildEgoGraph drops edges with a missing endpoint (never fabricates a node)', () => {
  const entities = [M.normalizeEntity({ label: 'KAI' }), M.normalizeEntity({ label: 'Stripe' })];
  const edges = [
    M.normalizeEdge({ src: 'KAI', relation: 'uses', dst: 'Stripe' }),
    M.normalizeEdge({ src: 'KAI', relation: 'uses', dst: 'Railway' }),   // Railway not in node set
  ];
  const g = M.buildEgoGraph(entities, edges);
  assert.strictEqual(g.nodes.length, 2);
  assert.strictEqual(g.edges.length, 1);           // the Railway edge is dropped, not backfilled
  assert.strictEqual(g.edges[0].dst, 'stripe');
});
test('buildEgoGraph drops self-loops', () => {
  const g = M.buildEgoGraph([M.normalizeEntity({ label: 'A' })], [M.normalizeEdge({ src: 'A', relation: 'x', dst: 'A' })]);
  assert.strictEqual(g.edges.length, 0);
});
test('a disconnected seed yields just the seed node, no fabricated edges', () => {
  const g = M.buildEgoGraph([M.normalizeEntity({ label: 'Lonely' })], []);
  assert.strictEqual(g.nodes.length, 1);
  assert.strictEqual(g.edges.length, 0);
});

// ── layout: deterministic, centered, finite ──────────────────────────────────
test('layoutGraph is deterministic (same input → identical positions), no Math.random', () => {
  const nodes = ['KAI', 'Stripe', 'Railway', 'Sol'].map((l) => M.normalizeEntity({ label: l }));
  const edges = [M.normalizeEdge({ src: 'KAI', relation: 'uses', dst: 'Stripe' }), M.normalizeEdge({ src: 'KAI', relation: 'runs_on', dst: 'Railway' })];
  const a = M.layoutGraph(nodes, edges, 'kai');
  const b = M.layoutGraph(nodes, edges, 'kai');
  assert.deepStrictEqual(a, b);
  assert.deepStrictEqual(a.kai, { x: 50, y: 50 });   // seed centered
  for (const id of Object.keys(a)) { assert.ok(Number.isFinite(a[id].x) && Number.isFinite(a[id].y)); }
});
test('layout centers the highest-degree node when no seed given', () => {
  const nodes = ['Hub', 'A', 'B', 'C'].map((l) => M.normalizeEntity({ label: l }));
  const edges = [
    M.normalizeEdge({ src: 'Hub', relation: 'r', dst: 'A' }),
    M.normalizeEdge({ src: 'Hub', relation: 'r', dst: 'B' }),
    M.normalizeEdge({ src: 'Hub', relation: 'r', dst: 'C' }),
  ];
  const pos = M.layoutGraph(nodes, edges, null);
  assert.deepStrictEqual(pos.hub, { x: 50, y: 50 });
});

// ── neighbors + summarize ────────────────────────────────────────────────────
test('neighborsOf splits in/out direction', () => {
  const edges = [
    M.normalizeEdge({ src: 'KAI', relation: 'uses', dst: 'Stripe' }),
    M.normalizeEdge({ src: 'Jhon', relation: 'owns', dst: 'KAI' }),
  ];
  const n = M.neighborsOf('KAI', edges);
  assert.strictEqual(n.out.length, 1);
  assert.strictEqual(n.in.length, 1);
  assert.strictEqual(n.degree, 2);
});
test('summarize counts by type + relation; capped flag reflects the ≤500 /stats cap', () => {
  const nodes = [M.normalizeEntity({ label: 'A', type: 'person' }), M.normalizeEntity({ label: 'B', type: 'service' })];
  const edges = [M.normalizeEdge({ src: 'A', relation: 'uses', dst: 'B' })];
  const s = M.summarize(nodes, edges, false);
  assert.strictEqual(s.entityCount, 2);
  assert.strictEqual(s.edgeCount, 1);
  assert.strictEqual(s.byType.person, 1);
  assert.strictEqual(s.byRelation.uses, 1);
  assert.strictEqual(s.capped, false);
  const big = M.summarize(new Array(500).fill(0).map((_, i) => M.normalizeEntity({ label: 'n' + i })), [], true);
  assert.strictEqual(big.capped, true);   // 500 with statsCap → "500+"
});

// ── security: untrusted label stays inert data ───────────────────────────────
test('a <script> entity label is preserved as data and escaped inert', () => {
  const evil = '<img src=x onerror=alert(1)>';
  const e = M.normalizeEntity({ label: evil, type: 'concept' });
  assert.strictEqual(e.label, evil);           // stored verbatim (data)
  assert.ok(e.untrusted);
  const html = M.escapeHtml(e.label);
  assert.ok(html.indexOf('<img') === -1 && html.indexOf('&lt;img') !== -1);
});

// ── the /stats cap is a SIGNAL, not a drawn-sample-size check (review regression) ─
test('capped fires from the /stats signal with a realistic small ego sample (not only at 500 drawn)', () => {
  const few = ['a', 'b', 'c'].map((l) => M.normalizeEntity({ label: l }));
  assert.strictEqual(M.summarize(few, [], true).capped, true);    // 3 drawn + statsCap → "500+"; the old `&& >=500` made this dead
  assert.strictEqual(M.summarize(few, [], false).capped, false);  // DEMO (no statsCap) stays honest
});

// ── summarizing the DRAWABLE graph excludes undrawable (missing-endpoint) edges ──
test('summarize over buildEgoGraph counts only drawable edges (no far-endpoint overcount)', () => {
  const nodes = [M.normalizeEntity({ label: 'KAI' }), M.normalizeEntity({ label: 'Stripe' })];
  const rawEdges = [
    M.normalizeEdge({ src: 'KAI', relation: 'uses', dst: 'Stripe' }),
    M.normalizeEdge({ src: 'KAI', relation: 'runs_on', dst: 'Railway' }),   // Railway not loaded → undrawable
  ];
  const rawSum = M.summarize(nodes, rawEdges, false);
  assert.strictEqual(rawSum.edgeCount, 2);                 // raw overcounts (includes the undrawable edge)
  const g = M.buildEgoGraph(nodes, rawEdges);
  const drawnSum = M.summarize(g.nodes, g.edges, false);
  assert.strictEqual(drawnSum.edgeCount, 1);               // honest: only the drawable edge
  assert.strictEqual(Object.keys(drawnSum.byRelation).length, 1);
});

// ── filtering out an endpoint drops its edge (filter honesty) ────────────────
test('removing a node from the set drops its incident edges (never orphaned)', () => {
  const full = ['KAI', 'Stripe'].map((l) => M.normalizeEntity({ label: l }));
  const edges = [M.normalizeEdge({ src: 'KAI', relation: 'uses', dst: 'Stripe' })];
  assert.strictEqual(M.buildEgoGraph(full, edges).edges.length, 1);
  const filtered = full.filter((n) => n.id !== 'stripe');   // simulate a type/search filter removing Stripe
  assert.strictEqual(M.buildEgoGraph(filtered, edges).edges.length, 0);   // the edge is dropped, not left dangling
});

console.log('\n' + pass + ' passed');
