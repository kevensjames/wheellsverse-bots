// Member account helpers (pure Node, zero dependencies, no network).
//   node tests/sol-frontend/account.test.mjs
//
// Loads the REAL frontend/sol/app/core/account.js (window.SolAccount) in a vm sandbox and
// checks the pure logic the new member pages share. Every token, address and code below is
// synthetic. Covers:
//   1. readTokenOnce(): an email link's ?token= is read once, removed from the address bar
//      with history.replaceState (other query parameters and the hash are kept), and never
//      written to storage or the console
//   2. notAvailable() / rateLimited(): 404 and 405 mean "not available yet" (a route that
//      exists only in a draft backend PR); 429 is a rate limit; nothing else is either
//   3. passwordProblem(): the backend's password rule (8 to 128 characters, counted the way
//      the backend counts them: code points, not UTF-16 units) and the confirm field
//   4. the outcome of the public auth calls (forgot, reset, verify) from the HTTP status
//   5. consentVersions() / signupPayload(): the sign-up body is exactly the deployed shape
//      with the switch off, and exactly the PR #34 shape with it on
//   6. guideSeen() / markGuideSeen(): the first-run guide's "seen" mark is kept per member
//      id and never throws when storage is blocked (then the guide may show again)
//   7. settings bodies: notificationsPatch() keeps the other notification keys (the backend
//      replaces the whole nested object), closePayload() is exactly the PR #33 body,
//      closeRefusals() shows the backend's reasons and never an id
//   8. callPublic(): never throws on an HTTP error; a network error is status 0
// What it does NOT prove: anything about the backend, or the pages that use these helpers
// (the browser journeys in journeys.mjs cover those).
import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const FILE = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'frontend', 'sol', 'app', 'core', 'account.js');

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('  ✓', m); } else { fail++; console.log('  ✗ FAIL:', m); } };
const scenario = async (name, fn) => { console.log('\n' + name); try { await fn(); } catch (e) { fail++; console.log('  ✗ FAIL: threw', String(e && e.stack || e).split('\n')[0]); } };

if (!existsSync(FILE)) {
  console.log('  ✗ FAIL: frontend/sol/app/core/account.js does not exist (window.SolAccount is missing)');
  console.log(`\nmember account helpers: 0 passed, 1 failed`);
  process.exit(1);
}
const SRC = readFileSync(FILE, 'utf8');

// A sandbox with a recording console and storage, so a test can prove a token was never
// written anywhere.
function load(extra = {}) {
  const logged = [];
  const rec = (...a) => logged.push(a.map(String).join(' '));
  const sandbox = {
    console: { log: rec, info: rec, warn: rec, error: rec, debug: rec },
    URLSearchParams, Promise, JSON, Date, Math, String, Number, Array, Object, Error, RegExp,
    ...extra,
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);
  return { S: sandbox.SolAccount, logged, sandbox };
}
function fakeWindow(href) {
  const u = new URL(href);
  const calls = [];
  const store = new Map();
  const storage = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: k => store.delete(k) };
  const win = {
    location: { pathname: u.pathname, search: u.search, hash: u.hash, href: u.href },
    history: {
      state: { kept: true },
      replaceState(state, title, url) {
        calls.push({ state, title, url: String(url) });
        const n = new URL(String(url), u.origin);
        win.location.pathname = n.pathname; win.location.search = n.search; win.location.hash = n.hash; win.location.href = n.href;
      },
    },
    localStorage: storage, sessionStorage: storage,
  };
  return { win, calls, store };
}

const TOKEN = 'synthetic-Tok3n_value-0123456789abcdefABCDEF';

