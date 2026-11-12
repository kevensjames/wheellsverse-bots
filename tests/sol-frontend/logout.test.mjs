// Sign-out regression test (pure Node, zero dependencies, no network).
//   node tests/sol-frontend/logout.test.mjs
//
// Loads the REAL core/router.js + core/api.js in a vm sandbox with an in-memory
// localStorage and a scripted fetch (synthetic tokens only; API points at a
// reserved .invalid host that is never contacted). It checks what logout() does
// in THIS client:
//   1. both stored tokens are gone (access AND refresh)
//   2. it asks the backend to revoke the refresh session: one POST /auth/logout
//      whose body is exactly {refresh_token} (the backend's LogoutRequest forbids
//      extra fields)
//   3. a revoke that fails, errors or hangs never keeps the user signed in here,
//      and a hang is bounded
//   4. repeated sign-out sends one revoke and redirects once
//   5. a refresh already in flight when the user signs out cannot store new
//      tokens afterwards; the session it created is revoked too
//   6. an ordinary refresh (no sign-out) still stores the rotated tokens
//
// What it does NOT prove: that the server revoked anything (the backend is not
// run here), or anything about the deployed frontend. Revoking the refresh
// session also does not end an access token already issued: the backend accepts
// that JWT until it expires.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const CORE = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'frontend', 'sol', 'app', 'core');
const SRC = ['router.js', 'api.js'].map(f => readFileSync(join(CORE, f), 'utf8'));
const API = 'https://sol-api.invalid';
const A = 'synthetic-access-1', R = 'synthetic-refresh-1';
const A2 = 'synthetic-access-2', R2 = 'synthetic-refresh-2';

const res = (status, body) => ({ status, ok: status >= 200 && status < 300, json: async () => body ?? {}, text: async () => JSON.stringify(body ?? {}) });
const deferred = () => { let resolve, reject; const p = new Promise((a, b) => { resolve = a; reject = b; }); return { p, resolve, reject }; };

// One fresh app context per scenario. `route(url, opts)` scripts the backend.
function makeApp(route, stored = { sol_token: A, sol_refresh: R }) {
  const store = new Map(Object.entries(stored));
  const calls = [];
  const hrefs = [];
  const location = { search: '' };
  Object.defineProperty(location, 'href', { get: () => hrefs[hrefs.length - 1] || '', set: v => hrefs.push(v) });
  const noop = () => {};
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, AbortController, DOMException, URLSearchParams, JSON,
    API, token: A, me: null,
    window: { location }, location,
    localStorage: {
      getItem: k => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => store.set(k, String(v)),
      removeItem: k => store.delete(k),
    },
    document: { querySelectorAll: () => [], querySelector: () => null, getElementById: () => null },
    fetch: (url, opts = {}) => {
      const call = { url: String(url), method: (opts.method || 'GET').toUpperCase(), headers: opts.headers || {}, body: opts.body };
      calls.push(call);
      return route(call);
    },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  for (const s of SRC) vm.runInContext(s, sandbox);
  const V = expr => vm.runInContext(expr, sandbox);
  const revokes = () => calls.filter(c => c.method === 'POST' && c.url === API + '/auth/logout');
  return { store, calls, hrefs, V, revokes };
}

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('  ✓', m); } else { fail++; console.log('  ✗ FAIL:', m); } };
const scenario = async (name, fn) => {
  console.log('\n' + name);
  try { await fn(); } catch (e) { fail++; console.log('  ✗ FAIL: threw', String(e && e.stack || e).split('\n')[0]); }
};
const tick = () => new Promise(r => setTimeout(r, 0));

await scenario('[1] tokens and revoke on a normal sign-out (server answers 204)', async () => {
  const app = makeApp(() => Promise.resolve(res(204)));
  await app.V('logout()');
  await tick();
  ok(!app.store.has('sol_token'), 'access token removed');
  ok(!app.store.has('sol_refresh'), 'refresh token removed');
  ok(app.V('token') !== A, 'in-memory access token cleared');
  const rv = app.revokes();
  ok(rv.length === 1, `exactly one POST /auth/logout (saw ${rv.length})`);
  if (rv[0]) {
    let body = null; try { body = JSON.parse(rv[0].body); } catch {}
    ok(body && JSON.stringify(Object.keys(body)) === '["refresh_token"]' && body.refresh_token === R, 'body is exactly {refresh_token: <stored refresh token>}');
    ok(/application\/json/.test(rv[0].headers['Content-Type'] || ''), 'JSON content type');
  }
  ok(app.hrefs.length === 1 && app.hrefs[0] === '/sol/', 'redirected once to /sol/');
});

