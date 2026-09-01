/* Node tests for kai-nexus-capabilities.js — honest state, no-credential inspector, §57 categories.
 * Run: node test_nexus_capabilities.js */
const assert = require('assert');
const C = require('./kai-nexus-capabilities.js');
const catalog = require('./kai-capability-catalog.json');   // the real honest snapshot

let pass = 0;
let pending = Promise.resolve();   // async tests (returning a promise) are chained + awaited at the end
function test(name, fn) {
  try {
    const r = fn();
    if (r && typeof r.then === 'function') {
      pending = pending.then(() => r.then(
        () => { console.log('  ok  ' + name); pass++; },
        (e) => { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; }));
    } else { console.log('  ok  ' + name); pass++; }
  } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; }
}

const byId = {};
catalog.capabilities.forEach((c) => { byId[c.id] = c; });

// ── honest state (§54 — no fake READY) ───────────────────────────────────────
test('stateLabel derives strictly from availability; DISCOVERED/BLOCKED never read READY', () => {
  assert.strictEqual(C.stateLabel({ availability: 'AVAILABLE' }), 'READY');
  assert.strictEqual(C.stateLabel({ availability: 'DISCOVERED' }), 'DISCOVERED');
  assert.strictEqual(C.stateLabel({ availability: 'EXTERNAL_BLOCKED' }), 'BLOCKED');
  assert.strictEqual(C.stateLabel({ availability: 'QUARANTINED' }), 'QUARANTINED');
  assert.strictEqual(C.stateLabel({ availability: 'AVAILABLE', activation: 'DISABLED' }), 'DISABLED');
});
test('on the REAL catalog, only genuinely-available capabilities show READY', () => {
  const ready = C.buildCapabilityRows(catalog).filter((r) => r.state === 'READY').map((r) => r.id);
  // native caps + CERTIFIED foundation MCPs + HERO + Wave-B-certified markitdown & yt-dlp; nothing else
  assert.deepStrictEqual(ready.sort(), ['claude-code', 'context7', 'hero', 'kai-memory', 'markitdown', 'playwright', 'yt-dlp'], 'only certified caps show READY (markitdown + yt-dlp certified in Wave B)');
});

// ── mode + restricted override ───────────────────────────────────────────────
test('modeLabel flags a RESTRICTED capability distinctly (never plain AUTO)', () => {
  assert.strictEqual(C.modeLabel(byId['reverse-skill']), 'RESTRICTED');
  assert.strictEqual(C.modeLabel(byId['context7']), 'ON DEMAND');
  assert.strictEqual(C.modeLabel(byId['kai-memory']), 'AUTO');
});

// ── §57 categories ───────────────────────────────────────────────────────────
test('categoryOf maps each capability to its functional-halo lane', () => {
  assert.strictEqual(C.categoryOf(byId['context7']), 'KNOWLEDGE');   // MCP docs
  assert.strictEqual(C.categoryOf(byId['filesystem']), 'CODE');      // MCP files
  assert.strictEqual(C.categoryOf(byId['playwright']), 'BROWSER');
  assert.strictEqual(C.categoryOf(byId['geolibre']), 'GEO');
  assert.strictEqual(C.categoryOf(byId['airllm']), 'INFERENCE');
  assert.strictEqual(C.categoryOf(byId['kai-memory']), 'MEMORY');
  assert.strictEqual(C.categoryOf(byId['reverse-skill']), 'ACTIVE SECURITY');
  // expansion groups — high-risk tiers are visually distinct (§26/§49)
  assert.strictEqual(C.categoryOf(byId['empire']), 'ADVERSARY EMULATION');
  assert.strictEqual(C.categoryOf(byId['seclists']), 'SECURITY REFERENCE');
  assert.strictEqual(C.categoryOf(byId['awesome-osint']), 'OSINT');
  assert.strictEqual(C.categoryOf(byId['appllama']), 'MOBILE DESIGN');
  assert.strictEqual(C.categoryOf(byId['hero']), 'AGENT BEHAVIOR');
});
test('Empire renders as a distinct high-risk row, never a green AUTO-READY tile (§26)', () => {
  const rows = C.buildCapabilityRows(catalog);
  const emp = rows.find((r) => r.id === 'empire');
  assert.ok(emp && emp.state !== 'READY', 'Empire must never show READY');
  assert.strictEqual(emp.risk, 'RESTRICTED');
  assert.strictEqual(emp.category, 'ADVERSARY EMULATION');
});

