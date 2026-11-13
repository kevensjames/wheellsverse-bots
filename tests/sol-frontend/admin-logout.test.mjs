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
//   6. signing out and in again while an old refresh is in flight keeps the NEW session
//      (the old request's failure path must not clear it)
//   7. a request sent before a sign-out whose 401 arrives after a new sign-in is not
//      refreshed or re-sent under the new session (it may be a different admin)
//   8. a page opened with a stored admin session (showApp() runs while the script loads)
//      still loads: anything api() reads must be declared before that call
//   9. a session that ends any other way (expiry, a new sign-in through the form) also
//      stops old requests from refreshing or being re-sent under the next session, and a
//      refresh from an earlier session is never shared with the next one
//  10. tokens are gone at once even if the revoke never answers; a sign-out while a
//      refresh answer is still being read stores nothing; the revoke uses keepalive
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
// The negative checks ([A4] no refresh, [A9] not re-sent) would pass vacuously if
// requests went to another host, so the API rewrite must apply.
if (!/const API = '[^']*';/.test(SRC)) throw new Error('admin API constant not found: the rewrite would not apply');
const API = 'https://sol-api.invalid';
const AT = 'synthetic-admin-access-1', RT = 'synthetic-admin-refresh-1';
const AT2 = 'synthetic-admin-access-2', RT2 = 'synthetic-admin-refresh-2';

const res = (status, body, bodyGate) => ({ status, ok: status >= 200 && status < 300, statusText: '', json: async () => { if (bodyGate) await bodyGate; return body ?? {}; } });
const deferred = () => { let resolve; const p = new Promise(r => { resolve = r; }); return { p, resolve }; };
const tick = () => new Promise(r => setTimeout(r, 0));

