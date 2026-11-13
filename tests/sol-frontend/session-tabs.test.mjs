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
//     session (N3, NF2, RC-3, RC-2): with the Web Locks stub; without it, the tab whose
//     refresh wins keeps the session (the loser may be signed out, [T6])
//   - a 429, 5xx or network error on refresh keeps the session ([T29], F2)
//   - waiting on a revoke is bounded (RC-4); a late revoke is answered before the tab
//     navigates (NF5)
//   - a sign-out in one tab signs the other tabs out at once; another user signing in
//     reloads them; another tab dropping only its access token signs nobody out (N2)
//   - revoke requests use keepalive so a navigation or a closed tab cannot cancel them
//     (N5, N6)
// The default mock browser is a synchronous shared Map: every tab sees every write at
// once. Real Chromium keeps a copy per renderer, so a tab can act on a stale view and its
// own write can land after another tab's; `lag: true` models that ([T25]-[T27]).
// What it does NOT prove: server-side revocation (the backend is a mock), Firefox or
// Safari behaviour, real cross-process timing, or anything about the deployed frontend.
// An access token already issued stays valid at the API until it expires.
import { readFileSync, existsSync } from 'node:fs';
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
// core/session.js (shared with the landing page) is loaded first when the tree has it.
const SESSION_JS = existsSync(join(CORE, 'session.js')) ? readFileSync(join(CORE, 'session.js'), 'utf8') : null;
// The landing page's real finishAuth() (index.html), so sign-ins write what the page writes.
const INDEX = readFileSync(join(CORE, '..', '..', 'index.html'), 'utf8');
const FA_START = INDEX.indexOf('function finishAuth(data)');
if (FA_START < 0) throw new Error('finishAuth() not found in index.html');
const FINISH_AUTH = INDEX.slice(FA_START, INDEX.indexOf('\n}\n', FA_START) + 2);
// The commit tag a page of this version writes after a pair (core/session.js), or null
// for a tree without core/session.js.
const solTag = !SESSION_JS ? null : (() => {
  const ctx = vm.createContext({ localStorage: { getItem: () => null }, atob, btoa });
  vm.runInContext(SESSION_JS, ctx);
  return (t, r, signout) => vm.runInContext(`_solTag(${JSON.stringify(t)}, ${JSON.stringify(r)}, ${JSON.stringify(signout)})`, ctx);
})();
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
  const issue = (user, exp = 4102444800, subClaim = user) => {
    n++;
    const a = `${b64u({ alg: 'HS256', typ: 'JWT' })}.${b64u({ sub: subClaim, type: 'access', exp, jti: `synthetic-${n}` })}.synthetic-signature-${n}`;
    const r = `synthetic-refresh-${user}-${n}`;
    sessions.set(r, { user, active: true });
    access.set(a, { user, valid: true });
    return { access_token: a, refresh_token: r, token_type: 'bearer' };
  };
  // gate(pred): the next matching request is processed at once (rotation on receipt)
  // but its answer waits for release(). opts.body holds the body too (headers first).
  // opts.before: the request waits before the server sees it (it never reached the server).
  const gate = (pred, opts = {}) => { const g = { pred, d: deferred(), body: opts.body ? deferred() : null, networkError: !!opts.networkError, before: !!opts.before, hit: false, release: () => g.d.resolve(), releaseBody: () => g.body && g.body.resolve() }; gates.push(g); return g; };
  const refreshFailures = [];   // next refreshes answer these instead (429, 503, 'network'), without rotating
  const failNextRefresh = (...kinds) => refreshFailures.push(...kinds);
  const handle = async call => {
    const path = call.url.slice(API.length);
    const bearer = (call.headers.Authorization || call.headers.authorization || '').replace(/^Bearer /, '');
    let body = {}; try { body = JSON.parse(call.body || '{}'); } catch {}
    const entry = { tab: call.tab, method: call.method, path, as: access.has(bearer) ? access.get(bearer).user : null, bearer, body };
    log.push(entry);
    const pre = gates.find(x => !x.hit && x.before && x.pred(entry, call));
    if (pre) { pre.hit = true; await pre.d.p; }
    let out;
    if (path === '/auth/refresh' && call.method === 'POST' && refreshFailures.length) {
      const kind = refreshFailures.shift();
      entry.status = kind;
      if (kind === 'network') throw new TypeError('Failed to fetch');
      return res(kind, { detail: kind === 429 ? 'Rate limit exceeded' : 'Service unavailable' });
    }
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
    const g = gates.find(x => !x.hit && !x.before && x.pred(entry, call));
    if (g) { g.hit = true; await g.d.p; if (g.networkError) throw new TypeError('Failed to fetch'); return res(out[0], out[1], g.body && g.body.p); }
    return res(out[0], out[1]);
  };
  const active = user => [...sessions].filter(([, s]) => s.active && (!user || s.user === user)).map(([k]) => k);
  return { issue, gate, handle, log, sessions, access, active, failNextRefresh, expire: a => { access.get(a).valid = false; } };
}

// ── Mock browser (shared storage, storage events, optional Web Locks) ───────
// Default: one synchronous shared Map, so every tab sees every write at once (atomic,
// instantly consistent). lag: true models Chromium's per-renderer copies instead: each
// tab reads its own view; a write lands in the browser's store and the writer's view at
// once, and reaches the other tabs' views (with its storage event) only when delivered.
// hold() queues deliveries, release() delivers them in order; on delivery a view takes
// the browser's current value for that key (views converge), and the event carries the
// value that write stored.
function makeBrowser({ locks = false, storageEvents = true, lag = false } = {}) {
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
  let holding = false;
  const queue = [];
  // A storage write reaches one tab: its view takes the browser's current value for that
  // key (views converge) and the event carries the value that write stored.
  const applyTo = (t, m) => {
    if (lag) { if (store.has(m.key)) t.view.set(m.key, store.get(m.key)); else t.view.delete(m.key); }
    if (storageEvents && m.oldValue !== m.newValue) t.dispatchStorage({ key: m.key, oldValue: m.oldValue, newValue: m.newValue });
  };
  const deliver = m => {
    if (m.broadcast) { if (m.to && m.to.held) m.to.pending.push(m); else m.broadcast(); return; }
    for (const t of tabs) {
      if (t === m.from) continue;
      if (t.held) t.pending.push(m); else applyTo(t, m);
    }
  };
  // One tab's renderer is busy: nothing reaches it until releaseTab(), in order.
  const holdTab = t => { t.held = true; t.pending = t.pending || []; };
  const releaseTab = t => { t.held = false; for (const m of (t.pending || []).splice(0)) { if (m.broadcast) m.broadcast(); else applyTo(t, m); } };
  const write = (from, k, v) => {
    const oldValue = store.has(k) ? store.get(k) : null;
    if (v === null) store.delete(k); else store.set(k, String(v));
    const newValue = v === null ? null : String(v);
    if (lag && from) { if (v === null) from.view.delete(k); else from.view.set(k, String(v)); }
    const m = { from, key: k, oldValue, newValue };
    if (holding) queue.push(m); else setTimeout(() => deliver(m), 0);
  };
  const hold = () => { holding = true; };
  // Deliver the first n held messages in order (a tab sees part of another tab's write).
  const deliverFirst = n => { for (const m of queue.splice(0, n)) deliver(m); };
  const queued = () => queue.map(m => (m.broadcast ? 'broadcast' : m.key));
  // Deliver only the held BroadcastChannel messages (storage events stay held).
  const deliverBroadcasts = () => { for (let i = 0; i < queue.length;) { if (queue[i].broadcast) deliver(queue.splice(i, 1)[0]); else i++; } };
  const release = () => { holding = false; const q = queue.splice(0); setTimeout(() => { for (const m of q) deliver(m); }, 0); };
  // Deliver held writes synchronously now (e.g. between two of a page's scripts).
  const deliverNow = () => { holding = false; for (const m of queue.splice(0)) deliver(m); };
  // A pair stored by another page of this version (e.g. a tab that refreshed): both tokens,
  // then the commit tag naming them and the sign-out record the writer sees; for a tree
  // without core/session.js, the two tokens.
  const storePair = (from, s) => {
    write(from, 'sol_token', s.access_token); write(from, 'sol_refresh', s.refresh_token);
    if (solTag) { const view = lag && from ? from.view : store; write(from, 'sol_session', solTag(s.access_token, s.refresh_token, view.has('sol_signout') ? view.get('sol_signout') : null)); }
  };
  // The old landing page (and a sign-in half written): two writes, nothing else.
  const rawSignIn = (server, user) => { const s = server.issue(user); write(null, 'sol_token', s.access_token); write(null, 'sol_refresh', s.refresh_token); return s; };
  // A sign-in through the landing page's real finishAuth(), on a newly loaded landing page
  // (it reads the current storage; the page it replaces has navigated away).
  let landing = null;
  const signIn = (server, user) => {
    if (landing) { const i = tabs.indexOf(landing); if (i >= 0) tabs.splice(i, 1); }
    landing = makeLanding(browser, server);
    const s = server.issue(user); landing.finish(s); return s;
  };
  // BroadcastChannel shared by this browser's pages: a message reaches the OTHER channels of
  // the same name (asynchronously), as in browsers. While held, messages wait with the
  // storage events (a busy tab receives nothing), in the order they were sent.
  const channels = [];
  const channelFor = owner => class extends BroadcastChannelStub { constructor(name) { super(name); this.owner = owner; } };
  class BroadcastChannelStub {
    constructor(name) { this.name = name; this.onmessage = null; this.listeners = []; channels.push(this); }
    postMessage(data) {
      if (this.owner && this.owner.navigated) return;           // a page that has gone posts nothing
      for (const c of channels) {
        if (c === this || c.name !== this.name || c.closed || (c.owner && c.owner.navigated)) continue;
        const m = { to: c.owner, broadcast: () => { const ev = { data }; if (c.onmessage) c.onmessage(ev); for (const fn of c.listeners) fn(ev); } };
        if (holding) queue.push(m); else setTimeout(() => deliver(m), 0);
      }
    }
    addEventListener(t, fn) { if (t === 'message') this.listeners.push(fn); }
    removeEventListener() {}
    close() { this.closed = true; }
  }
  const browser = { store, tabs, locksApi, write, storePair, signIn, rawSignIn, hold, release, deliverNow, deliverFirst, queued, deliverBroadcasts, holdTab, releaseTab, lag, BroadcastChannel: BroadcastChannelStub, channelFor, get landing() { return landing; } };
  return browser;
}

