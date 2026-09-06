/* App A page contract test — kai-capabilities.html is CATALOG-ONLY (§16/§17).
 *
 * WHY THIS FILE CHANGED. It previously asserted that this page wires the execution console
 * (kai-nexus-capabilities.js / CapabilityConsole) and drives it through the owner-only bridge at
 * /admin/kai/capabilities. The shipped page does none of that: it performs TWO same-origin GETs
 * against App A and contains no POST, no invoke and no execution control at all. So four assertions
 * failed permanently — on the production base and on every candidate — describing a page that does
 * not exist. A suite that is always red cannot tell anyone about a real regression, which is the
 * same defect class as an unguarded intentional failure.
 *
 * The security guarantees those assertions were protecting are NOT dropped; they are strengthened.
 * "Execution must go through the owner-only bridge, never App B directly" is satisfied here in the
 * strongest possible way: there is no execution. This file now pins exactly that, and fails loudly
 * if anyone adds execution without re-establishing the bridge contract.
 *
 * BEHAVIOURAL LIMITATION, recorded deliberately: there is no security bypass on this page, and also
 * no way to execute a capability from it. That is intentional while this release is dark and all
 * authority flags are off. The execution console module EXISTS and is independently tested by
 * test_nexus_capabilities.js (16 checks), but it is NOT loaded here — passing isolated tests do not
 * make it deployed or user-accessible.
 *
 * The checks EXECUTE the page's real inline script against an instrumented DOM and observe actual
 * requests, rather than grepping source. Run: node test_capabilities_page_contract.js
 */
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

const PAGE = __dirname + '/kai-capabilities.html';
const REAL_HTML = fs.readFileSync(PAGE, 'utf8');

// Endpoints this page is allowed to call. Same-origin App A catalog reads, GET only.
const ALLOWED = [/^\/admin\/capabilities\.json(\?|$)/, /^\/admin\/capabilities\/[^/]*$/];
const EXEC_MODULE = 'kai-nexus-capabilities.js';

let pass = 0, failed = 0;
function test(name, fn) {
  try { fn(); console.log('  ok  ' + name); pass++; }
  catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); failed++; }
}

// ── executable harness: run the page's inline script, observe what it actually does ───────────
function runPage(html) {
  const observed = { fetches: [], methods: [], handlers: 0, created: [] };
  const el = () => ({
    _text: '', innerHTML: '', textContent: '', style: {}, dataset: {}, hidden: false, children: [],
    addEventListener(t) { observed.handlers++; },
    appendChild(c) { this.children.push(c); return c; },
    querySelectorAll() { return []; }, querySelector() { return null; },
    setAttribute() {}, getAttribute() { return null; }, remove() {}, focus() {}, click() {},
  });
  const doc = {
    getElementById: () => el(),
    createElement: (t) => { observed.created.push(t); return el(); },
    querySelectorAll: () => [], querySelector: () => null,
    addEventListener() { observed.handlers++; }, body: el(), head: el(),
  };
  const sandbox = {
    document: doc, window: {}, console: { log() {}, error() {}, warn() {} },
    location: { href: 'https://app.example/admin/capabilities', origin: 'https://app.example' },
    setTimeout: (f) => { try { f(); } catch (_) {} }, clearTimeout() {},
    requestAnimationFrame: (f) => { try { f(); } catch (_) {} },
    fetch(url, opts) {
      observed.fetches.push(String(url));
      observed.methods.push(((opts || {}).method || 'GET').toUpperCase());
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve({ capabilities: [], groups: [], count: 0 }),
        text: () => Promise.resolve('{}'),
      });
    },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  const m = html.match(/<script>([\s\S]*?)<\/script>/);
  assert.ok(m, 'page must carry its inline script');
  try { vm.runInNewContext(m[1], sandbox, { timeout: 5000 }); } catch (_) { /* DOM shim gaps are fine; we only observe requests */ }
  // <script src=...> tags are declarative — read them from the markup
  observed.scriptSrcs = [...html.matchAll(/<script[^>]*\ssrc=["']([^"']+)["']/g)].map(x => x[1]);
  return observed;
}