await scenario('[A1] readTokenOnce reads ?token= once and removes it from the address bar', async () => {
  const { S, logged } = load();
  ok(S && typeof S.readTokenOnce === 'function', 'SolAccount.readTokenOnce exists');
  const { win, calls, store } = fakeWindow(`https://app.example.invalid/sol/reset-password?token=${TOKEN}`);
  const t = S.readTokenOnce(win);
  ok(t === TOKEN, 'returns the token from the query string');
  ok(calls.length === 1, `history.replaceState called once (saw ${calls.length})`);
  ok(calls[0] && calls[0].url === '/sol/reset-password', `the new address has no query (saw ${calls[0] && calls[0].url})`);
  ok(calls[0] && calls[0].state && calls[0].state.kept === true, 'the history state is kept');
  ok(!win.location.href.includes(TOKEN), 'the address bar no longer holds the token');
  ok(S.readTokenOnce(win) === null, 'a second read finds nothing (read once)');
  ok(store.size === 0, 'nothing written to storage');
  ok(!logged.some(l => l.includes(TOKEN)), 'the token never reaches the console');
});

await scenario('[A2] readTokenOnce keeps the other query parameters and the hash', async () => {
  const { S } = load();
  const { win, calls } = fakeWindow(`https://app.example.invalid/sol/verify?utm=mail&token=${TOKEN}&x=1#top`);
  ok(S.readTokenOnce(win) === TOKEN, 'returns the token');
  ok(calls[0] && calls[0].url === '/sol/verify?utm=mail&x=1#top', `other parameters and the hash kept (saw ${calls[0] && calls[0].url})`);
});

await scenario('[A3] readTokenOnce without a token, or with an empty one', async () => {
  const { S } = load();
  const a = fakeWindow('https://app.example.invalid/sol/verify');
  ok(S.readTokenOnce(a.win) === null && a.calls.length === 0, 'no token: null, the address is left alone');
  const b = fakeWindow('https://app.example.invalid/sol/verify?token=&a=1');
  ok(S.readTokenOnce(b.win) === null, 'an empty token reads as no token');
  ok(b.calls.length === 1 && b.calls[0].url === '/sol/verify?a=1', `the empty parameter is still removed (saw ${b.calls[0] && b.calls[0].url})`);
  const c = fakeWindow('https://app.example.invalid/sol/verify?token=' + 'x'.repeat(3000));
  ok(S.readTokenOnce(c.win) === null && c.calls.length === 1 && !c.win.location.href.includes('xxxx'), 'an oversized value is removed and not used');
});

await scenario('[A4] readTokenOnce still returns the token when replaceState throws', async () => {
  const { S } = load();
  const { win } = fakeWindow(`https://app.example.invalid/sol/verify?token=${TOKEN}`);
  win.history.replaceState = () => { throw new Error('SecurityError'); };
  let t, threw = false;
  try { t = S.readTokenOnce(win); } catch { threw = true; }
  ok(!threw && t === TOKEN, 'no throw; the token is still returned');
});

await scenario('[A5] notAvailable(): 404 and 405 only; rateLimited(): 429 only', async () => {
  const { S } = load();
  const e = s => Object.assign(new Error('x'), { status: s });
  ok(S.notAvailable(e(404)) === true && S.notAvailable(e(405)) === true, '404 and 405 are "not available yet"');
  for (const s of [200, 400, 401, 403, 409, 422, 429, 500, 503]) ok(S.notAvailable(e(s)) === false, `${s} is not "not available yet"`);
  ok(S.notAvailable(new TypeError('Failed to fetch')) === false && S.notAvailable(null) === false && S.notAvailable(undefined) === false, 'a network error, null or undefined is not "not available yet"');
  ok(S.rateLimited(e(429)) === true && S.rateLimited(e(404)) === false && S.rateLimited(null) === false, '429 is a rate limit; nothing else');
});