// The landing page: the real finishAuth() (and core/session.js when the tree has it), with
// its own view of storage like any tab. It has no listeners.
function makeLanding(browser, server) {
  const calls = [], hrefs = [];
  const page = { label: 'landing', calls, hrefs, view: new Map(browser.store), dispatchStorage() {} };
  const area = () => (browser.lag ? page.view : browser.store);
  const localStorage = { getItem: k => (area().has(k) ? area().get(k) : null), setItem: (k, v) => browser.write(page, k, v), removeItem: k => browser.write(page, k, null) };
  const location = {}; Object.defineProperty(location, 'href', { get: () => '/sol/', set: v => hrefs.push(v) });
  const sandbox = { console, Promise, JSON, Date, Math, API, localStorage, window: { location }, location, setTimeout, clearTimeout, atob, btoa, BroadcastChannel: browser.channelFor(page),
    fetch: (url, opts = {}) => { const call = { tab: 'landing', url: String(url), method: (opts.method || 'GET').toUpperCase(), headers: opts.headers || {}, body: opts.body, keepalive: !!opts.keepalive }; calls.push(call); return server.handle(call); } };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  if (SESSION_JS) vm.runInContext(SESSION_JS, sandbox);
  vm.runInContext(FINISH_AUTH, sandbox);
  browser.tabs.push(page);
  page.finish = s => vm.runInContext(`finishAuth(${JSON.stringify(s)})`, sandbox);
  return page;
}

// One tab of the member app: core/session.js (when the tree has it), state.js, router.js,
// api.js in app.html's order.
// Options: blockRevokes (this tab's revokes never answer), throwOnSet(key, attempt) (a
// localStorage write throws, e.g. QuotaExceededError), noAbortSignalTimeout (an older
// browser without AbortSignal.timeout), between(tab) (runs after state.js and before
// router.js, e.g. a sign-out elsewhere while this page is still loading).
// noSessionJs: core/session.js is not loaded (an app.html from before it was added, served
// with this version's scripts).
function makeTab(browser, server, label, { blockRevokes = false, throwOnSet = null, noAbortSignalTimeout = false, between = null, noSessionJs = false } = {}) {
  const calls = [], hrefs = [], events = [], listeners = { storage: [] };
  let reloads = 0;
  // Navigating (href set, reload) ends the page as in a browser: its pending fetches are
  // cancelled, except keepalive ones already sent, and it sends nothing new.
  const pending = new Set();
  const navigate = () => { if (tab.navigated) return; tab.navigated = true; for (const p of [...pending]) if (!p.keepalive) p.cancel(); };
  const location = { search: '', reload: () => { reloads++; events.push('reload'); navigate(); } };
  Object.defineProperty(location, 'href', { get: () => hrefs[hrefs.length - 1] || '/sol/app', set: v => { hrefs.push(v); events.push('redirect:' + v); navigate(); } });
  const tab = { label, calls, hrefs, events, get reloads() { return reloads; }, navigated: false, held: false, pending: [] };
  tab.view = new Map(browser.store);   // this tab's own copy (used when browser.lag)
  const sets = new Map();
  const area = () => (browser.lag ? tab.view : browser.store);
  const localStorage = {
    getItem: k => (area().has(k) ? area().get(k) : null),
    setItem: (k, v) => {
      const n = (sets.get(k) || 0) + 1; sets.set(k, n);
      if (throwOnSet && throwOnSet(k, n)) throw new DOMException('The quota has been exceeded.', 'QuotaExceededError');
      browser.write(tab, k, v);
    },
    removeItem: k => browser.write(tab, k, null),
  };
  const window = { location, addEventListener: (t, fn) => { (listeners[t] = listeners[t] || []).push(fn); }, removeEventListener() {} };
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, JSON, URLSearchParams, AbortController, DOMException, atob, btoa,
    AbortSignal: noAbortSignalTimeout ? { abort: AbortSignal.abort } : AbortSignal,
    window, location, localStorage,
    navigator: browser.locksApi ? { locks: browser.locksApi } : {},
    BroadcastChannel: browser.channelFor(tab),
    document: { querySelectorAll: () => [], querySelector: () => null, getElementById: () => null },
    fetch: (url, opts = {}) => {
      const call = { tab: label, url: String(url), method: (opts.method || 'GET').toUpperCase(), headers: opts.headers || {}, body: opts.body, keepalive: !!opts.keepalive };
      if (tab.navigated) { events.push('after-navigation:' + call.url.slice(API.length)); return new Promise(() => {}); }   // the page has gone
      calls.push(call);
      let answer;
      if (call.url === API + '/auth/logout') {
        if (blockRevokes) return new Promise(() => {});
        let tok = null; try { tok = JSON.parse(call.body).refresh_token; } catch {}
        answer = server.handle(call).then(r => { events.push('revoke-answered:' + tok); return r; });
      } else {
        answer = server.handle(call);
      }
      return new Promise((resolve, reject) => {
        const entry = { keepalive: call.keepalive, cancel: () => { pending.delete(entry); events.push('cancelled:' + call.url.slice(API.length)); reject(new DOMException('The operation was aborted.', 'AbortError')); } };
        pending.add(entry);
        const signal = opts.signal;
        if (signal) {
          const aborted = () => { pending.delete(entry); events.push('aborted:' + call.url.slice(API.length)); reject(new DOMException('The operation was aborted.', 'AbortError')); };
          if (signal.aborted) return aborted();
          signal.addEventListener('abort', aborted);
        }
        answer.then(v => { if (pending.delete(entry)) resolve(v); }, e => { if (pending.delete(entry)) reject(e); });
      });
    },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  tab.V = expr => vm.runInContext(expr, sandbox);
  tab.listeners = listeners;
  tab.dispatchStorage = ev => { for (const fn of listeners.storage || []) fn({ ...ev, storageArea: localStorage, url: 'https://app.invalid/sol/app' }); };
  browser.tabs.push(tab);
  if (SESSION_JS && !noSessionJs) vm.runInContext(SESSION_JS, sandbox);
  vm.runInContext(SRC['state.js'], sandbox);
  if (between) between(tab);
  for (const f of ['router.js', 'api.js']) vm.runInContext(SRC[f], sandbox);
  // A page restored from the back/forward cache is alive again (it navigated away before).
  tab.dispatch = (type, ev) => { if (type === 'pageshow' && ev && ev.persisted) tab.navigated = false; for (const fn of listeners[type] || []) fn(ev); };
  tab.revokes = () => calls.filter(c => c.method === 'POST' && c.url === API + '/auth/logout');
  tab.request = (path, opts) => tab.V(`api(${JSON.stringify(path)}, ${JSON.stringify(opts || {})})`).then(v => ({ ok: true, v }), e => ({ ok: false, e: String(e && e.message) }));
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
const userOf = jwt => { try { return JSON.parse(Buffer.from(String(jwt).split('.')[1], 'base64url')).sub; } catch { return null; } };
// What a tab opened now would run with: the access token its state.js accepts (null: it goes
// to the sign-in page). A new tab reads the browser's current storage.
let opened = 0;
const openNow = (browser, server) => makeTab(browser, server, 'new-' + (++opened)).V('token');
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
  ok(g.hit && server.log.some(l => l.tab === 'B' && l.path === '/auth/refresh' && l.status === 200), "B's refresh was processed before the sign-out (its late answer is a 200)");
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
  ok(gB.hit && gC.hit && server.log.find(l => l.tab === 'C' && l.path === '/auth/refresh').status === 401 && server.log.find(l => l.tab === 'B' && l.path === '/auth/refresh').status === 200, 'the interleaving happened: B rotated first (200), C got 401 and answered first');
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
  browser.storePair(C, newer);
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
  ok(g.hit && server.log.some(l => l.tab === 'B' && l.path === '/auth/refresh' && l.status === 200), "B's refresh was processed before its sign-out");
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
  ok(g.hit && server.log.some(l => l.tab === 'B' && l.path === '/auth/refresh' && l.status === 200), "B's refresh answered 200 before the sign-out (body still pending)");
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
  browser.storePair(null, stale);
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
  browser.storePair(C, newer);
  g.release();
  const r = await p; await settle();
  ok(g.hit, "B's refresh reached the network-error gate");
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
  A.navigated = false;                                      // the page is back from the cache (its pageshow handler runs below)
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
  const B = makeTab(browser, server, 'B');
  browser.signIn(server, 'user-y');                     // the session changed (no events in this browser)
  B.dispatch('pageshow', { persisted: false });         // an ordinary page load: state.js already ran
  ok(B.reloads === 0, `a non-persisted pageshow never reloads (reloads ${B.reloads})`);
});

