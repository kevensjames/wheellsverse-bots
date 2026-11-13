// Multi-tab session regression test for the member app (pure Node, zero dependencies,
// no network).
//   node tests/sol-frontend/session-tabs.test.mjs
//
// Loads the REAL core/state.js, core/router.js and core/api.js once per tab, in vm
// sandboxes that share one browser: one localStorage (with `storage` events delivered
// to the OTHER tabs, as browsers do), optionally the Web Locks API, and one mock
// backend. The backend models the sol-api auth contract read from c218dfb: access
// tokens are JWTs whose `sub` is the user id; POST /auth/refresh rotates the refresh
// token on receipt (the old one is revoked even if the answer is lost) and answers 401
// for a rotated token; POST /auth/logout revokes and answers 204, and 422 for extra
// fields. Synthetic tokens only; API points at a reserved .invalid host never contacted.
//
// What it checks (each case names the review finding it covers):
//   - a tab never re-sends a request under a session that is not its own: another
//     user's, or one stored after a sign-out (RC-1, N1, NF1, and the base path P)
//   - two tabs refreshing at once keep the browser signed in and leave no orphan
//     session (N3, NF2, RC-3, RC-2), with and without the Web Locks API
//   - waiting on a revoke is bounded (RC-4); a late revoke is answered before the tab
//     navigates (NF5)
//   - a sign-out in one tab signs the other tabs out at once; another user signing in
//     reloads them; a transient error in one tab signs nobody out (N2)
//   - revoke requests use keepalive so a navigation or a closed tab cannot cancel them
//     (N5, N6)
// What it does NOT prove: server-side revocation (the backend is a mock), Firefox or
// Safari behaviour, or anything about the deployed frontend. An access token already
// issued stays valid at the API until it expires.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const CORE = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'frontend', 'sol', 'app', 'core');
const PROD_API = "'https://sol-api-production.up.railway.app'";
const API = 'https://sol-api.invalid';
const STATE = readFileSync(join(CORE, 'state.js'), 'utf8');
if (!STATE.includes(PROD_API)) throw new Error('state.js API constant not found: the rewrite would not apply');
const SRC = {
  'state.js': STATE.split(PROD_API).join(JSON.stringify(API)),
  'router.js': readFileSync(join(CORE, 'router.js'), 'utf8'),
  'api.js': readFileSync(join(CORE, 'api.js'), 'utf8'),
};
const REVOKE_BOUND_MS = 3000;   // REVOKE_TIMEOUT_MS in core/router.js

const tick = () => new Promise(r => setTimeout(r, 0));
const settle = async (n = 6) => { for (let i = 0; i < n; i++) await tick(); };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const deferred = () => { let resolve; const p = new Promise(r => { resolve = r; }); return { p, resolve }; };
const b64u = o => Buffer.from(JSON.stringify(o)).toString('base64url');
const res = (status, body, bodyGate) => ({ status, ok: status >= 200 && status < 300, statusText: '', json: async () => { if (bodyGate) await bodyGate; return body ?? {}; } });

