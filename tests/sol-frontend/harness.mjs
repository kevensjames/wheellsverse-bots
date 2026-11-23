// SOL member app — test harness generator (Node).
//
// Generates frontend/sol/boot-test.html: the CURRENT app.html with an injected,
// query- and AbortSignal-aware MOCK backend. This lets the real modular frontend
// boot and run the primary member journeys in a browser WITHOUT the Sol backend
// (a separate repo) and without any real auth, payment, or PII.
//
// The generated boot-test.html is git-ignored and MUST NOT be committed — it
// embeds the internal API route map, which is fine for a local test file but
// would be recon material if served in production. Only this generator is
// committed. Import generateHarness() from journeys.mjs, or run directly:
//   node frontend/sol/app/tests/harness.mjs
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
const SOL = join(HERE, '..', '..', 'frontend', 'sol');   // repo/frontend/sol
export const HARNESS_PATH = join(SOL, 'boot-test.html');
export const HARNESS_URL_PATH = '/sol/boot-test.html';

// Stable fake ids (never real). Exported so journeys.mjs can reference them.
export const IDS = {
  U: 'aaaa1111-1111-4111-8111-aaaaaaaaaaaa',
  G_ACT: 'bbbb2222-2222-4222-8222-bbbbbbbbbbbb',
  G_FORM: 'cccc3333-3333-4333-8333-cccccccccccc',
  GOAL: 'dddd4444-4444-4444-8444-dddddddddddd',
  BANK: 'eeee5555-5555-4555-8555-eeeeeeeeeeee',
  POST: 'ffff6666-6666-4666-8666-ffffffffffff',
};