await scenario('[T24] a page in the back/forward cache misses another tab\'s sign-out (no storage events there): restored, it reloads', async () => {
  for (const [label, after] of [['X signs out in tab B', null], ['X signs out in tab B and Y signs in', 'user-y'], ['X signs out in tab B and signs in again', 'user-x']]) {
    const server = makeServer(), browser = makeBrowser({ storageEvents: false });   // a cached page runs no JS, so it gets no events
    browser.signIn(server, 'user-x');
    const A = makeTab(browser, server, 'A'), B = makeTab(browser, server, 'B');
    await B.V('logout()');
    if (after) browser.signIn(server, after);
    A.dispatch('pageshow', { persisted: true });
    ok(A.reloads === 1, `${label}: the restored page reloads (reloads ${A.reloads})`);
  }
});

// ── Round 3: second independent review (review 2) ───────────────────────────
await scenario("[T25] lagging views (Chromium): B's refresh answer is handled before A's sign-out reaches B, and B's write lands last: nobody uses that pair and B revokes it (RV2-H1)", async () => {
  const server = makeServer(), browser = makeBrowser({ lag: true });
  const X = browser.signIn(server, 'user-x');
  await settle();
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  server.expire(X.access_token);
  const g = server.gate(e => e.path === '/auth/refresh');
  const p = B.request('/groups');
  await settle();
  browser.hold();                                       // A's writes have not reached B's renderer yet
  await A.V('logout()');
  g.release(); await settle();                          // B stores its late pair; its write lands last
  ok(browser.store.has('sol_refresh'), "the race happened: B's late pair landed after A's sign-out");
  ok(openNow(browser, server) === null, 'a tab opened before B sees the sign-out does not use the late pair');
  browser.release(); await p; await sleep(80);
  ok(openNow(browser, server) === null, 'nor a tab opened after');
  ok(server.active().length === 0, `no session is left active (saw ${JSON.stringify(server.active())})`);
});

await scenario("[T26] lagging views: Y signs in over X while B's refresh answer is handled, and B's write lands last: X's session does not stay stored (RV2-M1)", async () => {
  const server = makeServer(), browser = makeBrowser({ lag: true });
  const X = browser.signIn(server, 'user-x');
  await settle();
  const B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  const g = server.gate(e => e.path === '/auth/refresh');
  const p = B.request('/groups');
  await settle();
  browser.hold();
  browser.rawSignIn(server, 'user-y');                  // the old landing page: two writes, no sign-out record
  g.release(); await settle();
  browser.release(); await p; await sleep(80);
  const t = openNow(browser, server);
  ok(userOf(t) !== 'user-x', `a tab opened now does not run as X (Y's app must not run as X; it got ${t ? userOf(t) : 'no session'})`);
  ok(server.active('user-x').length === 0, `no session of X is left active (saw ${JSON.stringify(server.active('user-x'))})`);
});

await scenario("[T27] lagging views, reverse order: B stored its new pair just before A's click, but A's view lacks it: B revokes it on the sign-out (RV2-L1)", async () => {
  const server = makeServer(), browser = makeBrowser({ lag: true });
  const X = browser.signIn(server, 'user-x');
  await settle();
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  server.expire(X.access_token);
  browser.hold();                                       // B's writes do not reach A before A's click
  const r = await B.request('/groups'); await settle();
  ok(r.ok && server.active('user-x').length === 1, 'B refreshed and stored a new pair');
  await A.V('logout()');                                // A revokes the token it sees: X's first, already rotated
  browser.release(); await sleep(80);
  ok(server.active().length === 0, `no session is left active (saw ${JSON.stringify(server.active())})`);
  ok(openNow(browser, server) === null, 'a tab opened now goes to the sign-in page');
});

await scenario("[T28] the sign-out record cannot be written (QuotaExceededError): a refresh in flight in tab B still stores nothing (F1)", async () => {
  for (const [label, throwOnSet] of [['every write of the record fails', k => k === 'sol_signout'], ['only the first write fails (retried after freeing space)', (k, n) => k === 'sol_signout' && n === 1]]) {
    const server = makeServer(), browser = makeBrowser();
    const X = browser.signIn(server, 'user-x');
    const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A', { throwOnSet }), C = makeTab(browser, server, 'C');
    const recordBefore = browser.store.get('sol_signout');
    server.expire(X.access_token);
    const g = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
    const p = B.request(...PAY);
    await settle();
    await A.V('logout()');
    g.release(); await p; await sleep(60);
    ok(!browser.store.has('sol_refresh') && server.active().length === 0, `${label}: nothing stored and no session active (saw ${JSON.stringify(server.active())})`);
    ok(sent(server, 'B', PAY[0]).length === 1, `${label}: B's POST was not re-sent`);
    if (label.startsWith('only')) {
      ok(C.hrefs.length === 1, `${label}: idle tab C was signed out (saw ${JSON.stringify(C.hrefs)})`);
      ok(browser.store.get('sol_signout') !== recordBefore, `${label}: the record was written on the retry (pages restored from the cache, and tabs that miss the announcement, read it)`);
    }
  }
});

