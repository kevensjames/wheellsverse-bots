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
//      tokens afterwards; the session it created is revoked before the redirect
//      (when the refresh answers within the bound)
//   6. an ordinary refresh (no sign-out) still stores the rotated tokens
//   7. the redirect waits for the revoke's answer, and the bound also covers a
//      refresh in flight that never answers
//   8. an api() call that gets a 401 during sign-out waits for the sign-out
//      instead of navigating away first (that navigation would cancel the
//      revoke request in a browser)
//   9. sign-out works before core/api.js has loaded (the button is clickable
//      before the scripts at the end of app.html have run)
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
const SRC = Object.fromEntries(['router.js', 'api.js'].map(f => [f, readFileSync(join(CORE, f), 'utf8')]));
const API = 'https://sol-api.invalid';
const A = 'synthetic-access-1', R = 'synthetic-refresh-1';
const A2 = 'synthetic-access-2', R2 = 'synthetic-refresh-2';

const res = (status, body) => ({ status, ok: status >= 200 && status < 300, json: async () => body ?? {}, text: async () => JSON.stringify(body ?? {}) });
const deferred = () => { let resolve, reject; const p = new Promise((a, b) => { resolve = a; reject = b; }); return { p, resolve, reject }; };

// One fresh app context per scenario. `route(url, opts)` scripts the backend.
// `files` picks which core scripts have loaded (app.html order: router.js, api.js).
// `events` records the order of revoke answers and redirects.
function makeApp(route, stored = { sol_token: A, sol_refresh: R }, files = ['router.js', 'api.js']) {
  const store = new Map(Object.entries(stored));
  const calls = [];
  const hrefs = [];
  const events = [];
  const location = { search: '' };
  Object.defineProperty(location, 'href', { get: () => hrefs[hrefs.length - 1] || '', set: v => { hrefs.push(v); events.push('redirect'); } });
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
      const out = route(call);
      if (call.url === API + '/auth/logout') {
        let tok = null; try { tok = JSON.parse(call.body).refresh_token; } catch {}
        return Promise.resolve(out).then(r => { events.push('revoke-answered:' + tok); return r; });
      }
      return out;
    },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  for (const f of files) vm.runInContext(SRC[f], sandbox);
  const V = expr => vm.runInContext(expr, sandbox);
  const revokes = () => calls.filter(c => c.method === 'POST' && c.url === API + '/auth/logout');
  return { store, calls, hrefs, events, V, revokes };
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
  await out;
  ok(app.events.indexOf('revoke-answered:' + R2) !== -1 && app.events.indexOf('revoke-answered:' + R2) < app.events.indexOf('redirect'),
    'the late session was revoked BEFORE the redirect: ' + JSON.stringify(app.events));
  const got = await refreshing; await tick(); await tick();
  ok(got === false, 'the late refresh reports failure (api() must not retry as if refreshed)');
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

await scenario('[9] the redirect waits for the revoke to answer', async () => {
  const gate = deferred();
  const app = makeApp(() => gate.p);
  const out = app.V('logout()');
  await new Promise(r => setTimeout(r, 100));
  ok(app.hrefs.length === 0, 'no redirect while the revoke is pending');
  gate.resolve(res(204));
  await out;
  ok(app.events.indexOf('revoke-answered:' + R) === 0 && app.events[1] === 'redirect', 'revoke answered, then redirect: ' + JSON.stringify(app.events));
});

await scenario('[10] a refresh in flight that never answers: still bounded', async () => {
  const app = makeApp(call => (call.url === API + '/auth/refresh' ? new Promise(() => {}) : Promise.resolve(res(204))));
  app.V('_tryRefresh()');
  await tick();
  const t0 = Date.now();
  await app.V('logout()');
  const ms = Date.now() - t0;
  ok(app.hrefs[app.hrefs.length - 1] === '/sol/', 'redirected');
  ok(ms < 4500, `redirect within the bound although the refresh never answered (${ms} ms)`);
  ok(!app.store.has('sol_token') && !app.store.has('sol_refresh'), 'both tokens removed');
});

