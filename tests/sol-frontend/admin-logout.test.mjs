// Admin portal sign-out regression test (pure Node, zero dependencies, no network).
//   node tests/sol-frontend/admin-logout.test.mjs
//
// Loads the REAL inline script of frontend/sol/admin.html in a vm sandbox with an
// in-memory sessionStorage, stub DOM elements and a scripted fetch (synthetic tokens; the
// API constant is rewritten to a reserved .invalid host that is never contacted). Checks:
//   1. adminLogout() removes the admin access AND refresh tokens and asks the backend to
//      revoke the refresh session: one POST /auth/logout with exactly {refresh_token}
//   2. a failing revoke never throws out of adminLogout() or leaves an unhandled rejection
//   3. after sign-out, an admin request that gets a 401 does not silently refresh with
//      the old refresh token
//   4. an admin refresh already in flight at sign-out stores nothing afterwards and
//      revokes the session it was given
//   5. an ordinary admin refresh (no sign-out) still stores the rotated pair
//
// Admin tokens live in sessionStorage (one tab), so there is no cross-tab case here.
// What it does NOT prove: server-side revocation, or anything about the deployed portal.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const HTML = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'frontend', 'sol', 'admin.html');
const scripts = [...readFileSync(HTML, 'utf8').matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const SRC = scripts.find(s => s.includes('function adminLogout'));
if (!SRC) throw new Error('admin script with adminLogout() not found in admin.html');
const API = 'https://sol-api.invalid';
const AT = 'synthetic-admin-access-1', RT = 'synthetic-admin-refresh-1';
const AT2 = 'synthetic-admin-access-2', RT2 = 'synthetic-admin-refresh-2';

const res = (status, body) => ({ status, ok: status >= 200 && status < 300, statusText: '', json: async () => body ?? {} });
const deferred = () => { let resolve; const p = new Promise(r => { resolve = r; }); return { p, resolve }; };
const tick = () => new Promise(r => setTimeout(r, 0));

function makeAdmin(route) {
  const session = new Map();   // empty at load: the script's `if (adminToken) showApp()` does not run
  const calls = [];
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { id, style: {}, textContent: '', value: '', disabled: false, classList: { add() {}, remove() {}, contains: () => false }, addEventListener() {} });
    return elements.get(id);
  };
  const rejections = [];
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, JSON, URLSearchParams,
    window: { location: { href: '', search: '' } },
    sessionStorage: { getItem: k => (session.has(k) ? session.get(k) : null), setItem: (k, v) => session.set(k, String(v)), removeItem: k => session.delete(k) },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: { getElementById: element, querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, createElement: () => element('created') },
    fetch: (url, opts = {}) => {
      const call = { url: String(url), method: (opts.method || 'GET').toUpperCase(), headers: opts.headers || {}, body: opts.body };
      calls.push(call);
      try { return Promise.resolve(route(call)); } catch (e) { return Promise.reject(e); }
    },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SRC.replace(/const API = '[^']*';/, `const API = '${API}';`), sandbox);
  const V = expr => vm.runInContext(expr, sandbox);
  const signIn = () => { session.set('sol_admin_token', AT); session.set('sol_admin_refresh', RT); V(`adminToken = '${AT}'`); };
  const revokes = () => calls.filter(c => c.method === 'POST' && c.url === API + '/auth/logout');
  const refreshes = () => calls.filter(c => c.method === 'POST' && c.url === API + '/auth/refresh');
  return { session, calls, element, V, signIn, revokes, refreshes, rejections };
}

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('  ✓', m); } else { fail++; console.log('  ✗ FAIL:', m); } };
const unhandled = [];
process.on('unhandledRejection', e => unhandled.push(String(e)));
const scenario = async (name, fn) => {
  console.log('\n' + name);
  try { await fn(); } catch (e) { fail++; console.log('  ✗ FAIL: threw', String(e && e.stack || e).split('\n')[0]); }
};