await scenario('[T29] a 429, a 503 or a network error on /auth/refresh keeps the session: the request fails, nothing is cleared, the tab stays (F2)', async () => {
  for (const kind of [429, 503, 'network']) {
    const server = makeServer(), browser = makeBrowser();
    const X = browser.signIn(server, 'user-x');
    const B = makeTab(browser, server, 'B');
    server.expire(X.access_token);
    server.failNextRefresh(kind);
    const r = await B.request('/groups'); await settle();
    ok(!r.ok && browser.store.get('sol_refresh') === X.refresh_token && B.hrefs.length === 0 && B.reloads === 0, `${kind}: the request fails, the session stays stored and the tab stays (${r.e}; redirects ${JSON.stringify(B.hrefs)})`);
    const again = await B.request('/groups'); await settle();
    ok(again.ok, `${kind}: the next request refreshes and succeeds (${again.ok ? 'ok' : again.e})`);
  }
});

await scenario('[T30] the refresh lock is not granted in time (holder hung; no AbortSignal.timeout here): the request fails without an unlocked refresh, the session stays (F3, RV2R-4)', async () => {
  const server = makeServer(), browser = makeBrowser({ locks: true });
  const X = browser.signIn(server, 'user-x');
  const C = makeTab(browser, server, 'C'), B = makeTab(browser, server, 'B', { noAbortSignalTimeout: true });
  server.expire(X.access_token);
  server.gate(e => e.tab === 'C' && e.path === '/auth/refresh');   // C holds the lock; its refresh never answers
  C.request('/groups');
  await settle();
  const r = await within(B.request('/groups'), 14000);
  ok(r.settled, `B's request settled after the bounded lock wait (${r.settled ? 'yes' : 'still waiting after 14 s'})`);
  if (r.settled) ok(!r.v.ok && B.hrefs.length === 0, `it failed and B stayed (${r.v.e}; redirects ${JSON.stringify(B.hrefs)})`);
  ok(sent(server, 'B', '/auth/refresh').length === 0, 'B sent no refresh without the lock');
  ok(browser.store.has('sol_refresh'), 'the session stays stored');
});

await scenario("[T31] a 401 in tab B while A's sign-out propagates and B's own refresh is in flight: B joins that refresh instead of leaving at once (F4)", async () => {
  const server = makeServer(), browser = makeBrowser();
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  server.expire(X.access_token);
  const g = server.gate(e => e.path === '/auth/refresh');
  const first = B.request('/groups');
  await settle();
  await A.V('logout()'); await sleep(20);
  const second = B.request('/circles');
  await sleep(50);
  ok(B.hrefs.length === 0 && B.reloads === 0, `B does not leave before its refresh answers (events ${JSON.stringify(B.events)})`);
  g.release(); await first; await second; await sleep(50);
  ok(server.active().length === 0, `B's late session was revoked (active ${JSON.stringify(server.active())})`);
  const i = B.events.findIndex(e => e.startsWith('revoke-answered:')), j = B.events.findIndex(e => e.startsWith('redirect') || e === 'reload');
  ok(i !== -1 && j !== -1 && i < j, `revoke answered before B left (events ${JSON.stringify(B.events)})`);
});

await scenario('[T32] X signs out in tab A while tab B is still loading (after state.js, before router.js): B notices at once (F5)', async () => {
  const server = makeServer(), browser = makeBrowser();
  browser.signIn(server, 'user-x');
  const A = makeTab(browser, server, 'A');
  // The storage events reach B before router.js has run (so before its listener exists).
  const B = makeTab(browser, server, 'B', { between: () => { browser.hold(); A.V('logout()'); browser.deliverNow(); } });
  await B.V('init()').catch(() => {});                  // main.js runs init() after the other scripts
  await sleep(60);
  ok(B.hrefs.length === 1 && B.hrefs[0] === '/sol/', `tab B goes to the sign-in page (saw ${JSON.stringify(B.events)})`);
  ok(B.calls.length === 0, `init() sends nothing (not even /auth/me) from a tab that is leaving (saw ${JSON.stringify(B.calls.map(c => c.url.slice(API.length)))})`);
});

await scenario('[T33] never adopt an expired stored token; a token adopted on a slow clock and rejected gets one real refresh (RV2R-5)', async () => {
  {
    const server = makeServer(), browser = makeBrowser({ storageEvents: false });
    const X = browser.signIn(server, 'user-x');
    const B = makeTab(browser, server, 'B'), C = makeTab(browser, server, 'C');
    server.expire(X.access_token);
    const g = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
    const p = B.request('/groups');
    await settle();
    const stale = server.issue('user-x', 1000); server.expire(stale.access_token);   // C stored a pair whose access token is already expired
    browser.storePair(C, stale);
    g.release();
    const r = await p; await settle();
    ok(!server.log.some(l => l.tab === 'B' && l.bearer === stale.access_token), 'B did not send the expired token');
    ok(browser.store.get('sol_refresh') === stale.refresh_token && B.hrefs.length === 0, `C's newer session is kept and B stays (${r.ok ? 'ok' : r.e})`);
  }
  {
    const server = makeServer(), browser = makeBrowser({ storageEvents: false });
    const X = browser.signIn(server, 'user-x');
    const B = makeTab(browser, server, 'B');
    server.expire(X.access_token);
    const skewed = server.issue('user-x'); server.expire(skewed.access_token);        // valid by the JWT exp, expired at the server
    server.sessions.get(X.refresh_token).active = false;
    browser.storePair(null, skewed);
    const r = await B.request('/groups'); await settle();
    ok(r.ok, `after the adopted token is rejected, one real refresh makes the request succeed (${r.ok ? 'ok' : r.e})`);
  }
});

await scenario('[T34] a stored token whose user claim is not readable as a string is treated as another user\'s (RV2R-10)', async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  const odd = server.issue('user-z', 4102444800, 12345);   // readable JWT, numeric sub
  browser.storePair(null, odd);
  await B.request(...PAY); await settle();
  ok(!server.log.some(l => l.tab === 'B' && (l.bearer === odd.access_token || l.path === '/auth/refresh')), 'B neither adopts nor refreshes that session');
  ok(B.reloads === 1, `B reloads (saw ${B.reloads})`);
});

await scenario('[T35] a page restored from the cache, then the storage events it missed: it reloads once and is not sent to the sign-in page (F9)', async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  browser.signIn(server, 'user-x');
  const A = makeTab(browser, server, 'A'), B = makeTab(browser, server, 'B');
  await B.V('logout()');
  browser.signIn(server, 'user-y');
  A.dispatch('pageshow', { persisted: true });
  A.dispatchStorage({ key: 'sol_signout', oldValue: null, newValue: 'later' });   // queued events delivered after restore
  await sleep(30);
  ok(A.reloads === 1 && A.hrefs.length === 0, `one reload, no redirect (events ${JSON.stringify(A.events)})`);
});

await scenario("[T36] one tab, the refresh is rejected (401, session revoked elsewhere): the session is not used again and the tab goes to the sign-in page, once", async () => {
  const server = makeServer(), browser = makeBrowser();
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  server.sessions.get(X.refresh_token).active = false;
  const r = await B.request('/groups'); await settle();
  ok(!r.ok && openNow(browser, server) === null, 'the dead session is not used again (a tab opened now goes to the sign-in page)');
  ok(B.hrefs.length === 1 && B.hrefs[0] === '/sol/' && B.reloads === 0, `the tab goes to the sign-in page once (events ${JSON.stringify(B.events)})`);
  ok(sent(server, 'B', '/auth/refresh').length === 1, 'one refresh attempt, no loop');
});

await scenario("[T37] Y signs in over X (no sign-out) while B's refresh is in flight: B sends nothing as Y (F10)", async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  const g = server.gate(e => e.path === '/auth/refresh');
  const pay = B.request(...PAY);
  await settle();
  const Y = browser.signIn(server, 'user-y');
  g.release(); await pay; await settle();
  ok(!server.log.some(l => l.tab === 'B' && l.as === 'user-y'), 'nothing was sent as Y');
  ok(browser.store.get('sol_refresh') === Y.refresh_token && server.sessions.get(Y.refresh_token).active, "Y's session is untouched");
  ok(server.active('user-x').length === 0, "B's late session of X was revoked");
  ok(B.reloads === 1, `B reloads (saw ${B.reloads})`);
});