function makeAdmin(route, initial = {}) {
  const session = new Map(Object.entries(initial));   // empty by default: `if (adminToken) showApp()` does not run at load
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
      const call = { url: String(url), method: (opts.method || 'GET').toUpperCase(), headers: opts.headers || {}, body: opts.body, keepalive: !!opts.keepalive };
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

await scenario('[A7] signed out and in again while an old refresh is in flight: the new session is kept', async () => {
  const AT3 = 'synthetic-admin-access-3', RT3 = 'synthetic-admin-refresh-3';
  const gate = deferred();
  const app = makeAdmin(call => (call.url === API + '/auth/refresh' ? gate.p : call.url === API + '/auth/logout' ? res(204) : res(401, { detail: 'Invalid token' })));
  app.signIn();
  const pending = app.V("api('/admin/users')").then(() => 'resolved', e => 'rejected: ' + e.message);
  await tick(); await tick();
  ok(app.refreshes().length === 1, 'the old request is refreshing');
  app.V('adminLogout()');
  app.session.set('sol_admin_token', AT3); app.session.set('sol_admin_refresh', RT3); app.V(`adminToken = '${AT3}'`);   // what doLogin() stores
  gate.resolve(res(200, { access_token: AT2, refresh_token: RT2 }));
  const outcome = await pending; await tick(); await tick();
  ok(app.session.get('sol_admin_token') === AT3 && app.session.get('sol_admin_refresh') === RT3 && app.V('adminToken') === AT3, `the new admin session is kept (saw ${JSON.stringify([...app.session])})`);
  ok(app.revokes().map(c => JSON.parse(c.body).refresh_token).includes(RT2), 'the late session from the old refresh was revoked');
  ok(/^rejected/.test(outcome), 'the old request fails (' + outcome + ')');
});

await scenario('[A9] a request from before the sign-out gets its 401 after a new sign-in: not re-sent under the new session', async () => {
  const AT3 = 'synthetic-admin-access-3', RT3 = 'synthetic-admin-refresh-3';
  const gate = deferred();
  const app = makeAdmin(call => (call.url === API + '/admin/users' ? gate.p : call.url === API + '/auth/refresh' ? res(200, { access_token: AT2, refresh_token: RT2 }) : res(204)));
  app.signIn();
  const pending = app.V("api('/admin/users')").then(() => 'resolved', e => 'rejected: ' + e.message);
  await tick();
  app.V('adminLogout()');
  app.session.set('sol_admin_token', AT3); app.session.set('sol_admin_refresh', RT3); app.V(`adminToken = '${AT3}'`);   // what doLogin() stores
  gate.resolve(res(401, { detail: 'Invalid token' }));
  const outcome = await pending; await tick(); await tick();
  ok(app.refreshes().length === 0, `the new session is not refreshed for the old request (saw ${app.refreshes().length})`);
  ok(app.calls.filter(c => c.url === API + '/admin/users').length === 1, 'the old request is not re-sent');
  ok(app.session.get('sol_admin_token') === AT3 && app.session.get('sol_admin_refresh') === RT3 && app.V('adminToken') === AT3, `the new admin session is unchanged (saw ${JSON.stringify([...app.session])})`);
  ok(/^rejected/.test(outcome), 'the old request fails (' + outcome + ')');
});

await scenario('[A8] a page opened with a stored admin session loads (showApp() at script load)', async () => {
  let app = null, threw = null;
  try {
    app = makeAdmin(() => new Promise(() => {}), { sol_admin_token: AT, sol_admin_refresh: RT });   // requests never answer
  } catch (e) { threw = e; }
  ok(threw === null, 'the admin script loads without throwing' + (threw ? ' (' + String(threw).split('\n')[0] + ')' : ''));
  ok(app && app.calls.some(c => c.url === API + '/auth/me'), 'showApp() ran and requested /auth/me');
});

await scenario('[A10] the session expires, another admin signs in, then an old request gets its 401: not refreshed or re-sent', async () => {
  const AT3 = 'synthetic-admin-access-3', RT3 = 'synthetic-admin-refresh-3';
  const gate = deferred();
  const app = makeAdmin(call => (call.url === API + '/admin/users' ? gate.p : call.url === API + '/auth/refresh' ? res(401, { detail: 'Invalid or expired refresh token' }) : call.url === API + '/auth/logout' ? res(204) : res(401, { detail: 'Token expired' })));
  app.signIn();
  const old = app.V("api('/admin/users')").then(() => 'resolved', e => 'rejected: ' + e.message);
  await tick();
  const expired = await app.V("api('/admin/groups')").then(() => 'resolved', e => 'rejected: ' + e.message);
  ok(/Session expired/.test(expired) && !app.session.has('sol_admin_token'), 'the session expired (refresh rejected) and the tokens were cleared');
  const refreshesBefore = app.refreshes().length;
  app.session.set('sol_admin_token', AT3); app.session.set('sol_admin_refresh', RT3); app.V(`adminToken = '${AT3}'`);   // the next admin signs in
  gate.resolve(res(401, { detail: 'Token expired' }));
  const outcome = await old; await tick(); await tick();
  ok(app.refreshes().length === refreshesBefore, `the new session is not refreshed for the old request (saw ${app.refreshes().length - refreshesBefore} more)`);
  ok(app.calls.filter(c => c.url === API + '/admin/users').length === 1, 'the old request is not re-sent');
  ok(app.session.get('sol_admin_token') === AT3 && app.session.get('sol_admin_refresh') === RT3 && app.V('adminToken') === AT3, `the new session is unchanged (saw ${JSON.stringify([...app.session])})`);
  ok(/^rejected/.test(outcome), 'the old request fails (' + outcome + ')');
});

await scenario('[A11] a sign-in through the real login form ends the earlier session: an old request is not re-sent under it', async () => {
  const AT3 = 'synthetic-admin-access-3', RT3 = 'synthetic-admin-refresh-3';
  const gate = deferred();
  let usersCalls = 0;   // showApp() after the sign-in loads /admin/users itself; only the first call is the old request
  const app = makeAdmin(call => (call.url === API + '/admin/users' ? (usersCalls++ === 0 ? gate.p : res(200, []))
    : call.url === API + '/auth/login' ? res(200, { access_token: AT3, refresh_token: RT3, token_type: 'bearer' })
    : call.url === API + '/admin/reconcile' ? res(200, {})
    : call.url === API + '/auth/refresh' ? res(200, { access_token: AT2, refresh_token: RT2 })
    : res(204)));
  app.signIn();
  const old = app.V("api('/admin/users')").then(() => 'resolved', e => 'rejected: ' + e.message);
  await tick();
  app.element('aEmail').value = 'admin-y@example.invalid'; app.element('aPassword').value = 'synthetic-password';
  await app.V('adminLogin()');
  ok(app.session.get('sol_admin_token') === AT3, 'the login form stored the new session');
  const usersAfterLogin = app.calls.filter(c => c.url === API + '/admin/users' && c.headers.Authorization !== 'Bearer ' + AT).length;   // showApp()'s own loads
  gate.resolve(res(401, { detail: 'Token expired' }));
  const outcome = await old; await tick(); await tick();
  ok(app.refreshes().length === 0, `no refresh for the old request (saw ${app.refreshes().length})`);
  const usersNow = app.calls.filter(c => c.url === API + '/admin/users' && c.headers.Authorization !== 'Bearer ' + AT).length;
  ok(usersNow === usersAfterLogin, `the old request is not re-sent under the new session (${usersNow - usersAfterLogin} extra /admin/users call(s))`);
  ok(app.session.get('sol_admin_token') === AT3 && app.session.get('sol_admin_refresh') === RT3, `the new session is unchanged (saw ${JSON.stringify([...app.session])})`);
  ok(/^rejected/.test(outcome), 'the old request fails (' + outcome + ')');
});

await scenario("[A12] a refresh from before a sign-out is not shared with the next session's 401 (N4, NF3)", async () => {
  const AT3 = 'synthetic-admin-access-3', RT3 = 'synthetic-admin-refresh-3', AT4 = 'synthetic-admin-access-4', RT4 = 'synthetic-admin-refresh-4';
  const oldRefresh = deferred();
  const app = makeAdmin(call => {
    if (call.url === API + '/auth/refresh') return JSON.parse(call.body).refresh_token === RT ? oldRefresh.p : res(200, { access_token: AT4, refresh_token: RT4 });
    if (call.url === API + '/auth/logout') return res(204);
    if (call.url === API + '/admin/groups') return call.headers.Authorization === 'Bearer ' + AT4 ? res(200, { groups: [] }) : res(401, { detail: 'Token expired' });
    return res(401, { detail: 'Token expired' });
  });
  app.signIn();
  const old = app.V("api('/admin/users')").then(() => 'resolved', e => 'rejected: ' + e.message);
  await tick(); await tick();
  ok(app.refreshes().length === 1, 'the old session is refreshing');
  app.V('adminLogout()');
  app.session.set('sol_admin_token', AT3); app.session.set('sol_admin_refresh', RT3); app.V(`adminToken = '${AT3}'`);   // the next admin signs in
  const freshP = app.V("api('/admin/groups')").then(v => 'resolved', e => 'rejected: ' + e.message);
  const fresh = await Promise.race([freshP, new Promise(r => setTimeout(() => r('still pending after 1000 ms (waiting on the old refresh)'), 1000))]);
  ok(fresh === 'resolved', `the new session's request refreshes on its own and succeeds (${fresh})`);
  ok(app.refreshes().some(c => JSON.parse(c.body).refresh_token === RT3), 'it refreshed with the new refresh token');
  ok(app.session.get('sol_admin_token') === AT4 && app.session.get('sol_admin_refresh') === RT4, `the new session's rotated pair is stored (saw ${JSON.stringify([...app.session])})`);
  oldRefresh.resolve(res(200, { access_token: AT2, refresh_token: RT2 }));
  await old; await freshP; await tick(); await tick();
  ok(app.session.get('sol_admin_token') === AT4, 'the old refresh answering late changes nothing');
  ok(app.revokes().some(c => JSON.parse(c.body).refresh_token === RT2), 'and its late session is revoked');
});

await scenario('[A13] the revoke never answers: both admin tokens are gone at once (NF8)', async () => {
  const app = makeAdmin(call => (call.url === API + '/auth/logout' ? new Promise(() => {}) : res(204)));
  app.signIn();
  app.V('adminLogout()');
  ok(!app.session.has('sol_admin_token') && !app.session.has('sol_admin_refresh') && app.V('adminToken') === null, 'both tokens removed synchronously, before any answer');
});

await scenario('[A14] sign-out while the refresh answer is still being read: nothing is stored (NF7)', async () => {
  const body = deferred();
  const app = makeAdmin(call => (call.url === API + '/auth/refresh' ? res(200, { access_token: AT2, refresh_token: RT2 }, body.p) : res(204)));
  app.signIn();
  const refreshing = app.V('_tryAdminRefresh()');
  await tick(); await tick();
  app.V('adminLogout()');
  body.resolve();
  const got = await refreshing; await tick(); await tick();
  ok(got === false, 'the refresh reports failure');
  ok(!app.session.has('sol_admin_token') && !app.session.has('sol_admin_refresh'), `nothing stored (saw ${JSON.stringify([...app.session])})`);
  ok(app.revokes().some(c => JSON.parse(c.body).refresh_token === RT2), 'the late session is revoked');
});

await scenario('[A15] the admin revoke is sent with keepalive, so closing the tab cannot cancel it (N6)', async () => {
  const app = makeAdmin(() => res(204));
  app.signIn();
  app.V('adminLogout()');
  const rv = app.revokes();
  ok(rv.length === 1 && rv[0].keepalive === true, `one revoke, keepalive set (saw ${JSON.stringify(rv.map(c => c.keepalive))})`);
});

await scenario("[A16] the old refresh finishing does not drop the new session's refresh in flight: a second 401 joins it", async () => {
  const AT3 = 'synthetic-admin-access-3', RT3 = 'synthetic-admin-refresh-3', AT4 = 'synthetic-admin-access-4', RT4 = 'synthetic-admin-refresh-4';
  const oldRefresh = deferred(), newRefresh = deferred();
  const app = makeAdmin(call => {
    if (call.url === API + '/auth/refresh') return JSON.parse(call.body).refresh_token === RT ? oldRefresh.p : newRefresh.p;
    if (call.url === API + '/auth/logout') return res(204);
    return call.headers.Authorization === 'Bearer ' + AT4 ? res(200, []) : res(401, { detail: 'Token expired' });
  });
  app.signIn();
  const old = app.V("api('/admin/users')").then(() => 'resolved', e => 'rejected: ' + e.message);
  await tick(); await tick();
  app.V('adminLogout()');
  app.session.set('sol_admin_token', AT3); app.session.set('sol_admin_refresh', RT3); app.V(`adminToken = '${AT3}'`);
  const first = app.V("api('/admin/groups')").then(() => 'resolved', e => 'rejected: ' + e.message);
  await tick(); await tick();
  oldRefresh.resolve(res(200, { access_token: AT2, refresh_token: RT2 }));   // the old refresh ends while the new one is pending
  await old; await tick(); await tick();
  const second = app.V("api('/admin/overview')").then(() => 'resolved', e => 'rejected: ' + e.message);
  await tick(); await tick();
  newRefresh.resolve(res(200, { access_token: AT4, refresh_token: RT4 }));
  const [a, b] = await Promise.all([first, second]); await tick();
  ok(app.refreshes().filter(c => JSON.parse(c.body).refresh_token === RT3).length === 1, `the new session's refresh token is rotated once (saw ${app.refreshes().filter(c => JSON.parse(c.body).refresh_token === RT3).length})`);
  ok(a === 'resolved' && b === 'resolved', `both new-session requests succeed (${a}, ${b})`);
  ok(app.session.get('sol_admin_refresh') === RT4, 'the rotated pair is stored');
});

await scenario('[A17] a sign-in whose answer has no refresh token does not keep the previous admin\'s refresh token', async () => {
  const AT3 = 'synthetic-admin-access-3';
  const app = makeAdmin(call => (call.url === API + '/auth/login' ? res(200, { access_token: AT3, token_type: 'bearer' }) : res(200, [])));
  app.signIn();
  app.element('aEmail').value = 'admin-y@example.invalid'; app.element('aPassword').value = 'synthetic-password';
  await app.V('adminLogin()');
  ok(app.session.get('sol_admin_token') === AT3, 'the new access token is stored');
  ok(!app.session.has('sol_admin_refresh'), `the previous admin's refresh token is gone (saw ${app.session.get('sol_admin_refresh')})`);
});

await tick(); await tick();
ok(unhandled.length === 0, `no unhandled promise rejections (saw ${JSON.stringify(unhandled)})`);
console.log(`\nadmin sign-out: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
