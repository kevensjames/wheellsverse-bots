// Verify-email page request (pure Node, zero dependencies, no network).
//   node tests/sol-frontend/verify.test.mjs
//
// Loads the REAL core/account.js and the REAL inline script of frontend/sol/verify.html in a
// vm sandbox with a stub DOM, a recording console, storage and cookie, and a scripted fetch
// (the API constant is rewritten to a reserved .invalid host that is never contacted). Every
// token below is synthetic. Checks:
//   1. nothing is sent when the page loads; the token leaves the address bar at once
//   2. "Verify my email" sends one POST /auth/verify-email whose URL holds no token and no
//      query string at all (proxies and access logs record URLs): the token travels only in
//      the JSON body, which is exactly {token}
//   3. a double click sends once; the button is busy while the request runs; after a 200 the
//      page says so, focus goes to the heading, and the token is dropped (nothing more is sent)
//   4. "Try again" after a failed answer sends the same body form again, never a URL with the token
//   5. 404 and 405 read "not available yet", in the body form too
//   6. the token never reaches the console, storage or a cookie
//   7. without a token, nothing is sent
//   8. deploy order: against a backend that still reads ?token= (the deployed base answers the
//      body form 422 at loc ["query","token"]) the page reads "not available yet", keeps the
//      token for "Try again" and never resends it in a URL
// What it does NOT prove: anything about the backend, or real-browser behaviour (journeys.mjs
// covers the page in Chromium, including the Referer of every request it makes).
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const SOL = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'frontend', 'sol');
const ACCOUNT = readFileSync(join(SOL, 'app', 'core', 'account.js'), 'utf8');
const HTML = readFileSync(join(SOL, 'verify.html'), 'utf8');
const INLINE = [...HTML.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).find(s => s.includes('function runVerify'));
if (!INLINE) throw new Error('verify.html: the inline script with runVerify() was not found');
// The negative checks (no token in the URL) would pass vacuously if the request went to another
// host or path, so the API rewrite must apply.
if (!/const API = '[^']*';/.test(INLINE)) throw new Error('verify.html: the API constant was not found: the rewrite would not apply');
const API = 'https://sol-api.invalid';
const SRC = INLINE.replace(/const API = '[^']*';/, `const API = '${API}';`);

const TOKEN = 'synthetic-verify-Tok3n_0123456789abcdefABCDEF';

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('  ✓', m); } else { fail++; console.log('  ✗ FAIL:', m); } };
const scenario = async (name, fn) => { console.log('\n' + name); try { await fn(); } catch (e) { fail++; console.log('  ✗ FAIL: threw', String(e && e.stack || e).split('\n')[0]); } };
const tick = () => new Promise(r => setTimeout(r, 0));
const deferred = () => { let resolve; const p = new Promise(r => { resolve = r; }); return { p, resolve }; };
const res = (status, body) => ({ ok: status >= 200 && status < 300, status, json: async () => body ?? {} });

// One verify page: the address it was opened at, and a function that answers each fetch
// (it may return a promise, to hold the answer).
function openPage(href, answer) {
  const u = new URL(href);
  const logged = [], stored = [], cookies = [], requests = [], focused = [];
  const rec = (...a) => logged.push(a.map(String).join(' '));
  const elements = new Map();
  const doc = { activeElement: null };
  const element = id => {
    if (!elements.has(id)) {
      const attrs = new Map();
      const el = {
        id, hidden: false, textContent: '',
        setAttribute(k, v) { attrs.set(k, String(v)); }, removeAttribute(k) { attrs.delete(k); },
        getAttribute(k) { return attrs.has(k) ? attrs.get(k) : null; },
        focus() { doc.activeElement = el; focused.push(id); },
      };
      elements.set(id, el);
    }
    return elements.get(id);
  };
  doc.getElementById = element;
  Object.defineProperty(doc, 'cookie', { get: () => '', set: v => cookies.push(String(v)) });
  const storage = { getItem: () => null, setItem: (k, v) => stored.push(`${k}=${v}`), removeItem() {}, clear() {} };
  const win = {
    location: { pathname: u.pathname, search: u.search, hash: u.hash, href: u.href },
    history: {
      state: null,
      replaceState(state, title, url) {
        const n = new URL(String(url), u.origin);
        win.location.pathname = n.pathname; win.location.search = n.search; win.location.hash = n.hash; win.location.href = n.href;
      },
    },
  };
  const sandbox = {
    console: { log: rec, info: rec, warn: rec, error: rec, debug: rec },
    URLSearchParams, URL, Promise, JSON, Date, Math, String, Number, Array, Object, Error, RegExp, encodeURIComponent,
    document: doc, localStorage: storage, sessionStorage: storage,
    location: win.location, history: win.history,
    fetch: async (url, init) => {
      requests.push({ url: String(url), init: init || {} });
      return answer(requests.length, String(url), init || {});
    },
  };
  sandbox.window = Object.assign(sandbox, win);
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(ACCOUNT, sandbox);
  vm.runInContext(SRC, sandbox);
  return { sb: sandbox, win, el: element, logged, stored, cookies, requests, focused, doc };
}