// ── Mock backend ─────────────────────────────────────────────────────────────
function makeServer() {
  const sessions = new Map();   // refresh token -> { user, active }
  const access = new Map();     // access token  -> { user, valid }
  const log = [];
  const gates = [];
  let n = 0;
  const issue = (user, exp = 4102444800) => {
    n++;
    const a = `${b64u({ alg: 'HS256', typ: 'JWT' })}.${b64u({ sub: user, type: 'access', exp, jti: `synthetic-${n}` })}.synthetic-signature-${n}`;
    const r = `synthetic-refresh-${user}-${n}`;
    sessions.set(r, { user, active: true });
    access.set(a, { user, valid: true });
    return { access_token: a, refresh_token: r, token_type: 'bearer' };
  };
  // gate(pred): the next matching request is processed at once (rotation on receipt)
  // but its answer waits for release(). opts.body holds the body too (headers first).
  const gate = (pred, opts = {}) => { const g = { pred, d: deferred(), body: opts.body ? deferred() : null, networkError: !!opts.networkError, hit: false, release: () => g.d.resolve(), releaseBody: () => g.body && g.body.resolve() }; gates.push(g); return g; };
  const handle = async call => {
    const path = call.url.slice(API.length);
    const bearer = (call.headers.Authorization || call.headers.authorization || '').replace(/^Bearer /, '');
    let body = {}; try { body = JSON.parse(call.body || '{}'); } catch {}
    const entry = { tab: call.tab, method: call.method, path, as: access.has(bearer) ? access.get(bearer).user : null, bearer, body };
    log.push(entry);
    let out;
    if (path === '/auth/refresh' && call.method === 'POST') {
      const s = sessions.get(body.refresh_token);
      if (!s || !s.active) out = [401, { detail: 'Invalid or expired refresh token' }];
      else { s.active = false; out = [200, issue(s.user)]; }
    } else if (path === '/auth/logout' && call.method === 'POST') {
      if (JSON.stringify(Object.keys(body)) !== '["refresh_token"]') out = [422, { detail: 'extra fields' }];
      else { const s = sessions.get(body.refresh_token); if (s) s.active = false; out = [204]; }
    } else {
      const a = access.get(bearer);
      out = a && a.valid ? [200, { ok: true, as: a.user }] : [401, { detail: 'Token expired' }];
    }
    entry.status = out[0];
    const g = gates.find(x => !x.hit && x.pred(entry, call));
    if (g) { g.hit = true; await g.d.p; if (g.networkError) throw new TypeError('Failed to fetch'); return res(out[0], out[1], g.body && g.body.p); }
    return res(out[0], out[1]);
  };
  const active = user => [...sessions].filter(([, s]) => s.active && (!user || s.user === user)).map(([k]) => k);
  return { issue, gate, handle, log, sessions, access, active, expire: a => { access.get(a).valid = false; } };
}

// ── Mock browser (shared storage, storage events, optional Web Locks) ───────
function makeBrowser({ locks = false, storageEvents = true } = {}) {
  const store = new Map();
  const tabs = [];
  const held = new Map();
  const locksApi = !locks ? undefined : {
    request(name, a, b) {
      const cb = typeof a === 'function' ? a : b;
      const opts = typeof a === 'function' ? {} : (a || {});
      return new Promise((resolve, reject) => {
        const st = held.get(name) || { busy: false, queue: [] }; held.set(name, st);
        const release = () => { st.busy = false; const next = st.queue.shift(); if (next) next(); };
        const run = () => { st.busy = true; Promise.resolve().then(() => cb({ name })).then(v => { release(); resolve(v); }, e => { release(); reject(e); }); };
        if (opts.signal && opts.signal.aborted) return reject(new DOMException('The lock request is aborted', 'AbortError'));
        if (!st.busy) return run();
        st.queue.push(run);
        if (opts.signal) opts.signal.addEventListener('abort', () => { const i = st.queue.indexOf(run); if (i >= 0) { st.queue.splice(i, 1); reject(new DOMException('The lock request is aborted', 'AbortError')); } });
      });
    },
  };
  const write = (from, k, v) => {
    const oldValue = store.has(k) ? store.get(k) : null;
    if (v === null) store.delete(k); else store.set(k, String(v));
    const newValue = v === null ? null : String(v);
    if (storageEvents && oldValue !== newValue) for (const t of tabs) if (t !== from) setTimeout(() => t.dispatchStorage({ key: k, oldValue, newValue }), 0);
  };
  // What the landing page's finishAuth() stores after a sign-in.
  const signIn = (server, user) => { const s = server.issue(user); write(null, 'sol_token', s.access_token); write(null, 'sol_refresh', s.refresh_token); return s; };
  return { store, tabs, locksApi, write, signIn };
}