await scenario('[A1] admin sign-out clears both tokens and revokes the refresh session', async () => {
  const app = makeAdmin(() => res(204));
  app.signIn();
  app.V('adminLogout()');
  await tick(); await tick();
  ok(!app.session.has('sol_admin_token') && !app.session.has('sol_admin_refresh'), `both admin tokens removed (saw ${JSON.stringify([...app.session])})`);
  ok(app.V('adminToken') === null, 'in-memory admin token cleared');
  ok(app.element('loginGate').style.display === 'flex' && app.element('appShell').style.display === 'none', 'login gate shown');
  const rv = app.revokes();
  ok(rv.length === 1, `exactly one POST /auth/logout (saw ${rv.length})`);
  if (rv[0]) {
    const body = JSON.parse(rv[0].body);
    ok(JSON.stringify(Object.keys(body)) === '["refresh_token"]' && body.refresh_token === RT, 'body is exactly {refresh_token: <admin refresh token>}');
  }
});

await scenario('[A2] no admin refresh token stored: no revoke request', async () => {
  const app = makeAdmin(() => res(204));
  app.session.set('sol_admin_token', AT); app.V(`adminToken = '${AT}'`);
  app.V('adminLogout()');
  await tick();
  ok(app.revokes().length === 0, 'no request without a refresh token');
  ok(!app.session.has('sol_admin_token'), 'admin access token removed');
});

for (const [label, route] of [['500', () => res(500, { detail: 'boom' })], ['network error', () => { throw new TypeError('Failed to fetch'); }]]) {
  await scenario(`[A3] revoke fails (${label}): still signed out, nothing thrown`, async () => {
    const app = makeAdmin(route);
    app.signIn();
    let threw = null;
    try { app.V('adminLogout()'); } catch (e) { threw = e; }
    await tick(); await tick();
    ok(threw === null, 'adminLogout() does not throw');
    ok(app.revokes().length === 1, 'revoke attempted once');
    ok(!app.session.has('sol_admin_token') && !app.session.has('sol_admin_refresh'), 'both admin tokens removed');
  });
}

await scenario('[A4] after sign-out, a 401 does not silently refresh with the old token', async () => {
  const app = makeAdmin(call => (call.url === API + '/auth/logout' ? res(204) : call.url === API + '/auth/refresh' ? res(200, { access_token: AT2, refresh_token: RT2 }) : res(401, { detail: 'Invalid token' })));
  app.signIn();
  app.V('adminLogout()');
  await tick();
  const outcome = await app.V("api('/admin/users')").then(() => 'resolved', e => 'rejected: ' + e.message);
  ok(app.refreshes().length === 0, `no POST /auth/refresh after sign-out (saw ${app.refreshes().length})`);
  ok(!app.session.has('sol_admin_token') && !app.session.has('sol_admin_refresh') && app.V('adminToken') === null, 'still signed out: no tokens stored');
  ok(/^rejected/.test(outcome), 'the request fails (' + outcome + ')');
});

await scenario('[A5] admin refresh in flight at sign-out: stores nothing, revokes the new session', async () => {
  const gate = deferred();
  const app = makeAdmin(call => (call.url === API + '/auth/refresh' ? gate.p : res(204)));
  app.signIn();
  const refreshing = app.V('_tryAdminRefresh()');
  await tick();
  app.V('adminLogout()');
  gate.resolve(res(200, { access_token: AT2, refresh_token: RT2 }));
  const got = await refreshing; await tick(); await tick();
  ok(got === false, 'the refresh reports failure');
  ok(!app.session.has('sol_admin_token') && !app.session.has('sol_admin_refresh'), `nothing stored after sign-out (saw ${JSON.stringify([...app.session])})`);
  ok(app.V('adminToken') !== AT2, 'in-memory admin token not replaced');
  const bodies = app.revokes().map(c => JSON.parse(c.body).refresh_token);
  ok(bodies.includes(RT2), 'the session the late refresh created was revoked');
});

await scenario('[A6] ordinary admin refresh without sign-out still stores the rotated pair', async () => {
  const app = makeAdmin(call => (call.url === API + '/auth/refresh' ? res(200, { access_token: AT2, refresh_token: RT2 }) : res(204)));
  app.signIn();
  const got = await app.V('_tryAdminRefresh()');
  ok(got === true, 'refresh succeeds');
  ok(app.session.get('sol_admin_token') === AT2 && app.session.get('sol_admin_refresh') === RT2, 'rotated admin tokens stored');
  ok(app.V('adminToken') === AT2, 'in-memory admin token updated');
  ok(app.revokes().length === 0, 'no revoke request');
});

await tick(); await tick();
ok(unhandled.length === 0, `no unhandled promise rejections (saw ${JSON.stringify(unhandled)})`);
console.log(`\nadmin sign-out: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