await scenario('[11] sign-out while the refresh body is still being read', async () => {
  const bodyGate = deferred();
  const app = makeApp(call => (call.url === API + '/auth/refresh'
    ? Promise.resolve({ status: 200, ok: true, json: () => bodyGate.p, text: async () => '' })
    : Promise.resolve(res(204))));
  const refreshing = app.V('_tryRefresh()');
  await tick(); await tick();
  const out = app.V('logout()');
  bodyGate.resolve({ access_token: A2, refresh_token: R2, token_type: 'bearer' });
  const got = await refreshing; await out; await tick();
  ok(got === false, 'refresh reports failure');
  ok(!app.store.has('sol_token') && !app.store.has('sol_refresh'), 'the late body did not store tokens');
  ok(app.V('token') !== A2, 'in-memory access token not replaced');
  ok(app.revokes().some(c => JSON.parse(c.body).refresh_token === R2), 'the late session was revoked');
});

await scenario('[12] an api() call gets a 401 during sign-out: it waits for the sign-out', async () => {
  const gate = deferred();
  const app = makeApp(call => (call.url === API + '/auth/logout' ? gate.p
    : call.url === API + '/groups' ? Promise.resolve(res(401, { detail: 'Invalid token' }))
    : Promise.resolve(res(204))));
  const out = app.V('logout()');
  const call = app.V("api('/groups')").then(() => 'resolved', e => 'rejected: ' + e.message);
  await new Promise(r => setTimeout(r, 100));
  ok(app.hrefs.length === 0, `no redirect while the revoke is pending (saw ${JSON.stringify(app.hrefs)})`);
  gate.resolve(res(204));
  await out; const outcome = await call; await tick();
  ok(app.hrefs.length === 1 && app.hrefs[0] === '/sol/', `exactly one redirect, by the sign-out (saw ${JSON.stringify(app.hrefs)})`);
  ok(app.events.indexOf('revoke-answered:' + R) !== -1 && app.events.indexOf('revoke-answered:' + R) < app.events.indexOf('redirect'), 'revoke answered before the redirect');
  ok(/^rejected/.test(outcome), 'the api() call fails instead of retrying (' + outcome + ')');
});

await scenario('[13] a refresh in flight answers 429 after sign-out: no early redirect', async () => {
  const refreshGate = deferred(), revokeGate = deferred();
  const app = makeApp(call => (call.url === API + '/auth/refresh' ? refreshGate.p
    : call.url === API + '/auth/logout' ? revokeGate.p
    : call.url === API + '/groups' ? Promise.resolve(res(401, { detail: 'Invalid token' }))
    : Promise.resolve(res(204))));
  const call = app.V("api('/groups')").then(() => 'resolved', e => 'rejected: ' + e.message);
  await tick(); await tick();
  const out = app.V('logout()');
  refreshGate.resolve(res(429, { detail: 'rate limited' }));
  await new Promise(r => setTimeout(r, 100));
  ok(app.hrefs.length === 0, `no redirect while the revoke is pending (saw ${JSON.stringify(app.hrefs)})`);
  revokeGate.resolve(res(204));
  await out; await call; await tick();
  ok(app.hrefs.length === 1, `exactly one redirect (saw ${JSON.stringify(app.hrefs)})`);
  ok(app.events.indexOf('revoke-answered:' + R) !== -1 && app.events.indexOf('revoke-answered:' + R) < app.events.indexOf('redirect'), 'the stored refresh token was revoked before the redirect');
});

await scenario('[14] sign-out clicked before core/api.js has loaded', async () => {
  const app = makeApp(() => Promise.resolve(res(204)), undefined, ['router.js']);
  let threw = null;
  try { await app.V('logout()'); } catch (e) { threw = e; }
  await tick();
  ok(threw === null, 'logout() does not throw' + (threw ? ' (' + threw.message + ')' : ''));
  ok(!app.store.has('sol_token') && !app.store.has('sol_refresh'), 'both tokens removed');
  ok(app.revokes().length === 1, 'the refresh session is still revoked');
  ok(app.hrefs[app.hrefs.length - 1] === '/sol/', 'redirected to /sol/');
});

await scenario('[15] a refresh in flight answers 50 ms after sign-out (within the bound)', async () => {
  const app = makeApp(call => (call.url === API + '/auth/refresh'
    ? new Promise(r => setTimeout(() => r(res(200, { access_token: A2, refresh_token: R2, token_type: 'bearer' })), 50))
    : Promise.resolve(res(204))));
  app.V('_tryRefresh()');
  await tick();
  await app.V('logout()');
  const iR2 = app.events.indexOf('revoke-answered:' + R2), iNav = app.events.indexOf('redirect');
  ok(iR2 !== -1 && iR2 < iNav, 'the session the late refresh created was revoked before the redirect: ' + JSON.stringify(app.events));
  ok(!app.store.has('sol_token') && !app.store.has('sol_refresh'), 'nothing stored');
});

console.log(`\nsign-out: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