// One tab of the member app: state.js, router.js, api.js in app.html's order.
function makeTab(browser, server, label, { blockRevokes = false } = {}) {
  const calls = [], hrefs = [], events = [], listeners = { storage: [] };
  let reloads = 0;
  const location = { search: '', reload: () => { reloads++; events.push('reload'); } };
  Object.defineProperty(location, 'href', { get: () => hrefs[hrefs.length - 1] || '/sol/app', set: v => { hrefs.push(v); events.push('redirect:' + v); } });
  const tab = { label, calls, hrefs, events, get reloads() { return reloads; } };
  const localStorage = {
    getItem: k => (browser.store.has(k) ? browser.store.get(k) : null),
    setItem: (k, v) => browser.write(tab, k, v),
    removeItem: k => browser.write(tab, k, null),
  };
  const window = { location, addEventListener: (t, fn) => { (listeners[t] = listeners[t] || []).push(fn); }, removeEventListener() {} };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, JSON, URLSearchParams, AbortController, AbortSignal, DOMException, atob, btoa,
    window, location, localStorage,
    navigator: browser.locksApi ? { locks: browser.locksApi } : {},
    document: { querySelectorAll: () => [], querySelector: () => null, getElementById: () => null },
    fetch: (url, opts = {}) => {
      const call = { tab: label, url: String(url), method: (opts.method || 'GET').toUpperCase(), headers: opts.headers || {}, body: opts.body, keepalive: !!opts.keepalive };
      calls.push(call);
      if (call.url === API + '/auth/logout') {
        if (blockRevokes) return new Promise(() => {});
        let tok = null; try { tok = JSON.parse(call.body).refresh_token; } catch {}
        return server.handle(call).then(r => { events.push('revoke-answered:' + tok); return r; });
      }
      return server.handle(call);
    },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  for (const f of ['state.js', 'router.js', 'api.js']) vm.runInContext(SRC[f], sandbox);
  tab.V = expr => vm.runInContext(expr, sandbox);
  tab.dispatchStorage = ev => { for (const fn of listeners.storage) fn({ ...ev, storageArea: localStorage, url: 'https://app.invalid/sol/app' }); };
  tab.listeners = listeners;
  tab.dispatch = (type, ev) => { for (const fn of listeners[type] || []) fn(ev); };
  tab.revokes = () => calls.filter(c => c.method === 'POST' && c.url === API + '/auth/logout');
  tab.request = (path, opts) => tab.V(`api(${JSON.stringify(path)}, ${JSON.stringify(opts || {})})`).then(v => ({ ok: true, v }), e => ({ ok: false, e: String(e && e.message) }));
  browser.tabs.push(tab);
  return tab;
}

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('  ✓', m); } else { fail++; console.log('  ✗ FAIL:', m); } };
const scenario = async (name, fn) => {
  console.log('\n' + name);
  try { await fn(); } catch (e) { fail++; console.log('  ✗ FAIL: threw', String(e && e.stack || e).split('\n')[0]); }
};
const within = (p, ms) => Promise.race([p.then(v => ({ settled: true, v })), sleep(ms).then(() => ({ settled: false }))]);
const sent = (server, tab, path) => server.log.filter(l => l.tab === tab && l.path === path);
const PAY = ['/circles/c1/contributions', { method: 'POST', body: JSON.stringify({ amount_cents: 2500 }) }];

// ── Another user's session is never used by this tab ────────────────────────
await scenario('[T1] tab B (user X) refreshing when X signs out in tab A and user Y signs in: B does not re-send under Y', async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  server.expire(X.access_token);
  const g = server.gate(e => e.path === '/auth/refresh');
  const pay = B.request(...PAY);
  await settle();
  ok(g.hit, "B's refresh reached the server (it rotated X's token)");
  await A.V('logout()');
  const Y = browser.signIn(server, 'user-y');
  g.release();
  const out = await pay; await settle();
  const posts = sent(server, 'B', PAY[0]);
  ok(posts.length === 1, `the contribution POST was sent once, not re-sent (saw ${posts.length})`);
  ok(!server.log.some(l => l.tab === 'B' && l.as === 'user-y'), 'tab B sent nothing as user Y');
  ok(B.V('token') !== Y.access_token, "tab B did not take Y's access token");
  ok(server.active('user-x').length === 0, `no session of X is left active (saw ${JSON.stringify(server.active('user-x'))})`);
  ok(browser.store.get('sol_refresh') === Y.refresh_token && server.active('user-y').includes(Y.refresh_token), "Y's session is still stored and active");
  ok(B.reloads === 1 && B.hrefs.length === 0, `tab B reloads to show the current session (reloads ${B.reloads}, redirects ${JSON.stringify(B.hrefs)})`);
  ok(!out.ok, 'the request fails in tab B');
});