for (const [label, route] of [
  ['500 from the server', () => Promise.resolve(res(500, { detail: 'boom' }))],
  ['network error', () => Promise.reject(new TypeError('Failed to fetch'))],
  ['fetch throws synchronously', () => { throw new TypeError('blocked'); }],
]) {
  await scenario(`[2] revoke fails (${label}): still signed out here`, async () => {
    const app = makeApp(route);
    await app.V('logout()');
    await tick();
    ok(!app.store.has('sol_token') && !app.store.has('sol_refresh'), 'both tokens removed');
    ok(app.revokes().length === 1, 'revoke was attempted once');
    ok(app.hrefs[app.hrefs.length - 1] === '/sol/', 'redirected to /sol/');
  });
}

await scenario('[3] revoke hangs: tokens cleared at once, redirect bounded', async () => {
  const app = makeApp(() => new Promise(() => {}));
  const t0 = Date.now();
  const p = app.V('logout()');
  ok(!app.store.has('sol_token') && !app.store.has('sol_refresh'), 'both tokens removed before the server answers');
  await p;
  const ms = Date.now() - t0;
  ok(app.hrefs[app.hrefs.length - 1] === '/sol/', 'redirected although the server never answered');
  ok(ms < 4500, `redirect within the bound (${ms} ms)`);
});

await scenario('[4] repeated sign-out: one revoke, one redirect', async () => {
  const gate = deferred();
  const app = makeApp(() => gate.p);
  const p1 = app.V('logout()');
  const p2 = app.V('logout()');
  gate.resolve(res(204));
  await Promise.all([p1, p2]);
  await app.V('logout()');
  await tick();
  ok(app.revokes().length === 1, `one POST /auth/logout for three clicks (saw ${app.revokes().length})`);
  ok(app.hrefs.length === 1, `one redirect (saw ${app.hrefs.length})`);
});

await scenario('[5] no refresh token stored: no revoke request, still signed out', async () => {
  const app = makeApp(() => Promise.resolve(res(204)), { sol_token: A });
  await app.V('logout()');
  await tick();
  ok(app.revokes().length === 0, 'no request without a refresh token');
  ok(!app.store.has('sol_token'), 'access token removed');
  ok(app.hrefs[app.hrefs.length - 1] === '/sol/', 'redirected to /sol/');
});

await scenario('[6] refresh in flight when the user signs out', async () => {
  const refreshGate = deferred();
  const app = makeApp(call => (call.url === API + '/auth/refresh' ? refreshGate.p : Promise.resolve(res(204))));
  const refreshing = app.V('_tryRefresh()');       // e.g. a 401 on a background load
  await tick();
  const out = app.V('logout()');
  refreshGate.resolve(res(200, { access_token: A2, refresh_token: R2, token_type: 'bearer' }));
  await refreshing; await out; await tick(); await tick();
  ok(app.store.get('sol_token') !== A2 && !app.store.has('sol_token'), 'the late refresh did not store a new access token');
  ok(app.store.get('sol_refresh') !== R2 && !app.store.has('sol_refresh'), 'the late refresh did not store a new refresh token');
  ok(app.V('token') !== A2, 'in-memory access token not replaced by the late refresh');
  const bodies = app.revokes().map(c => { try { return JSON.parse(c.body).refresh_token; } catch { return null; } });
  ok(bodies.includes(R), 'the stored refresh token was revoked');
  ok(bodies.includes(R2), 'the session created by the late refresh was revoked too');
  ok(app.hrefs[app.hrefs.length - 1] === '/sol/', 'redirected to /sol/');
});

await scenario('[7] refresh in flight is rejected by the server after sign-out', async () => {
  const refreshGate = deferred();
  const app = makeApp(call => (call.url === API + '/auth/refresh' ? refreshGate.p : Promise.resolve(res(204))));
  const refreshing = app.V('_tryRefresh()');
  await tick();
  const out = app.V('logout()');
  refreshGate.resolve(res(401, { detail: 'Invalid or expired refresh token' }));
  const got = await refreshing; await out; await tick();
  ok(got === false, 'refresh reports failure');
  ok(!app.store.has('sol_token') && !app.store.has('sol_refresh'), 'nothing stored');
  ok(app.revokes().length === 1, `only the stored token was revoked (saw ${app.revokes().length})`);
});

await scenario('[8] ordinary refresh without sign-out still stores rotated tokens', async () => {
  const app = makeApp(call => (call.url === API + '/auth/refresh'
    ? Promise.resolve(res(200, { access_token: A2, refresh_token: R2, token_type: 'bearer' }))
    : Promise.resolve(res(204))));
  const got = await app.V('_tryRefresh()');
  ok(got === true, 'refresh succeeds');
  ok(app.store.get('sol_token') === A2 && app.store.get('sol_refresh') === R2, 'rotated tokens stored');
  ok(app.V('token') === A2, 'in-memory access token updated');
  ok(app.revokes().length === 0, 'no revoke request');
});

console.log(`\nsign-out: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