// The parts of a request that must hold: the URL is the bare route, the token only in the body.
function bodyForm(r) {
  const url = r.url;
  let body = null;
  try { body = typeof r.init.body === 'string' ? JSON.parse(r.init.body) : null; } catch { body = null; }
  const headers = r.init.headers || {};
  return {
    url,
    urlExact: url === API + '/auth/verify-email',
    noQuery: !url.includes('?'),
    noTokenInUrl: !url.includes(TOKEN) && !/token/i.test(url),
    post: r.init.method === 'POST',
    json: headers['Content-Type'] === 'application/json',
    exactBody: !!body && typeof body === 'object' && JSON.stringify(Object.keys(body)) === JSON.stringify(['token']) && body.token === TOKEN,
  };
}

await scenario('[V1] nothing is sent when the page loads; the token leaves the address bar', async () => {
  const p = openPage(`https://app.example.invalid/sol/verify?token=${TOKEN}&from=mail`, () => res(200, { detail: 'Email verified' }));
  await tick();
  ok(p.requests.length === 0, `no request on load (saw ${p.requests.length})`);
  ok(!p.win.location.href.includes(TOKEN) && p.win.location.search === '?from=mail', `the address bar no longer holds the token; other parameters kept (saw ${p.win.location.search})`);
  ok(p.el('verifyStart').hidden === false && p.el('verifyInvalid').hidden === true, 'the "Verify my email" section shows');
});

await scenario('[V2] one click: POST /auth/verify-email with the token in the JSON body only, never in the URL', async () => {
  const p = openPage(`https://app.example.invalid/sol/verify?token=${TOKEN}`, () => res(200, { detail: 'Email verified' }));
  await p.sb.runVerify();
  ok(p.requests.length === 1, `exactly one request (saw ${p.requests.length})`);
  const f = p.requests[0] ? bodyForm(p.requests[0]) : {};
  ok(f.post === true, 'the method is POST');
  ok(f.noTokenInUrl === true, `the request URL holds no token and no "token" (saw ${f.url})`);
  ok(f.noQuery === true, `the request URL has no query string (saw ${f.url})`);
  ok(f.urlExact === true, `the request URL is exactly <API>/auth/verify-email (saw ${f.url})`);
  ok(f.json === true, 'Content-Type: application/json');
  ok(f.exactBody === true, `the body is exactly {"token": <the token>} (saw ${p.requests[0] && p.requests[0].init.body})`);
  ok(p.el('verifyDone').hidden === false && p.el('pageTitle').textContent === 'Email verified', 'success: the done section and the heading say so');
});

await scenario('[V3] a double click sends once; busy while it runs; after the 200 the token is dropped', async () => {
  const gate = deferred();
  const p = openPage(`https://app.example.invalid/sol/verify?token=${TOKEN}`, () => gate.p.then(() => res(200, { detail: 'Email verified' })));
  const a = p.sb.runVerify(); const b = p.sb.runVerify();
  await tick();
  ok(p.requests.length === 1, `two clicks before the answer: one request (saw ${p.requests.length})`);
  ok(p.el('verifyGo').getAttribute('aria-busy') === 'true' && p.el('verifyGo').getAttribute('aria-disabled') === 'true' && p.el('verifyGo').textContent === 'Verifying…', 'the button is busy while the request runs');
  gate.resolve(); await a; await b;
  ok(p.el('verifyGo').getAttribute('aria-busy') === null && p.el('verifyGo').getAttribute('aria-disabled') === null, 'busy cleared after the answer');
  ok(p.focused[p.focused.length - 1] === 'pageTitle', 'focus moves to the heading with the answer');
  const f = p.requests[0] ? bodyForm(p.requests[0]) : {};
  ok(f.noTokenInUrl === true && f.exactBody === true, `that one request carries the token in the body only (saw ${f.url})`);
  await p.sb.runVerify();
  ok(p.requests.length === 1, 'after success the token is dropped: a later click sends nothing');
});