await scenario('[T38] two sign-outs in one browser: a tab opened after the first sign-out still notices the second', async () => {
  const server = makeServer(), browser = makeBrowser();
  browser.signIn(server, 'user-x');
  const A = makeTab(browser, server, 'A');
  await A.V('logout()'); await sleep(20);
  browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), C = makeTab(browser, server, 'C');
  await C.V('logout()'); await sleep(40);
  ok(B.hrefs.length === 1 && B.hrefs[0] === '/sol/', `tab B is signed out by the second sign-out (saw ${JSON.stringify(B.events)})`);
});

await scenario('[T39] a storage clear event (key null) signs the tab out; a reload already wanted is not replaced by the sign-in page', async () => {
  {
    const server = makeServer(), browser = makeBrowser();
    browser.signIn(server, 'user-x');
    const B = makeTab(browser, server, 'B');
    browser.store.clear();
    B.dispatchStorage({ key: null, oldValue: null, newValue: null });
    await sleep(20);
    ok(B.hrefs.length === 1 && B.hrefs[0] === '/sol/', `cleared storage: B goes to the sign-in page (saw ${JSON.stringify(B.events)})`);
  }
  {
    const server = makeServer(), browser = makeBrowser();
    const X = browser.signIn(server, 'user-x');
    const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
    server.expire(X.access_token);
    const g = server.gate(e => e.path === '/auth/refresh');
    const p = B.request('/groups');
    await settle();
    const Y = server.issue('user-y');
    browser.storePair(null, Y);   // another user: B wants a reload
    await sleep(20);
    await A.V('logout()'); await sleep(20);              // then a sign-out event
    g.release(); await p; await sleep(50);
    ok(B.reloads === 1 && B.hrefs.length === 0, `B reloads once and is not sent to the sign-in page (events ${JSON.stringify(B.events)})`);
  }
});

await scenario('[T40] X signs out and signs in again in another tab before tab B reacts: B reloads (a session is stored by then) instead of showing the sign-in page', async () => {
  const server = makeServer(), browser = makeBrowser();
  browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  A.V('logout()');
  browser.signIn(server, 'user-x');                     // the landing page stores X's new session before B's events run
  await sleep(50);
  ok(B.reloads === 1 && B.hrefs.length === 0, `B reloads once (events ${JSON.stringify(B.events)})`);
});

await scenario("[T41] B's refresh is rejected because another tab rotated first, and that tab's stored access token is already expired: B does not adopt it", async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  server.sessions.get(X.refresh_token).active = false;   // rotated by another tab ...
  const g = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
  const p = B.request('/groups');
  await settle();
  const stale = server.issue('user-x', 1000); server.expire(stale.access_token);   // ... which stored a pair whose access token is expired
  browser.storePair(null, stale);
  g.release();
  const r = await p; await settle();
  ok(g.hit && server.log.find(l => l.tab === 'B' && l.path === '/auth/refresh').status === 401, "B's refresh was rejected (401)");
  ok(!server.log.some(l => l.tab === 'B' && l.bearer === stale.access_token), 'B did not send the expired token');
  ok(browser.store.get('sol_refresh') === stale.refresh_token && B.hrefs.length === 0, `the newer session is kept and B stays (${r.ok ? 'ok' : r.e})`);
  await sleep(REVOKE_BOUND_MS + 200);
  ok(B.hrefs.length === 0 && B.reloads === 0, `B neither leaves nor reloads (events ${JSON.stringify(B.events)})`);
});

for (const legacy of [false, true]) await scenario(`[T42] B's refresh answers while another user's sign-in is half written (Y's access token, still X's refresh token): B writes nothing over it${legacy ? ' (storage from before this version, no commit tag)' : ''}`, async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = legacy ? browser.rawSignIn(server, 'user-x') : browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  const g = server.gate(e => e.path === '/auth/refresh');
  const p = B.request(...PAY);
  await settle();
  const Y = server.issue('user-y');
  browser.write(null, 'sol_token', Y.access_token);     // the landing page's first write has landed, its second not yet
  g.release(); await p; await settle();
  ok(browser.store.get('sol_token') === Y.access_token, "Y's access token was not overwritten");
  browser.write(null, 'sol_refresh', Y.refresh_token);   // the second write lands
  ok(server.active('user-x').length === 0, `B's late session of X was revoked (active ${JSON.stringify(server.active('user-x'))})`);
  ok(!server.log.some(l => l.tab === 'B' && l.as === 'user-y') && B.reloads === 1, 'B sent nothing as Y and reloads');
});

// ── Round 4: third independent review (review 3) ────────────────────────────
await scenario("[T43] X signs out and Y signs in while tab B, which refreshed earlier, has not seen it yet: Y's new session is not removed (RV3-N1)", async () => {
  for (const lag of [true, false]) {
    const label = lag ? 'lagging views' : 'shared view';
    const server = makeServer(), browser = makeBrowser({ lag });
    const X = browser.signIn(server, 'user-x');
    await settle();
    const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
    server.expire(X.access_token);
    const r = await B.request('/groups'); await settle();       // B refreshed: the stored pair is the one B wrote
    ok(r.ok, `${label}: B refreshed and stored its pair`);
    browser.hold();                                             // B's renderer is busy (e.g. a background tab)
    await A.V('logout()');
    const Y = browser.signIn(server, 'user-y');                 // the landing page, loaded after the sign-out
    browser.release(); await sleep(80);
    ok(browser.store.get('sol_token') === Y.access_token && browser.store.get('sol_refresh') === Y.refresh_token, `${label}: Y's session is still stored (saw ${JSON.stringify([...browser.store].filter(([k]) => k === 'sol_token' || k === 'sol_refresh').map(([k, v]) => k + '=' + userOf(v) + '/' + String(v).slice(-12)))})`);
    ok(userOf(openNow(browser, server)) === 'user-y', `${label}: a tab opened now runs as Y`);
    ok(server.sessions.get(Y.refresh_token).active, `${label}: Y's session is active at the server`);
    ok(server.active('user-x').length === 0, `${label}: no session of X is left active (saw ${JSON.stringify(server.active('user-x'))})`);
  }
});

await scenario("[T44] lagging views: B's late refresh of X lands after X signed out and Y signed in; Y's app tab opened then does not run as X (RV3C-1)", async () => {
  const server = makeServer(), browser = makeBrowser({ lag: true });
  const X = browser.signIn(server, 'user-x');
  await settle();
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  server.expire(X.access_token);
  const g = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
  const p = B.request('/groups');
  await settle();
  browser.hold();                                             // B's renderer has not seen the sign-out or the sign-in
  await A.V('logout()');
  browser.signIn(server, 'user-y');
  g.release(); await settle();                                // B stores its late pair of X; its writes land last
  ok(userOf(browser.store.get('sol_token')) === 'user-x', "the race happened: X's late access token is in storage");
  const t = openNow(browser, server);                         // Y's app tab, loaded before B sees anything
  ok(userOf(t) !== 'user-x', `the tab opened now does not run as X (it got ${t ? userOf(t) : 'no session'})`);
  browser.release(); await p; await sleep(80);
  ok(userOf(openNow(browser, server)) !== 'user-x', 'nor a tab opened after B saw the sign-out');
  ok(server.active('user-x').length === 0, `B's late session of X was revoked (active ${JSON.stringify(server.active('user-x'))})`);
});

