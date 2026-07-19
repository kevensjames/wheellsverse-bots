// P3 route-cancellation money-safety test (pure Node, zero dependencies).
//   node frontend/sol/app/tests/route-abort.test.mjs
//
// Loads the REAL core/router.js + core/api.js in a vm sandbox (with minimal DOM
// and a recording fetch), and proves the invariant the app depends on:
//   • nav() aborts the previous route's controller and mints a fresh one
//   • a GET route-load carries the route AbortSignal
//   • a mutation (POST/PATCH/DELETE) NEVER carries it — so navigating away can
//     never cancel a payment / join / subscribe / cancel (money-safety)
//   • a GET can opt out with { noAbort: true } (the background unread badge)
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const CORE = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'frontend', 'sol', 'app', 'core');
const noop = () => {};
const stubEl = { classList: { add: noop, remove: noop, contains: () => false }, setAttribute: noop, removeAttribute: noop, focus: noop };

// Recording fetch: captures the signal each request was issued with.
const calls = [];
const sandbox = {
  console, setTimeout, clearTimeout, Promise, AbortController, DOMException, URLSearchParams,
  API: '', token: 'tok', me: { id: 'u1' },
  window: { location: { search: '', href: '' } },
  location: { search: '', href: '' },
  localStorage: { getItem: () => null, setItem: noop, removeItem: noop },
  document: { querySelectorAll: () => [], querySelector: () => null, getElementById: () => stubEl },
  fetch: async (url, opts = {}) => {
    calls.push({ url: String(url), method: (opts.method || 'GET').toUpperCase(), signal: opts.signal || null });
    return { status: 200, ok: true, json: async () => ({}), text: async () => '{}' };
  },
};
// nav() dispatches to these loaders — stub them all as no-ops.
for (const fn of ['loadGroups', 'loadKYC', 'loadBank', 'loadMyPayments', 'loadDiscover', 'loadTimeline',
  'loadTrust', 'loadPremium', 'loadNotifications', 'loadCommunity', 'loadGoals', 'loadDashboard',
  'consumePendingInvite', 'refreshUnread', 'init']) sandbox[fn] = noop;
sandbox.globalThis = sandbox;
vm.createContext(sandbox);
vm.runInContext(readFileSync(join(CORE, 'router.js'), 'utf8'), sandbox);
vm.runInContext(readFileSync(join(CORE, 'api.js'), 'utf8'), sandbox);

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) pass++; else { fail++; console.log('  ✗ FAIL:', m); } };
const lastSignal = () => calls[calls.length - 1].signal;
// Top-level `let`/`const` (e.g. _routeAbort) live in the context's lexical scope,
// not on the sandbox object, so read/drive them by evaluating IN the context.
const V = (expr) => vm.runInContext(expr, sandbox);

await (async () => {
  // 1. nav() manages the route controller
  V("nav('goals')");
  const c1 = V('_routeAbort');
  ok(c1 && !c1.signal.aborted, 'nav() mints a fresh, un-aborted controller');
  V("nav('bank')");
  ok(c1.signal.aborted === true, 'nav() aborts the previous route controller');
  ok(V('_routeAbort') !== c1 && !V('_routeAbort').signal.aborted, 'nav() installs a new controller');

  // 2. GET route-load carries the current route signal
  V("nav('goals')");
  await V("api('/goals')");
  ok(lastSignal() === V('_routeAbort').signal, 'GET carries the route AbortSignal');

  // 3. MUTATIONS never carry the signal (money-safety) — for every write method
  for (const method of ['POST', 'PATCH', 'PUT', 'DELETE']) {
    await V(`api('/payments/initiate', { method: '${method}', body: '{}' })`);
    ok(lastSignal() === null, `${method} carries NO signal (survives navigation)`);
  }

  // 4. GET opt-out (the background unread-badge refresh)
  await V("api('/notifications', { noAbort: true })");
  ok(lastSignal() === null, 'GET with { noAbort:true } carries no signal');

  // 5. explicit signal always wins
  sandbox.__own = new AbortController();
  await V("api('/goals', { signal: __own.signal })");
  ok(lastSignal() === sandbox.__own.signal, 'an explicit opts.signal is preserved');

  console.log(`\nP3 route-abort: ${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
