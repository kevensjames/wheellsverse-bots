/* App A page contract — kai-capabilities.html is CATALOG-ONLY (§16/§17).
 *
 * Run: node --test test_capabilities_page_contract.js   (also runs bare: node test_...js)
 *
 * WHY THIS FILE LOOKS LIKE THIS.
 * It first asserted an execution console this page does not implement (load
 * kai-nexus-capabilities.js, instantiate CapabilityConsole, drive /admin/kai/capabilities), so four
 * checks failed permanently on production base b0674ce and every candidate. A permanently red suite
 * cannot report a real regression. Those were replaced by a catalog-only contract in 2f0cce0.
 *
 * That first replacement was itself OVER-CLAIMED, and this is the correction. Its harness observed
 * only the initial /admin/capabilities.json GET: it discarded event handlers, returned a fresh
 * element from every getElementById, never awaited the promise chain, and swallowed VM/timer errors.
 * So "no POST or execution request exists" was proven for page load and merely ASSUMED for the
 * interactive catalog-detail path — the path that actually issues the second request.
 *
 * This harness drives the real flow end to end: catalog fetch -> render -> the row click handler the
 * page itself registers -> inspect() -> detail fetch -> inspector render. Elements are stable,
 * handlers are retained and invoked, every promise is awaited, and NOTHING is swallowed — an
 * incomplete shim fails loudly naming the missing DOM operation rather than silently proving less.
 *
 * SECURITY POSITION. "Execution must use the owner-only bridge, never App B directly" holds here in
 * the strongest available form: there is no execution at all. Recorded limitation — there is no
 * security bypass on this page and equally no way to execute a capability from it, intentional while
 * this release is dark and all authority flags are off. kai-nexus-capabilities.js exists and is
 * independently tested by test_nexus_capabilities.js (16 checks, unchanged); passing isolated tests
 * do NOT make it deployed or user-accessible — no served page loads it.
 */
'use strict';
const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const vm = require('node:vm');

const PAGE = __dirname + '/kai-capabilities.html';
const REAL_HTML = fs.readFileSync(PAGE, 'utf8');
const EXEC_MODULE = 'kai-nexus-capabilities.js';

// The ONLY requests this page may make. Same-origin App A catalog reads, GET only.
// Detail ids are the catalog's own ids: one path segment, no query, no fragment, non-empty.
const CATALOG_URL = '/admin/capabilities.json';
const DETAIL_RE = /^\/admin\/capabilities\/[A-Za-z0-9._~%-]+$/;   // %-escapes allowed (encodeURIComponent)
const isAllowed = (u) => u === CATALOG_URL || DETAIL_RE.test(u);

// A realistic capability, shaped exactly as render() consumes it.
const CAP = {
  id: 'claude-code', name: 'Claude Code', group: 'CODING WORKFORCE',
  runtime: { kai_server: 'CATALOG_ONLY', claude_local: 'AVAILABLE' },
  certification: 'CERTIFIED', risk_class: 'LOW', security_tier: 1,
};
const CATALOG = { count: 1, source: 'registry', generated: '2026-09-06T00:00:00Z', capabilities: [CAP] };
// The detail response must be as realistic as the catalog one: inspect() reads type, availability,
// activation, provenance, automatic_activation_allowed and several list fields. A thin {id,name}
// stub made the render throw — which the harness correctly surfaced rather than hiding.
const DETAIL = Object.assign({}, CAP, {
  type: 'MCP', availability: 'AVAILABLE', activation: 'MANUAL',
  automatic_activation_allowed: false, notes: 'catalog-only fixture',
  capabilities: ['read'], dependencies: [], conflicts: [], permissions: [],
  provenance: { source: 'registry', verified: '2026-09-06' },
});