await scenario('[T2] idle tab B (user X) after X signed out and Y signed in elsewhere: its next 401 does not touch Y\'s session', async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  await A.V('logout()');
  const Y = browser.signIn(server, 'user-y');
  server.expire(X.access_token);
  const out = await B.request(...PAY); await settle();
  ok(sent(server, 'B', '/auth/refresh').length === 0, "tab B did not refresh with Y's refresh token");
  ok(sent(server, 'B', PAY[0]).length === 1 && !server.log.some(l => l.tab === 'B' && l.as === 'user-y'), 'the POST was sent once and never as Y');
  ok(browser.store.get('sol_refresh') === Y.refresh_token && server.sessions.get(Y.refresh_token).active, "Y's stored session is unchanged and active");
  ok(B.reloads === 1, `tab B reloads (saw ${B.reloads})`);
  ok(!out.ok, 'the request fails in tab B');
});

await scenario('[T3] X signs out and back in (same user) while tab B refreshes: a request from before the sign-out is not re-sent', async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  server.expire(X.access_token);
  const g = server.gate(e => e.path === '/auth/refresh');
  const pay = B.request(...PAY);
  await settle();
  await A.V('logout()');
  const X3 = browser.signIn(server, 'user-x');
  g.release();
  await pay; await settle();
  ok(sent(server, 'B', PAY[0]).length === 1, 'the POST was not re-sent under the new session');
  ok(browser.store.get('sol_refresh') === X3.refresh_token && server.sessions.get(X3.refresh_token).active, 'the new session is kept, stored and active');
  ok(server.active('user-x').length === 1, `B's late session was revoked (active X sessions: ${server.active('user-x').length})`);
  ok(B.reloads === 1, `tab B reloads (saw ${B.reloads})`);
});

// ── Two tabs refreshing at the same time ────────────────────────────────────
await scenario('[T4] two tabs get a 401 at once (Web Locks available): both continue, one session, nothing orphaned', async () => {
  const server = makeServer(), browser = makeBrowser({ locks: true });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), C = makeTab(browser, server, 'C');
  server.expire(X.access_token);
  const [rb, rc] = await Promise.all([B.request('/groups'), C.request('/groups')]); await settle();
  ok(rb.ok && rc.ok, `both requests succeed after the refresh (B ${rb.ok ? 'ok' : rb.e}, C ${rc.ok ? 'ok' : rc.e})`);
  ok(B.hrefs.length + C.hrefs.length + B.reloads + C.reloads === 0, 'neither tab navigates or reloads');
  const act = server.active('user-x');
  ok(act.length === 1 && act[0] === browser.store.get('sol_refresh'), `exactly one active session and it is the stored one (active ${JSON.stringify(act)})`);
  ok(server.log.filter(l => l.path === '/auth/refresh').length === 1, `one refresh for both tabs (saw ${server.log.filter(l => l.path === '/auth/refresh').length})`);
});