function seed() {
  const { U, G_ACT, G_FORM, GOAL, BANK, POST } = IDS;
  return {
    // GET /auth/me (BASE schemas/auth.py:43-68): email_verified_at is the verified flag (there
    // is no boolean), totp_enabled and totp_backup_codes_remaining the two-factor state.
    user: { id: U, email: 'member@example.invalid', full_name: 'Test User', phone: null, kyc_status: 'VERIFIED', account_status: 'ACTIVE', role: 'ADMIN', is_admin: true,
      totp_enabled: false, totp_backup_codes_remaining: 0, email_verified_at: '2026-01-02T00:00:00Z', created_at: '2026-01-01T00:00:00Z', locale: 'en' },
    // GET /account/settings (BASE api/account.py:64-69): {locale, preferences, dark_mode}.
    settings: { locale: 'en', preferences: { notifications: { email: true, sms: false } }, dark_mode: false },
    // GET /payments/my-payouts (BASE api/payments.py:366-397). Ids are never rendered.
    // status is any PayoutStatus value (BASE models/payout.py:24-36). settled_at stays set on a
    // payout that settled and was later returned, reversed or sent to manual review. Each of the
    // last five rows has its own net amount, so a journey can find its row. The last row is what the
    // legacy flow returns: SUCCESS with settled_at null (BASE services/payout.py:597-599 sets SUCCESS
    // and no date; only the gated SETTLED path sets settled_at, :795-796; models/payout.py:93-94).
    payouts: [
      { id: '99990000-0000-4000-8000-999999999991', circle_id: G_ACT, cycle_id: '99990000-0000-4000-8000-999999999992', status: 'SUCCESS', gross_cents: 120000, fee_cents: 12000, net_cents: 108000, currency: 'USD', settled_at: '2026-06-20T00:00:00Z', created_at: '2026-06-15T00:00:00Z' },
      { id: '99990000-0000-4000-8000-999999999993', circle_id: G_ACT, cycle_id: '99990000-0000-4000-8000-999999999994', status: 'PROCESSING', gross_cents: 120000, fee_cents: 12000, net_cents: 108000, currency: 'USD', settled_at: null, created_at: '2026-07-15T00:00:00Z' },
      { id: '99990000-0000-4000-8000-999999999995', circle_id: G_ACT, cycle_id: '99990000-0000-4000-8000-999999999996', status: 'SETTLED', gross_cents: 60000, fee_cents: 6000, net_cents: 54000, currency: 'USD', settled_at: '2026-08-20T00:00:00Z', created_at: '2026-08-15T00:00:00Z' },
      { id: '99990000-0000-4000-8000-999999999997', circle_id: G_ACT, cycle_id: '99990000-0000-4000-8000-999999999998', status: 'MANUAL_REVIEW', gross_cents: 60100, fee_cents: 6000, net_cents: 54100, currency: 'USD', settled_at: '2026-09-20T00:00:00Z', created_at: '2026-09-15T00:00:00Z' },
      { id: '99990000-0000-4000-8000-999999999999', circle_id: G_ACT, cycle_id: '99990000-0000-4000-8000-99999999999a', status: 'RETURNED', gross_cents: 60200, fee_cents: 6000, net_cents: 54200, currency: 'USD', settled_at: '2026-10-20T00:00:00Z', created_at: '2026-10-15T00:00:00Z' },
      { id: '99990000-0000-4000-8000-99999999999b', circle_id: G_ACT, cycle_id: '99990000-0000-4000-8000-99999999999c', status: 'REVERSED', gross_cents: 60300, fee_cents: 6000, net_cents: 54300, currency: 'USD', settled_at: '2026-11-02T00:00:00Z', created_at: '2026-10-28T00:00:00Z' },
      { id: '99990000-0000-4000-8000-99999999999d', circle_id: G_ACT, cycle_id: '99990000-0000-4000-8000-99999999999e', status: 'SUCCESS', gross_cents: 60400, fee_cents: 6000, net_cents: 54400, currency: 'USD', settled_at: null, created_at: '2026-05-15T00:00:00Z' },
    ],
    groupsActive: [{
      id: G_ACT, name: 'Family Savings Circle', status: 'ACTIVE',
      contribution_cents: 20000, fee_bps: 1000, member_count: 6, max_members: 6,
      current_cycle_number: 2, payout_day_of_month: 15,
      current_cycle: { cycle_number: 2, status: 'COLLECTING', total_collected_cents: 80000, recipient_id: U },
      invite_code: 'FAM123', is_private: true, created_by: U,
      members: [
        { id: U, name: 'You', position: 1, user_id: U, status: 'ACTIVE', has_received_payout: false },
        { id: 'm2', name: 'SOL member', position: 2, user_id: 'u2', status: 'ACTIVE', has_received_payout: true },
      ],
    }],
    groupsForming: [{
      id: G_FORM, name: 'New Year Circle', status: 'FORMING',
      contribution_cents: 15000, fee_bps: 1000, member_count: 3, max_members: 8,
      current_cycle_number: 0, current_cycle: 0, payout_day_of_month: 1,
      invite_code: 'NY2026', is_private: false, created_by: 'u9', members: [],
    }],
    goals: [{
      id: GOAL, type: 'EMERGENCY_FUND', name: 'Emergency fund',
      target_cents: 500000, saved_cents: 200000, target_date: '2026-12-31',
      status: 'ACTIVE', progress_percent: 40, created_at: '2026-01-01T00:00:00Z', updated_at: '2026-07-01T00:00:00Z',
    }],
    notifications: {
      unread_count: 2,
      notifications: [
        { id: 'n1', type: 'PAYMENT_DUE', title: 'Contribution due', body: 'Your Family Savings Circle contribution is due Jul 15.', created_at: '2026-07-10T12:00:00Z', read: false, read_at: null, related_group_id: G_ACT },
        { id: 'n2', type: 'PAYOUT', title: 'Payout scheduled', body: 'A payout is scheduled for next cycle.', created_at: '2026-07-08T12:00:00Z', read: false, read_at: null, related_group_id: G_ACT },
      ],
      items: [],
    },
    subscription: { is_premium: true, status: 'ACTIVE', cancel_at_period_end: false, current_period_end: '2026-08-01T00:00:00Z', price_cents: 1499 },
    invoices: [
      { amount_cents: 1499, created_at: '2026-07-01T00:00:00Z', hosted_url: 'https://invoice.stripe.com/i/test_abc', status: 'paid' },
      { amount_cents: 1499, created_at: '2026-06-01T00:00:00Z', hosted_url: 'https://invoice.stripe.com/i/test_def', status: 'paid' },
    ],
    bank: [{ id: BANK, account_last4: '4321', account_type: 'checking', institution_name: 'Test Bank', is_primary: true, status: 'verified', verified: true, created_at: '2026-05-01T00:00:00Z' }],
    trust: { sol_score: 720, max_score: 850, components: { on_time_payments: 95, circles_completed: 80, account_tenure: 60 }, badges: [{ title: 'On-time payer', description: 'Paid on time 12 months running.' }] },
    timeline: {
      next_contribution: { amount_cents: 20000, group_name: 'Family Savings Circle', due_date: '2026-07-15' },
      upcoming_payout: { amount_cents: 108000, net_cents: 108000, date: '2026-09-15', payout_date: '2026-09-15' },
      remaining_payments: 4,
      circle_progress: [{ group_name: 'Family Savings Circle', current_cycle: 2, total_cycles: 6 }],
      payment_history: [
        { created_at: '2026-06-15T00:00:00Z', amount_cents: 20000, status: 'COMPLETED' },
        { created_at: '2026-05-15T00:00:00Z', amount_cents: 20000, status: 'COMPLETED' },
      ],
    },
    payments: [{ id: 'p1', group_id: G_ACT, amount_cents: 20000, status: 'COMPLETED', created_at: '2026-06-15T00:00:00Z' }],
    feed: [{ id: POST, ref: POST, author: 'SOL member', author_id: 'u2', user_id: 'u2', body: 'Just completed my first circle! Grateful for this community.', text: 'Just completed my first circle!', created_at: '2026-07-12T09:00:00Z', created: '2026-07-12T09:00:00Z', scope: 'CIRCLE', group_id: G_ACT, mine: false }],
    comments: [{ id: 'c1', ref: 'c1', author: 'You', body: 'Congratulations!', created_at: '2026-07-12T10:00:00Z', mine: true, user_id: IDS.U }],
    // Phase 3 — Circle Catalog (admin-defined offerings) + participation gate.
    catalog: [
      { id: 'a1a1a1a1-1111-4111-8111-a1a1a1a1a1a1', name: 'Weekly Starter Circle', description: 'A small weekly circle to build the saving habit.', status: 'OPEN', contribution_cents: 5000, cadence: 'WEEKLY', entry_fee_cents: 500, fee_bps: 1000, member_count: 3, max_members: 8, payout_day_of_month: null, is_private: false, tier: 'STANDARD' },
      { id: 'b2b2b2b2-2222-4222-8222-b2b2b2b2b2b2', name: 'Monthly Family Circle', description: 'Monthly contributions toward bigger goals.', status: 'FORMING', contribution_cents: 20000, cadence: 'MONTHLY', entry_fee_cents: 0, fee_bps: 1000, member_count: 5, max_members: 6, payout_day_of_month: 15, is_private: false, tier: 'STANDARD' },
      { id: 'c3c3c3c3-3333-4333-8333-c3c3c3c3c3c3', name: 'Private Biweekly Circle', description: 'Invite-only, every two weeks.', status: 'FULL', contribution_cents: 10000, cadence: 'BIWEEKLY', entry_fee_cents: 1000, fee_bps: 1000, member_count: 8, max_members: 8, payout_day_of_month: null, is_private: true, tier: 'PREMIUM' },
    ],
    participation: { can_join: true, status: 'TRIALING', trial_end: '2026-08-15T00:00:00Z', current_period_end: '2026-08-15T00:00:00Z', price_cents: 999 },
    eligibility: { can_join: true, checks: { subscription: 'ok', kyc: 'ok', bank: 'ok', account: 'ok' }, your_position: 4, entry_fee_cents: 500, entry_fee_refundable_until: 'FORMING_END' },
    adminCircles: [
      { id: 'a1a1a1a1-1111-4111-8111-a1a1a1a1a1a1', name: 'Weekly Starter Circle', status: 'OPEN', contribution_cents: 5000, entry_fee_cents: 500, cadence: 'WEEKLY', member_count: 3, max_members: 8, is_private: false },
      { id: 'd4d4d4d4-4444-4444-8444-d4d4d4d4d4d4', name: 'Draft Autumn Circle', status: 'DRAFT', contribution_cents: 25000, entry_fee_cents: 0, cadence: 'MONTHLY', member_count: 0, max_members: 10, is_private: false },
      { id: 'c3c3c3c3-3333-4333-8333-c3c3c3c3c3c3', name: 'Private Biweekly Circle', status: 'CLOSED', contribution_cents: 10000, entry_fee_cents: 1000, cadence: 'BIWEEKLY', member_count: 8, max_members: 8, is_private: true },
    ],
    adminParticipants: [{ position: 1, status: 'ACTIVE' }, { position: 2, status: 'COMPLETED' }, { position: 3, status: 'PENDING' }],
  };
}