// ── inspector never exposes credentials (§55) ─────────────────────────────────
test('inspect() returns public detail only — no credentials/secrets key exists', () => {
  const d = C.inspect(byId['jcode']);   // an external repo → has verified provenance
  assert.ok(d.provenance && d.provenance.upstream.indexOf('github.com') !== -1, 'public provenance present');
  assert.ok(d.notes, 'notes shown');
  const blob = JSON.stringify(d).toLowerCase();
  for (const bad of ['password', 'token', 'api_key', 'apikey', 'secret', 'credential']) {
    assert.ok(blob.indexOf(bad) === -1, 'inspector must not contain ' + bad);
  }
});

// ── DOM render via a fake document ────────────────────────────────────────────
function fakeDoc() {
  function el(tag) {
    return { tag, children: [], dataset: {}, _text: '', className: '',
      set textContent(v) { this._text = v; }, get textContent() { return this._text; },
      appendChild(c) { this.children.push(c); return c; },
      removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); },
      get firstChild() { return this.children[0] || null; },
      addEventListener(t, fn) { (this._l = this._l || {})[t] = fn; } };
  }
  return { createElement: el };
}
test('renderPanel builds one row per capability with an honest data-state', () => {
  const doc = fakeDoc();
  const rootEl = doc.createElement('div');
  const selected = [];
  const n = C.renderPanel(rootEl, catalog, { document: doc, onSelect: (id) => selected.push(id) });
  assert.strictEqual(n, catalog.capabilities.length);
  const table = rootEl.firstChild;
  const dataRows = table.children.filter((r) => r.dataset && r.dataset.capId);
  assert.strictEqual(dataRows.length, catalog.capabilities.length);
  const geo = dataRows.find((r) => r.dataset.capId === 'geolibre');
  assert.strictEqual(geo.dataset.state, 'DISCOVERED', 'geolibre is verified-but-not-installed → DISCOVERED, never READY');
  geo._l.click();
  assert.deepStrictEqual(selected, ['geolibre']);
});

// ── EXECUTION UI (§3-9) ───────────────────────────────────────────────────────
test('serverStateLabel is backend-authoritative, else honest CATALOG_ONLY (§33)', () => {
  assert.strictEqual(C.serverStateLabel({ server_state: 'KAI_SERVER_READY' }), 'KAI_SERVER_READY');
  assert.strictEqual(C.serverStateLabel({}), 'CATALOG_ONLY');
  assert.strictEqual(C.serverStateLabel(null), 'CATALOG_ONLY');
});
test('testableOperation offers TEST only when the backend declares a safe_test (§4)', () => {
  assert.strictEqual(C.testableOperation({ operations: [{ operation: 'convert', safe_test: true }] }), 'convert');
  assert.strictEqual(C.testableOperation({ operations: [{ operation: 'metadata', safe_test: false }] }), null);
  assert.strictEqual(C.testableOperation({ operations: [] }), null);
});
test('executionStateLabel maps statuses; denials never read as success (§6/§32)', () => {
  assert.strictEqual(C.executionStateLabel('OK'), 'COMPLETED');
  assert.strictEqual(C.executionStateLabel('OPERATION_NOT_ENABLED'), 'DENIED');
  assert.strictEqual(C.executionStateLabel('CAPABILITY_UNAVAILABLE'), 'UNAVAILABLE');
  assert.strictEqual(C.executionStateLabel('INPUT_REJECTED'), 'REJECTED');
});
test('activityLabel exposes only a SAFE label, never reasoning (§7)', () => {
  assert.strictEqual(C.activityLabel('yt-dlp'), 'Inspecting media metadata');
  assert.strictEqual(C.activityLabel('markitdown'), 'Converting document');
  assert.ok(!/reason|prompt|think/i.test(C.activityLabel('anything')));
});
test('history rows carry no secrets / no request bodies (§5/§32)', () => {
  const rows = C.historyRows([{ capability: 'yt-dlp', operation: 'metadata', status: 'OK',
    duration_ms: 661, provenance: 'REAL', correlation_id: 'c-1' }]);
  assert.strictEqual(rows[0].state, 'COMPLETED');
  const blob = JSON.stringify(rows).toLowerCase();
  for (const bad of ['url', 'token', 'secret', 'input', 'cookie', 'password']) {
    assert.ok(blob.indexOf(bad) === -1, 'history must not surface ' + bad);
  }
});
test('renderHistory builds a row per invocation (fake DOM)', () => {
  const doc = fakeDoc();
  const rootEl = doc.createElement('div');
  const n = C.renderHistory(rootEl, [{ capability: 'yt-dlp', operation: 'metadata', status: 'OK',
    duration_ms: 5, provenance: 'REAL', correlation_id: 'c-1' }], { document: doc });
  assert.strictEqual(n, 1);
  const dataRows = rootEl.firstChild.children.filter((r) => r.dataset && r.dataset.state);
  assert.strictEqual(dataRows[0].dataset.state, 'COMPLETED');
});

