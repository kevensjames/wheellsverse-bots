// Phase 4M — systems model tests. Run: node test_nexus_systems.js
const assert = require('assert');
const S = require('./kai-nexus-systems.js');

let pass = 0;
const test = (n, fn) => { try { fn(); pass++; console.log('  ok  ' + n); } catch (e) { console.error('FAIL  ' + n + '\n      ' + e.message); process.exitCode = 1; } };

test('classifyProbe: real result → discrete state (no fake %)', () => {
  assert.equal(S.classifyProbe({ ok: true, status: 200 }), 'NOMINAL');
  assert.equal(S.classifyProbe({ ok: false, status: 503 }), 'CRITICAL');
  assert.equal(S.classifyProbe({ ok: false, status: 429 }), 'WARNING');
  assert.equal(S.classifyProbe({ ok: false, status: 404 }), 'DEGRADED');
  assert.equal(S.classifyProbe({ error: true }), 'UNKNOWN');
  assert.equal(S.classifyProbe(null), 'UNKNOWN');
});

test('summarize: counts by state', () => {
  const c = S.summarize([{ status: 'NOMINAL' }, { status: 'NOMINAL' }, { status: 'CRITICAL' }, { status: 'UNKNOWN' }, { status: 'weird' }]);
  assert.equal(c.NOMINAL, 2); assert.equal(c.CRITICAL, 1); assert.equal(c.UNKNOWN, 2); // 'weird' → UNKNOWN
});

test('isStale: no last_seen or beyond ttl', () => {
  assert.equal(S.isStale({ last_seen: null }, 1000, 500), true);
  assert.equal(S.isStale({ last_seen: 100 }, 1000, 500), true);   // 900 > 500
  assert.equal(S.isStale({ last_seen: 800 }, 1000, 500), false);  // 200 < 500
});

test('alertsFromSystems: only from real state, with source', () => {
  const a = S.alertsFromSystems([
    { id: 'postgres', name: 'Postgres', status: 'CRITICAL', provenance: 'DEMO' },
    { id: 'appB', name: 'App B', status: 'NOMINAL' },
    { id: 'redis', name: 'Redis', status: 'OFFLINE' },
  ]);
  assert.equal(a.length, 2);
  assert.equal(a[0].sev, 'critical'); assert.equal(a[0].system, 'postgres'); assert.equal(a[0].source, 'DEMO');
  assert.ok(a.every(x => x.system && x.source));   // every alert carries system + provenance
});

test('no arbitrary alerts: all-nominal → zero alerts', () => {
  assert.equal(S.alertsFromSystems([{ status: 'NOMINAL' }, { status: 'NOMINAL' }]).length, 0);
});

test('topology reflects real architecture, probes are real endpoints', () => {
  const ids = S.TOPOLOGY.nodes.map(n => n.id);
  ['client', 'cloudflare', 'appA', 'bridge', 'appB', 'postgres', 'redis', 'providers'].forEach(id => assert.ok(ids.includes(id), 'missing ' + id));
  const appB = S.TOPOLOGY.nodes.find(n => n.id === 'appB');
  assert.equal(appB.probe, '/health');
  const pg = S.TOPOLOGY.nodes.find(n => n.id === 'postgres');
  assert.equal(pg.probe, null);   // no probe → must never be green-by-default
  assert.ok(S.TOPOLOGY.edges.some(e => e[0] === 'bridge' && e[1] === 'appB'));
});

test('backoff grows and is deterministic (no Math.random)', () => {
  const a = S.backoffMs(1000, 0, 60000), b = S.backoffMs(1000, 3, 60000);
  assert.ok(b > a); assert.ok(b <= 60000 * 1.25);
  assert.equal(S.backoffMs(1000, 3, 60000), S.backoffMs(1000, 3, 60000)); // deterministic
});

console.log('\n' + pass + ' passed');