// Response shapes of the routes the new member pages call, copied from the backend.
// BASE = deployed origin/integration/money-path @ c218dfb; A33/C34/S35 = draft PRs #33/#34/#35.
// The defaults are the deployed base: a route that exists only in a draft PR answers
// 404 {"detail":"Not Found"} (FastAPI's default for an unknown path), so the pages' "not
// available yet" paths run unless a journey opts in with __mockSet()/__mock flags.
// A 429 is slowapi's default handler (BASE main.py:52): {"error": "Rate limit exceeded: …"},
// no "detail" key and no Retry-After header.
const MOCK_SHARED = String.raw`
window.__errs = window.__errs || [];
window.addEventListener('error', e => window.__errs.push(String(e.message || e.error)));
window.addEventListener('unhandledrejection', e => window.__errs.push('unhandledrejection: ' + String(e.reason)));
window.__reqLog = [];
// Per-route overrides: __mockSet('POST /auth/resend-verification', 202, {...}); with
// { once: true } the override answers one request and is then removed.
// revoked: every refresh session was ended (a 2FA disable does that, BASE services/auth.py:412),
// so POST /auth/refresh answers 401 until __mockClear(). delay: ms before every answer.
// versions: per consent kind, the document versions GET /legal/documents serves (C34).
// verifyFromQuery: POST /auth/verify-email answers like the deployed base, which reads the token
// from the query string only (see _publicRoute); the deploy-order checks of journeys.mjs turn it on.
window.__mock = Object.assign({ over: {}, s35: false, c34: false, a33: false, revoked: false, delay: 0, versions: {}, verifyFromQuery: false }, window.__mock || {});
window.__mockSet = (key, status, body, opts) => { window.__mock.over[key] = { status, body, once: !!(opts && opts.once) }; };
window.__mockClear = () => { window.__mock.over = {}; window.__mock.s35 = false; window.__mock.c34 = false; window.__mock.a33 = false; window.__mock.revoked = false; window.__mock.delay = 0; window.__mock.versions = {}; window.__mock.verifyFromQuery = false; };
const R = (status, body) => ({ __mockStatus: status, body });
const NOT_FOUND = () => R(404, { detail: 'Not Found' });
const LIMITED = limit => R(429, { error: 'Rate limit exceeded: ' + limit });
const EXTRA = field => R(422, { detail: [{ type: 'extra_forbidden', loc: ['body', field], msg: 'Extra inputs are not permitted', input: true }] });
const TOKENS = { access_token: 'synthetic-access-token', refresh_token: 'synthetic-refresh-token', token_type: 'bearer' };
// A 1x1 PNG, standing in for the backend's QR code (BASE api/auth.py:173-186).
const QR = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';
const LEGAL_DOCS = [
  { kind: 'terms', title: 'Sol Terms of Service', sha256: '0'.repeat(64), consent_kind: 'terms', text: 'SYNTHETIC TERMS TEXT.\n\nSecond paragraph of the synthetic terms.' },
  { kind: 'privacy', title: 'Sol Privacy Policy', sha256: '1'.repeat(64), consent_kind: 'privacy', text: 'SYNTHETIC PRIVACY TEXT.' },
  { kind: 'esign_disclosure', title: 'Consent to Electronic Records and Signatures', sha256: '2'.repeat(64), consent_kind: 'esign', text: 'SYNTHETIC E-SIGN TEXT.' },
  { kind: 'ach_debit_authorization', title: 'Bank-Debit (ACH) Authorization', sha256: '3'.repeat(64), consent_kind: 'ach_debit_authorization', text: 'SYNTHETIC ACH TEXT.' },
];
const BACKUP = ['a1b2-c3d4-e5','f6a7-b8c9-d0','e1f2-a3b4-c5','d6e7-f8a9-b0','c1d2-e3f4-a5','b6c7-d8e9-f0','a2b3-c4d5-e6','f7a8-b9c0-d1','e2f3-a4b5-c6','d7e8-f9a0-b1'];
// The synthetic codes POST /auth/2fa/backup-codes/regenerate returns (the backend's format, XXXX-XXXX-XX).
const BACKUP_NEW = ['9f8e-7d6c-5b','4a39-2817-06','f5e4-d3c2-b1','0a1b-2c3d-4e','5f6a-7b8c-9d','e0f1-a2b3-c4','d5e6-f7a8-b9','c0d1-e2f3-a4','b5c6-d7e8-f9','a0b1-c2d3-e4'];
// Public routes (no session): the landing page, /sol/reset-password and /sol/verify.
function _publicRoute(method, path, query, body) {
  // POST /auth/forgot-password -> 200, the same answer for unknown emails (BASE api/auth.py:124-132).
  if (method === 'POST' && path === '/auth/forgot-password') return R(200, { detail: 'If that email is registered, a reset link has been sent' });
  // POST /auth/reset-password {token, new_password 8..128} -> 200 (BASE api/auth.py:135-145;
  // schemas/auth.py:77-81); 400 "Invalid or expired token" (BASE services/auth.py:497-499).
  if (method === 'POST' && path === '/auth/reset-password') return R(200, { detail: 'Password updated' });
  // POST /auth/verify-email {token} -> 200; an empty token -> 400 "Invalid or expired token".
  // The token goes in the JSON body, as for /auth/reset-password: a URL lands in proxy and
  // access logs. BASE api/auth.py:113-121 (and A33 api/auth.py:116-124) still read it from the
  // query string; the backend change "keep email-verify tokens out of sol-api logs" is to read it
  // from this body. Extra keys are refused, as in the other auth bodies (BASE schemas/auth.py).
  // A query string is not read here: a request without the body is a 422, so a page that still
  // sends ?token= does not verify against this mock.
  // With __mock.verifyFromQuery the route is the deployed base instead: "token: str" is a query
  // parameter (BASE api/auth.py:113-121), the body is not read, and a request without ?token= gets
  // FastAPI's 422 at loc ["query","token"]. That is what the body form meets if the page ships
  // before the backend that reads the body.
  if (method === 'POST' && path === '/auth/verify-email' && window.__mock.verifyFromQuery) {
    const q = new URLSearchParams(query || '');
    if (!q.has('token')) return R(422, { detail: [{ type: 'missing', loc: ['query', 'token'], msg: 'Field required', input: null }] });
    return q.get('token') ? R(200, { detail: 'Email verified' }) : R(400, { detail: 'Invalid or expired token' });
  }
  if (method === 'POST' && path === '/auth/verify-email') {
    if (!body || typeof body !== 'object' || Array.isArray(body)) return R(422, { detail: [{ type: 'missing', loc: ['body'], msg: 'Field required' }] });
    for (const k of Object.keys(body)) if (k !== 'token') return EXTRA(k);
    if (typeof body.token !== 'string') return R(422, { detail: [{ type: 'missing', loc: ['body', 'token'], msg: 'Field required' }] });
    return body.token ? R(200, { detail: 'Email verified' }) : R(400, { detail: 'Invalid or expired token' });
  }
  // POST /auth/signup -> 201 tokens (BASE api/auth.py:48-64). Extra keys are forbidden on BASE
  // (schemas/auth.py:9-15); C34 adds accepted_terms_version, accepted_privacy_version and
  // esign_consent (C34 schemas/auth.py:16-20).
  if (method === 'POST' && path === '/auth/signup') {
    if (!window.__mock.c34) { for (const k of Object.keys(body || {})) if (!['email', 'password', 'full_name', 'phone'].includes(k)) return EXTRA(k); }
    return R(201, TOKENS);
  }
  // GET /legal/documents (C34 api/legal.py:13-16; legal/__init__.py:41-62, 94-102): the titles
  // are PR #34's; the texts are synthetic stand-ins. 404 on BASE.
  if (method === 'GET' && path === '/legal/documents') {
    if (!window.__mock.c34) return NOT_FOUND();
    const v = k => (window.__mock.versions && window.__mock.versions[k]) || '2026-11-22-draft-1';
    return R(200, LEGAL_DOCS.map(d => Object.assign({}, d, { version: v(d.consent_kind) })));
  }
  // POST /auth/login -> 200 tokens, or 428 {"detail":{"totp_required":true,"challenge_token":…}}
  // for a two-factor account (BASE services/auth.py:176-182).
  if (method === 'POST' && path === '/auth/login') return (body && /^totp/.test(body.email || '')) ? R(428, { detail: { totp_required: true, challenge_token: 'synthetic-challenge-token' } }) : R(200, TOKENS);
  // POST /auth/login/totp {challenge_token, code 6..12} -> 200 tokens (BASE api/auth.py:235-249).
  if (method === 'POST' && path === '/auth/login/totp') return R(200, TOKENS);
  if (method === 'POST' && path === '/auth/logout') return R(204, null);
  // POST /auth/refresh -> new pair (BASE api/auth.py:84-97); 401 "Invalid or expired refresh
  // token" (BASE services/auth.py:436-437) once every session was ended (__mock.revoked).
  if (method === 'POST' && path === '/auth/refresh') {
    if (window.__mock.revoked) return R(401, { detail: 'Invalid or expired refresh token' });
    window.__refreshes = (window.__refreshes || 0) + 1;
    return R(200, { access_token: 'boot-test-token-' + window.__refreshes, refresh_token: 'r' + window.__refreshes, token_type: 'bearer' });
  }
  return null;
}
function _logRequest(method, full, opts) {
  const sig = opts && opts.signal;
  let body = opts && opts.body;
  if (typeof body === 'string') { try { body = JSON.parse(body); } catch (e) {} }
  const entry = { method, url: full, hadSignal: !!sig, abortedAtSend: !!(sig && sig.aborted), body: body === undefined ? null : body };
  window.__reqLog.push(entry);
  // journeys.mjs exposes __recordReq on pages that navigate away (sign-in, sign-out), so the
  // request survives the navigation.
  try { if (typeof window.__recordReq === 'function') window.__recordReq(JSON.parse(JSON.stringify(entry))); } catch (e) {}
}
const STATUS_TEXT = { 200: 'OK', 201: 'Created', 202: 'Accepted', 204: 'No Content', 400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden', 404: 'Not Found', 405: 'Method Not Allowed', 409: 'Conflict', 422: 'Unprocessable Content', 428: 'Precondition Required', 429: 'Too Many Requests', 500: 'Internal Server Error' };
function _mockFetch(resolve) {
  return async (u, o) => {
    const opts = o || {}; const sig = opts.signal;
    const method = (opts.method || 'GET').toUpperCase();
    const full = String(u).replace(/^https?:\/\/[^/]+/, '');
    const [path, query = ''] = full.split('?');
    _logRequest(method, full, opts);
    let parsed = opts.body; if (typeof parsed === 'string') { try { parsed = JSON.parse(parsed); } catch (e) {} }
    const over = window.__mock.over[method + ' ' + path];
    if (over && over.once) delete window.__mock.over[method + ' ' + path];
    let res = over ? R(over.status, over.body) : resolve(method, path, query, parsed, opts);
    if (!res || res.__mockStatus === undefined) res = R(200, res);
    const err = () => new DOMException('The user aborted a request.', 'AbortError');
    if (sig && sig.aborted) throw err();
    const delay = /__slow/.test(String(u)) ? 300 : (Number(window.__mock.delay) || 0);
    await new Promise((ok, rej) => { const t = setTimeout(ok, delay); if (sig) sig.addEventListener('abort', () => { clearTimeout(t); rej(err()); }, { once: true }); });
    const status = res.__mockStatus, body = res.body;
    return { ok: status >= 200 && status < 300, status, statusText: STATUS_TEXT[status] || '', headers: { get: () => null },
      json: async () => { if (body === null || body === undefined) throw new SyntaxError('Unexpected end of JSON input'); return JSON.parse(JSON.stringify(body)); },
      text: async () => (body === null || body === undefined ? '' : JSON.stringify(body)) };
  };
}
`;