await scenario("[T5] two tabs refresh at once without Web Locks; the loser's 401 arrives after the winner stored: the loser adopts", async () => {
  const server = makeServer(), browser = makeBrowser({ locks: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), C = makeTab(browser, server, 'C');
  server.expire(X.access_token);
  const gB = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
  const gC = server.gate(e => e.tab === 'C' && e.path === '/auth/refresh');
  const pb = B.request('/groups');
  await settle();
  const pc = C.request('/groups');
  await settle();
  ok(gB.hit && gC.hit, 'both refreshes reached the server; B rotated first, so C got 401');
  gB.release(); const rb = await pb; await settle();
  gC.release(); const rc = await pc; await settle();
  ok(rb.ok && rc.ok, `both requests succeed (B ${rb.ok ? 'ok' : rb.e}, C ${rc.ok ? 'ok' : rc.e})`);
  ok(C.hrefs.length === 0 && B.hrefs.length === 0, `no tab is sent to the sign-in page (B ${JSON.stringify(B.hrefs)}, C ${JSON.stringify(C.hrefs)})`);
  const act = server.active('user-x');
  ok(act.length === 1 && act[0] === browser.store.get('sol_refresh'), `the stored session is the one active session (active ${JSON.stringify(act)}, stored ${browser.store.get('sol_refresh')})`);
});

await scenario("[T6] same without Web Locks, but the loser's 401 arrives first: the winner keeps its session (RC-2)", async () => {
  const server = makeServer(), browser = makeBrowser({ locks: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), C = makeTab(browser, server, 'C');
  server.expire(X.access_token);
  const gB = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
  const gC = server.gate(e => e.tab === 'C' && e.path === '/auth/refresh');
  const pb = B.request('/groups');
  await settle();
  const pc = C.request('/groups');
  await settle();
  gC.release(); await pc; await settle();
  gB.release(); const rb = await pb; await settle();
  ok(rb.ok, `the winner's request succeeds (${rb.ok ? 'ok' : rb.e})`);
  ok(B.hrefs.length === 0 && B.reloads === 0, `the winner is not signed out (redirects ${JSON.stringify(B.hrefs)})`);
  const act = server.active('user-x');
  ok(act.length === 1 && act[0] === browser.store.get('sol_refresh'), `the winner's session is stored and active, nothing orphaned (active ${JSON.stringify(act)}, stored ${browser.store.get('sol_refresh')})`);
  ok(!B.revokes().length, "the winner did not revoke its own new session");
});

// ── Bounded and ordered revokes ─────────────────────────────────────────────
await scenario('[T7] another tab refreshed meanwhile and revoking the redundant late session hangs: the request still settles (RC-4)', async () => {
  const server = makeServer(), browser = makeBrowser({ locks: false, storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B', { blockRevokes: true }), C = makeTab(browser, server, 'C');
  server.expire(X.access_token);
  const gB = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
  const pb = B.request('/groups');
  await settle();
  // B's refresh has been processed (X's first refresh token is rotated); before its
  // answer arrives, another tab stores a newer pair for the same user X.
  const newer = server.issue('user-x');
  browser.write(C, 'sol_token', newer.access_token); browser.write(C, 'sol_refresh', newer.refresh_token);
  gB.release();
  const r = await within(pb, REVOKE_BOUND_MS + 1500);
  ok(r.settled, `tab B's request settled within the revoke bound (${r.settled ? 'yes' : 'still pending after ' + (REVOKE_BOUND_MS + 1500) + ' ms'})`);
  if (r.settled) ok(r.v.ok, `and it succeeded with the newer session (${r.v.ok ? 'ok' : r.v.e})`);
  const later = await within(B.request('/groups'), REVOKE_BOUND_MS + 1500);
  ok(later.settled, 'a later request in tab B is not stuck behind it');
});

await scenario("[T8] tab A signs out during tab B's refresh: B's late session is revoked and answered before B navigates (NF5)", async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  server.expire(X.access_token);
  const g = server.gate(e => e.path === '/auth/refresh');
  const rv = server.gate(e => e.tab === 'B' && e.path === '/auth/logout');
  const p = B.request('/groups');
  await settle();
  await A.V('logout()');
  g.release();
  await sleep(100);
  ok(B.hrefs.length === 0 && B.reloads === 0, `B waits for its revoke before navigating (saw ${JSON.stringify(B.events)})`);
  rv.release();
  await p; await settle();
  const i = B.events.findIndex(e => e.startsWith('revoke-answered:')), j = B.events.findIndex(e => e.startsWith('redirect') || e === 'reload');
  ok(i !== -1 && j !== -1 && i < j, `revoke answered, then navigation (events ${JSON.stringify(B.events)})`);
  ok(server.active().length === 0, `no session is left active (saw ${JSON.stringify(server.active())})`);
});

await scenario("[T9] tab B signs out during its own refresh while tab A signs in: B adopts nothing and re-sends nothing (NF4)", async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  const g = server.gate(e => e.path === '/auth/refresh');
  const pay = B.request(...PAY);
  await settle();
  const out = B.V('logout()');
  const X3 = browser.signIn(server, 'user-x');
  g.release();
  await pay; await out; await settle();
  ok(sent(server, 'B', PAY[0]).length === 1, 'the POST was not re-sent');
  ok(B.V('token') !== X3.access_token, 'tab B did not adopt the new session');
  ok(browser.store.get('sol_refresh') === X3.refresh_token, 'the new session stays stored');
  ok(B.hrefs.length === 1 && B.hrefs[0] === '/sol/', `tab B leaves once, by its own sign-out (saw ${JSON.stringify(B.hrefs)})`);
});

await scenario('[T10] another tab already refreshed; this tab\'s in-memory token is stale: it continues and the stored session stays live (NF6)', async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), C = makeTab(browser, server, 'C');
  server.expire(X.access_token);
  await C.request('/groups'); await settle();          // C refreshes X's session first
  const r = await B.request('/groups'); await settle();
  ok(r.ok, `tab B's request succeeds (${r.ok ? 'ok' : r.e})`);
  ok(B.hrefs.length === 0 && B.reloads === 0, 'tab B does not navigate');
  ok(server.sessions.get(browser.store.get('sol_refresh'))?.active === true, 'the stored refresh token is active at the server');
  ok(server.active('user-x').length === 1, `one active session (saw ${server.active('user-x').length})`);
});

