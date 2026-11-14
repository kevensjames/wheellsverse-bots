// Admin portal stored-XSS regression test (pure Node, zero dependencies, no network).
//   node tests/sol-frontend/admin-xss.test.mjs
//
// Loads the REAL inline script of frontend/sol/admin.html in a vm sandbox with stub DOM
// elements and a scripted fetch (synthetic data only; the API constant is rewritten to a
// reserved .invalid host that is never contacted). Every field a member or a provider can
// influence is filled with a harmless payload, every admin view that renders it is run,
// and every HTML string the page writes (innerHTML, or returned for innerHTML) is checked:
//   - no payload markup survives as markup: '<img src=x' and '<svg onload' only appear
//     escaped (&lt;...), so a member's name, circle name or bank name cannot run script in
//     the admin's page;
//   - the data is still shown (its escaped form is present);
//   - every inline onclick handler, after the browser decodes the attribute, is exactly one
//     call whose arguments are string literals: a value that breaks out of a quoted JS
//     string (x');...) cannot add a statement.
// Fields covered: full_name, email, circle name, invite code, bank institution_name,
// provider and account_type, member e-mails, payment and payout provider codes, audit
// actor/action/target/payload, API error messages, the 2FA setup secret and QR URL, and
// the reconcile report. Ids are server-generated, but are covered too (defence in depth).
// What it does NOT prove: anything about the deployed portal, or rendering in a browser
// (checks/ has a real-Chromium reproduction that runs the payload).
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const HTML = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'frontend', 'sol', 'admin.html');
const scripts = [...readFileSync(HTML, 'utf8').matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
const SRC = scripts.find(s => s.includes('function renderUsers'));
if (!SRC) throw new Error('admin script with renderUsers() not found in admin.html');
if (!/const API = '[^']*';/.test(SRC)) throw new Error('admin API constant not found: the rewrite would not apply');
const API = 'https://sol-api.invalid';

// Synthetic payloads. TAG and ATTR would run script if rendered as markup; JSID breaks out
// of a single-quoted JS string inside an inline handler.
const TAG = '<img src=x onerror="window.__xss=1">';
const ATTR = '"><svg onload=window.__xss=2>';
const JSID = "x');window.__xss=3;//";
const TAG_ESC = '&lt;img src=x onerror=';

const res = (status, body) => ({ status, ok: status >= 200 && status < 300, statusText: '', json: async () => body ?? {} });
const tick = () => new Promise(r => setTimeout(r, 0));
const settle = async () => { for (let i = 0; i < 8; i++) await tick(); };

function makeAdmin(route) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, { id, style: {}, innerHTML: '', textContent: '', value: '', disabled: false, classList: { add() {}, remove() {}, contains: () => false }, addEventListener() {} });
    return elements.get(id);
  };
  const session = new Map();
  const sandbox = {
    console, setTimeout, clearTimeout, Promise, JSON, URLSearchParams,
    window: { location: { href: '', search: '', pathname: '/sol/admin', replace() {}, reload() {} }, addEventListener() {}, open: () => null },
    sessionStorage: { getItem: k => (session.has(k) ? session.get(k) : null), setItem: (k, v) => session.set(k, String(v)), removeItem: k => session.delete(k) },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    document: { getElementById: element, querySelector: () => null, querySelectorAll: () => [], addEventListener() {}, createElement: () => element('created') },
    alert() {}, confirm: () => false,
    fetch: (url, opts = {}) => { try { return Promise.resolve(route(String(url).replace(API, ''), (opts.method || 'GET').toUpperCase())); } catch (e) { return Promise.reject(e); } },
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SRC.replace(/const API = '[^']*';/, `const API = '${API}';`), sandbox);
  const V = (expr, vars = {}) => { Object.assign(sandbox, vars); return vm.runInContext(expr, sandbox); };
  V("adminToken = 'synthetic-admin-access-1'");
  const htmlOf = () => [...elements.values()].map(e => e.innerHTML).filter(Boolean).join('\n');
  return { V, element, htmlOf };
}

let pass = 0, fail = 0;
const ok = (c, m) => { if (c) { pass++; console.log('  ✓', m); } else { fail++; console.log('  ✗ FAIL:', m); } };
const scenario = async (name, fn) => {
  console.log('\n' + name);
  try { await fn(); } catch (e) { fail++; console.log('  ✗ FAIL: threw', String(e && e.stack || e).split('\n')[0]); }
};