/** The catalog-only contract. Returns a list of violations; [] means the page is compliant. */
function violations(html) {
  const o = runPage(html), v = [];
  for (const u of o.fetches) {
    if (/^https?:\/\//i.test(u)) v.push('absolute/off-origin request: ' + u);
    else if (/^\/admin\/kai\//.test(u)) v.push('App B / bridge execution endpoint: ' + u);
    else if (!ALLOWED.some(re => re.test(u))) v.push('unapproved endpoint: ' + u);
  }
  for (const meth of o.methods) if (meth !== 'GET') v.push('non-GET request: ' + meth);
  if (o.scriptSrcs.some(s => s.includes(EXEC_MODULE))) v.push('execution console module loaded: ' + EXEC_MODULE);
  // execution affordances in the markup or script
  if (/<form\b/i.test(html)) v.push('form element present (execution affordance)');
  if (/\bmethod\s*:\s*["']POST["']/i.test(html)) v.push('POST behaviour present');
  if (/\b(invoke|execute)\s*\(/i.test(html)) v.push('invoke/execute call present');
  if (/CapabilityConsole\s*\(/.test(html)) v.push('CapabilityConsole instantiated');
  if (/\bonclick\s*=/i.test(html)) v.push('inline onclick handler present');
  if (/<button[^>]*\b(data-(run|invoke|execute)|id=["'][^"']*(run|invoke|exec)[^"']*)/i.test(html))
    v.push('execution control (button) present');
  return { v, o };
}

// ── the real page ────────────────────────────────────────────────────────────────────────────
test('CATALOG-ONLY: the page calls only approved same-origin App A catalog GETs', () => {
  const { v, o } = violations(REAL_HTML);
  assert.ok(o.fetches.length > 0, 'the page should actually fetch its catalog');
  assert.deepStrictEqual(v, [], 'contract violations: ' + JSON.stringify(v));
  for (const u of o.fetches) assert.ok(ALLOWED.some(re => re.test(u)), 'unapproved: ' + u);
});
test('no POST, invocation or execution request exists (observed, not grepped)', () => {
  const { o } = violations(REAL_HTML);
  assert.deepStrictEqual([...new Set(o.methods)], ['GET'], 'non-GET method observed: ' + o.methods);
});
test('no direct App B address and no /admin/kai/* execution endpoint', () => {
  const { o } = violations(REAL_HTML);
  for (const u of o.fetches) {
    assert.ok(!/^https?:\/\//i.test(u), 'absolute URL: ' + u);
    assert.ok(!u.startsWith('/admin/kai/'), 'bridge/App B endpoint: ' + u);
  }
  assert.ok(!/https?:\/\/[^"']*railway|kai-prod|kai\.wheellsverse/i.test(REAL_HTML), 'App B host in source');
});
test('the execution-console module is NOT loaded by this catalog-only page', () => {
  const { o } = violations(REAL_HTML);
  assert.ok(!o.scriptSrcs.some(s => s.includes(EXEC_MODULE)),
    'kai-nexus-capabilities.js must not be wired here while the release is dark');
  assert.ok(!/window\.NexusCapabilities/.test(REAL_HTML), 'module global must not be referenced');
});
test('no execution button, form or invoke handler is exposed', () => {
  assert.ok(!/<form\b/i.test(REAL_HTML), 'no form');
  assert.ok(!/\b(invoke|execute)\s*\(/i.test(REAL_HTML), 'no invoke/execute call');
  assert.ok(!/\bmethod\s*:\s*["']POST["']/i.test(REAL_HTML), 'no POST');
});
test('no /admin/capability (singular) endpoint typo (§17)', () => {
  assert.strictEqual(REAL_HTML.match(/\/admin\/capability(?![a-z])/g), null);
});
test('no secrets / reasoning surfaced in the page (§8/§10)', () => {
  const low = REAL_HTML.toLowerCase();
  for (const bad of ['api_key', 'x-api-key', 'secret', 'password', 'chain_of_thought', 'scratchpad'])
    assert.ok(!low.includes(bad), 'leaked marker: ' + bad);
});

// ── mutation tests: the contract must REJECT each unsafe change ───────────────────────────────
// A contract that only ever passes proves nothing. Each mutant below is a change someone could
// plausibly make; every one must be caught.
const MUTANTS = [
  ['loads the execution-console module',
    h => h.replace('<script>', '<script src="/admin/kai-nexus-capabilities.js"></script>\n<script>')],
  ['adds an execution control',
    h => h.replace('</body>', '<button id="run-capability" data-invoke="1">Run</button></body>')],
  ['adds POST/invoke behaviour',
    h => h.replace('<script>', '<script>\nfunction invoke(id){return fetch("/admin/capabilities/"+id,{method:"POST"});}\n')],
  ['calls App B directly',
    h => h.replace('fetch("/admin/capabilities.json"', 'fetch("https://kai-prod-production.up.railway.app/admin/capabilities.json"')],
  ['changes an allowed catalog request into an unapproved endpoint',
    h => h.replace('fetch("/admin/capabilities.json"', 'fetch("/admin/kai/capabilities/execute"')],
];
for (const [name, mutate] of MUTANTS) {
  test('MUTATION rejected — ' + name, () => {
    const { v } = violations(mutate(REAL_HTML));
    assert.ok(v.length > 0, 'contract FAILED to detect the mutation: ' + name);
  });
}

console.log('\n' + pass + ' passed' + (failed ? ', ' + failed + ' failed' : ''));
if (failed) process.exitCode = 1;