await scenario("[T11] tab A signs out while tab B is still reading its refresh answer: nothing is stored (NF7)", async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  server.expire(X.access_token);
  const g = server.gate(e => e.path === '/auth/refresh', { body: true });
  const p = B.request('/groups');
  await settle();
  g.release(); await settle();                          // headers arrived; body still pending
  await A.V('logout()');
  g.releaseBody();
  await p; await settle();
  ok(!browser.store.has('sol_token') && !browser.store.has('sol_refresh'), `nothing stored after the sign-out (saw ${JSON.stringify([...browser.store].filter(([k]) => k !== 'sol_signout'))})`);
  ok(server.active().length === 0, `no session left active (saw ${JSON.stringify(server.active())})`);
});

// ── Sign-out reaches the other tabs (storage events) ────────────────────────
await scenario('[T12] sign-out in tab A signs idle tab B out at once (N2)', async () => {
  const server = makeServer(), browser = makeBrowser();
  browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  await A.V('logout()');
  await sleep(50);
  ok(B.hrefs.length === 1 && B.hrefs[0] === '/sol/', `tab B goes to the sign-in page (saw ${JSON.stringify(B.hrefs)})`);
  ok(B.V('token') === null, "tab B's in-memory access token is cleared");
  ok(B.calls.length === 0, 'tab B needed no request to notice');
});

await scenario('[T13] user Y signs in over X in another tab (no sign-out): tab B reloads instead of acting for X', async () => {
  const server = makeServer(), browser = makeBrowser();
  browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B');
  browser.signIn(server, 'user-y');
  await sleep(50);
  ok(B.reloads === 1, `tab B reloads (saw ${B.reloads})`);
});