function mockBlock() {
  // Injected verbatim into the page <head>; runs before every script of the page.
  return `
<script>
// ── Enriched mock backend (test harness — NOT committed) ──────────────────────
// Every load starts from a clean browser: a pair an earlier run stored after a refresh
// (with its commit tag) must not outlive a reload of the harness.
localStorage.clear();
localStorage.setItem('sol_token','boot-test-token');
localStorage.setItem('sol_refresh','r');
const SEED = ${JSON.stringify(seed())};
// The first-run guide has been seen by the seeded member, so it does not sit over the
// journeys; the guide's own journey removes this mark.
try { localStorage.setItem('sol_guide_seen:' + SEED.user.id, '1'); } catch (e) {}
${MOCK_SHARED}
function _memberRoute(method, path, query, body) {
  const pub = _publicRoute(method, path, query, body);
  if (pub) return pub;
  if (method !== 'GET') {
    if (/^\\/feed\\/[^/]+\\/like$/.test(path)) return { liked: method === 'POST', like_count: method === 'POST' ? 1 : 0 };
    if (path === '/subscriptions/checkout') return { checkout_url: 'about:blank#mock-checkout' };
    if (path === '/payments/initiate') return { checkout_url: 'about:blank#mock-pay', status: 'PENDING' };
    if (path === '/goals' && method === 'POST') return SEED.goals[0];
    if (/^\\/catalog\\/[^/]+\\/join$/.test(path)) return { id: path.split('/')[2], members: [{ user_id: SEED.user.id, position: 5, status: 'ACTIVE' }] };
    if (path === '/participation/checkout') return { checkout_url: 'about:blank#mock-participation-checkout' };
    if (path === '/participation/cancel') return {};
    if (path === '/admin/circles' && method === 'POST') return { id: 'e5e5e5e5-5555-4555-8555-e5e5e5e5e5e5', name: 'New circle', status: 'DRAFT' };
    if (/^\\/admin\\/circles\\/[^/]+\\/close$/.test(path)) return {};
    if (/^\\/admin\\/circles\\/[^/]+$/.test(path) && method === 'PATCH') return { id: path.split('/')[3] };
    // POST /auth/resend-verification: A33 only (A33 api/auth.py:127-143): 202 sent, or 200
    // {"already_verified": true}; 3/hour per member. 404 on BASE.
    if (path === '/auth/resend-verification' && method === 'POST') {
      if (!window.__mock.a33) return NOT_FOUND();
      return SEED.user.email_verified_at ? R(200, { already_verified: true }) : R(202, { already_verified: false, detail: 'Verification email sent' });
    }
    // PATCH /account/profile {full_name?, phone?, avatar_url?}, extra keys forbidden -> 200
    // {id, email, full_name, phone, avatar_url} (BASE api/account.py:36-41, 54-61, 72-84).
    if (path === '/account/profile' && method === 'PATCH') {
      for (const k of Object.keys(body || {})) if (!['full_name', 'phone', 'avatar_url'].includes(k)) return EXTRA(k);
      if (typeof body.full_name === 'string') SEED.user.full_name = body.full_name;
      return { id: SEED.user.id, email: SEED.user.email, full_name: SEED.user.full_name, phone: SEED.user.phone, avatar_url: null };
    }
    // PATCH /account/settings {locale?, dark_mode?, preferences?}, extra keys forbidden; the
    // merge is shallow at the top level (BASE api/account.py:44-51, 95-125). S35 adds
    // ai_assistant_consent (StrictBool) at the top level (S35 api/account.py:60, 142-145).
    if (path === '/account/settings' && method === 'PATCH') {
      const allowed = ['locale', 'dark_mode', 'preferences'].concat(window.__mock.s35 ? ['ai_assistant_consent'] : []);
      for (const k of Object.keys(body || {})) if (!allowed.includes(k)) return EXTRA(k);
      const prefs = Object.assign({}, SEED.settings.preferences, body.preferences || {});
      if (typeof body.dark_mode === 'boolean') prefs.dark_mode = body.dark_mode;
      if (typeof body.ai_assistant_consent === 'boolean') prefs.ai_assistant_consent = body.ai_assistant_consent;
      SEED.settings.preferences = prefs;
      return _settingsOut();
    }
    // 2FA (BASE api/auth.py:167-232; services/auth.py:275-412).
    if (path === '/auth/2fa/setup' && method === 'POST') {
      if (SEED.user.totp_enabled) return R(409, { detail: '2FA already enabled' });
      return { secret: 'JBSWY3DPEHPK3PXP', otpauth_url: 'otpauth://totp/WheellsVerse%20Sol:member%40example.invalid?secret=JBSWY3DPEHPK3PXP&issuer=WheellsVerse%20Sol', qr_data_url: QR };
    }
    if (path === '/auth/2fa/activate' && method === 'POST') {
      if (!body || typeof body.code !== 'string' || body.code.length !== 6) return R(422, { detail: [{ type: 'string_too_short', loc: ['body', 'code'], msg: 'String should have at least 6 characters' }] });
      SEED.user.totp_enabled = true; SEED.user.totp_backup_codes_remaining = 10;
      return { detail: '2FA enabled', backup_codes: BACKUP };
    }
    // POST /auth/2fa/backup-codes/regenerate {password, code} (TotpDisableRequest: password str,
    // code 6..6; BASE api/auth.py:162-164, 205-218) -> 200 {"detail": "Backup codes regenerated",
    // "backup_codes": [10 new codes]}; 400 "2FA not enabled", 401 "Invalid password" or "Invalid
    // code" (BASE services/auth.py:326-345; a journey sets the 401s with __mockSet). The old codes
    // stop working; no session is ended. PR #35 has the same route (S35 api/auth.py:211-224).
    if (path === '/auth/2fa/backup-codes/regenerate' && method === 'POST') {
      if (!body || typeof body.password !== 'string') return R(422, { detail: [{ type: 'missing', loc: ['body', 'password'], msg: 'Field required' }] });
      if (typeof body.code !== 'string' || body.code.length !== 6) return R(422, { detail: [{ type: 'string_too_short', loc: ['body', 'code'], msg: 'String should have at least 6 characters' }] });
      if (!SEED.user.totp_enabled) return R(400, { detail: '2FA not enabled' });
      SEED.user.totp_backup_codes_remaining = 10;
      return { detail: 'Backup codes regenerated', backup_codes: BACKUP_NEW };
    }
    // Turning 2FA off ends every refresh session (BASE services/auth.py:412): refresh then answers 401.
    if (path === '/auth/2fa/disable' && method === 'POST') {
      if (!SEED.user.totp_enabled) return R(400, { detail: '2FA not enabled' });
      SEED.user.totp_enabled = false;
      window.__mock.revoked = true;
      return { detail: '2FA disabled' };
    }
    // POST /account/close: A33 only (A33 api/account.py:63-70, 180-205; services/
    // account_lifecycle.py:249-264, 491-555). 404 on BASE.
    if (path === '/account/close' && method === 'POST') {
      if (!window.__mock.a33) return NOT_FOUND();
      return CLOSE_SUMMARY(5);
    }
    return {};
  }
  if (path === '/auth/me') return SEED.user;
  if (path === '/groups') return /status=FORMING/.test(query) ? SEED.groupsForming : SEED.groupsActive;
  if (/^\\/groups\\/[^/]+\\/my-payments$/.test(path)) return SEED.payments;
  if (/^\\/groups\\/[^/]+$/.test(path)) { const gid = path.split('/')[2]; return (SEED.groupsForming[0] && gid === SEED.groupsForming[0].id) ? SEED.groupsForming[0] : SEED.groupsActive[0]; }
  if (path === '/goals') return SEED.goals;
  if (/^\\/goals\\/[^/]+$/.test(path)) return SEED.goals[0];
  if (path === '/notifications') return SEED.notifications;
  if (path === '/subscriptions/me') return SEED.subscription;
  if (path === '/subscriptions/invoices') return SEED.invoices;
  if (path === '/bank/list') return SEED.bank;
  if (path === '/trust/me') return SEED.trust;
  if (path === '/timeline/me') return SEED.timeline;
  if (path === '/payments/my') return SEED.payments;
  if (path === '/payments/my-payouts') return SEED.payouts;
  if (path === '/feed') return /offset=0/.test(query) || !/offset=/.test(query) ? SEED.feed : [];
  if (/^\\/feed\\/[^/]+\\/comments$/.test(path)) return SEED.comments;
  if (path === '/kyc/submit') return { kyc_status: 'VERIFIED' };
  if (path === '/catalog') return SEED.catalog;
  if (/^\\/catalog\\/[^/]+\\/eligibility$/.test(path)) return SEED.eligibility;
  if (/^\\/catalog\\/[^/]+$/.test(path)) { const cid = path.split('/')[2]; return SEED.catalog.find(c => c.id === cid) || SEED.catalog[0]; }
  if (path === '/participation/me') return SEED.participation;
  if (path === '/admin/circles') return SEED.adminCircles;
  if (/^\\/admin\\/circles\\/[^/]+\\/participants$/.test(path)) return SEED.adminParticipants;
  // GET /account/settings (BASE api/account.py:64-69, 87-92); S35 adds ai_assistant_consent
  // (S35 api/account.py:76-83).
  if (path === '/account/settings') return _settingsOut();
  // GET /account/export: A33 only (A33 api/account.py:164-175; services/account_lifecycle.py:98-244). 404 on BASE.
  if (path === '/account/export') {
    if (!window.__mock.a33) return NOT_FOUND();
    return { format_version: 1, generated_at: '2026-11-23T12:00:00+00:00', profile: { email: SEED.user.email, full_name: SEED.user.full_name }, settings: _settingsOut(), kyc: { status: 'VERIFIED' }, bank_accounts: [], circle_memberships: [], payments: [], payouts: [], notifications: [], notifications_truncated: false, subscriptions: [], devices: [] };
  }
  return [];
}
// The 200 body of POST /account/close: PR #33's lists (A33 services/account_lifecycle.py:491-555),
// for a retention period of \`years\` (ACCOUNT_RECORD_RETENTION_YEARS, 5 by default).
function CLOSE_SUMMARY(years) {
  const kept = (item, description) => ({ item, description, retention_years: years });
  return { closed: true, user_id: SEED.user.id, closed_at: '2026-11-23T12:00:00+00:00',
    removed: [
      { item: 'email', description: 'Your email address, replaced with a placeholder.' },
      { item: 'name', description: 'Your name, replaced with "Closed account".' },
      { item: 'phone', description: 'Your phone number.' },
      { item: 'profile', description: 'Date of birth, avatar, language and settings.' },
      { item: 'password', description: 'Your password; signing in is no longer possible.' },
      { item: 'two_factor', description: 'Two-factor secret and backup codes.' },
      { item: 'sessions', description: 'Every session revoked, with the IP address and device description it recorded; refresh tokens and pending email links stop working.' },
      { item: 'bank_references', description: 'Encrypted bank references; bank accounts deactivated.' },
      { item: 'devices', description: 'Registered devices revoked and their tokens erased.' },
      { item: 'notifications', description: 'Your in-app notifications.' },
      { item: 'goals', description: 'Your savings goals.' },
      { item: 'waitlist', description: 'Waiting circle reservations cancelled.' },
      { item: 'waitlist_signup', description: 'Your pre-launch waitlist signup under your old email address (email, name and IP address), if you had one.' },
    ],
    kept: [
      kept('payments', 'Your contributions and their status.'),
      kept('payouts', 'Payouts made to you.'),
      kept('ledger', 'Ledger entries and fees for those payments and payouts.'),
      kept('circle_memberships', 'Which circles you were in, and when.'),
      kept('bank_accounts', "Bank name, account type, last 4 digits and the bank provider's account reference."),
      kept('identity_verification', 'KYC status and the verification provider reference.'),
      kept('subscriptions', 'Plan and invoice history.'),
      kept('provider_references', "The payment, identity-verification and billing providers' references to you, so those records can be reconciled and closed."),
      kept('provider_event_log', 'Notifications those providers sent about your account, stored as received; they can include your name or email address.'),
      kept('fraud_review', 'Fraud-review flags about this account, including the normalised email or phone number they matched on.'),
      kept('account_record', 'Account id, creation and closing dates, payment counts.'),
      kept('audit_log', 'The audit trail, including this closure.'),
      kept('community_posts', 'Messages and posts you wrote in shared circle spaces.'),
    ],
    retention: { years, until: (2026 + years) + '-11-23', note: 'Money records are kept for ' + years + ' years after closing for financial record-keeping. This period is pending legal review.' } };
}
window.__closeSummary = CLOSE_SUMMARY;
function _settingsOut() {
  const prefs = SEED.settings.preferences || {};
  const out = { locale: SEED.settings.locale, preferences: prefs, dark_mode: !!prefs.dark_mode };
  if (window.__mock.s35) out.ai_assistant_consent = prefs.ai_assistant_consent === true;
  return out;
}
window.fetch = _mockFetch(_memberRoute);
</script>
`;
}