await scenario("[T45] lagging views: B's refresh is rejected because tab C rotated first, and C's new pair has not reached B's view: C's pair stays usable", async () => {
  const server = makeServer(), browser = makeBrowser({ lag: true });
  const X = browser.signIn(server, 'user-x');
  await settle();
  const B = makeTab(browser, server, 'B'), C = makeTab(browser, server, 'C');
  server.expire(X.access_token);
  browser.hold();                                             // C's writes do not reach B before B's 401
  const rc = await C.request('/groups');
  ok(rc.ok && browser.store.get('sol_refresh') !== X.refresh_token, 'C refreshed and stored a new pair');
  const cPair = [browser.store.get('sol_token'), browser.store.get('sol_refresh')];
  const rb = await B.request('/groups');                      // B sends X's first refresh token: 401
  ok(sent(server, 'B', '/auth/refresh').some(l => l.status === 401), "B's refresh was rejected (401)");
  browser.release(); await sleep(80);
  ok(browser.store.get('sol_token') === cPair[0] && browser.store.get('sol_refresh') === cPair[1], `C's pair is still stored (B ${rb.ok ? 'continued' : 'failed: ' + rb.e})`);
  ok(openNow(browser, server) === cPair[0], "a tab opened now uses C's pair");
  ok(server.sessions.get(cPair[1]).active, "C's session is active at the server");
});

await scenario('[T46] a refresh that never answers is given up after a bound: the lock is released, the session kept, and the next refresh works (RV3-N5)', async () => {
  const server = makeServer(), browser = makeBrowser({ locks: true });
  const X = browser.signIn(server, 'user-x');
  const C = makeTab(browser, server, 'C'), B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  server.gate(e => e.tab === 'C' && e.path === '/auth/refresh', { before: true });   // the request never gets through
  const rc = await within(C.request('/groups'), 23000);
  ok(rc.settled, `C's request settled once the refresh was given up (${rc.settled ? 'yes' : 'still waiting after 23 s'})`);
  if (rc.settled) ok(!rc.v.ok && C.hrefs.length === 0 && C.reloads === 0, `it failed and C stayed (${rc.v.e})`);
  ok(browser.store.get('sol_refresh') === X.refresh_token, 'the session stays stored');
  const rb = await within(B.request('/groups'), 5000);
  ok(rb.settled && rb.v.ok, `B's next request gets the lock, refreshes and succeeds (${rb.settled ? (rb.v.ok ? 'ok' : rb.v.e) : 'still waiting after 5 s'})`);
  await sleep(REVOKE_BOUND_MS + 300);
  ok(C.hrefs.length === 0 && C.reloads === 0, `C still stays after the leave bound: a request that gave up waiting is not a sign-out (events ${JSON.stringify(C.events)})`);
});

await scenario('[T47] the sign-out record can never be written (storage full): an idle tab is still signed out (RV3-N6)', async () => {
  const server = makeServer(), browser = makeBrowser();
  browser.signIn(server, 'user-x');
  const A = makeTab(browser, server, 'A', { throwOnSet: k => k === 'sol_signout' }), C = makeTab(browser, server, 'C');
  await A.V('logout()'); await sleep(40);
  ok(C.hrefs.length === 1 && C.hrefs[0] === '/sol/', `idle tab C goes to the sign-in page (saw ${JSON.stringify(C.events)})`);
  ok(server.active().length === 0, 'no session is left active');
});

await scenario('[T48] a pair stored before this version (no commit tag) still counts; after X signs out here, a late pair of X written by a tab still on the earlier version does not', async () => {
  const server = makeServer(), browser = makeBrowser();
  const X = browser.rawSignIn(server, 'user-x');              // stored by the earlier landing page: two writes, no tag
  const A = makeTab(browser, server, 'A');
  ok(A.V('token') === X.access_token, 'a pair stored before this version is used as before');
  await A.V('logout()'); await sleep(20);
  const late = server.issue('user-x');                        // that tab rotated X's token and now stores the pair (two writes)
  browser.write(null, 'sol_token', late.access_token); browser.write(null, 'sol_refresh', late.refresh_token);
  const t = openNow(browser, server);
  ok(t === null, `a tab opened now does not use the late pair (it got ${t ? userOf(t) : 'no session'})`);
});

await scenario("[T49] lagging views, the sign-out record can never be written, and only the announcement reaches B before its refresh answers: B stores nothing that counts", async () => {
  const server = makeServer(), browser = makeBrowser({ lag: true });
  const X = browser.signIn(server, 'user-x');
  await settle();
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A', { throwOnSet: k => k === 'sol_signout' });
  server.expire(X.access_token);
  const g = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
  const p = B.request('/groups');
  await settle();
  browser.hold();                                             // A's storage writes do not reach B ...
  await A.V('logout()');
  browser.deliverBroadcasts(); await settle();                // ... but its announcement does
  g.release(); await settle();
  browser.release(); await p; await sleep(80);
  const t = openNow(browser, server);
  ok(userOf(t) !== 'user-x', `a tab opened now does not run as X (it got ${t ? userOf(t) : 'no session'})`);
  ok(server.active('user-x').length === 0, `no session of X is left active (saw ${JSON.stringify(server.active('user-x'))})`);
});

await scenario("[T50] a page restored from the back/forward cache while the stored pair is dead (another tab's refresh of it was rejected): it reloads", async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const P = makeTab(browser, server, 'P'), C = makeTab(browser, server, 'C');
  server.expire(X.access_token);
  server.sessions.get(X.refresh_token).active = false;      // revoked elsewhere
  await C.request('/groups'); await settle();               // C's refresh is rejected; the pair stays stored, listed dead
  ok(browser.store.get('sol_refresh') === X.refresh_token && openNow(browser, server) === null, 'the pair is still stored but no longer counts');
  P.dispatch('pageshow', { persisted: true });
  ok(P.reloads === 1, `the restored page reloads (saw ${P.reloads})`);
});

await scenario("[T51] the old landing page (no record): B's late pair of X is listed dead; tab C, still behind, then gets its stale refresh rejected and lists that too: X's pair stays dead (review 5, RV5-TESTS-1/2)", async () => {
  const server = makeServer(), browser = makeBrowser({ lag: true });
  const X = browser.signIn(server, 'user-x');
  await settle();
  const B = makeTab(browser, server, 'B'), C = makeTab(browser, server, 'C');
  browser.holdTab(C);                                         // C's renderer is busy: it sees nothing of what follows
  server.expire(X.access_token);
  const g = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
  const p = B.request('/groups');
  await settle();
  browser.hold();
  browser.rawSignIn(server, 'user-y');                        // the old landing page: two writes, no record
  g.release(); await settle();                                // B stores its late pair of X last
  browser.release(); await p; await sleep(80);               // B sees Y's token, lists its own pair dead, revokes it, leaves
  const late = browser.store.get('sol_refresh');
  ok(late && late !== X.refresh_token && /user-x/.test(late), 'the race happened: B\'s late pair of X is the stored one');
  ok(userOf(openNow(browser, server)) !== 'user-x', 'a tab opened now does not run as X');
  const rc = await C.request('/groups'); await sleep(40);    // C still sends X's first refresh token: rejected, and C lists it dead
  ok(sent(server, 'C', '/auth/refresh').some(l => l.status === 401), `C sent its stale refresh and it was rejected (${rc.ok ? 'ok' : rc.e})`);
  const t = openNow(browser, server);
  ok(userOf(t) !== 'user-x', `after C's listing, a tab opened now still does not run as X (it got ${t ? userOf(t) : 'no session'})`);
  browser.releaseTab(C);
});

// ── Round 5: findings of the interrupted review 4 (regression lens) ───────────
await scenario('[T52] a tab still on the earlier version refreshes the session (no sign-out): its pair, written without a tag, still counts (review 4, E1)', async () => {
  const server = makeServer(), browser = makeBrowser();
  const X = browser.signIn(server, 'user-x');                 // stored by this version: tagged
  const B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  server.sessions.get(X.refresh_token).active = false;        // the earlier-version tab rotated X's refresh token ...
  const X2 = server.issue('user-x');
  browser.write(null, 'sol_token', X2.access_token); browser.write(null, 'sol_refresh', X2.refresh_token);   // ... and stored the new pair (two writes, no tag)
  await settle();
  ok(openNow(browser, server) === X2.access_token, 'a tab opened now uses that pair');
  const r = await B.request('/groups'); await settle();
  ok(r.ok && B.hrefs.length === 0 && B.reloads === 0, `B's next 401 continues with it instead of signing out (${r.ok ? 'ok' : r.e}; redirects ${JSON.stringify(B.hrefs)})`);
});

