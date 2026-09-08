// Admin read-boundary UI contract (hotfix: anonymous /admin JSON).
//
// Four App A surfaces became owner-gated. Both pages that read them now receive 401 where they used
// to receive data, and the danger of THAT is specific: a page that treats an auth failure as "no
// data" renders "0 jobs", "not configured", or an empty capability catalogue — which is a fabricated
// operational claim, and a worse defect than the exposure being fixed.
//
// So this does not grep for strings. It EXECUTES each page's real script against a stubbed DOM and a
// stubbed fetch, and asserts what an operator would actually read on screen.
//
// Run: node test_admin_read_boundary_ui.js
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');

let pass = 0, total = 0;
const test = (n, f) => {
  total++;
  return Promise.resolve().then(f).then(
    () => { pass++; console.log('  ok  ' + n); },
    e => { console.error('FAIL  ' + n + '\n      ' + (e && e.message)); process.exitCode = 1; });
};

// ── a DOM small enough to read, real enough to run these two pages ────────────────────────────────
// kai-capabilities.html escapes with `d = createElement('div'); d.textContent = s; return d.innerHTML`,
// so a detached element MUST turn textContent into escaped innerHTML. A stub that does not will make
// esc() return '' — every label silently disappears and the test reads it as "nothing rendered".
function makeDom() {
  const nodes = {};
  const mkEl = (id) => {
    const el = {
      id, innerHTML: '', _text: '', _classes: new Set(),
      classList: { add(c) { el._classes.add(c); }, remove(c) { el._classes.delete(c); },
                   contains: c => el._classes.has(c) },
      addEventListener() {}, querySelectorAll: () => [], setAttribute() {}, getAttribute: () => null,
    };
    Object.defineProperty(el, 'textContent', {
      get: () => el._text,
      set(v) {
        el._text = String(v == null ? '' : v);
        el.innerHTML = el._text.replace(/&/g, '&amp;').replace(/</g, '&lt;')
                               .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
      },
    });
    return el;
  };
  const node = id => (nodes[id] = nodes[id] || mkEl(id));
  return {
    nodes,
    document: { getElementById: node, querySelectorAll: () => [], addEventListener() {},
                createElement: () => mkEl('_detached'), body: node('_body') },
    // Everything painted anywhere on the page, so an assertion cannot miss the panel it landed in.
    screen: () => Object.values(nodes).map(n => (n.innerHTML || '') + ' ' + (n.textContent || ''))
                        .join(' ').replace(/<[^>]*>/g, ' ').replace(/&#39;/g, "'")
                        .replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim(),
  };
}

// Both pages wrap everything in `(function(){ "use strict"; ... })();`. Unwrapping it puts the page's
// own functions in the VM's global scope so a test can call one directly — the alternative is
// re-implementing them here, which would test the copy instead of the page.
const scriptOf = (file, { unwrap = false } = {}) => {
  const html = fs.readFileSync(__dirname + '/' + file, 'utf8');
  const blocks = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
  assert.ok(blocks.length, file + ' has no inline <script>');
  let src = blocks.join('\n;\n');
  if (unwrap) {
    const open = src.indexOf('(function(){');
    const close = src.lastIndexOf('})();');
    assert.ok(open >= 0 && close > open, file + ' is no longer a single IIFE — update this harness');
    src = src.slice(open + '(function(){'.length, close).replace(/^\s*"use strict";/, '');
  }
  return src;
};

// Runs a page with a fetch that answers `status` for every request. Resolves once the promise
// chain has settled.
function runPage(file, status, body) {
  const dom = makeDom();
  const calls = [];
  const fetchStub = (url, opts) => {
    calls.push({ url, opts });
    return Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(status === 401
        ? { detail: 'owner authentication required' }
        : (typeof body === 'function' ? body(url) : body)),
    });
  };
  const ctx = vm.createContext({ document: dom.document, fetch: fetchStub, window: {},
                                 console, setTimeout, location: { pathname: '/admin/x' } });
  vm.runInContext(scriptOf(file), ctx);
  // let the stubbed promise chain drain
  return new Promise(r => setImmediate(() => setImmediate(() => setImmediate(r))))
    .then(() => ({ dom, calls, screen: dom.screen() }));
}