await scenario('[A6] passwordProblem(): 8 to 128 characters, counted as code points; confirm must match', async () => {
  const { S } = load();
  ok(S.passwordProblem('abcdefgh', 'abcdefgh') === '', '8 characters that match: no problem');
  ok(/8/.test(S.passwordProblem('abcdefg', 'abcdefg')), 'fewer than 8: a message that names 8');
  ok(S.passwordProblem('a'.repeat(128), 'a'.repeat(128)) === '', '128 characters: no problem');
  ok(/128/.test(S.passwordProblem('a'.repeat(129), 'a'.repeat(129))), 'more than 128: a message that names 128');
  // Four emoji are 8 UTF-16 units but 4 code points: the backend (pydantic) counts 4 and refuses.
  const emoji4 = '\u{1F511}\u{1F511}\u{1F511}\u{1F511}';
  ok(emoji4.length === 8 && S.passwordProblem(emoji4, emoji4) !== '', 'four emoji (8 UTF-16 units, 4 code points) are too short');
  const emoji8 = emoji4 + emoji4;
  ok(S.passwordProblem(emoji8, emoji8) === '', 'eight emoji are long enough');
  const p = S.passwordProblem('abcdefgh', 'abcdefgX');
  ok(p !== '' && !/abcdefg/.test(p), 'a confirm that does not match is a problem; the message never repeats the password');
  ok(S.passwordProblem('', '') !== '', 'an empty password is a problem');
});

await scenario('[A7] public call outcomes: forgot, reset, verify', async () => {
  const { S } = load();
  // Forgot password: the same neutral answer whatever the server says, except a rate limit;
  // no answer at all (status 0) is a connection problem, not "we sent a link".
  for (const s of [200, 400, 404, 422, 500, 503]) ok(S.forgotOutcome(s) === 'sent', `forgot ${s} -> sent (neutral)`);
  ok(S.forgotOutcome(429) === 'limited', 'forgot 429 -> limited');
  ok(S.forgotOutcome(0) === 'offline', 'forgot no answer -> offline');
  ok(S.resetOutcome(200) === 'done', 'reset 200 -> done');
  ok(S.resetOutcome(400) === 'invalid', 'reset 400 (invalid or expired token) -> invalid');
  ok(S.resetOutcome(429) === 'limited' && S.resetOutcome(0) === 'offline', 'reset 429 -> limited, no answer -> offline');
  ok(S.resetOutcome(422) === 'retry' && S.resetOutcome(500) === 'retry', 'reset 422 or 5xx -> retry');
  ok(S.verifyOutcome(200) === 'done', 'verify 200 -> done');
  ok(S.verifyOutcome(400) === 'invalid' && S.verifyOutcome(422) === 'invalid', 'verify 400 or 422 -> invalid');
  ok(S.verifyOutcome(404) === 'unavailable' && S.verifyOutcome(405) === 'unavailable', 'verify 404 or 405 -> unavailable');
  ok(S.verifyOutcome(429) === 'limited' && S.verifyOutcome(0) === 'offline' && S.verifyOutcome(502) === 'retry', 'verify 429 -> limited, no answer -> offline, 5xx -> retry');
});

await scenario('[A8] sign-up body: exactly the deployed shape when consent is off, exactly the PR #34 shape when on', async () => {
  const { S } = load();
  const fields = { email: 'member@example.invalid', password: 'synthetic-pass-1', fullName: 'Test Member' };
  const off = S.signupPayload(fields, null);
  ok(JSON.stringify(Object.keys(off).sort()) === JSON.stringify(['email', 'full_name', 'password']), `consent off: exactly email, password, full_name (saw ${Object.keys(off)})`);
  ok(off.email === fields.email && off.password === fields.password && off.full_name === fields.fullName, 'consent off: values passed through');
  // GET /legal/documents (PR #34 api/legal.py:13-16; legal/__init__.py:94-102): consent_kind maps a document to its consent.
  const docs = [
    { kind: 'terms', version: '2026-11-22-draft-1', consent_kind: 'terms', title: 'Terms', sha256: 'a', text: '...' },
    { kind: 'privacy', version: '2026-11-22-draft-2', consent_kind: 'privacy', title: 'Privacy', sha256: 'b', text: '...' },
    { kind: 'esign_disclosure', version: '2026-11-22-draft-1', consent_kind: 'esign', title: 'E-sign', sha256: 'c', text: '...' },
    { kind: 'ach_debit_authorization', version: 'v', consent_kind: 'ach_debit_authorization', title: 'ACH', sha256: 'd', text: '...' },
  ];
  const v = S.consentVersions(docs);
  ok(v && v.terms === '2026-11-22-draft-1' && v.privacy === '2026-11-22-draft-2', 'consentVersions reads the terms and privacy versions by consent_kind');
  const on = S.signupPayload(fields, v);
  ok(JSON.stringify(Object.keys(on).sort()) === JSON.stringify(['accepted_privacy_version', 'accepted_terms_version', 'email', 'esign_consent', 'full_name', 'password']), `consent on: the PR #34 fields (saw ${Object.keys(on)})`);
  ok(on.accepted_terms_version === v.terms && on.accepted_privacy_version === v.privacy && on.esign_consent === true, 'consent on: current versions and esign_consent true');
  ok(S.consentVersions([docs[0]]) === null && S.consentVersions(null) === null && S.consentVersions({}) === null, 'a list without terms and privacy versions gives null');
  ok(S.consentVersions([{ consent_kind: 'terms', version: '' }, { consent_kind: 'privacy', version: 'x' }]) === null, 'an empty version gives null');
});