await scenario("[T53] lagging views: B sees only part of tab A's write of its refreshed pair (a torn read) when B gets a 401: B continues with A's session (review 4, E5)", async () => {
  for (const seen of [1, 2]) {
    const server = makeServer(), browser = makeBrowser({ lag: true, locks: true });
    const X = browser.signIn(server, 'user-x');
    await settle();
    const A = makeTab(browser, server, 'A'), B = makeTab(browser, server, 'B');
    server.expire(X.access_token);
    browser.hold();
    const ra = await A.request('/groups');
    const q = browser.queued();
    ok(ra.ok && q.slice(0, 2).join() === 'sol_token,sol_refresh', `A refreshed; its writes are held, tokens first (${q.join()})`);
    browser.deliverFirst(seen);                               // B has seen the first `seen` of A's writes
    const rb = await B.request('/groups');
    browser.release(); await sleep(40);
    ok(rb.ok && B.hrefs.length === 0 && B.reloads === 0, `B saw ${seen} of A's writes: it continues (${rb.ok ? 'ok' : rb.e}; redirects ${JSON.stringify(B.hrefs)})`);
    ok(userOf(openNow(browser, server)) === 'user-x', 'and a tab opened afterwards still runs as X');
  }
});

await scenario("[T54] the same-user rule never crosses users: a late pair of X written without a tag over Y's tagged sign-in (no record change) is not used", async () => {
  const server = makeServer(), browser = makeBrowser();
  browser.signIn(server, 'user-x');
  const A = makeTab(browser, server, 'A');
  await A.V('logout()'); await sleep(20);
  browser.signIn(server, 'user-y');                           // this version's landing page: tagged for Y, after the sign-out
  const late = server.issue('user-x');                        // a tab still on the earlier version stores its late pair of X
  browser.write(null, 'sol_token', late.access_token); browser.write(null, 'sol_refresh', late.refresh_token);
  const t = openNow(browser, server);
  ok(userOf(t) !== 'user-x', `a tab opened now does not run as X (it got ${t ? userOf(t) : 'no session'})`);
});

await scenario('[T55] an app.html from before core/session.js, served with this version\'s scripts: the page loads without errors, takes no session and goes to the sign-in page; sign-out still works (review 4, E3)', async () => {
  const server = makeServer(), browser = makeBrowser();
  const X = browser.signIn(server, 'user-x');
  let P = null, threw = null;
  try { P = makeTab(browser, server, 'P', { noSessionJs: true }); } catch (e) { threw = e; }
  ok(threw === null, `state.js, router.js and api.js load without core/session.js${threw ? ' (' + String(threw).split('\n')[0] + ')' : ''}`);
  if (!P) return;
  ok(P.V('token') === null && P.hrefs[0] === '/sol/', `no session is taken; the page goes to the sign-in page (saw ${JSON.stringify(P.hrefs)})`);
  await P.V('init()').catch(() => {});                      // main.js runs init() after the scripts
  await settle();
  ok(P.calls.length === 0, `init() sends nothing without a session (saw ${JSON.stringify(P.calls.map(c => c.url.slice(API.length)))})`);
  P.navigated = false;                                        // if the page were still showing, its Sign out must work
  let out = null; try { await P.V('logout()'); out = 'ok'; } catch (e) { out = String(e).split('\n')[0]; }
  ok(out === 'ok' && server.active('user-x').length === 0 && !browser.store.has('sol_refresh'), `logout() still works: tokens removed and the session revoked (${out}; active ${JSON.stringify(server.active('user-x'))})`);
  void X;
});

await scenario('[T56] a refresh the server received (and rotated) answers only after the bound: the request fails then, but the late answer is kept and the next request works (review 4, E4)', async () => {
  const server = makeServer(), browser = makeBrowser({ locks: true });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  const g = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');   // received and rotated at once; the answer waits
  const first = await within(B.request('/groups'), 23000);
  ok(first.settled && !first.v.ok && B.hrefs.length === 0 && B.reloads === 0, `the request fails at the bound and B stays (${first.settled ? first.v.e : 'still waiting'})`);
  g.release(); await sleep(60);
  const live = openNow(browser, server);
  ok(live && userOf(live) === 'user-x' && live !== X.access_token, 'the late answer was stored: a tab opened now uses the rotated pair');
  const again = await B.request('/groups'); await settle();
  ok(again.ok && sent(server, 'B', '/auth/refresh').length === 1, `the next request works without another refresh (${again.ok ? 'ok' : again.e}; refreshes ${sent(server, 'B', '/auth/refresh').length})`);
});

await scenario('[T57] while the late answer is still awaited, the tab\'s next 401 waits for it instead of sending the rotated token again', async () => {
  const server = makeServer(), browser = makeBrowser({ locks: true });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  const g = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
  const first = await within(B.request('/groups'), 23000);
  ok(first.settled && !first.v.ok, `the first request fails at the bound (${first.settled ? first.v.e : 'still waiting'})`);
  const second = B.request('/circles');
  await sleep(300);
  g.release();
  const r2 = await within(second, 23000); await settle();
  ok(r2.settled && r2.v.ok, `the second request succeeds with the late pair (${r2.settled ? (r2.v.ok ? 'ok' : r2.v.e) : 'still waiting'})`);
  ok(sent(server, 'B', '/auth/refresh').length === 1 && B.hrefs.length === 0, `one refresh in all, no sign-out (refreshes ${sent(server, 'B', '/auth/refresh').length}; redirects ${JSON.stringify(B.hrefs)})`);
});

await scenario('[T58] X signs out while that late answer is still awaited: when it comes, nothing is stored and its session is revoked', async () => {
  const server = makeServer(), browser = makeBrowser({ locks: true });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), A = makeTab(browser, server, 'A');
  server.expire(X.access_token);
  const g = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
  const first = await within(B.request('/groups'), 23000);
  ok(first.settled && !first.v.ok, 'the request failed at the bound');
  await A.V('logout()'); await sleep(20);
  g.release(); await sleep(80);
  ok(openNow(browser, server) === null, 'nothing counts afterwards');
  ok(server.active('user-x').length === 0, `the late session was revoked (active ${JSON.stringify(server.active('user-x'))})`);
  const i = B.events.findIndex(e => e.startsWith('revoke-answered:synthetic-refresh-user-x-2')), j = B.events.findIndex(e => e.startsWith('redirect') || e === 'reload');
  ok(i !== -1 && (j === -1 || i < j), `B revoked it before navigating (a navigation cancels B's pending answer) (events ${JSON.stringify(B.events)})`);
});

await scenario('[T59] B signs out itself while its own late refresh answer is still awaited: the answer is revoked before B leaves', async () => {
  const server = makeServer(), browser = makeBrowser({ locks: true });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  const g = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');   // received and rotated; the answer waits
  const first = await within(B.request('/groups'), 23000);
  ok(first.settled && !first.v.ok, 'the request failed at the bound');
  const out = B.V('logout()');
  setTimeout(() => g.release(), 400);                         // the answer comes within the sign-out's bound
  await out; await sleep(60);
  const i = B.events.findIndex(e => e.startsWith('revoke-answered:synthetic-refresh-user-x-2')), j = B.events.findIndex(e => e.startsWith('redirect'));
  ok(i !== -1 && j !== -1 && i < j, `the late session was revoked before B navigated (events ${JSON.stringify(B.events)})`);
  ok(server.active('user-x').length === 0 && openNow(browser, server) === null, `nothing is left active or counts (active ${JSON.stringify(server.active('user-x'))})`);
});

