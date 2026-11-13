// Landing page sign-in regression test (pure Node, zero dependencies, no network).
//   node tests/sol-frontend/login.test.mjs
//
// Loads the REAL finishAuth() of frontend/sol/index.html (the function that stores the
// tokens after a successful sign-in) in a vm sandbox with an in-memory localStorage and a
// recording fetch (synthetic tokens; the API constant is rewritten to a reserved .invalid
// host that is never contacted). Checks:
//   1. a plain sign-in stores both tokens and enters the app
//   2. a sign-in that replaces a session already stored in this browser records a sign-out
//      for the open app tabs (sol_signout, written BEFORE the new tokens) and asks the
//      backend to revoke the replaced session: one POST /auth/logout, exactly
//      {refresh_token}, keepalive (the page navigates at once)
//   3. no revoke when the stored refresh token is the new one; a failing revoke never
//      blocks the sign-in; an answer without a refresh token does not keep the old one
//   4. a malformed answer changes nothing
//   5. the sign-in ends with the session's commit tag (sol_session, core/session.js), after
//      both tokens, so the app accepts the new pair; replacing a session is also announced
//      to the open app tabs on the 'sol-auth' BroadcastChannel
// What it does NOT prove: server-side revocation, or anything about the deployed page.
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const SOL = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'frontend', 'sol');
const HTML = readFileSync(join(SOL, 'index.html'), 'utf8');
// core/session.js (index.html loads it before its own script) when the tree has it.
const SESSION_FILE = join(SOL, 'app', 'core', 'session.js');
const SESSION_JS = existsSync(SESSION_FILE) ? readFileSync(SESSION_FILE, 'utf8') : null;
const start = HTML.indexOf('function finishAuth(data)');
if (start < 0) throw new Error('finishAuth() not found in index.html');
const end = HTML.indexOf('\n}\n', start);
const FINISH = HTML.slice(start, end + 2);
const API = 'https://sol-api.invalid';

function makePage(stored = {}, fetchImpl = null) {
  const store = new Map(Object.entries(stored));
  const writes = [];
  const calls = [];
  const hrefs = [];
  const posted = [];
  class BroadcastChannel { constructor(name) { this.name = name; } postMessage(data) { posted.push({ name: this.name, data }); } close() {} }
  const location = {};
  Object.defineProperty(location, 'href', { get: () => hrefs[hrefs.length - 1] || '/sol/', set: v => hrefs.push(v) });
  const sandbox = {
    console, Promise, JSON, Date, Math, API, BroadcastChannel, setTimeout, clearTimeout,
    window: { location }, location,
    localStorage: {
      getItem: k => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => { writes.push(['set', k]); store.set(k, String(v)); },
      removeItem: k => { writes.push(['remove', k]); store.delete(k); },
    },
    fetch: (url, opts = {}) => {
      calls.push({ url: String(url), method: (opts.method || 'GET').toUpperCase(), body: opts.body, keepalive: !!opts.keepalive, headers: opts.headers || {} });
      return fetchImpl ? fetchImpl() : Promise.resolve({ ok: true, status: 204, json: async () => ({}) });
    },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  if (SESSION_JS) vm.runInContext(SESSION_JS, sandbox);
  vm.runInContext(FINISH, sandbox);
  return { store, writes, calls, hrefs, posted, V: e => vm.runInContext(e, sandbox) };
}
const revokes = p => p.calls.filter(c => c.method === 'POST' && c.url === API + '/auth/logout');

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('  ✓', m); } else { fail++; console.log('  ✗ FAIL:', m); } };
const scenario = (name, fn) => { console.log('\n' + name); try { fn(); } catch (e) { fail++; console.log('  ✗ FAIL: threw', String(e && e.stack || e).split('\n')[0]); } };
const answer = (a, r) => JSON.stringify({ access_token: a, refresh_token: r, token_type: 'bearer' });

scenario('[L1] a plain sign-in stores both tokens and enters the app', () => {
  const p = makePage();
  p.V(`finishAuth(${answer('synthetic-access-y', 'synthetic-refresh-y')})`);
  ok(p.store.get('sol_token') === 'synthetic-access-y' && p.store.get('sol_refresh') === 'synthetic-refresh-y', 'both tokens stored');
  ok(revokes(p).length === 0 && !p.store.has('sol_signout'), 'no revoke and no sign-out record (nothing was replaced)');
  ok(p.hrefs.length === 1 && p.hrefs[0] === '/sol/app', 'enters the app');
});