await scenario('[A9] first-run guide "seen" mark: per member, and storage that throws never breaks the page', async () => {
  const { S } = load();
  const store = new Map();
  const storage = { getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };
  ok(S.guideSeen(storage, 'member-a') === false, 'not seen yet');
  ok(S.markGuideSeen(storage, 'member-a') === true, 'markGuideSeen reports it was stored');
  ok(S.guideSeen(storage, 'member-a') === true, 'seen after the mark');
  ok(S.guideSeen(storage, 'member-b') === false, 'another member on the same browser has not seen it');
  ok([...store.keys()].every(k => !/@/.test(k)), 'the key holds no email address');
  const blocked = { getItem() { throw new Error('SecurityError'); }, setItem() { throw new Error('QuotaExceededError'); } };
  let threw = false, seen, marked;
  try { seen = S.guideSeen(blocked, 'member-a'); marked = S.markGuideSeen(blocked, 'member-a'); } catch { threw = true; }
  ok(!threw, 'blocked storage never throws');
  ok(seen === false && marked === false, 'blocked storage: not seen (the guide may show again), and the mark reports false');
  ok(S.guideSeen(null, 'member-a') === false && S.markGuideSeen(null, 'member-a') === false, 'no storage at all: not seen, mark false');
  ok(S.guideSeen(storage, '') === true && S.guideSeen(storage, null) === true, 'no member id: treated as seen (never shown to an unknown member)');
  const getter = { get localStorage() { throw new Error('SecurityError'); } };
  let st, threw2 = false;
  try { st = S.storageOf(getter); } catch { threw2 = true; }
  ok(!threw2 && st === null, 'storageOf(): a window whose localStorage getter throws gives null');
});