// ── DOM shim: stable elements, retained handlers, real textContent->innerHTML escaping ────────
function makeDom() {
  const byId = new Map();
  const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');

  function makeEl(tag) {
    const el = {
      tagName: (tag || 'div').toUpperCase(), _attrs: {}, _handlers: {}, children: [], _html: '', _rows: [],
      get innerHTML() { return this._html; },
      set innerHTML(v) {
        this._html = String(v);
        // The page builds rows as a string then queries them back — parse them so
        // querySelectorAll('tr.cap') returns real, clickable elements with their data-id.
        this._rows = [...this._html.matchAll(/<tr class="cap" data-id="([^"]*)"/g)].map((m) => {
          const row = makeEl('tr');
          row._attrs['data-id'] = m[1].replace(/&amp;/g, '&').replace(/&quot;/g, '"');
          row._attrs.class = 'cap';
          return row;
        });
      },
      get textContent() { return this._text || ''; },
      set textContent(v) { this._text = String(v == null ? '' : v); this._html = esc(this._text); },
      setAttribute(k, v) { this._attrs[k] = String(v); },
      getAttribute(k) { return k in this._attrs ? this._attrs[k] : null; },
      addEventListener(type, fn) { (this._handlers[type] = this._handlers[type] || []).push(fn); },
      removeEventListener() {},
      appendChild(c) { this.children.push(c); return c; },
      querySelectorAll(sel) { return sel === 'tr.cap' ? this._rows : []; },
      querySelector() { return null; },
      classList: { _s: new Set(), add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); }, contains(c) { return this._s.has(c); } },
      focus() {}, remove() {}, style: {}, dataset: {}, hidden: false,
      click() { (this._handlers.click || []).forEach((fn) => fn({ type: 'click', target: this })); },
    };
    // Requirement 9: an incomplete shim must FAIL naming the missing operation, never silently
    // let the page take a different path and prove less than we claim.
    return new Proxy(el, {
      get(t, p) {
        if (p in t || typeof p === 'symbol') return t[p];
        throw new Error(`DOM shim missing operation: <${t.tagName.toLowerCase()}>.${String(p)} — ` +
          `extend the shim; do not weaken the contract`);
      },
    });
  }
  const document = {
    getElementById(id) { if (!byId.has(id)) byId.set(id, makeEl('div')); return byId.get(id); },
    createElement: (t) => makeEl(t),
    querySelectorAll: () => [], querySelector: () => null, addEventListener() {},
    body: makeEl('body'), head: makeEl('head'),
  };
  return { document, byId };
}