await scenario('[V4] "Try again" after a failed answer sends the body form again', async () => {
  const p = openPage(`https://app.example.invalid/sol/verify?token=${TOKEN}`, n => (n === 1 ? res(500, { detail: 'Internal Server Error' }) : res(200, { detail: 'Email verified' })));
  await p.sb.runVerify();
  ok(p.el('verifyRetry').hidden === false && /something went wrong/i.test(p.el('verifyRetryText').textContent), 'a 500: the retry section with its reason');
  ok(p.el('verifyState').textContent === p.el('verifyRetryText').textContent && p.focused[p.focused.length - 1] === 'pageTitle', 'the reason is in the status region; focus on the heading');
  await p.sb.runVerify();
  ok(p.requests.length === 2, `"Try again" sends a second request (saw ${p.requests.length})`);
  const forms = p.requests.map(bodyForm);
  ok(forms.length === 2 && forms.every(f => f.urlExact && f.noTokenInUrl && f.exactBody && f.post), `both requests: the bare URL, the token in the body only (saw ${forms.map(f => f.url).join(', ')})`);
  ok(p.el('verifyDone').hidden === false, 'the second answer (200) shows success');
});

await scenario('[V5] 404 and 405 read "not available yet"; the request is the body form', async () => {
  for (const st of [404, 405]) {
    const p = openPage(`https://app.example.invalid/sol/verify?token=${TOKEN}`, () => res(st, { detail: st === 404 ? 'Not Found' : 'Method Not Allowed' }));
    await p.sb.runVerify();
    ok(/not available yet/i.test(p.el('verifyRetryText').textContent) && p.el('verifyRetry').hidden === false, `${st}: "not available yet", with "Try again"`);
    const f = p.requests[0] ? bodyForm(p.requests[0]) : {};
    ok(f.urlExact === true && f.exactBody === true, `${st}: the bare URL and {token} in the body (saw ${f.url})`);
  }
});

await scenario('[V6] the token never reaches the console, storage or a cookie', async () => {
  const p = openPage(`https://app.example.invalid/sol/verify?token=${TOKEN}`, n => (n === 1 ? res(429, { error: 'Rate limit exceeded: 10 per 1 minute' }) : res(400, { detail: 'Invalid or expired token' })));
  await p.sb.runVerify(); await p.sb.runVerify();
  ok(p.requests.length === 2, `two requests (429, then 400) (saw ${p.requests.length})`);
  ok(!p.logged.some(l => l.includes(TOKEN)), 'nothing logged holds the token');
  ok(p.stored.length === 0 && p.cookies.length === 0, 'nothing written to storage or a cookie');
  ok(p.requests.every(r => !r.url.includes(TOKEN)), 'no request URL holds the token');
  ok(p.el('verifyInvalid').hidden === false, 'a 400 shows the expired-link section');
});

await scenario('[V7] without a token, nothing is sent', async () => {
  const p = openPage('https://app.example.invalid/sol/verify?from=mail', () => res(200, {}));
  await p.sb.runVerify();
  ok(p.requests.length === 0, 'no request');
  ok(p.el('verifyInvalid').hidden === false && /incomplete/i.test(p.el('verifyInvalidText').textContent), 'the "link is incomplete" message');
});

await scenario('[V8] deploy order: a backend that still reads ?token= (422 at loc query) reads "not available yet"; no fallback to the URL', async () => {
  // The deployed base (api/auth.py:113-121) answers the body form 422 at loc ["query","token"]. If
  // this page reaches members first, the link must not read as expired, the token must stay in
  // memory for "Try again", and the page must never resend it in a URL to make it work.
  const OLD = { detail: [{ type: 'missing', loc: ['query', 'token'], msg: 'Field required', input: null }] };
  let backendReadsBody = false;
  const p = openPage(`https://app.example.invalid/sol/verify?token=${TOKEN}`, () => (backendReadsBody ? res(200, { detail: 'Email verified' }) : res(422, OLD)));
  await p.sb.runVerify();
  ok(p.el('verifyRetry').hidden === false && /not available yet/i.test(p.el('verifyRetryText').textContent), `the retry section says "not available yet" (saw "${p.el('verifyRetryText').textContent}")`);
  ok(p.el('verifyInvalid').hidden === true && p.el('pageTitle').textContent !== 'This link does not work', 'not the expired-link section');
  ok(p.el('verifyState').textContent !== '' && p.el('verifyState').textContent === p.el('verifyRetryText').textContent && p.focused[p.focused.length - 1] === 'pageTitle', 'the reason is in the status region; focus on the heading');
  ok(p.requests.length === 1, `one request: nothing resent with the token in the URL (saw ${p.requests.length})`);
  backendReadsBody = true;   // the backend that reads the body is now live
  await p.sb.runVerify();
  ok(p.requests.length === 2 && p.el('verifyDone').hidden === false, '"Try again" once that backend is live verifies with the token kept in memory');
  const forms = p.requests.map(bodyForm);
  ok(forms.length === 2 && forms.every(f => f.post && f.urlExact && f.noTokenInUrl && f.exactBody), `both requests: the bare URL, the token in the body only (saw ${forms.map(f => f.url).join(', ')})`);
  ok(!p.logged.some(l => l.includes(TOKEN)) && p.stored.length === 0 && p.cookies.length === 0, 'the token never reaches the console, storage or a cookie');
});

console.log(`\nverify-email page: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