// One node's rendered text. Assertions about a specific panel must use this, never screen() — a
// page-wide match can be satisfied by a neighbouring panel and will pass a mutant.
const text = n => String((n && n.innerHTML) || '').replace(/<[^>]*>/g, ' ')
                    .replace(/&#39;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim();

const FABRICATIONS = [
  /\b0 jobs\b/i, /no jobs registered/i, /\bnot configured\b/i, /\bOFF\b/,
  /NOT CONNECTED/i, /\bstopped\b/i,
];

const AUTOMATIONS_OK = {
  generated_at: '2026-09-08T00:00:00Z',
  autopilot: { enabled: true, mode: 'full', hourly_cycles: 3, daily_cycles: 1,
               total_posts_auto: 7, recent_errors: [], last_hourly_run: 'x', last_daily_run: 'y' },
  automation: { email_configured: true, slack_configured: false, discord_configured: false,
                queue_size: 0, delivery_log_count: 0 },
  scheduler: { running: true, total: 137, jobs: [{ bot: 'aeo/102_aeo_audit',
                                                   schedule: '@weekly mon 10:00',
                                                   next_run: '2026-09-14T10:00:00' }] },
};

const CAPS_OK = {
  version: '1', count: 1, source: 'CapabilityRegistry',
  capabilities: [{ id: 'kai-memory', name: 'KAI Memory', type: 'NATIVE_KAI_TOOL', group: 'g',
                   availability: 'AVAILABLE', certification: 'CERTIFIED', activation: 'AUTO',
                   risk_class: 'P1', security_tier: 'T1', automatic_activation_allowed: false,
                   capabilities: [], dependencies: [], conflicts: [], permissions: [],
                   runtime: { kai_server: 'AVAILABLE', claude_local: 'NONE' },
                   provenance: { upstream: 'u', owner: 'o', license: 'l', ref: 'r' }, notes: '' }],
};

(async () => {
  // ── automations.html ────────────────────────────────────────────────────────────────────────────
  await test('automations: a 401 renders an honest failure, never a fabricated idle system', async () => {
    const { screen } = await runPage('automations.html', 401);
    assert.ok(/could not load automations/i.test(screen),
              'no honest failure message on screen: ' + screen.slice(0, 200));
    assert.ok(/nothing fabricated/i.test(screen), 'the page did not disclaim fabrication');
    for (const bad of FABRICATIONS) {
      assert.ok(!bad.test(screen),
                'a 401 was rendered as real operational state matching ' + bad + ': ' + screen.slice(0, 200));
    }
  });

  await test('automations: the 401 status reaches the operator, so it is diagnosable', async () => {
    const { screen } = await runPage('automations.html', 401);
    assert.ok(/401/.test(screen), 'the operator cannot tell an auth failure from an outage');
  });

  await test('automations: an authorized 200 still renders the real inventory', async () => {
    const { screen } = await runPage('automations.html', 200, AUTOMATIONS_OK);
    assert.ok(/aeo\/102_aeo_audit/.test(screen), 'the job table did not render');
    assert.ok(/137/.test(screen), 'the job total did not render');
    assert.ok(!/could not load/i.test(screen), 'a successful load reported a failure');
  });

  await test('automations: it asks for JSON explicitly', async () => {
    const { calls } = await runPage('automations.html', 200, AUTOMATIONS_OK);
    const c = calls.find(c => String(c.url).includes('/admin/automations.json'));
    assert.ok(c, 'the page never requested /admin/automations.json');
    assert.equal((c.opts && c.opts.headers || {}).Accept, 'application/json');
  });

  // ── kai-capabilities.html ───────────────────────────────────────────────────────────────────────
  await test('capabilities: a 401 says sign-in required, never an empty catalogue', async () => {
    const { screen } = await runPage('kai-capabilities.html', 401);
    assert.ok(/owner sign-in required/i.test(screen),
              'no sign-in prompt on screen: ' + screen.slice(0, 200));
    assert.ok(/not an empty catalogue/i.test(screen),
              'the page let 401 read as "there are no capabilities"');
    assert.ok(!/fabric/i.test(screen),
              'a 401 blamed KAI_CAPABILITY_FABRIC_ENABLED and sends the operator to the wrong setting');
  });

  await test('capabilities: an authorized 200 still renders the catalogue', async () => {
    const { screen } = await runPage('kai-capabilities.html', 200, CAPS_OK);
    assert.ok(/KAI Memory/.test(screen), 'the catalogue did not render');
    assert.ok(!/sign-in required/i.test(screen), 'a successful load demanded sign-in');
  });

  // The detail drawer is the regression this hotfix could have introduced: inspect() did not check
  // r.ok, so a 401 body parsed as JSON and died on `c.runtime.kai_server` — an uncaught rejection
  // with nothing on screen.
  await test('capabilities: inspect() survives a 401 and explains it', async () => {
    const dom = makeDom();
    let rejected = null;
    const ctx = vm.createContext({
      document: dom.document, window: {}, console, setTimeout, location: { pathname: '/admin/x' },
      fetch: () => Promise.resolve({ ok: false, status: 401,
                                     json: () => Promise.resolve({ detail: 'owner authentication required' }) }),
    });
    process.once('unhandledRejection', e => { rejected = e; });
    vm.runInContext(scriptOf('kai-capabilities.html', { unwrap: true })
                    + '\n;globalThis.__inspect = inspect;', ctx);
    ctx.__inspect('kai-memory');
    await new Promise(r => setImmediate(() => setImmediate(() => setImmediate(r))));
    // Scoped to the INSPECTOR node, not the whole page. The catalogue panel renders its own
    // "Owner sign-in required" from the same 401, and asserting against the whole screen let a
    // mutant that removed inspect()'s r.ok check pass on the neighbouring panel's text.
    const drawer = text(dom.nodes.inspector);
    assert.ok(!rejected, 'inspect() threw on a 401: ' + (rejected && rejected.message));
    assert.ok(/detail unavailable/i.test(drawer), 'the drawer showed nothing: ' + drawer.slice(0, 200));
    assert.ok(/owner sign-in required/i.test(drawer), 'the drawer did not name the cause: ' + drawer.slice(0, 200));
    assert.ok(!/cannot read propert/i.test(drawer), 'a TypeError leaked into the drawer');
  });

  await test('capabilities: inspect() still renders a capability for an authorized reader', async () => {
    const dom = makeDom();
    const ctx = vm.createContext({
      document: dom.document, window: {}, console, setTimeout, location: { pathname: '/admin/x' },
      fetch: () => Promise.resolve({ ok: true, status: 200,
                                     json: () => Promise.resolve(CAPS_OK.capabilities[0]) }),
    });
    vm.runInContext(scriptOf('kai-capabilities.html', { unwrap: true })
                    + '\n;globalThis.__inspect = inspect;', ctx);
    ctx.__inspect('kai-memory');
    await new Promise(r => setImmediate(() => setImmediate(() => setImmediate(r))));
    const screen = text(dom.nodes.inspector);
    assert.ok(/KAI Memory/.test(screen), 'the drawer did not render the capability');
    assert.ok(/No credentials are ever shown/i.test(screen), 'the credential disclaimer was lost');
    assert.ok(!/detail unavailable/i.test(screen), 'a successful inspect reported failure');
  });

  // ── neither page may echo a credential ──────────────────────────────────────────────────────────
  await test('neither page reflects a credential on any path', async () => {
    for (const file of ['automations.html', 'kai-capabilities.html']) {
      for (const [status, body] of [[401, null], [200, file === 'automations.html' ? AUTOMATIONS_OK : CAPS_OK]]) {
        const { screen } = await runPage(file, status, body);
        for (const pat of [/x-api-key/i, /api_key=/i, /wv_session/i, /verifier-token/i, /Bearer\s+\S/i]) {
          assert.ok(!pat.test(screen), file + ' @' + status + ' reflected ' + pat);
        }
      }
    }
  });

  console.log('\nADMIN READ-BOUNDARY UI TESTS: ' + pass + '/' + total + ' — ' + (pass === total ? 'PASS' : 'FAIL'));
  if (pass !== total) process.exitCode = 1;
})();