/** Load the page: run its script, await the catalog fetch + render. Nothing is swallowed. */
async function loadPage(html, { catalog = CATALOG, detail = DETAIL } = {}) {
  const observed = [];                       // {url, method}
  const { document, byId } = makeDom();
  const sandbox = {
    document,
    console: { log() {}, error() {}, warn() {} },
    location: { href: 'https://appa.example/admin/capabilities', origin: 'https://appa.example' },
    setTimeout: (fn) => { fn(); return 0; },  // errors propagate deliberately
    clearTimeout() {},
    fetch(url, opts) {
      const method = ((opts || {}).method || 'GET').toUpperCase();
      observed.push({ url: String(url), method });
      const body = String(url) === CATALOG_URL ? catalog : detail;
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  assert.ok(m, 'page must carry its inline script');
  vm.runInNewContext(m[1], sandbox, { timeout: 5000 });   // NOT wrapped — a throw fails the test
  await drain();
  return { observed, byId, document, scriptSrcs: [...html.matchAll(/<script[^>]*\ssrc=["']([^"']+)["']/g)].map((x) => x[1]) };
}
const drain = async () => { for (let i = 0; i < 50; i++) await Promise.resolve();
  await new Promise((r) => setImmediate(r)); };

/** Drive the interactive path: click the first catalog row the page itself wired. */
async function clickFirstRow(ctx) {
  const rows = ctx.byId.get('list')._rows;
  assert.ok(rows && rows.length, 'render() must produce clickable catalog rows');
  const handlers = rows[0]._handlers.click;
  assert.ok(handlers && handlers.length, 'the page must register a click handler on each row');
  handlers.forEach((fn) => fn({ type: 'click', target: rows[0] }));   // the REAL registered handler
  await drain();
  return rows[0].getAttribute('data-id');
}

/** Contract violations for a set of observed requests + declarative markup. */
function violations(ctx, html) {
  const v = [];
  for (const { url, method } of ctx.observed) {
    if (/^https?:\/\//i.test(url)) v.push('OFF_ORIGIN:' + url);
    else if (url.startsWith('/admin/kai/')) v.push('BRIDGE_OR_APPB:' + url);
    else if (!isAllowed(url)) v.push('UNAPPROVED_ENDPOINT:' + url);
    if (method !== 'GET') v.push('NON_GET:' + method + ':' + url);
  }
  if (ctx.scriptSrcs.some((s) => s.includes(EXEC_MODULE))) v.push('EXEC_MODULE_LOADED');
  if (/<form\b/i.test(html)) v.push('EXEC_CONTROL:form');
  if (/\bonclick\s*=/i.test(html)) v.push('EXEC_CONTROL:inline-onclick');
  if (/<button[^>]*\bdata-(run|invoke|execute)\b/i.test(html)) v.push('EXEC_CONTROL:button');
  if (/\b(invoke|execute)\s*\(/i.test(html)) v.push('EXEC_CALL');
  if (/CapabilityConsole\s*\(/.test(html)) v.push('EXEC_CONSOLE');
  return v;
}

// ── the real page, initial load AND interaction ──────────────────────────────────────────────
test('initial load + row click issue exactly the two approved catalog GETs', async () => {
  const ctx = await loadPage(REAL_HTML);
  assert.deepStrictEqual(ctx.observed.map((o) => o.url), [CATALOG_URL],
    'initial load must fetch only the catalog');
  const id = await clickFirstRow(ctx);
  assert.strictEqual(id, CAP.id);
  const urls = ctx.observed.map((o) => o.url);
  assert.strictEqual(urls.length, 2, 'exactly two requests: catalog + detail, got ' + JSON.stringify(urls));
  assert.strictEqual(urls[0], CATALOG_URL);
  assert.strictEqual(urls[1], '/admin/capabilities/' + encodeURIComponent(CAP.id));
  assert.ok(DETAIL_RE.test(urls[1]), 'detail URL must match the tightened allowlist: ' + urls[1]);
  assert.deepStrictEqual([...new Set(ctx.observed.map((o) => o.method))], ['GET']);
  assert.deepStrictEqual(violations(ctx, REAL_HTML), []);
});

test('no POST, invocation or execution request on either path (observed)', async () => {
  const ctx = await loadPage(REAL_HTML);
  await clickFirstRow(ctx);
  for (const { url, method } of ctx.observed) assert.strictEqual(method, 'GET', 'non-GET to ' + url);
  assert.ok(!/\bmethod\s*:\s*["']POST["']/i.test(REAL_HTML), 'no POST in source');
});

test('no direct App B address and no /admin/kai/* endpoint on either path', async () => {
  const ctx = await loadPage(REAL_HTML);
  await clickFirstRow(ctx);
  for (const { url } of ctx.observed) {
    assert.ok(!/^https?:\/\//i.test(url), 'absolute URL: ' + url);
    assert.ok(!url.startsWith('/admin/kai/'), 'bridge/App B endpoint: ' + url);
  }
  assert.ok(!/kai-prod|kai\.wheellsverse|railway\.app/i.test(REAL_HTML), 'App B host in source');
});

test('the execution-console module is NOT loaded by this catalog-only page', async () => {
  const ctx = await loadPage(REAL_HTML);
  assert.ok(!ctx.scriptSrcs.some((s) => s.includes(EXEC_MODULE)));
  assert.ok(!/window\.NexusCapabilities/.test(REAL_HTML));
});

test('no execution button, form or invoke handler is exposed', () => {
  assert.ok(!/<form\b/i.test(REAL_HTML));
  assert.ok(!/\b(invoke|execute)\s*\(/i.test(REAL_HTML));
  assert.ok(!/\bonclick\s*=/i.test(REAL_HTML));
});

test('detail endpoint allowlist rejects empty id, extra segment, query and fragment', () => {
  for (const bad of ['/admin/capabilities/', '/admin/capabilities/a/b', '/admin/capabilities/a?x=1',
    '/admin/capabilities/a#f', '/admin/capabilities/a/', '/admin/capabilities']) {
    assert.ok(!DETAIL_RE.test(bad), 'must reject: ' + bad);
  }
  assert.ok(DETAIL_RE.test('/admin/capabilities/claude-code'));
  assert.ok(DETAIL_RE.test('/admin/capabilities/' + encodeURIComponent('a b')));
});

test('no /admin/capability (singular) endpoint typo (§17)', () => {
  assert.strictEqual(REAL_HTML.match(/\/admin\/capability(?![a-z])/g), null);
});

// Renamed deliberately: this scans a fixed marker list in one file. It cannot establish universal
// credential non-exposure, and N1 stays bounded/PARTIAL.
test('no listed sensitive markers present in the page source', () => {
  const low = REAL_HTML.toLowerCase();
  for (const bad of ['api_key', 'x-api-key', 'secret', 'password', 'chain_of_thought', 'scratchpad'])
    assert.ok(!low.includes(bad), 'listed marker present: ' + bad);
});

// ── mutation tests: each must be a real source change AND fail for its own specific reason ────
const MUTANTS = [
  ['unsafe initial endpoint', (h) => h.replace('fetch("/admin/capabilities.json"', 'fetch("/admin/evil.json"'),
    'UNAPPROVED_ENDPOINT:/admin/evil.json'],
  ['unsafe detail endpoint', (h) => h.replace('fetch("/admin/capabilities/"+encodeURIComponent(id)', 'fetch("/admin/evil/"+encodeURIComponent(id)'),
    'UNAPPROVED_ENDPOINT:/admin/evil/claude-code'],
  ['POST on the catalog request', (h) => h.replace('fetch("/admin/capabilities.json",{headers:', 'fetch("/admin/capabilities.json",{method:"POST",headers:'),
    'NON_GET:POST:/admin/capabilities.json'],
  ['POST on the detail request', (h) => h.replace('{headers:{Accept:"application/json"}})\n      .then(function(r){return r.json();}).then(function(c){', '{method:"POST",headers:{Accept:"application/json"}})\n      .then(function(r){return r.json();}).then(function(c){'),
    'NON_GET:POST:/admin/capabilities/claude-code'],
  ['absolute/off-origin detail URL', (h) => h.replace('fetch("/admin/capabilities/"+encodeURIComponent(id)', 'fetch("https://kai-prod-production.up.railway.app/admin/capabilities/"+encodeURIComponent(id)'),
    'OFF_ORIGIN:https://kai-prod-production.up.railway.app/admin/capabilities/claude-code'],
  ['/admin/kai/* detail URL', (h) => h.replace('fetch("/admin/capabilities/"+encodeURIComponent(id)', 'fetch("/admin/kai/capabilities/"+encodeURIComponent(id)'),
    'BRIDGE_OR_APPB:/admin/kai/capabilities/claude-code'],
  ['execution module loading', (h) => h.replace('<script>', '<script src="/admin/kai-nexus-capabilities.js"></script>\n<script>'),
    'EXEC_MODULE_LOADED'],
  ['execution control exposed', (h) => h.replace('</body>', '<button data-invoke="1">Run</button></body>'),
    'EXEC_CONTROL:button'],
];

for (const [name, mutate, expected] of MUTANTS) {
  test('MUTATION rejected — ' + name, async () => {
    const mutated = mutate(REAL_HTML);
    assert.notStrictEqual(mutated, REAL_HTML, 'mutation did not change the source — the test would be vacuous');
    const ctx = await loadPage(mutated);
    try { await clickFirstRow(ctx); } catch (_) { /* a mutant may break rendering; the initial-path violation still stands */ }
    const v = violations(ctx, mutated);
    assert.ok(v.includes(expected),
      `expected violation ${expected}; got ${JSON.stringify(v)}`);
  });
}
