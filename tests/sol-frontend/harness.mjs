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
    user: { id: U, email: 'test@sol.app', full_name: 'Test User', kyc_status: 'VERIFIED', account_status: 'ACTIVE' },
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
  };
}

function mockBlock() {
  // Injected verbatim into the page <head>; runs before the module scripts.
  return `
<script>
// ── Enriched mock backend (test harness — NOT committed) ──────────────────────
localStorage.setItem('sol_token','boot-test-token');
localStorage.setItem('sol_refresh','r');
const SEED = ${JSON.stringify(seed())};
window.__errs = [];
window.addEventListener('error', e => window.__errs.push(String(e.message || e.error)));
window.addEventListener('unhandledrejection', e => window.__errs.push('unhandledrejection: ' + String(e.reason)));
window.__reqLog = [];
function _mockResolve(rawUrl, opts) {
  const method = ((opts && opts.method) || 'GET').toUpperCase();
  const full = String(rawUrl).replace(/^https?:\\/\\/[^/]+/, '');
  const [path, query = ''] = full.split('?');
  const sig = opts && opts.signal;
  window.__reqLog.push({ method, url: full, hadSignal: !!sig, abortedAtSend: !!(sig && sig.aborted) });
  if (method !== 'GET') {
    if (/^\\/feed\\/[^/]+\\/like$/.test(path)) return { liked: method === 'POST', like_count: method === 'POST' ? 1 : 0 };
    if (path === '/subscriptions/checkout') return { checkout_url: 'about:blank#mock-checkout' };
    if (path === '/payments/initiate') return { checkout_url: 'about:blank#mock-pay', status: 'PENDING' };
    if (path === '/goals' && method === 'POST') return SEED.goals[0];
    if (/^\\/catalog\\/[^/]+\\/join$/.test(path)) return { id: path.split('/')[2], members: [{ user_id: SEED.user.id, position: 5, status: 'ACTIVE' }] };
    if (path === '/participation/checkout') return { checkout_url: 'about:blank#mock-participation-checkout' };
    if (path === '/participation/cancel') return {};
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
  if (path === '/feed') return /offset=0/.test(query) || !/offset=/.test(query) ? SEED.feed : [];
  if (/^\\/feed\\/[^/]+\\/comments$/.test(path)) return SEED.comments;
  if (path === '/kyc/submit') return { kyc_status: 'VERIFIED' };
  if (path === '/catalog') return SEED.catalog;
  if (/^\\/catalog\\/[^/]+\\/eligibility$/.test(path)) return SEED.eligibility;
  if (/^\\/catalog\\/[^/]+$/.test(path)) { const cid = path.split('/')[2]; return SEED.catalog.find(c => c.id === cid) || SEED.catalog[0]; }
  if (path === '/participation/me') return SEED.participation;
  return [];
}
window.fetch = async (u, o) => {
  const opts = o || {}; const sig = opts.signal;
  const body = _mockResolve(u, opts);
  const err = () => new DOMException('The user aborted a request.', 'AbortError');
  if (sig && sig.aborted) throw err();
  const delay = /__slow/.test(String(u)) ? 300 : 0;
  await new Promise((res, rej) => { const t = setTimeout(res, delay); if (sig) sig.addEventListener('abort', () => { clearTimeout(t); rej(err()); }, { once: true }); });
  return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) };
};
</script>
`;
}

// Write boot-test.html from the current app.html + mock. Returns the file path.
export function generateHarness() {
  const appHtml = readFileSync(join(SOL, 'app.html'), 'utf8');
  const marker = '<script src="/sol/app/core/state.js"></script>';
  if (!appHtml.includes(marker)) throw new Error('state.js script tag not found in app.html');
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
