/* Node tests for kai-nexus-capabilities.js — honest state, no-credential inspector, §57 categories.
 * Run: node test_nexus_capabilities.js */
const assert = require('assert');
const C = require('./kai-nexus-capabilities.js');
const catalog = require('./kai-capability-catalog.json');   // the real honest snapshot

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

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
  // native caps + CERTIFIED foundation MCPs + HERO + the Wave-B-certified markitdown; nothing else
  assert.deepStrictEqual(ready.sort(), ['claude-code', 'context7', 'hero', 'kai-memory', 'markitdown', 'playwright'], 'only certified caps show READY (markitdown certified in Wave B)');
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

console.log('\n' + pass + ' passed');