const decode = s => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&#x27;/g, "'").replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&#96;/g, '`').replace(/&amp;/g, '&');
// One call, optional `event, `, string-literal arguments only, optionally followed by one
// argument-less call (approveKYC("…");closeUserModal()).
const STR = `(?:"(?:[^"\\\\]|\\\\.)*"|'(?:[^'\\\\]|\\\\.)*')`;
const HANDLER = new RegExp(`^[A-Za-z_$][\\w$]*\\((?:event, ?)?(?:${STR}(?:, ?${STR})*)?\\)(?:;[A-Za-z_$][\\w$]*\\(\\))?$`);
function checkHtml(html, label, { shown = true } = {}) {
  ok(!html.includes('<img src=x') && !html.includes('<svg onload'), `${label}: no payload markup survives as markup`);
  if (shown) ok(html.includes(TAG_ESC), `${label}: the data is still shown, escaped`);
  const handlers = [...html.matchAll(/onclick="([^"]*)"/g)].map(m => decode(m[1]));
  const bad = handlers.filter(h => !HANDLER.test(h));
  ok(bad.length === 0, `${label}: every inline handler is one call with string-literal arguments${bad.length ? ' (bad: ' + JSON.stringify(bad.slice(0, 2)) + ')' : ''}`);
}

const user = (over = {}) => ({ id: JSID, email: `member${ATTR}@example.invalid`, full_name: TAG, account_status: 'ACTIVE', kyc_status: 'PENDING', successful_payments: 1, failed_payments: 0, created_at: '2026-11-01T00:00:00Z', ...over });
const group = (over = {}) => ({ id: JSID, name: TAG, status: 'FORMING', is_private: true, member_count: 2, max_members: 5, contribution_cents: 5000, current_cycle_number: 1, payout_day_of_month: 3, invite_code: ATTR, ...over });

await scenario('[X1] users table: full_name, email and the row handler', async () => {
  const app = makeAdmin(() => res(200, []));
  app.V('allUsers = __u; renderUsers(null)', { __u: [user()] });
  checkHtml(app.element('userTable').innerHTML, 'users table');
});

await scenario('[X2] KYC table: full_name, email and the approve/reject handlers', async () => {
  const app = makeAdmin(() => res(200, []));
  app.V('allUsers = __u; renderKYC()', { __u: [user()] });
  checkHtml(app.element('kycTable').innerHTML, 'KYC table');
});

await scenario('[X3] overview: recent users (email)', async () => {
  const app = makeAdmin(path => (path === '/admin/reconcile' ? res(200, { balanced: true }) : res(200, [])));
  app.V('allUsers = __u; allGroups = __g; loadOverview()', { __u: [user({ email: TAG })], __g: [group()] });
  await settle();
  checkHtml(app.element('recentActivity').innerHTML, 'overview recent users');
});

await scenario('[X4] user detail: bank fields, circle name, payment error code, action handlers', async () => {
  const app = makeAdmin(() => res(200, []));
  const d = {
    user: { id: JSID, full_name: TAG, email: 'm@example.invalid', account_status: 'SUSPENDED', kyc_status: 'PENDING', role: 'USER', successful_payments: 0, failed_payments: 0 },
    bank_accounts: [{ institution_name: TAG, provider: ATTR, account_last4: '0000', account_type: TAG, verified: false, is_primary: true }],
    groups: [{ name: TAG, is_private: false, current_cycle_number: 1, contribution_cents: 100, status: 'ACTIVE' }],
    recent_payments: [{ created_at: '2026-11-01T00:00:00Z', amount_cents: 100, status: 'FAILED', attempt_count: 1, ach_error_code: TAG }],
  };
  checkHtml(app.V('renderUserDetail(__d)', { __d: d }), 'user detail');
});

await scenario('[X5] circles table: circle name, invite code and the row handler', async () => {
  const app = makeAdmin(() => res(200, []));
  app.V('allGroups = __g; renderGroups(null)', { __g: [group()] });
  checkHtml(app.element('groupTable').innerHTML, 'circles table');
});

await scenario('[X6] circle detail: member e-mails, invite code, payout transfer id, payment error code', async () => {
  const app = makeAdmin(() => res(200, []));
  const d = {
    group: { ...group(), invite_code: TAG },
    members: [{ position: 1, user_email: TAG, status: 'ACTIVE', successful_payments_in_group: 1, has_received_payout: false }],
    cycles: [{ id: 'c1', cycle_number: 1, total_collected_cents: 100, payout_cents: 0, status: 'COLLECTING' }],
    payouts: [{ cycle_id: 'c1', net_cents: 100, status: 'FAILED', ach_transfer_id: ATTR }],
    recent_payments: [{ created_at: '2026-11-01T00:00:00Z', amount_cents: 100, status: 'FAILED', attempt_count: 1, ach_error_code: ATTR }],
  };
  checkHtml(app.V('renderGroupDetail(__d)', { __d: d }), 'circle detail');
});