// The mock for the pages that run without a session (index.html, reset-password.html,
// verify.html). Pass it to page.addInitScript({ content }) so it runs before the page's own
// scripts. `flags` presets __mock (e.g. { c34: true }); `over` presets route overrides.
export function publicMockScript({ flags = {}, over = {} } = {}) {
  return `
window.__mock = ${JSON.stringify({ ...flags, over })};
${MOCK_SHARED}
window.fetch = _mockFetch((method, path, query, body) => _publicRoute(method, path, query, body) || R(404, { detail: 'Not Found' }));
`;
}

// Write boot-test.html from the current app.html + mock. Returns the file path.
export function generateHarness() {
  const appHtml = readFileSync(join(SOL, 'app.html'), 'utf8');
  // The mock goes into <head>, so it runs before every script of the page (all of them are
  // in <body>) and its SEED (raw ids such as "u2") is never part of document.body. The
  // privacy checks of journeys.mjs scan document.body.innerHTML for raw ids: with the mock
  // in <body> they matched the mock's own SEED, not the member markup.
  const marker = '</head>';
  if (appHtml.split(marker).length !== 2) throw new Error('app.html must have exactly one </head>');
  let out = appHtml.replace(marker, mockBlock() + marker);
  // Cache-bust every /sol/app asset so a static server with no cache headers
  // can't serve a stale module across edits.
  const v = Date.now();
  out = out.replace(/(src|href)="(\/sol\/app\/[^"]+?)"/g, `$1="$2?v=${v}"`);
  writeFileSync(HARNESS_PATH, out, 'utf8');
  return HARNESS_PATH;
}

// Allow running directly: node harness.mjs
if (import.meta.url === `file://${process.argv[1]}`) {
  const p = generateHarness();
  console.log('wrote', p);
}