// ── Round 6: review 5 ────────────────────────────────────────────────────────
await scenario("[T60] a refresh the server rotated answers only after 45 s: the tab's later 401s fail without sending the rotated token again, and the answer still counts when it comes (RV5-CLOSURE-2, RV5-REGRESSION-3)", async () => {
  const server = makeServer(), browser = makeBrowser({ locks: true });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B');
  server.expire(X.access_token);
  const g = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
  const first = await within(B.request('/groups'), 23000);
  ok(first.settled && !first.v.ok, `the first request fails at the 20 s bound (${first.settled ? first.v.e : 'still waiting'})`);
  const second = await within(B.request('/circles'), 23000);   // its 401 comes while the answer is still awaited
  ok(second.settled && !second.v.ok, `a second request fails too, at once or within the bound (${second.settled ? second.v.e : 'still waiting'})`);
  await sleep(2000);
  const third = await within(B.request('/groups'), 23000);
  ok(sent(server, 'B', '/auth/refresh').length === 1, `the rotated token was never sent again (refreshes ${sent(server, 'B', '/auth/refresh').length})`);
  ok(B.hrefs.length === 0 && B.reloads === 0, `B neither leaves nor reloads meanwhile (events ${JSON.stringify(B.events)})`);
  g.release(); await sleep(80);
  const after = await within(B.request('/groups'), 5000);
  ok(after.settled && after.v.ok, `once the answer comes, the next request works (${after.settled ? (after.v.ok ? 'ok' : after.v.e) : 'no answer: B has left'})`);
  ok(userOf(openNow(browser, server)) === 'user-x' && server.active('user-x').length === 1, 'the rotated session is the stored one and the only one active');
  void third;
});

await scenario("[T61] another tab gets a 401 while B's refresh answer is still awaited: it does not send the rotated token, does not sign out, and continues once the answer comes (RV5-TRANSITION-8)", async () => {
  const server = makeServer(), browser = makeBrowser({ locks: true });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), C = makeTab(browser, server, 'C');
  server.expire(X.access_token);
  const g = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
  const first = await within(B.request('/groups'), 23000);
  ok(first.settled && !first.v.ok, 'B\'s request fails at the bound; its answer is still awaited');
  const rc = await within(C.request('/groups'), 23000);
  ok(rc.settled && !rc.v.ok && sent(server, 'C', '/auth/refresh').length === 0, `C's request fails without sending the rotated token (${rc.settled ? rc.v.e : 'still waiting'}; C refreshes ${sent(server, 'C', '/auth/refresh').length})`);
  ok(C.hrefs.length === 0 && C.reloads === 0, `C stays (events ${JSON.stringify(C.events)})`);
  g.release(); await sleep(80);
  const again = await within(C.request('/groups'), 5000);
  ok(again.settled && again.v.ok && sent(server, 'C', '/auth/refresh').length === 0, `C's next request works with the session B stored (${again.settled ? (again.v.ok ? 'ok' : again.v.e) : 'no answer: C has left'})`);
  ok(openNow(browser, server) !== null, 'and the session still counts');
});

await scenario("[T62] while B's own answer is still awaited, another tab stores a newer usable session: B's next 401 uses it at once (RV5-CLOSURE-4)", async () => {
  const server = makeServer(), browser = makeBrowser({ locks: true });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), C = makeTab(browser, server, 'C');
  server.expire(X.access_token);
  server.gate(e => e.tab === 'B' && e.path === '/auth/refresh', { before: true });   // B's request never gets through
  const first = await within(B.request('/groups'), 23000);
  ok(first.settled && !first.v.ok, 'B\'s request fails at the bound');
  const newer = server.issue('user-x'); server.sessions.get(X.refresh_token).active = false;
  browser.storePair(C, newer);                                // another tab refreshed meanwhile
  await settle();
  const t0 = Date.now();
  const r = await within(B.request('/groups'), 23000);
  ok(r.settled && r.v.ok && Date.now() - t0 < 2000, `B continues with the newer session without waiting (${r.settled ? (r.v.ok ? 'ok' : r.v.e) : 'still waiting'} after ${Date.now() - t0} ms)`);
});

await scenario("[T63] lagging views: after a sign-in elsewhere, the sign-out record and the announcement reach B before the new pair: B reloads into the new session instead of going to the sign-in page (RV3-2, RV5-CLOSURE-1)", async () => {
  for (const user of ['user-y', 'user-x']) {
    const server = makeServer(), browser = makeBrowser({ lag: true });
    browser.signIn(server, 'user-x');
    await settle();
    const B = makeTab(browser, server, 'B');
    browser.hold();
    browser.signIn(server, user);                             // the landing page replaces the session
    const q = browser.queued();
    const firstPair = q.indexOf('sol_token');
    browser.deliverFirst(firstPair);                          // B sees the record (and announcement) first ...
    await sleep(0);
    setTimeout(() => browser.release(), 120);                 // ... and the new pair 120 ms later
    await sleep(REVOKE_BOUND_MS + 900);
    ok(B.reloads === 1 && B.hrefs.length === 0, `${user}: B reloads once and is not sent to the sign-in page (events ${JSON.stringify(B.events)}; queued first ${JSON.stringify(q.slice(0, firstPair))})`);
  }
});

await scenario('[T64] two tabs list their own dead refresh tokens at the same moment (lagging views): both stay listed (RV5-TESTS-1)', async () => {
  const server = makeServer(), browser = makeBrowser({ lag: true });
  browser.signIn(server, 'user-x');
  await settle();
  const B = makeTab(browser, server, 'B'), D = makeTab(browser, server, 'D');
  const rb = server.issue('user-x').refresh_token, rd = server.issue('user-x').refresh_token;
  browser.hold();                                             // neither sees the other's write before its own
  B.V(`_solMarkDead(${JSON.stringify(rb)})`);
  D.V(`_solMarkDead(${JSON.stringify(rd)})`);
  browser.release(); await sleep(40);
  const F = makeTab(browser, server, 'F');
  ok(F.V(`_solIsDead(${JSON.stringify(rb)})`) === true && F.V(`_solIsDead(${JSON.stringify(rd)})`) === true, 'both refresh tokens are listed dead');
});

await scenario("[T65] a page restored from the back/forward cache after a sign-out ends the pair it stored itself (RV5-CLOSURE-7, M13)", async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const P = makeTab(browser, server, 'P'), A = makeTab(browser, server, 'A');
  server.expire(X.access_token);
  const r = await P.request('/groups'); await settle();      // P refreshed: its own pair is stored
  const mine = P.V('_myRefresh');
  ok(r.ok && mine, 'P stored its own pair');
  P.navigated = true;                                         // P is in the back/forward cache (it misses the sign-out)
  await A.V('logout()'); await sleep(20);
  P.dispatch('pageshow', { persisted: true }); await sleep(40);
  ok(!server.sessions.get(mine).active, `restored, P revokes its own pair (active ${JSON.stringify(server.active('user-x'))})`);
  ok(P.reloads === 1, 'and reloads');
});

await scenario('[T66] another tab stored a newer pair while B\'s refresh was in flight: B uses the newer one and revokes the session its own refresh created (RV5-TESTS-4, M21)', async () => {
  const server = makeServer(), browser = makeBrowser({ storageEvents: false });
  const X = browser.signIn(server, 'user-x');
  const B = makeTab(browser, server, 'B'), C = makeTab(browser, server, 'C');
  server.expire(X.access_token);
  const gB = server.gate(e => e.tab === 'B' && e.path === '/auth/refresh');
  const pb = B.request('/groups');
  await settle();
  const newer = server.issue('user-x');
  browser.storePair(C, newer);
  gB.release();
  const r = await pb; await sleep(40);
  ok(r.ok, `B's request succeeds (${r.ok ? 'ok' : r.e})`);
  ok(JSON.stringify(server.active('user-x')) === JSON.stringify([newer.refresh_token]), `only the stored session is active; B's redundant one was revoked (active ${JSON.stringify(server.active('user-x'))})`);
});

await scenario('[T67] storage from before this version: another user signs in on the old landing page while B is still loading: B reloads (RV5-TESTS-4, M12)', async () => {
  const server = makeServer(), browser = makeBrowser();
  browser.rawSignIn(server, 'user-x');                        // no tag anywhere
  const B = makeTab(browser, server, 'B', { between: () => { browser.rawSignIn(server, 'user-y'); } });
  await sleep(REVOKE_BOUND_MS + 300);
  ok(B.reloads === 1 && B.hrefs.length === 0, `B reloads (events ${JSON.stringify(B.events)})`);
  ok(!server.log.some(l => l.tab === 'B' && l.as === 'user-y'), 'and sends nothing as Y');
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