await scenario('[A10] settings bodies: notifications keep the other keys; close is exactly the PR #33 body; refusals show reasons, never ids', async () => {
  const { S } = load();
  const p = S.notificationsPatch({ notifications: { email: true, sms: false }, dark_mode: true }, false);
  ok(JSON.stringify(p) === JSON.stringify({ preferences: { notifications: { email: false, sms: false } } }), `only preferences.notifications, with sms kept (saw ${JSON.stringify(p)})`);
  ok(JSON.stringify(S.notificationsPatch({}, true)) === JSON.stringify({ preferences: { notifications: { email: true } } }), 'no stored notifications: just email');
  ok(JSON.stringify(S.notificationsPatch({ notifications: 'bad' }, true)) === JSON.stringify({ preferences: { notifications: { email: true } } }), 'a stored non-object is replaced');
  ok(S.emailNotificationsOn({}) === true && S.emailNotificationsOn({ notifications: { email: false } }) === false && S.emailNotificationsOn(null) === true, 'email updates read as on unless stored false');
  const c1 = S.closePayload('synthetic-pw', '', false);
  ok(JSON.stringify(c1) === JSON.stringify({ password: 'synthetic-pw', totp_code: null, confirm: 'DELETE' }), `two-factor off: totp_code null (saw ${JSON.stringify(c1)})`);
  const c2 = S.closePayload('synthetic-pw', ' 123456 ', true);
  ok(JSON.stringify(c2) === JSON.stringify({ password: 'synthetic-pw', totp_code: '123456', confirm: 'DELETE' }), `two-factor on: the trimmed code (saw ${JSON.stringify(c2)})`);
  // 409 detail (PR #33 services/account_lifecycle.py:281-368, 583-594).
  const detail = { error: 'account_close_refused', message: 'Your account cannot be closed yet.', reasons: [
    { code: 'circle_not_finished', message: 'You still belong to a circle that has not finished.', count: 1, group_ids: ['bbbb2222-2222-4222-8222-bbbbbbbbbbbb'] },
    { code: 'checkout_in_progress', message: 'A plan checkout you started in the last 24 hours could still be paid.', count: 1, plans: ['premium'] },
    { code: 'admin_account' },
  ] };
  const r = S.closeRefusals(detail);
  ok(r.length === 3 && r[0] === detail.reasons[0].message && r[1] === detail.reasons[1].message, 'the backend\'s own messages, in order');
  ok(typeof r[2] === 'string' && /admin/i.test(r[2]), 'a reason without a message gets a plain one from its code');
  ok(!r.join(' ').includes('bbbb2222'), 'no id in the refusals');
  ok(Array.isArray(S.closeRefusals(null)) && S.closeRefusals(null).length === 0 && S.closeRefusals('x').length === 0, 'no reasons: empty list');
  ok(S.groupSecret('JBSWY3DPEHPK3PXP') === 'JBSW Y3DP EHPK 3PXP', 'groupSecret() splits a secret into groups of 4 for reading');
  ok(/^mysol-data-\d{4}-\d{2}-\d{2}\.json$/.test(S.exportFileName(new Date('2026-11-23T10:00:00Z'))), 'exportFileName() is mysol-data-YYYY-MM-DD.json');
});

await scenario('[A11] callPublic(): HTTP errors are returned, a network error is status 0, the body is JSON', async () => {
  const seen = [];
  const { S } = load({
    fetch: async (url, opts) => {
      seen.push({ url, opts });
      if (url.endsWith('/net')) throw new TypeError('Failed to fetch');
      if (url.endsWith('/bad')) return { ok: false, status: 429, json: async () => ({ error: 'Rate limit exceeded: 5 per 15 minute' }) };
      if (url.endsWith('/nojson')) return { ok: true, status: 200, json: async () => { throw new SyntaxError('x'); } };
      return { ok: true, status: 200, json: async () => ({ detail: 'ok' }) };
    },
  });
  const a = await S.callPublic('https://api.example.invalid', '/auth/forgot-password', { method: 'POST', body: { email: 'member@example.invalid' } });
  ok(a.ok === true && a.status === 200 && a.data && a.data.detail === 'ok', 'a 2xx answer');
  ok(seen[0].opts.method === 'POST' && seen[0].opts.body === JSON.stringify({ email: 'member@example.invalid' }) && seen[0].opts.headers['Content-Type'] === 'application/json', 'POST with a JSON body');
  const b = await S.callPublic('https://api.example.invalid', '/bad', { method: 'POST', body: {} });
  ok(b.ok === false && b.status === 429, 'an HTTP error is returned, not thrown');
  const c = await S.callPublic('https://api.example.invalid', '/net', { method: 'POST' });
  ok(c.ok === false && c.status === 0 && c.data === null, 'a network error is status 0');
  const d = await S.callPublic('https://api.example.invalid', '/nojson', { method: 'POST' });
  ok(d.ok === true && d.data === null, 'a body that is not JSON reads as null');
  ok(seen[2].opts.body === undefined, 'no body when none is given');
});

console.log(`\nmember account helpers: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