await scenario('[T14] events that are not a sign-out leave tab B alone: same-user refresh elsewhere, or another tab dropping only its access token', async () => {
  const server = makeServer(), browser = makeBrowser();
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), C = makeTab(browser, server, 'C');
  server.expire(X.access_token);
  await C.request('/groups'); await sleep(50);        // C refreshes: same user, new pair
  ok(B.hrefs.length === 0 && B.reloads === 0, `a same-user refresh in tab C does not move tab B (saw ${JSON.stringify(B.events)})`);
  browser.write(C, 'sol_token', null);                 // e.g. tab C's init() error path
  await sleep(50);
  ok(B.hrefs.length === 0 && B.reloads === 0, `another tab dropping its access token does not sign tab B out (saw ${JSON.stringify(B.events)})`);
});

await scenario("[T15] sign-out in tab A while tab B's refresh is in flight: B's late session is revoked before B leaves", async () => {
  const server = makeServer(), browser = makeBrowser();
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  server.expire(X.access_token);
  const g = server.gate(e => e.path === '/auth/refresh');
  const p = B.request('/groups');
  await settle();
  await A.V('logout()');
  await sleep(50);
  g.release();
  await p; await sleep(50);
  ok(server.active().length === 0, `no session left active (saw ${JSON.stringify(server.active())})`);
  ok(!browser.store.has('sol_refresh'), 'nothing stored');
  const i = B.events.findIndex(e => e.startsWith('revoke-answered:'));
  const j = B.events.findIndex(e => e.startsWith('redirect'));
  ok(j !== -1 && (i === -1 ? false : i < j), `tab B revoked its late session and then left (events ${JSON.stringify(B.events)})`);
});

await scenario("[T17] with storage events: tab B refreshing when X signs out and Y signs in elsewhere: B's late session is revoked before it reloads", async () => {
  const server = makeServer(), browser = makeBrowser();
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  server.expire(X.access_token);
  const g = server.gate(e => e.path === '/auth/refresh');
  const pay = B.request(...PAY);
  await settle();
  await A.V('logout()');
  const Y = browser.signIn(server, 'user-y');
  await sleep(50);                                     // B has seen both storage events
  ok(B.reloads === 0 && B.hrefs.length === 0, `B waits for its refresh in flight before leaving (saw ${JSON.stringify(B.events)})`);
  g.release();
  await pay; await sleep(50);
  ok(server.active('user-x').length === 0, `no session of X is left active (saw ${JSON.stringify(server.active('user-x'))})`);
  ok(sent(server, 'B', PAY[0]).length === 1 && !server.log.some(l => l.tab === 'B' && l.as === 'user-y'), 'the POST was sent once and nothing as Y');
  ok(browser.store.get('sol_refresh') === Y.refresh_token, "Y's session stays stored");
  const i = B.events.findIndex(e => e.startsWith('revoke-answered:'));
  const j = B.events.findIndex(e => e === 'reload' || e.startsWith('redirect'));
  ok(i !== -1 && j !== -1 && i < j && B.events.filter(e => e === 'reload' || e.startsWith('redirect')).length === 1, `B revoked its late session, then left once (events ${JSON.stringify(B.events)})`);
});

await scenario("[T18] another tab stored a newer access token that is already expired: this tab refreshes instead of adopting it", async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  const stale = server.issue('user-x', 1000);           // exp in 1970: already expired
  server.expire(stale.access_token);
  server.sessions.get(X.refresh_token).active = false;  // the other tab rotated X's first token into `stale`
  browser.write(null, 'sol_token', stale.access_token); browser.write(null, 'sol_refresh', stale.refresh_token);
  const r = await B.request('/groups'); await settle();
  ok(r.ok, `tab B's request succeeds after a real refresh (${r.ok ? 'ok' : r.e})`);
  ok(sent(server, 'B', '/auth/refresh').length === 1, 'tab B refreshed the stored session');
  ok(server.sessions.get(browser.store.get('sol_refresh'))?.active === true, 'the stored session is active');
});

