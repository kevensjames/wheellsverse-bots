/* App A page contract test (§16/§17) — mechanical, not visual.
 * Verifies kai-capabilities.html wires the TESTED module + uses the owner-only bridge, with no
 * endpoint typos and no direct App B URL. Run: node test_capabilities_page_contract.js */
const assert = require('assert');
const fs = require('fs');
const html = fs.readFileSync(__dirname + '/kai-capabilities.html', 'utf8');

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

test('loads the tested execution module (no duplicated logic §3)', () => {
  assert.ok(html.includes('src="/admin/kai-nexus-capabilities.js"'), 'must <script src> the module');
  assert.ok(html.includes('window.NexusCapabilities'), 'must use the module global');
  assert.ok(html.includes('CapabilityConsole('), 'must use the module CapabilityConsole, not reimplement');
});

test('execution talks ONLY to the owner-only bridge, never App B directly (§4)', () => {
  assert.ok(html.includes("base: \"/admin/kai/capabilities\""), 'console base must be the bridge path');
  assert.ok(!/kai-prod|railway\.app|kai\.wheellsverse\.com/.test(html), 'no direct App B / kai-prod URL in the page');
});

test('no /admin/capability (singular) endpoint typo (§17)', () => {
  // every capability path must be the plural /admin/capabilities* — catch the classic mistake
  const singular = html.match(/\/admin\/capability(?![a-z])/g);
  assert.strictEqual(singular, null, 'found /admin/capability (singular) — must be /admin/capabilities');
});

test('catalog DISPLAY stays on App A; EXECUTION uses the bridge (§16 split)', () => {
  assert.ok(html.includes('/admin/capabilities.json'), 'catalog display fetches App A /admin/capabilities.json');
  assert.ok(html.includes('/admin/kai/capabilities'), 'execution goes through the bridge /admin/kai/capabilities');
});

test('bridge exec endpoints match App B routes (list/test/invocations) (§17)', () => {
  // the module builds base, base+/{id}/test, base+/invocations → App B /admin/capabilities{,/{id}/test,/invocations}
  const mod = fs.readFileSync(__dirname + '/kai-nexus-capabilities.js', 'utf8');
  assert.ok(mod.includes("'/test'"), 'module posts /{id}/test');
  assert.ok(mod.includes("'/invocations'"), 'module gets /invocations');
});

test('flag-OFF UX: page renders EXECUTION DISABLED, not error spam (§11)', () => {
  assert.ok(/EXECUTION&nbsp;DISABLED|DISABLED/.test(html), 'must show a DISABLED state');
  assert.ok(html.includes('catalog browsing only') || html.includes('Catalog browsing'), 'catalog still browsable when off');
});

test('no secrets / reasoning surfaced in the page (§8/§10)', () => {
  assert.ok(html.includes('No credentials'), 'reaffirms no credentials shown');
  assert.ok(!/chain.of.thought|reasoning_trace|private reasoning shown/i.test(html));
});

console.log('\n' + pass + ' passed');