// controller with an injected fake fetch (no network)
function fakeFetch(routes) {
  const calls = [];
  const f = (url, init) => {
    calls.push({ url, method: (init && init.method) || 'GET' });
    const r = routes[url] || routes[(init && init.method || 'GET') + ' ' + url] || { status: 404, body: {} };
    return Promise.resolve({ ok: r.status < 400, status: r.status || 200, json: () => Promise.resolve(r.body) });
  };
  f.calls = calls;
  return f;
}
test('CapabilityConsole hits the BRIDGE path, never App A catalog routes (§16)', () => {
  const f = fakeFetch({ '/admin/kai/capabilities': { status: 200, body: { capabilities: [] } } });
  const con = C.CapabilityConsole({ fetch: f });
  assert.strictEqual(con.base, '/admin/kai/capabilities');
  return con.loadExecutable().then(() => {
    assert.ok(f.calls[0].url === '/admin/kai/capabilities', 'must call the bridge exec path');
    assert.ok(f.calls[0].url.indexOf('/admin/capabilities') !== 0, 'must NOT call App A /admin/capabilities catalog');
  });
});
test('runTest emits started→completed and returns the ExecutionResult (§6/§34-halo)', () => {
  const events = [];
  const f = fakeFetch({ 'POST /admin/kai/capabilities/yt-dlp/test':
    { status: 200, body: { status: 'OK', correlation_id: 'c-9' } } });
  const con = C.CapabilityConsole({ fetch: f, onEvent: (e) => events.push(e) });
  return con.runTest('yt-dlp').then((er) => {
    assert.strictEqual(er.status, 'OK');
    assert.deepStrictEqual(events.map((e) => e.event), ['capability.started', 'capability.completed']);
    assert.strictEqual(events[0].activity, 'Inspecting media metadata');
  });
});
test('runTest emits started→failed on a denied/failed result (no fake success)', () => {
  const events = [];
  const f = fakeFetch({ 'POST /admin/kai/capabilities/yt-dlp/test':
    { status: 403, body: { status: 'OPERATION_NOT_ENABLED', correlation_id: 'c-x' } } });
  const con = C.CapabilityConsole({ fetch: f, onEvent: (e) => events.push(e) });
  return con.runTest('yt-dlp').then((er) => {
    assert.strictEqual(er.status, 'OPERATION_NOT_ENABLED');
    assert.deepStrictEqual(events.map((e) => e.event), ['capability.started', 'capability.failed']);
  });
});

pending.then(() => console.log('\n' + pass + ' passed'));