await scenario("[T19] tab B's refresh fails with a network error while another tab stores a newer session of the same user: B continues with it", async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), C = makeTab(browser, server, 'C');
  server.expire(X.access_token);
  const g = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh', { networkError: true });
  const p = B.request('/groups');
  await settle();
  const newer = server.issue('user-x');
  browser.write(C, 'sol_token', newer.access_token); browser.write(C, 'sol_refresh', newer.refresh_token);
  g.release();
  const r = await p; await settle();
  ok(browser.store.get('sol_refresh') === newer.refresh_token, "tab C's newer session is not cleared");
  ok(r.ok && B.hrefs.length === 0, `tab B continues with it (${r.ok ? 'ok' : r.e}; redirects ${JSON.stringify(B.hrefs)})`);
});

await scenario("[T20] init() in a tab whose session was replaced (X signed out, Y signed in): it reloads and leaves Y's session alone", async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  await A.V('logout()');
  const Y = browser.signIn(server, 'user-y');
  server.expire(X.access_token);
  await B.V('init()').catch(() => {}); await settle();
  ok(browser.store.get('sol_token') === Y.access_token && browser.store.get('sol_refresh') === Y.refresh_token, `Y's stored session is untouched (saw ${JSON.stringify([...browser.store].filter(([k]) => k !== 'sol_signout'))})`);
  ok(B.reloads === 1 && B.hrefs.length === 0, `tab B reloads once and does not also redirect (reloads ${B.reloads}, redirects ${JSON.stringify(B.hrefs)})`);
});

// ── Back button: a page restored from the back/forward cache (critic CR-1, CR-1b) ──
await scenario('[T21] X signs out, Y signs in, X presses Back (page restored from the cache): nothing goes out as Y and the page reloads', async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const A = makeTab(browser, server, 'A');
  await A.V('logout()');
  const Y = browser.signIn(server, 'user-y');
  server.expire(X.access_token);
  const out = await A.request(...PAY); await settle();      // a request from the restored page's old code
  ok(!server.log.some(l => l.tab === 'A' && (l.as === 'user-y' || (l.path === '/auth/refresh'))), "the signed-out page neither refreshes Y's session nor sends anything as Y");
  ok(!out.ok, 'its request fails');
  const before = A.reloads;
  A.dispatch('pageshow', { persisted: true });
  ok(A.reloads === before + 1, `restored from the cache, the page reloads (state.js then starts from the stored session) (reloads ${A.reloads - before})`);
  ok(browser.store.get('sol_refresh') === Y.refresh_token && server.sessions.get(Y.refresh_token).active, "Y's session is untouched");
});

await scenario('[T22] X signs out and presses Back with nobody signed in: the restored page reloads (and state.js sends it to the sign-in page)', async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  browser.signIn(server, 'user-x');
  const A = makeTab(browser, server, 'A');
  await A.V('logout()');
  const before = A.reloads;
  A.dispatch('pageshow', { persisted: true });
  ok(A.reloads === before + 1, `the page reloads (reloads ${A.reloads - before})`);
});

await scenario('[T23] a page restored from the cache with its session unchanged is left alone; a normal page load is too', async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  browser.signIn(server, 'user-x');
  const A = makeTab(browser, server, 'A');
  A.dispatch('pageshow', { persisted: true });
  A.dispatch('pageshow', { persisted: false });
  ok(A.reloads === 0 && A.hrefs.length === 0, `no reload, no redirect (events ${JSON.stringify(A.events)})`);
});

// ── keepalive ───────────────────────────────────────────────────────────────
await scenario('[T16] the sign-out revoke is sent with keepalive, so a navigation cannot cancel it (N5)', async () => {
  const server = makeServer(), browser = makeBrowser();
  browser.signIn(server, 'user-x');
  const A = makeTab(browser, server, 'A');
  await A.V('logout()');
  const rv = A.revokes();
  ok(rv.length === 1 && rv[0].keepalive === true, `one revoke, keepalive set (saw ${JSON.stringify(rv.map(c => c.keepalive))})`);
});

console.log(`\nsession tabs: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