scenario('[L2] a sign-in that replaces a stored session records a sign-out first and revokes the replaced session', () => {
  const p = makePage({ sol_token: 'synthetic-access-x', sol_refresh: 'synthetic-refresh-x' });
  p.V(`finishAuth(${answer('synthetic-access-y', 'synthetic-refresh-y')})`);
  const i = p.writes.findIndex(w => w[0] === 'set' && w[1] === 'sol_signout'), j = p.writes.findIndex(w => w[0] === 'set' && w[1] === 'sol_token');
  ok(i !== -1 && i < j, `the sign-out record is written before the new tokens (writes ${JSON.stringify(p.writes)})`);
  const rv = revokes(p);
  ok(rv.length === 1 && JSON.stringify(Object.keys(JSON.parse(rv[0].body))) === '["refresh_token"]' && JSON.parse(rv[0].body).refresh_token === 'synthetic-refresh-x', 'one POST /auth/logout with exactly {refresh_token: <replaced token>}');
  ok(rv[0] && rv[0].keepalive === true, 'sent with keepalive (the page navigates at once)');
  ok(p.store.get('sol_token') === 'synthetic-access-y' && p.store.get('sol_refresh') === 'synthetic-refresh-y', 'the new session is stored');
});

scenario('[L3] the stored refresh token is the new one: no revoke', () => {
  const p = makePage({ sol_token: 'synthetic-access-y', sol_refresh: 'synthetic-refresh-y' });
  p.V(`finishAuth(${answer('synthetic-access-y2', 'synthetic-refresh-y')})`);
  ok(revokes(p).length === 0, 'no revoke');
});

scenario('[L4] a failing revoke never blocks the sign-in', () => {
  for (const [label, impl] of [['rejects', () => Promise.reject(new TypeError('Failed to fetch'))], ['throws', () => { throw new TypeError('blocked'); }]]) {
    const p = makePage({ sol_refresh: 'synthetic-refresh-x' }, impl);
    p.V(`finishAuth(${answer('synthetic-access-y', 'synthetic-refresh-y')})`);
    ok(p.store.get('sol_token') === 'synthetic-access-y' && p.hrefs[0] === '/sol/app', `revoke ${label}: still signed in and in the app`);
  }
});

scenario('[L5] an answer without a refresh token does not keep the previous one', () => {
  const p = makePage({ sol_token: 'synthetic-access-x', sol_refresh: 'synthetic-refresh-x' });
  p.V(`finishAuth(${JSON.stringify({ access_token: 'synthetic-access-y', token_type: 'bearer' })})`);
  ok(!p.store.has('sol_refresh'), `the previous refresh token is gone (saw ${p.store.get('sol_refresh')})`);
  ok(revokes(p).length === 1, 'and it was revoked');
});

scenario('[L6] a malformed answer changes nothing', () => {
  const p = makePage({ sol_token: 'synthetic-access-x', sol_refresh: 'synthetic-refresh-x' });
  let threw = false; try { p.V('finishAuth({})'); } catch { threw = true; }
  ok(threw && p.store.get('sol_refresh') === 'synthetic-refresh-x' && revokes(p).length === 0 && !p.store.has('sol_signout'), 'it throws and nothing is stored, recorded or revoked');
});

scenario('[L7] the sign-in ends with the commit tag, after both tokens, and the app accepts the new pair (RV3-N1, RV3C-1)', () => {
  for (const stored of [{}, { sol_token: 'synthetic-access-x', sol_refresh: 'synthetic-refresh-x', sol_signout: 'earlier' }]) {
    const label = stored.sol_token ? 'replacing a session' : 'nothing stored before';
    const p = makePage(stored);
    p.V(`finishAuth(${answer('synthetic-access-y', 'synthetic-refresh-y')})`);
    const last = p.writes[p.writes.length - 1];
    const t = p.writes.findIndex(w => w[1] === 'sol_token'), r = p.writes.findIndex(w => w[1] === 'sol_refresh');
    ok(last && last[0] === 'set' && last[1] === 'sol_session' && t !== -1 && r !== -1, `${label}: the last write is the commit tag, after both tokens (writes ${JSON.stringify(p.writes)})`);
    const accepted = p.V("typeof _solStoredSession === 'function' ? _solStoredSession() : null");
    ok(accepted && accepted.token === 'synthetic-access-y' && accepted.refresh === 'synthetic-refresh-y', `${label}: the member app accepts the new pair`);
  }
});

scenario('[L8] replacing a session is also announced on the sol-auth BroadcastChannel (the record may not be writable)', () => {
  const p = makePage({ sol_token: 'synthetic-access-x', sol_refresh: 'synthetic-refresh-x' });
  p.V(`finishAuth(${answer('synthetic-access-y', 'synthetic-refresh-y')})`);
  ok(p.posted.length === 1 && p.posted[0].name === 'sol-auth' && p.posted[0].data && p.posted[0].data.type === 'signed-out', `one 'signed-out' message (saw ${JSON.stringify(p.posted)})`);
  const q = makePage();
  q.V(`finishAuth(${answer('synthetic-access-y', 'synthetic-refresh-y')})`);
  ok(q.posted.length === 0, 'none when nothing was replaced');
});

console.log(`\nlanding sign-in: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