await scenario('[X7] cycles table: circle name and the initiate handler', async () => {
  const g = group({ id: 'g1', status: 'ACTIVE' });
  const app = makeAdmin(path => (path === '/admin/groups' ? res(200, [g])
    : path === '/admin/groups/g1' ? res(200, { group: g, cycles: [{ id: JSID, cycle_number: 1, status: 'PENDING' }], members: [] })
      : res(200, [])));
  app.V('loadCyclesData()');
  await settle();
  checkHtml(app.element('cyclesTable').innerHTML, 'cycles table');
});

await scenario('[X8] payouts table: provider transfer id and the retry handler', async () => {
  const app = makeAdmin(path => (path.startsWith('/admin/payouts') ? res(200, [{ id: JSID, status: 'FAILED', net_cents: 100, fee_cents: 0, attempt_count: 1, ach_transfer_id: TAG, created_at: '2026-11-01T00:00:00Z' }]) : res(200, [])));
  app.V('loadPayoutsData()');
  await settle();
  checkHtml(app.element('payoutsTable').innerHTML, 'payouts table');
});

await scenario('[X9] audit log: actor, action, target and payload', async () => {
  const app = makeAdmin(path => (path.startsWith('/admin/audit/archive-status') ? res(200, {})
    : path.startsWith('/admin/audit') ? res(200, [{ created_at: '2026-11-01T00:00:00Z', actor_email: TAG, action: ATTR, target_type: TAG, target_id: 'abcdefghij', payload: { name: TAG, note: ATTR } }])
      : res(200, [])));
  app.V('loadAuditLog()');
  await settle();
  checkHtml(app.element('auditTable').innerHTML, 'audit log');
});

await scenario('[X10] payment retries: the process handler', async () => {
  const app = makeAdmin(path => (path.startsWith('/admin/payments/retries') ? res(200, [{ id: JSID + 'xxxxxxxx', group_id: 'g1xxxxxxxxx', amount_cents: 100, attempt_count: 1, next_retry_at: null }]) : res(200, [])));
  app.V('loadRetries()');
  await settle();
  checkHtml(app.element('retryTable').innerHTML, 'payment retries', { shown: false });
});

await scenario('[X11] API error messages are rendered as text in every view', async () => {
  for (const [call, id] of [
    ['loadUsers()', 'userTable'], ['loadGroupsData()', 'groupTable'], ['loadAuditLog()', 'auditTable'],
    ['loadPayoutsData()', 'payoutsTable'], ['loadRetries()', 'retryTable'],
    ["openUserModal('u1')", 'userModalBody'], ["openGroupModal('g1')", 'groupModalBody'], ['loadSecurity()', 'securityCard'],
  ]) {
    const app = makeAdmin(() => res(400, { detail: TAG }));
    app.V(call);
    await settle();
    checkHtml(app.element(id).innerHTML, `error in ${call}`);
  }
  // loadCyclesData() and loadOverview() load users and circles through loadUsers() and
  // loadGroupsData(), which render the API error themselves (above); their own catch is not
  // reached by an API error. Everything the page wrote is still checked for markup.
  for (const call of ['loadCyclesData()', 'allUsers = []; allGroups = []; loadOverview()']) {
    const app = makeAdmin(() => res(400, { detail: TAG }));
    app.V(call);
    await settle();
    checkHtml(app.htmlOf(), `error in ${call.replace(/^.*; /, '')} (all page HTML)`);
  }
});

await scenario('[X12] 2FA setup: secret and QR URL from the server', async () => {
  const app = makeAdmin(path => (path === '/auth/2fa/setup' ? res(200, { qr_data_url: ATTR, secret: TAG }) : res(200, {})));
  app.V('startTotp()');
  await settle();
  checkHtml(app.element('securityCard').innerHTML, '2FA setup');
});

await scenario('[X13] reconcile report: currency and a non-object answer', async () => {
  const app = makeAdmin(() => res(200, {}));
  checkHtml(app.V('formatReconcileReport(__r)', { __r: { balanced: false, total_debits: 1, total_credits: 2, difference: 1, currency: TAG } }), 'reconcile report');
  checkHtml(app.V('formatReconcileReport(__r)', { __r: TAG }), 'reconcile report (non-object)');
});

console.log(`\nadmin XSS: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
