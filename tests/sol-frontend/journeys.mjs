// SOL member app — authenticated browser regression journeys (Playwright).
//
// Requires playwright (NOT a shipped dependency — the frontend stays buildless):
//   npm i -D playwright && npx playwright install chromium
//   node frontend/sol/app/tests/journeys.mjs
//
// Self-contained: starts a static server rooted at frontend/, generates the
// mock-backed harness (see harness.mjs), drives real Chromium through the
// primary member journeys, and asserts render + money-format + privacy +
// dialog/guard + P3 cancellation + P4 circle-detail. No real backend/auth/PII.
//
// Also: the member account pages (forgot and reset password, email verification, the
// Settings page, the first-run guide, consent at sign-up, payout history) against the
// deployed base and the draft PR shapes, and automated accessibility checks (labels,
// names, one h1, landmarks, tabindex, alt text, aria-current, Tab order, focus after
// navigation) on every page visited. Requests to deployed hosts are blocked.
//
// NOTE: the real Sol backend is a separate repo, so this runs against the
// enriched mock. A real-backend authenticated E2E remains a future addition.
// The port is 8891 unless SOL_JOURNEYS_PORT is set (to run beside another copy).
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join, normalize } from 'node:path';
import { generateHarness, HARNESS_URL_PATH, IDS, publicMockScript } from './harness.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = join(HERE, '..', '..', 'frontend');   // repo/frontend
const PORT = Number(process.env.SOL_JOURNEYS_PORT) || 8891;
const MIME = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css', '.json': 'application/json', '.svg': 'image/svg+xml' };

let failures = 0;
const T = (name, cond) => { if (cond) console.log('  ✓', name); else { failures++; console.log('  ✗ FAIL:', name); } };

async function main() {
  let chromium;
  try { ({ chromium } = await import('playwright')); }
  catch { console.error('playwright not installed — run: npm i -D playwright && npx playwright install chromium'); process.exit(2); }

  generateHarness();

  const server = createServer(async (req, res) => {
    try {
      const path = decodeURIComponent(req.url.split('?')[0]);
      const file = normalize(join(FRONTEND, path));
      if (!file.startsWith(FRONTEND)) { res.writeHead(403).end(); return; }
      const body = await readFile(file);
      const ext = file.slice(file.lastIndexOf('.'));
      res.writeHead(200, { 'Content-Type': MIME[ext] || 'application/octet-stream' }).end(body);
    } catch { res.writeHead(404).end(); }
  });
  await new Promise(r => server.listen(PORT, r));

  const browser = await chromium.launch();
  const context = await browser.newContext({ acceptDownloads: true });
  // Safety net: nothing may reach a deployed environment. The pages call fetch(), which the
  // mock replaces; anything else to these hosts is aborted and counted.
  const leaks = [];
  await context.route(/^https?:\/\/(sol-api-production\.up\.railway\.app|([^/]*\.)?wheellsverse\.com)(\/|$)/, r => { leaks.push(r.request().url()); return r.abort(); });
  await context.route(/^https?:\/\/fonts\.(googleapis|gstatic)\.com\//, r => r.fulfill({ status: 200, contentType: 'text/css', body: '' }));
  const page = await context.newPage();
  const consoleErrors = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text()); });
  await page.goto(`http://localhost:${PORT}${HARNESS_URL_PATH}`);

  // Journeys A–J: each route renders real-shape data; privacy + money format hold.
  const A = await page.evaluate(async (IDS) => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const view = () => document.body.innerText;
    const has = s => view().includes(s);
    const out = {};
    window.nav('dashboard'); await sleep(150); out.A_dashboard = has('Family Savings Circle');
    window.nav('kyc'); await sleep(120); out.B_kyc = /verif/i.test(view());
    window.nav('bank'); await sleep(120); out.C_bank_last4 = has('4321'); out.C_bank_noRawId = !document.body.innerHTML.includes(IDS.BANK);
    window.nav('discover'); await sleep(150); out.D_discover = has('New Year Circle');
    window.nav('timeline'); await sleep(120); out.E_timeline = has('Family Savings Circle');
    window.nav('premium'); await sleep(150); out.F_premium = has('14.99') || /premium/i.test(view());
    window.nav('goals'); await sleep(150); out.G_goals = has('Emergency fund') && has('40');
    window.nav('notifications'); await sleep(150); out.H_notifs = has('Contribution') || has('due');
    window.nav('community'); await sleep(180); out.I_community = has('Grateful') || has('first circle'); out.I_noRawUser = !document.body.innerHTML.includes('"u2"');
    window.nav('trust'); await sleep(120); out.J_trust = /720|score|badge/i.test(view());
    return out;
  }, IDS);
  Object.entries(A).forEach(([k, v]) => T('journey ' + k, v === true));

  // Dialogs (SolDialog) + guards (SolGuard) + P3 cancellation + P4 circle-detail.
  const B = await page.evaluate(async (IDS) => {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
    const esc = () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    const o = {};
    // dialog open/trap/Escape resets page state
    window.nav('goals'); await sleep(80);
    window.openGoalDialog('goalFormDialog', '#gfName'); await sleep(70);
    o.dialogOpen = window.SolDialog.isOpen('goalFormDialog');
    o.dialogFocus = document.activeElement && document.activeElement.id === 'gfName';
    esc(); await sleep(60);
    o.dialogEscClosed = !window.SolDialog.isOpen('goalFormDialog');
    // guard duplicate-drop
    const k = 'test:probe';
    o.guardDrop = window.SolGuard.acquire(k) === true && window.SolGuard.acquire(k) === false; window.SolGuard.release(k);
    // P3: GET carries a signal, mutation does NOT (money-safety), in-flight GET aborts on nav
    window.__reqLog.length = 0; window.nav('goals'); await sleep(120);
    o.getHasSignal = !!window.__reqLog.find(r => r.method === 'GET' && r.url.startsWith('/goals') && r.hadSignal);
    window.__reqLog.length = 0; await api('/goals', { method: 'POST', body: '{}' });
    o.mutationNoSignal = window.__reqLog.find(r => r.method === 'POST')?.hadSignal === false;
    const slow = api('/__slow/x').then(() => 'resolved').catch(e => _aborted(e) ? 'aborted' : 'err');
    await sleep(20); window.nav('trust'); o.abortsOnNav = (await slow) === 'aborted';
    // P4: circle-detail member view money math + no legacy badge
    await window.showGroup(IDS.G_ACT); await sleep(150);
    const h = document.getElementById('groupDetail').innerHTML, t = document.getElementById('groupDetail').innerText;
    o.p4_money = t.includes('$200.00') && t.includes('$1,080.00') && t.includes('10%');
    o.p4_noLegacyBadge = !h.includes('badge-gold');
    o.p4_usesClasses = h.includes('cdetail__head') && h.includes('fig-val');
    // Applied-style check (not just class presence): the figures block must pick
    // up the design-system fig treatment — regresses if .fig-label/.fig-val are
    // only scoped to .circle-card__figs and not extended to .cdetail__figs.
    const figLabel = document.querySelector('#groupDetail .cdetail__figs .fig-label');
    o.p4_figStyled = !!figLabel && getComputedStyle(figLabel).textTransform === 'uppercase';
    o.p4_noPII = !h.includes(IDS.U) && !h.includes('"u2"');
    return o;
  }, IDS);
  Object.entries(B).forEach(([k, v]) => T(k, v === true));

  const allConsole = [];
  page.on('console', m => allConsole.push(m.text()));
  await memberPages(page);
  await accessibility(page);

  const errs = await page.evaluate(() => window.__errs || []);
  T('no page errors captured', errs.length === 0);
  if (errs.length) console.log('    page errors:', JSON.stringify(errs.slice(0, 5)));
  await keyboardFromTop(page);
  await closeAccountSignsOut(browser, leaks);
  await publicPages(browser, leaks);
  // Secrets shown on the Settings page (2FA secret, backup codes) never reach the console.
  T('no 2FA secret or backup code in the console', !allConsole.some(t => SECRETS.some(x => t.includes(x))));
  T('no console errors', consoleErrors.length === 0);
  if (consoleErrors.length) console.log('    console errors:', JSON.stringify(consoleErrors.slice(0, 5)));
  T('no request reached a deployed host', leaks.length === 0);

  await browser.close();
  await new Promise(r => server.close(r));
  console.log(`\n${failures ? '✗ ' + failures + ' FAILURE(S)' : '✓ all journeys passed'}`);
  process.exit(failures ? 1 : 0);
}

// ════ Member account pages and accessibility (items 3 and 6) ═══════════════════
// Synthetic values the mock returns (harness.mjs). None may be stored, logged or kept in
// the address bar.
const SECRETS = ['JBSWY3DPEHPK3PXP', 'a1b2-c3d4-e5', 'synthetic-challenge-token'];
const RESET_TOKEN = 'synthetic-reset-Tok3n_0123456789abcdefABCDEF';
const VERIFY_TOKEN = 'synthetic-verify-Tok3n_0123456789abcdefABCDEF';

// Requests to a path, and POSTs to /auth/refresh, in a request log (helpers().reqs()).
const countOf = (rs, url) => rs.filter(r => r.url === url).length;
const refreshCount = rs => rs.filter(r => r.url === '/auth/refresh' && r.method === 'POST').length;
// Runs in the journey page: the access token becomes a JWT-shaped synthetic token of the seeded
// member that expires in `seconds` (the harness token has no expiry, which reads as "expires soon").
function SET_TOKEN(seconds) {
  const b64 = o => btoa(JSON.stringify(o)).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
  token = b64({ alg: 'none' }) + '.' + b64({ sub: SEED.user.id, exp: Math.floor(Date.now() / 1000) + seconds }) + '.synthetic';
}

// The accessibility-tree node of the first element matching `sel` (Chromium, over CDP): whether
// it is in the tree (not ignored, e.g. display:none) and its role.
async function axNode(page, sel) {
  let cdp;
  try {
    cdp = await page.context().newCDPSession(page);
    const { root } = await cdp.send('DOM.getDocument', { depth: 0 });
    const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector: sel });
    if (!nodeId) return { inTree: false, role: null };
    const { node } = await cdp.send('DOM.describeNode', { nodeId });
    const { nodes } = await cdp.send('Accessibility.getPartialAXTree', { backendNodeId: node.backendNodeId, fetchRelatives: false });
    const n = (nodes || []).find(x => x.backendDOMNodeId === node.backendNodeId) || (nodes || [])[0];
    return { inTree: !!n && !n.ignored, role: n && n.role ? n.role.value : null };
  } catch (e) { return { inTree: false, role: null, error: String(e) }; }
  finally { if (cdp) await cdp.detach().catch(() => {}); }
}

// page.evaluate that reads as false (a failed check) instead of throwing when an element is missing.
async function ev(pg, fn, arg) { try { return await pg.evaluate(fn, arg); } catch { return false; } }
const exactKeys = (o, keys) => !!o && typeof o === 'object' && !Array.isArray(o) && JSON.stringify(Object.keys(o).sort()) === JSON.stringify([...keys].sort());
function helpers(page) {
  const wait = ms => page.waitForTimeout(ms);
  const vis = sel => page.evaluate(s => { const e = document.querySelector(s); return !!(e && (e.offsetWidth || e.offsetHeight || e.getClientRects().length) && getComputedStyle(e).visibility !== 'hidden'); }, sel);
  const text = sel => page.evaluate(s => { const e = document.querySelector(s); return e ? (e.innerText || e.textContent || '') : ''; }, sel);
  const click = async sel => { if (!(await vis(sel))) return false; try { await page.click(sel, { timeout: 2000 }); return true; } catch { return false; } };
  const fill = async (sel, v) => { if (!(await vis(sel))) return false; try { await page.fill(sel, v, { timeout: 2000 }); return true; } catch { return false; } };
  const reqs = () => page.evaluate(() => (window.__reqLog || []).map(r => ({ method: r.method, url: r.url, body: r.body, hadSignal: r.hadSignal })));
  const clearReqs = () => page.evaluate(() => { if (window.__reqLog) window.__reqLog.length = 0; });
  const alertText = scope => page.evaluate(sc => [...document.querySelectorAll(sc + ' [role=alert]')].map(e => (e.offsetParent !== null ? e.textContent : '')).join('').trim(), scope);
  return { wait, vis, text, click, fill, reqs, clearReqs, alertText };
}

// The accessibility checks of item 6c, run inside a page. mode 'app' = the member app (the
// active page is the scope; the nav item has aria-current); 'doc' = a standalone page.
function auditPage(mode) {
  const txt = el => (el.textContent || '').replace(/\s+/g, ' ').trim();
  const byId = id => document.getElementById(id);
  const nameOf = el => {
    const lb = el.getAttribute('aria-labelledby');
    if (lb) { const t = lb.split(/\s+/).map(id => (byId(id) ? txt(byId(id)) : '')).join(' ').trim(); if (t) return t; }
    const al = (el.getAttribute('aria-label') || '').trim(); if (al) return al;
    const t = txt(el); if (t) return t;
    const img = el.querySelector('img[alt]'); if (img && img.alt.trim()) return img.alt.trim();
    return (el.getAttribute('title') || '').trim();
  };
  const labelled = el => {
    if ((el.getAttribute('aria-label') || '').trim()) return true;
    const lb = el.getAttribute('aria-labelledby');
    if (lb && lb.split(/\s+/).some(id => byId(id) && txt(byId(id)))) return true;
    if (el.id && [...document.querySelectorAll('label')].some(l => l.htmlFor === el.id && txt(l))) return true;
    const wrap = el.closest('label'); return !!(wrap && txt(wrap));
  };
  const desc = el => el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/)[0] : '');
  const active = mode === 'app' ? document.querySelector('.page.active') : document.body;
  // App: the active page, the shell (header, navs, skip link) and any open dialog outside the pages.
  const scopes = mode === 'app'
    ? [active, ...document.querySelectorAll('body > header, body > nav, body > .skip-link, body > [role=dialog].is-open, body > [role=dialog].open')].filter(Boolean)
    : [document.body];
  const within = sel => scopes.flatMap(sc => [...sc.querySelectorAll(sel)].concat(sc.matches && sc.matches(sel) ? [sc] : []));
  const out = {};
  out.unlabeled = within('input,select,textarea').filter(e => e.type !== 'hidden' && !labelled(e)).map(desc);
  out.unnamed = within('button,a[href],[role=button]').filter(e => !nameOf(e)).map(desc);
  const h1s = mode === 'app' ? (active ? active.querySelectorAll('h1').length : 0) : document.querySelectorAll('h1').length;
  const strayH1 = mode === 'app' ? [...document.querySelectorAll('h1')].filter(h => !h.closest('.page')).length : 0;
  out.h1 = h1s === 1 && strayH1 === 0 ? 'ok' : `h1 in page: ${h1s}, outside pages: ${strayH1}`;
  const banner = [...document.querySelectorAll('header')].some(h => !h.closest('article,aside,main,nav,section')) || !!document.querySelector('[role=banner]');
  const navLabelled = [...document.querySelectorAll('nav')].some(n => (n.getAttribute('aria-label') || '').trim() || n.getAttribute('aria-labelledby'));
  const main = document.querySelectorAll('main').length === 1;
  out.landmarks = banner && navLabelled && main ? 'ok' : `header:${banner} nav(labelled):${navLabelled} main:${main}`;
  out.posTabindex = [...document.querySelectorAll('[tabindex]')].filter(e => parseInt(e.getAttribute('tabindex'), 10) > 0).map(desc);
  out.imgNoAlt = [...document.querySelectorAll('img')].filter(e => !e.hasAttribute('alt')).map(desc);
  if (mode === 'app') {
    const page = active ? active.id.replace(/^page-/, '') : '';
    const navItem = document.querySelector(`.nav-item[data-page="${page}"]`);
    const others = [...document.querySelectorAll('.nav-item[aria-current]')].filter(n => n !== navItem).length;
    out.ariaCurrent = (!navItem || navItem.getAttribute('aria-current') === 'page') && others === 0 ? 'ok' : `current:${navItem && navItem.getAttribute('aria-current')} others:${others}`;
  }
  const bad = Object.entries(out).filter(([, v]) => (Array.isArray(v) ? v.length : v !== 'ok'));
  return { ok: bad.length === 0, problems: Object.fromEntries(bad) };
}
function reportAudit(name, r) {
  T(name, r.ok);
  if (!r.ok) console.log('      ' + JSON.stringify(r.problems).slice(0, 400));
}
// Tab from the top: the skip link, then the nav, and the skip link leads into main.
async function keyboardOrder(page, label, navSel) {
  await page.keyboard.press('Tab');
  const first = await page.evaluate(() => { const a = document.activeElement; return { skip: !!(a && a.matches('a.skip-link[href]')), text: a ? (a.textContent || '').trim() : '' }; });
  T(`6c keyboard ${label}: the first Tab reaches the skip link`, first.skip && /skip/i.test(first.text));
  await page.keyboard.press('Tab');
  T(`6c keyboard ${label}: the next Tab reaches the nav`, await ev(page, s => !!(document.activeElement && document.activeElement.closest(s)), navSel));
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(120);
  T(`6c keyboard ${label}: the skip link moves focus into main`, await ev(page, () => !!(document.activeElement && document.activeElement.closest('main'))));
  await page.keyboard.press('Tab');
  T(`6c keyboard ${label}: Tab then continues in the main content`, await ev(page, () => !!(document.activeElement && document.activeElement.closest('main'))));
}

async function memberPages(page) {
  const { wait, vis, text, click, fill, reqs, clearReqs, alertText } = helpers(page);

  // ── [3c] verify-email banner on the dashboard (GET /auth/me email_verified_at) ──
  await page.evaluate(async () => { window.__mockClear(); SEED.user.email_verified_at = null; me = await api('/auth/me'); window.nav('dashboard'); });
  await wait(300);
  T('3c banner: an unverified member sees a verify-email banner on the dashboard', await vis('#dashVerify .verify-banner'));
  T('3c banner: it offers "Resend email"', await vis('#verifyResend') && /resend email/i.test(await text('#verifyResend')));
  await clearReqs();
  await page.evaluate(() => { const b = document.getElementById('verifyResend'); if (b) { b.click(); b.click(); } });
  await wait(200);
  let rs = (await reqs()).filter(r => r.url === '/auth/resend-verification');
  T('3c banner: Resend sends one POST /auth/resend-verification with no body (a double click is dropped)', rs.length === 1 && rs[0].method === 'POST' && rs[0].body === null);
  T('3c banner (deployed base, 404): the button is hidden and the member is told to contact support', !(await vis('#verifyResend')) && /contact support/i.test(await text('#dashVerify')));
  T('3c banner (404): no error alert and no toast', (await alertText('#dashVerify')) === '' && !(await ev(page, () => !!document.querySelector('.toast'))));
  await page.evaluate(() => { window.__mock.a33 = true; window.nav('dashboard'); });
  await wait(300);
  await click('#verifyResend'); await wait(200);
  T('3c banner (PR #33, 202): "sent" is announced', /sent/i.test(await text('#dashVerify')) && /sent/i.test(await ev(page, () => [...document.querySelectorAll('#dashVerify [role=status], #dashVerify [aria-live]')].map(e => e.textContent).join(' '))));
  await page.evaluate(() => { window.__mockSet('POST /auth/resend-verification', 429, { error: 'Rate limit exceeded: 3 per 1 hour' }); window.nav('dashboard'); });
  await wait(300);
  await click('#verifyResend'); await wait(200);
  T('3c banner (429): "try again later"', /try again later/i.test(await text('#dashVerify')));
  await page.evaluate(async () => { window.__mockClear(); SEED.user.email_verified_at = '2026-01-02T00:00:00Z'; me = await api('/auth/me'); window.nav('dashboard'); });
  await wait(300);
  T('3c banner: a verified member sees no banner', !(await vis('#dashVerify .verify-banner')));

  // ── [3d] Settings ──
  await page.evaluate(() => { window.__mockClear(); window.nav('settings'); });
  await wait(350);
  T('3d settings: nav(\'settings\') opens #page-settings', await ev(page, () => !!document.getElementById('page-settings') && document.getElementById('page-settings').classList.contains('active')));
  T('3d settings: the sidebar has a Settings entry, marked current', await ev(page, () => { const n = document.querySelector('.nav-item[data-page="settings"]'); return !!n && n.getAttribute('aria-current') === 'page'; }));
  T('3d settings: the mobile More sheet lists Settings', await ev(page, () => [...document.querySelectorAll('#moreSheet .more-item')].some(b => /settings/i.test(b.textContent))));
  // Profile: PATCH /account/profile {full_name} (BASE api/account.py:72-84).
  T('3d profile: the name is prefilled', (await page.inputValue('#setName', { timeout: 1000 }).catch(() => null)) === 'Test User');
  // full_name is the name the backend sends to the ID check (BASE services/kyc.py:33) and to the
  // bank provider when the first bank is linked (BASE services/bank.py:110-114) (SECURITY-SEC-4).
  T('SEC-4 profile: the name field is labelled as the full legal name', /full legal name/i.test(await text('label[for="setName"]')) && !/display name/i.test(await text('#setProfile')));
  T('SEC-4 profile: a note tied to the field says it is used for the ID check and the bank link', await ev(page, () => { const i = document.getElementById('setName'); const ids = (i && i.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean); const t = ids.map(id => (document.getElementById(id) || {}).textContent || '').join(' '); return /ID check/i.test(t) && /bank/i.test(t); }));
  T('3d profile: the email is shown read-only, with its verified status', await ev(page, () => { const e = document.getElementById('setEmail'); return !!e && e.tagName !== 'INPUT' && /member@example\.invalid/.test(e.textContent); }) && (await text('#setEmailStatus')).trim() === 'Verified');
  await clearReqs();
  await fill('#setName', '  Alex Example  '); await click('#setNameSave'); await wait(200);
  let pr = (await reqs()).filter(r => r.url === '/account/profile');
  T('3d profile: Save sends PATCH /account/profile with exactly {full_name}, trimmed', pr.length === 1 && pr[0].method === 'PATCH' && exactKeys(pr[0].body, ['full_name']) && pr[0].body.full_name === 'Alex Example');
  T('3d profile: the save is announced in a live region', /saved/i.test(await text('#settingsLive')));
  await clearReqs();
  await fill('#setName', '   '); await click('#setNameSave'); await wait(150);
  T('3d profile: an empty name is refused before any request (never a null full_name)', (await reqs()).filter(r => r.url === '/account/profile').length === 0 && (await text('#setNameErr')).trim().length > 0);
  // Password: no change-password route exists in any tree; offer the reset email instead.
  T('3d password: says changing it here is not available yet', /not available yet/i.test(await text('#setPassword')));
  await clearReqs();
  await click('#setPwReset'); await wait(200);
  let fp = (await reqs()).filter(r => r.url === '/auth/forgot-password');
  T('3d password: "Email me a reset link" sends POST /auth/forgot-password with exactly {email}', fp.length === 1 && exactKeys(fp[0].body, ['email']) && fp[0].body.email === 'member@example.invalid');
  // Two-factor (BASE api/auth.py:167-232).
  T('3d two-factor: the status reads Off', (await text('#set2faState')).trim() === 'Off');
  await clearReqs();
  await click('#set2faStart'); await wait(250);
  T('3d two-factor: setup calls POST /auth/2fa/setup', (await reqs()).some(r => r.url === '/auth/2fa/setup' && r.method === 'POST'));
  T('3d two-factor: the secret is shown as text for manual entry', /JBSW\s?Y3DP\s?EHPK\s?3PXP/.test(await text('#set2faSecret')));
  T('3d two-factor: a 6-digit code field with a label', await ev(page, () => { const i = document.getElementById('set2faCode'); return !!i && !!document.querySelector('label[for="set2faCode"]'); }));
  await fill('#set2faCode', '123456'); await click('#set2faConfirm'); await wait(250);
  const act = (await reqs()).filter(r => r.url === '/auth/2fa/activate');
  T('3d two-factor: confirm sends POST /auth/2fa/activate with exactly {code}', act.length === 1 && exactKeys(act[0].body, ['code']) && act[0].body.code === '123456');
  T('3d two-factor: the 10 backup codes are shown', (await ev(page, () => document.querySelectorAll('#set2faCodes li').length)) === 10);
  T('3d two-factor: with a copy button and a warning to store them', await vis('#set2faCopyCodes') && /(store|save|keep).{0,40}(safe|somewhere)/i.test(await text('#setTwoFactor')));
  T('3d two-factor: the secret is gone from the page once confirmed', await ev(page, () => { const ps = document.getElementById('page-settings'); return !!ps && !ps.innerHTML.includes('JBSWY3DPEHPK3PXP'); }));
  T('3d two-factor: secret and codes are never stored or put in the address bar', await ev(page, s => { const all = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage }) + location.href; return !s.some(x => all.includes(x)); }, SECRETS));
  await click('#set2faSaved'); await wait(150);
  T('3d two-factor: "I saved my codes" removes them from the page', await ev(page, () => { const ps = document.getElementById('page-settings'); return !!ps && !ps.innerHTML.includes('a1b2-c3d4-e5'); }));
  T('3d two-factor: the status reads On', (await text('#set2faState')).trim() === 'On');
  // A wrong password when turning off: 401 "Invalid password" (BASE services/auth.py:403-404).
  // That is not an expired session: one POST, and no POST /auth/refresh (5 per 15 minutes per
  // IP, BASE api/auth.py:84-86), so the field error shows (CONTRACT-C1, SECURITY-SEC-1).
  await page.evaluate(() => window.__mockSet('POST /auth/2fa/disable', 401, { detail: 'Invalid password' }));
  await clearReqs();
  await fill('#set2faPw', 'synthetic-wrong-password'); await fill('#set2faOffCode', '654321'); await click('#set2faOff'); await wait(300);
  let rq = await reqs();
  T('C1 two-factor off, wrong password: one POST /auth/2fa/disable and no POST /auth/refresh', countOf(rq, '/auth/2fa/disable') === 1 && refreshCount(rq) === 0);
  T('C1 two-factor off, wrong password: says the password is not right', /password is not right/i.test(await alertText('#setTwoFactor')));
  await page.evaluate(() => { delete window.__mock.over['POST /auth/2fa/disable']; });
  // Turn off: {password, code} (BASE api/auth.py:162-164, 221-232).
  await clearReqs();
  await fill('#set2faPw', 'synthetic-password'); await fill('#set2faOffCode', '654321'); await click('#set2faOff'); await wait(250);
  const off = (await reqs()).filter(r => r.url === '/auth/2fa/disable');
  T('3d two-factor: turning off sends POST /auth/2fa/disable with exactly {password, code}', off.length === 1 && exactKeys(off[0].body, ['password', 'code']) && off[0].body.code === '654321');
  T('3d two-factor: then reads Off and says the sessions were signed out', (await text('#set2faState')).trim() === 'Off' && /signed out/i.test(await text('#set2faMsg')));
  // A wrong code: 401 "Invalid code" (BASE services/auth.py:315-316). Turning off ended every
  // refresh session, so the mock's POST /auth/refresh now answers 401: a refresh here would sign
  // the member out. One POST, no refresh, the code error, and the member stays signed in.
  await page.evaluate(() => { window.__mockSet('POST /auth/2fa/activate', 401, { detail: 'Invalid code' }); });
  await click('#set2faStart'); await wait(250);
  await clearReqs();
  await fill('#set2faCode', '000000'); await click('#set2faConfirm'); await wait(400);
  const stayed = await ev(page, () => /boot-test\.html$/.test(location.pathname) && typeof window.nav === 'function');
  rq = stayed ? await reqs() : [];
  T('C1 two-factor on, wrong code right after turning off: the member stays signed in', stayed === true);
  T('C1 two-factor on, wrong code: one POST /auth/2fa/activate and no POST /auth/refresh', stayed === true && countOf(rq, '/auth/2fa/activate') === 1 && refreshCount(rq) === 0);
  if (stayed !== true) {   // signed out (the defect): reload the journey page so the rest still runs
    await page.goto(`http://localhost:${PORT}${HARNESS_URL_PATH}`); await wait(500);
    await page.evaluate(() => { window.__mockSet('POST /auth/2fa/activate', 401, { detail: 'Invalid code' }); window.nav('settings'); }); await wait(300);
    await click('#set2faStart'); await wait(250);
    await fill('#set2faCode', '000000'); await click('#set2faConfirm'); await wait(400);
  }
  T('3d two-factor: a wrong code shows a clear error and no backup codes', /code did not work/i.test(await alertText('#setTwoFactor')) && (await ev(page, () => document.querySelectorAll('#set2faCodes li').length)) === 0);
  // With an access token that is still fresh, the POST is sent straight away: no GET /auth/me first.
  await page.evaluate(SET_TOKEN, 3600);
  await clearReqs();
  await fill('#set2faCode', '111111'); await click('#set2faConfirm'); await wait(300);
  rq = await reqs();
  T('C1 two-factor on, wrong code, fresh token: only the POST (no GET /auth/me, no refresh)', countOf(rq, '/auth/2fa/activate') === 1 && countOf(rq, '/auth/me') === 0 && refreshCount(rq) === 0);
  // A token about to expire is renewed first by an ordinary GET /auth/me (which refreshes the usual
  // way when it must), then the POST is sent once.
  await page.evaluate(SET_TOKEN, 10);
  await clearReqs();
  await fill('#set2faCode', '222222'); await click('#set2faConfirm'); await wait(300);
  rq = (await reqs()).filter(r => ['/auth/me', '/auth/2fa/activate', '/auth/refresh'].includes(r.url));
  T('C1 two-factor on, token about to expire: GET /auth/me, then one POST', JSON.stringify(rq.map(r => r.method + ' ' + r.url)) === JSON.stringify(['GET /auth/me', 'POST /auth/2fa/activate']));
  // A 401 about the token, not the code ("Invalid token", BASE core/deps.py:33-38): the session is
  // renewed once through GET /auth/me and the code is sent once more; two-factor then turns on.
  await page.evaluate(SET_TOKEN, 3600);
  await page.evaluate(() => {
    window.__mock.revoked = false;   // signed in again
    window.__mockSet('POST /auth/2fa/activate', 401, { detail: 'Invalid token' }, { once: true });
    window.__mockSet('GET /auth/me', 401, { detail: 'Invalid token' }, { once: true });
  });
  await clearReqs();
  await fill('#set2faCode', '333333'); await click('#set2faConfirm'); await wait(400);
  rq = (await reqs()).filter(r => ['/auth/me', '/auth/2fa/activate', '/auth/refresh'].includes(r.url));
  T('C1 two-factor on, token refused: POST, GET /auth/me (401), one refresh, GET /auth/me, POST again',
    JSON.stringify(rq.map(r => r.method + ' ' + r.url)) === JSON.stringify(['POST /auth/2fa/activate', 'GET /auth/me', 'POST /auth/refresh', 'GET /auth/me', 'POST /auth/2fa/activate']));
  T('C1 two-factor on, token refused: two-factor turns on after the renewal', (await ev(page, () => document.querySelectorAll('#set2faCodes li').length)) === 10);
  await page.evaluate(() => { delete window.__mock.over['GET /auth/me']; delete window.__mock.over['POST /auth/2fa/activate']; SEED.user.totp_enabled = false; SEED.user.totp_backup_codes_remaining = 0; if (me) me.totp_enabled = false; window.nav('settings'); });
  await wait(300);
  await click('#set2faStart'); await wait(250);
  await click('#set2faCancel'); await wait(100);
  T('3d two-factor: Cancel clears the secret from the page', await ev(page, () => { const ps = document.getElementById('page-settings'); return !!ps && !ps.innerHTML.includes('JBSWY3DPEHPK3PXP'); }));
  // Notifications: preferences.notifications (BASE api/account.py:95-125; shallow merge).
  await page.evaluate(() => { window.__mockClear(); window.nav('settings'); }); await wait(300);
  T('3d notifications: the email toggle reflects the stored preference', await ev(page, () => { const c = document.getElementById('setNotifEmail'); return !!c && c.checked === true; }));
  await clearReqs();
  await click('#setNotifEmail'); await wait(250);
  const np = (await reqs()).filter(r => r.url === '/account/settings' && r.method === 'PATCH');
  T('3d notifications: a change sends exactly {preferences:{notifications}} and keeps the other keys', np.length === 1 && exactKeys(np[0].body, ['preferences']) && exactKeys(np[0].body.preferences, ['notifications']) && JSON.stringify(np[0].body.preferences.notifications) === JSON.stringify({ email: false, sms: false }));
  // AI assistant: only when GET /account/settings carries ai_assistant_consent (S35 api/account.py:76-83).
  T('3d AI assistant: hidden on the deployed base (no ai_assistant_consent key)', !(await vis('#setAi')));
  await page.evaluate(() => { window.__mock.s35 = true; window.nav('settings'); }); await wait(300);
  T('3d AI assistant (PR #35): shown, off by default', await vis('#setAi') && await ev(page, () => document.getElementById('setAiConsent') && document.getElementById('setAiConsent').checked === false));
  await clearReqs();
  await click('#setAiConsent'); await wait(250);
  const ai = (await reqs()).filter(r => r.url === '/account/settings' && r.method === 'PATCH');
  T('3d AI assistant (PR #35): opting in sends exactly {ai_assistant_consent: true}', ai.length === 1 && exactKeys(ai[0].body, ['ai_assistant_consent']) && ai[0].body.ai_assistant_consent === true);
  await page.evaluate(() => { window.__mockSet('PATCH /account/settings', 422, { detail: [{ type: 'extra_forbidden', loc: ['body', 'ai_assistant_consent'], msg: 'Extra inputs are not permitted', input: false }] }); });
  await click('#setAiConsent'); await wait(300);
  T('3d AI assistant: a PATCH refused as an unknown key hides the toggle', !(await vis('#setAi')));
  // Your data: GET /account/export and POST /account/close exist only in PR #33.
  await page.evaluate(() => { window.__mockClear(); window.nav('settings'); }); await wait(300);
  await click('#setExport'); await wait(250);
  T('3d data (deployed base, 404): "Download my data" says not available yet, no error', /not available yet/i.test(await text('#setData')) && (await alertText('#setData')) === '');
  await page.evaluate(() => { window.__mock.a33 = true; window.nav('settings'); }); await wait(300);
  const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 3000 }).catch(() => null), click('#setExport')]);
  T('3d data (PR #33): the export is saved as mysol-data-YYYY-MM-DD.json', !!dl && /^mysol-data-\d{4}-\d{2}-\d{2}\.json$/.test(dl.suggestedFilename()));
  let exported = null; try { exported = JSON.parse(await readFile(await dl.path(), 'utf8')); } catch {}
  T('3d data (PR #33): the file holds the export JSON', !!exported && exported.format_version === 1);
  // Close account dialog.
  await page.evaluate(() => { window.__mockClear(); window.nav('settings'); }); await wait(300);
  await click('#setCloseOpen'); await wait(150);
  T('3d close: a confirmation dialog opens with focus inside', await ev(page, () => window.SolDialog.isOpen('closeAccountDialog') && document.getElementById('closeAccountDialog').contains(document.activeElement)));
  T('3d close: it says what is kept and that it cannot be undone', /keep/i.test(await text('#closeAccountDialog')) && /undone/i.test(await text('#closeAccountDialog')));
  // What is kept, from PR #33's list (A33 services/account_lifecycle.py:491-555): the name and
  // email address are replaced on the account, but copies stay in kept records (CONTRACT-C3, SECURITY-SEC-2).
  const intro = await text('#closeIntro');
  T('C3 close: the dialog does not say the name and email address are removed everywhere', !/remove your name, email address/i.test(intro) && /replace your name and email address/i.test(intro));
  T('C3 close: it says kept records can include the name, email address or phone number (provider messages, fraud checks)', /can include your name, email address or phone number/i.test(intro) && /payment, ID check and billing providers/i.test(intro) && /fraud/i.test(intro));
  T("C3 close: it lists the bank provider's reference, the ID check provider's reference, the account record and the audit trail", /bank provider's reference/i.test(intro) && /ID check provider's reference/i.test(intro) && /account record/i.test(intro) && /audit trail/i.test(intro));
  T('C3 close: it does not call the bank links removed (the account reference is kept)', !/saved bank links/i.test(intro));
  T('C3 close: the 5 years are given as the default, still under legal review', /by default/i.test(intro) && /5 years/.test(intro) && /legal review/i.test(intro));
  await fill('#closePw', 'synthetic-password');
  T('3d close: the confirm button stays disabled until DELETE is typed', await ev(page, () => document.getElementById('closeConfirm').disabled === true));
  await fill('#closePhrase', 'delete');
  T('3d close: a phrase that does not match keeps it disabled', await ev(page, () => document.getElementById('closeConfirm').disabled === true));
  await fill('#closePhrase', 'DELETE');
  T('3d close: typing DELETE enables it', await ev(page, () => document.getElementById('closeConfirm').disabled === false));
  await clearReqs();
  await click('#closeConfirm'); await wait(250);
  const cl = (await reqs()).filter(r => r.url === '/account/close');
  T('3d close: sends POST /account/close with exactly {password, totp_code: null, confirm: "DELETE"}', cl.length === 1 && exactKeys(cl[0].body, ['password', 'totp_code', 'confirm']) && cl[0].body.totp_code === null && cl[0].body.confirm === 'DELETE');
  T('3d close (deployed base, 404): says not available yet, no error alert', /not available yet/i.test(await text('#closeAccountDialog')) && (await alertText('#closeAccountDialog')) === '');
  // 403 switch off (A33 services/account_lifecycle.py:249-264): the backend's own message.
  await page.evaluate(() => window.__mockSet('POST /account/close', 403, { detail: { error: 'account_close_disabled', message: 'Closing an account is not available yet.' } }));
  await click('#closeConfirm'); await wait(250);
  T('3d close (403 switch off): shows the backend\'s message, not raw JSON', /Closing an account is not available yet\./.test(await text('#closeAccountDialog')) && !/account_close_disabled|\{"/.test(await text('#closeAccountDialog')));
  // 409 refused (A33 services/account_lifecycle.py:281-368, 583-594): reasons, never ids.
  await page.evaluate(gid => window.__mockSet('POST /account/close', 409, { detail: { error: 'account_close_refused', message: 'Your account cannot be closed yet.', reasons: [
    { code: 'circle_not_finished', message: 'You still belong to a circle that has not finished.', count: 1, group_ids: [gid] },
    { code: 'checkout_in_progress', message: 'A plan checkout you started in the last 24 hours could still be paid. Try again once it has expired, or cancel the plan if you paid.', count: 1, plans: ['premium'] },
    { code: 'admin_account', message: 'An admin account cannot be closed. Remove the admin role first.' },
  ] } }), IDS.G_ACT);
  await click('#closeConfirm'); await wait(250);
  const reasons = await page.evaluate(() => [...document.querySelectorAll('#closeReasons li')].map(li => li.textContent.trim()));
  T('3d close (409): lists the backend\'s refusal reasons (circle, checkout, admin)', reasons.length === 3 && /circle/.test(reasons[0]) && /checkout/.test(reasons[1]) && /admin/i.test(reasons[2]));
  T('3d close (409): no id in the dialog', await ev(page, gid => { const d = document.getElementById('closeAccountDialog'); return !!d && !d.innerHTML.includes(gid); }, IDS.G_ACT));
  // A wrong password, or a missing 2FA code: 401 (A33 services/account_lifecycle.py:267-278).
  // Not an expired session: one POST, no POST /auth/refresh (CONTRACT-C1, SECURITY-SEC-1).
  await page.evaluate(() => window.__mockSet('POST /account/close', 401, { detail: 'Invalid password' }));
  await clearReqs();
  await click('#closeConfirm'); await wait(300);
  rq = await reqs();
  T('C1 close, wrong password: one POST /account/close and no POST /auth/refresh', countOf(rq, '/account/close') === 1 && refreshCount(rq) === 0);
  T('C1 close, wrong password: says the password is not right', /password is not right/i.test(await alertText('#closeAccountDialog')));
  await page.evaluate(() => window.__mockSet('POST /account/close', 401, { detail: '2FA code required' }));
  await clearReqs();
  await click('#closeConfirm'); await wait(300);
  rq = await reqs();
  T('C1 close, 2FA code required: one POST, no refresh, and the code field is shown', countOf(rq, '/account/close') === 1 && refreshCount(rq) === 0 && await vis('#closeCode'));
  // The page thought two-factor was off (it was turned on elsewhere since Settings loaded): focus
  // goes to the code field, and the code typed next is sent.
  T('close, 2FA code required: focus moves to the code field', await ev(page, () => !!document.activeElement && document.activeElement.id === 'closeCode'));
  await fill('#closeCode', '123456');
  await page.evaluate(() => window.__mockSet('POST /account/close', 401, { detail: 'Invalid code' }));
  await clearReqs();
  await click('#closeConfirm'); await wait(300);
  const withCode = (await reqs()).filter(r => r.url === '/account/close');
  T('close, 2FA code required: the code typed next is sent as totp_code', withCode.length === 1 && !!withCode[0].body && withCode[0].body.totp_code === '123456');
  T('close, a wrong code: says the code did not work', /code did not work/i.test(await alertText('#closeAccountDialog')));
  await page.keyboard.press('Escape'); await wait(120);
  T('3d close: Escape closes the dialog and focus returns to its button', await ev(page, () => !window.SolDialog.isOpen('closeAccountDialog') && document.activeElement && document.activeElement.id === 'setCloseOpen'));
  T('3d close: the password is cleared when the dialog closes', await ev(page, () => document.getElementById('closePw').value === ''));
  await page.evaluate(() => window.__mockClear());

  // ── A11Y-3: an empty polite status region stays in the accessibility tree, so its message is read ──
  await page.evaluate(() => window.nav('settings')); await wait(300);
  let ax = await axNode(page, '#setExportMsg');
  T('A11Y-3 settings: the empty "Download my data" status region is in the accessibility tree', ax.inTree && ax.role === 'status');
  await click('#setCloseOpen'); await wait(150);
  ax = await axNode(page, '#closeNote');
  T('A11Y-3 close dialog: the empty status region is in the accessibility tree', ax.inTree && ax.role === 'status');
  await page.keyboard.press('Escape'); await wait(120);

  // ── A11Y-2: keyboard focus stays on the page after each Settings action (each answer takes 150 ms) ──
  // Disabling the focused control, or hiding or re-rendering it, drops focus to <body>.
  const focusAfter = async (sel, key, scope) => {
    try { await page.focus(sel, { timeout: 1000 }); } catch { return { mid: 'no control', end: 'no control' }; }
    await page.keyboard.press(key);
    const where = () => ev(page, sc => { const a = document.activeElement; if (!a || a === document.body) return 'body'; return a.closest(sc) ? 'ok' : 'outside:' + (a.id || a.tagName); }, scope);
    await wait(50); const mid = await where();
    await wait(400); const end = await where();
    return { mid, end };
  };
  const focusOk = (name, r) => { T(`A11Y-2 ${name}: focus stays on the page while it runs and after`, r.mid === 'ok' && r.end === 'ok'); if (!(r.mid === 'ok' && r.end === 'ok')) console.log('      ' + JSON.stringify(r)); };
  await page.evaluate(() => { window.__mockClear(); window.nav('settings'); }); await wait(300);
  await page.evaluate(() => { window.__mock.delay = 150; });
  await fill('#setName', 'Alex Example');
  focusOk('Save name', await focusAfter('#setNameSave', 'Enter', '#page-settings'));
  focusOk('Email me a reset link', await focusAfter('#setPwReset', 'Enter', '#page-settings'));
  focusOk('the email notifications checkbox', await focusAfter('#setNotifEmail', 'Space', '#page-settings'));
  focusOk('Download my data (not available yet)', await focusAfter('#setExport', 'Enter', '#page-settings'));
  focusOk('Turn on two-factor', await focusAfter('#set2faStart', 'Enter', '#page-settings'));
  await page.evaluate(() => window.__mockSet('POST /auth/2fa/activate', 401, { detail: 'Invalid code' }));
  await fill('#set2faCode', '000000');
  focusOk('Turn on (a wrong code)', await focusAfter('#set2faConfirm', 'Enter', '#page-settings'));
  await page.evaluate(() => window.__mockSet('POST /auth/2fa/activate', 400, { detail: 'No TOTP setup in progress — call /auth/2fa/setup first' }));
  await fill('#set2faCode', '000000');
  focusOk('Turn on (setup expired, the card is drawn again)', await focusAfter('#set2faConfirm', 'Enter', '#page-settings'));
  await page.evaluate(() => { window.__mock.delay = 0; SEED.user.totp_enabled = true; window.nav('settings'); }); await wait(300);
  await page.evaluate(() => { window.__mock.delay = 150; window.__mockSet('POST /auth/2fa/disable', 401, { detail: 'Invalid password' }); });
  await fill('#set2faPw', 'synthetic-wrong-password'); await fill('#set2faOffCode', '654321');
  focusOk('Turn off two-factor (a wrong password)', await focusAfter('#set2faOff', 'Enter', '#page-settings'));
  // (The AI setting was hidden by an earlier refusal; show it again for this check.)
  await page.evaluate(() => { window.__mock.delay = 0; SEED.user.totp_enabled = false; SEED.user.email_verified_at = null; window.__mock.s35 = true; setState.aiHidden = false; window.nav('settings'); }); await wait(300);
  await page.evaluate(() => { window.__mock.delay = 150; window.__mockSet('PATCH /account/settings', 422, { detail: [{ type: 'extra_forbidden', loc: ['body', 'ai_assistant_consent'], msg: 'Extra inputs are not permitted', input: true }] }); });
  focusOk('the AI assistant checkbox (refused, the setting is hidden)', await focusAfter('#setAiConsent', 'Space', '#page-settings'));
  focusOk('Resend email in Settings (not available yet, the button is hidden)', await focusAfter('#setResend', 'Enter', '#page-settings'));
  await page.evaluate(() => { window.__mock.delay = 0; delete window.__mock.over['PATCH /account/settings']; window.nav('settings'); }); await wait(300);
  await click('#setCloseOpen'); await wait(150);
  await fill('#closePw', 'synthetic-password'); await fill('#closePhrase', 'DELETE');
  await page.evaluate(() => { window.__mock.delay = 150; window.__mockSet('POST /account/close', 409, { detail: { error: 'account_close_refused', message: 'Your account cannot be closed yet.', reasons: [{ code: 'admin_account', message: 'An admin account cannot be closed. Remove the admin role first.' }] } }); });
  focusOk('Close my account (refused)', await focusAfter('#closeConfirm', 'Enter', '#closeAccountDialog'));
  T('A11Y-2 close (409): the refusal reasons are inside the alert region', await ev(page, () => !!document.querySelector('#closeAccountDialog [role=alert] #closeReasons li')));
  await page.evaluate(() => { window.__mock.delay = 0; }); await page.keyboard.press('Escape'); await wait(120);
  await page.evaluate(() => window.nav('dashboard')); await wait(400);
  await page.evaluate(() => { window.__mock.delay = 150; });
  focusOk('Resend email on the dashboard banner (not available yet, the button is hidden)', await focusAfter('#verifyResend', 'Enter', '#page-dashboard'));
  await page.evaluate(async () => { window.__mockClear(); SEED.user.email_verified_at = '2026-01-02T00:00:00Z'; me = await api('/auth/me'); });

  // ── [3f] payout history on the payments page (GET /payments/my-payouts, BASE api/payments.py:366-397) ──
  await clearReqs();
  await page.evaluate(() => window.nav('payments')); await wait(300);
  T('3f payouts: the payments page lists payouts to the member', /payouts to you/i.test(await text('#page-payments')));
  T('3f payouts: GET /payments/my-payouts carries the route abort signal', (await reqs()).some(r => r.url.startsWith('/payments/my-payouts') && r.hadSignal));
  const po = await text('#payoutsList');
  T('3f payouts: amounts are formatted from cents', po.includes('$1,080.00'));
  T('3f payouts: each shows its status and a date', /settled/i.test(po) && /processing/i.test(po) && /\b2026\b/.test(po));
  T('3f payouts: no raw payout, circle or cycle id in the page', !(await ev(page, ids => { const h = document.getElementById('page-payments').innerHTML; return ids.some(i => h.includes(i)); }, ['99990000-0000-4000-8000-999999999991', '99990000-0000-4000-8000-999999999992', IDS.G_ACT])));

  // ── [6a] first-run guide ──
  await page.evaluate(() => { window.__mockClear(); localStorage.removeItem('sol_guide_seen:' + SEED.user.id); window.nav('dashboard'); });
  await wait(450);
  T('6a guide: opens on the first dashboard load', await ev(page, () => !!document.getElementById('guideDialog') && window.SolDialog.isOpen('guideDialog')));
  T('6a guide: an accessible dialog (role=dialog, aria-modal, labelled)', await ev(page, () => { const d = document.getElementById('guideDialog'); return !!d && d.getAttribute('role') === 'dialog' && d.getAttribute('aria-modal') === 'true' && !!d.getAttribute('aria-labelledby') && !!document.getElementById(d.getAttribute('aria-labelledby')); }));
  T('6a guide: focus is inside it', await ev(page, () => { const d = document.getElementById('guideDialog'); return !!d && d.contains(document.activeElement); }));
  const steps = await page.evaluate(async () => {
    const seen = [];
    for (let i = 0; i < 6; i++) { const d = document.getElementById('guideDialog'); if (!d) break; seen.push((document.getElementById('guideBody') || d).innerText); const n = document.getElementById('guideNext'); if (!n || n.offsetParent === null) break; n.click(); await new Promise(r => setTimeout(r, 60)); }
    return seen;
  });
  T('6a guide: 3 or 4 steps', steps.length >= 3 && steps.length <= 4);
  T('6a guide: explains a sol, a cycle (same amount, one member receives, order set in the circle), the checks and what to do next', /sol/i.test(steps[0] || '') && /same amount/i.test(steps.join(' ')) && /order/i.test(steps.join(' ')) && /identity|ID check/i.test(steps.join(' ')) && /settle/i.test(steps.join(' ')));
  T('6a guide: the last step has buttons for email, ID check, bank and circles', await ev(page, () => ['settings', 'kyc', 'bank', 'discover'].every(p => !!document.querySelector(`#guideDialog [data-guide-go="${p}"]`))));
  await page.keyboard.press('Escape'); await wait(150);
  T('6a guide: Escape closes it and focus returns to the page heading', await ev(page, () => !window.SolDialog.isOpen('guideDialog') && document.activeElement === document.querySelector('#page-dashboard h1')));
  T('6a guide: "seen" is remembered for this member', await ev(page, () => localStorage.getItem('sol_guide_seen:' + SEED.user.id) !== null));
  await page.evaluate(() => window.nav('dashboard')); await wait(350);
  T('6a guide: not shown again on the next dashboard load', await ev(page, () => !window.SolDialog.isOpen('guideDialog')));
  // Re-open from Settings; a "next step" button navigates there.
  await page.evaluate(() => window.nav('settings')); await wait(300);
  await click('#setGuide'); await wait(150);
  T('6a guide: Settings > How MySol works re-opens it', await ev(page, () => window.SolDialog.isOpen('guideDialog')));
  await page.evaluate(async () => { for (let i = 0; i < 6; i++) { const n = document.getElementById('guideNext'); if (!n || n.offsetParent === null) break; n.click(); await new Promise(r => setTimeout(r, 40)); } });
  await click('#guideDialog [data-guide-go="bank"]'); await wait(250);
  T('6a guide: "Link a bank" closes it and opens the bank page with focus on its heading', await ev(page, () => !window.SolDialog.isOpen('guideDialog') && document.getElementById('page-bank').classList.contains('active') && document.activeElement === document.querySelector('#page-bank h1')));
  // The close button.
  await page.evaluate(() => window.nav('settings')); await wait(250);
  await click('#setGuide'); await wait(120);
  await click('#guideClose'); await wait(120);
  T('6a guide: the close button (with an accessible name) dismisses it, focus on the heading', await ev(page, () => !window.SolDialog.isOpen('guideDialog') && document.activeElement === document.querySelector('#page-settings h1')));
  // Storage blocked: the guide still opens, nothing throws.
  const blocked = await page.evaluate(async () => {
    const before = window.__errs.length;
    const g = Storage.prototype.getItem, s = Storage.prototype.setItem;
    Storage.prototype.getItem = function () { throw new DOMException('blocked', 'SecurityError'); };
    Storage.prototype.setItem = function () { throw new DOMException('blocked', 'SecurityError'); };
    let opened = false;
    try { window.nav('dashboard'); await new Promise(r => setTimeout(r, 450)); opened = window.SolDialog.isOpen('guideDialog'); if (opened) window.SolDialog.close('guideDialog'); }
    finally { Storage.prototype.getItem = g; Storage.prototype.setItem = s; }
    return { opened, errs: window.__errs.length - before };
  });
  T('6a guide: with storage blocked it still opens and nothing throws', blocked.opened === true && blocked.errs === 0);
  await page.evaluate(() => { try { localStorage.setItem('sol_guide_seen:' + SEED.user.id, '1'); } catch (e) {} });
}

async function accessibility(page) {
  const { wait } = helpers(page);
  // ── [6b/6c] every member route: checks, focus on the h1, page title ──
  const routes = ['dashboard', 'groups', 'discover', 'kyc', 'bank', 'payments', 'timeline', 'trust', 'premium', 'notifications', 'community', 'goals', 'settings'];
  for (const r of routes) {
    await page.evaluate(x => window.nav(x), r); await wait(260);
    reportAudit(`6c a11y ${r}: labels, names, one h1, landmarks, no positive tabindex, alt text, aria-current`, await page.evaluate(auditPage, 'app'));
    T(`6b ${r}: focus moves to the page h1 and the title names the page`, await ev(page, x => { const h = document.querySelector(`#page-${x} h1`); return !!h && document.activeElement === h && h.getAttribute('tabindex') === '-1' && document.title.includes(h.textContent.trim()); }, r));
  }
  await page.evaluate(id => window.showGroup(id), IDS.G_FORM); await wait(300);
  reportAudit('6c a11y group-detail: labels, names, one h1, landmarks, no positive tabindex, alt text, aria-current', await page.evaluate(auditPage, 'app'));
  T('6b mobile nav: the active item has aria-current', await ev(page, () => { window.nav('payments'); const a = document.querySelector('.mn[data-mpage="payments"]'); const others = [...document.querySelectorAll('.mn[aria-current]')].filter(n => n !== a).length; return !!a && a.getAttribute('aria-current') === 'page' && others === 0; }));
  // Focus ring: visible, 3:1 against the page.
  await page.evaluate(() => { window.nav('dashboard'); document.querySelector('.nav-item[data-page="goals"]').focus(); });
  await page.keyboard.press('Tab');   // keyboard focus, so :focus-visible applies
  await page.waitForTimeout(400);     // .nav-item transitions every property (.15s): read the settled outline
  const ring = await page.evaluate(() => {
    const b = document.activeElement;
    const cs = getComputedStyle(b);
    const rgb = s => (s.match(/\d+(\.\d+)?/g) || []).slice(0, 3).map(Number);
    const lin = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
    const L = a => 0.2126 * lin(a[0]) + 0.7152 * lin(a[1]) + 0.0722 * lin(a[2]);
    const ratio = (a, b2) => { const x = L(a), y = L(b2); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
    let bgEl = b.parentElement, bg = 'rgb(255, 255, 255)';
    while (bgEl) { const c = getComputedStyle(bgEl).backgroundColor; if (c && !/rgba\(0, 0, 0, 0\)|transparent/.test(c)) { bg = c; break; } bgEl = bgEl.parentElement; }
    return { style: cs.outlineStyle, width: parseFloat(cs.outlineWidth), ratio: ratio(rgb(cs.outlineColor), rgb(bg)), focusVisible: b.matches(':focus-visible') };
  });
  T('6b focus ring: a keyboard-focused control shows an outline with 3:1 contrast', ring.style !== 'none' && ring.width >= 2 && ring.ratio >= 3);
  if (!(ring.style !== 'none' && ring.width >= 2 && ring.ratio >= 3)) console.log('      ' + JSON.stringify(ring));
  // The dark dashboard hero and the dark Premium card: the ring is drawn on their background, so it
  // must reach 3:1 against every colour of their gradient (A11Y-1).
  for (const [label, sel] of [['dashboard hero', '#dashHero .hero-actions .btn'], ['Premium card', '#dashPremium .premium-card .btn']]) {
    await page.evaluate(() => window.nav('dashboard')); await page.waitForTimeout(400);
    await page.evaluate(s => { const b = document.querySelector(s); if (b) b.focus(); }, sel);
    await page.keyboard.press('Shift+Tab'); await page.keyboard.press('Tab');   // keyboard focus, so :focus-visible applies
    await page.waitForTimeout(400);
    const dark = await page.evaluate(s => {
      const b = document.activeElement;
      if (!b || !b.matches(s)) return { focused: false };
      const cs = getComputedStyle(b);
      const rgb = c => (c.match(/\d+(\.\d+)?/g) || []).slice(0, 3).map(Number);
      const lin = c => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
      const L = a => 0.2126 * lin(a[0]) + 0.7152 * lin(a[1]) + 0.0722 * lin(a[2]);
      const ratio = (a, b2) => { const x = L(a), y = L(b2); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };
      let el = b.parentElement, colors = [];
      while (el) {
        const st = getComputedStyle(el);
        if (st.backgroundImage && st.backgroundImage !== 'none') { colors = st.backgroundImage.match(/rgba?\([^)]*\)/g) || []; break; }
        if (st.backgroundColor && !/rgba\(0, 0, 0, 0\)|transparent/.test(st.backgroundColor)) { colors = [st.backgroundColor]; break; }
        el = el.parentElement;
      }
      const ring = rgb(cs.outlineColor);
      const ratios = colors.map(c => ratio(ring, rgb(c)));
      return { focused: true, focusVisible: b.matches(':focus-visible'), style: cs.outlineStyle, width: parseFloat(cs.outlineWidth), colors, min: ratios.length ? Math.min(...ratios) : 0 };
    }, sel);
    const okDark = dark.focused && dark.focusVisible && dark.style !== 'none' && dark.width >= 2 && dark.colors.length >= 2 && dark.min >= 3;
    T(`A11Y-1 focus ring on the ${label}: 3:1 against every colour of its dark background`, okDark);
    if (!okDark) console.log('      ' + JSON.stringify(dark));
  }
  await page.emulateMedia({ reducedMotion: 'reduce' });
  T('6b prefers-reduced-motion: transitions are switched off', await ev(page, () => parseFloat(getComputedStyle(document.querySelector('.btn')).transitionDuration) < 0.01));
  await page.emulateMedia({ reducedMotion: 'no-preference' });
}

// Tab order from the top of a freshly loaded app (reloads the journey page, so it runs after
// the page-error check of everything before it).
async function keyboardFromTop(page) {
  await page.reload(); await page.waitForTimeout(500);
  await keyboardOrder(page, 'member app', 'nav[aria-label]');
  const errs = await page.evaluate(() => window.__errs || []);
  T('no page errors after the reload', errs.length === 0);
}

// A fresh browser context (its own storage, so a sign-in or sign-out there never reaches the
// main journey page) with the same safety routes.
async function safeContext(browser, leaks) {
  const ctx = await browser.newContext({ acceptDownloads: true });
  await ctx.route(/^https?:\/\/(sol-api-production\.up\.railway\.app|([^/]*\.)?wheellsverse\.com)(\/|$)/, r => { leaks.push(r.request().url()); return r.abort(); });
  await ctx.route(/^https?:\/\/fonts\.(googleapis|gstatic)\.com\//, r => r.fulfill({ status: 200, contentType: 'text/css', body: '' }));
  return ctx;
}

// Closing the account (PR #33 200) signs the member out with the existing logout().
async function closeAccountSignsOut(browser, leaks) {
  const ctx = await safeContext(browser, leaks);
  const page = await ctx.newPage();
  const recorded = [];
  await page.exposeFunction('__recordReq', e => { recorded.push(e); });
  await page.goto(`http://localhost:${PORT}${HARNESS_URL_PATH}`); await page.waitForTimeout(400);
  const { wait, click, fill } = helpers(page);
  // The response's retention period is 7 years here (ACCOUNT_RECORD_RETENTION_YEARS is a setting):
  // the summary must come from the response, not from a fixed 5.
  const summary = await page.evaluate(() => { const b = window.__closeSummary(7); window.__mockSet('POST /account/close', 200, b); window.__mock.a33 = true; window.nav('settings'); return b; });
  await wait(300);
  await click('#setCloseOpen'); await wait(120);
  await fill('#closePw', 'synthetic-password'); await fill('#closePhrase', 'DELETE');
  await click('#closeConfirm'); await wait(400);
  const done = await ev(page, () => {
    const box = document.getElementById('closeDone');
    const items = id => [...document.querySelectorAll('#' + id + ' li')].map(li => li.textContent.trim());
    return { shown: !!box && box.offsetParent !== null, text: box ? box.innerText : '', removed: items('closeDoneRemoved'), kept: items('closeDoneKept'),
      focusIn: document.getElementById('closeAccountDialog').contains(document.activeElement), url: location.pathname };
  });
  T('C3 close (PR #33, 200): the dialog then lists what was removed, from the response', !!done && done.shown && JSON.stringify(done.removed) === JSON.stringify(summary.removed.map(d => d.description)));
  T('C3 close (PR #33, 200): and what is kept, from the response', !!done && JSON.stringify(done.kept) === JSON.stringify(summary.kept.map(d => d.description)));
  T('C3 close (PR #33, 200): the retention period is the response\'s (7 years), not a fixed 5', !!done && /7 years/.test(done.text) && !/5 years/.test(done.text));
  T('C3 close (PR #33, 200): the member can read it first: not signed out yet, focus inside the dialog', !!done && /boot-test\.html$/.test(done.url) && done.focusIn && !recorded.some(r => r.url === '/auth/logout'));
  await click('#closeDoneSignOut');
  await page.waitForURL(/\/sol\/$/, { timeout: 5000 }).catch(() => {});
  const close = recorded.filter(r => r.url === '/account/close');
  T('3d close (PR #33, 200): POST /account/close was sent once', close.length === 1 && close[0].body && close[0].body.confirm === 'DELETE');
  T('3d close (PR #33, 200): "Sign out" runs the existing logout(): POST /auth/logout and back to the sign-in page', recorded.some(r => r.url === '/auth/logout' && r.method === 'POST') && /\/sol\/$/.test(page.url()));
  // Escape (any way out of the summary) signs out too.
  const page2 = await ctx.newPage();
  const rec2 = [];
  await page2.exposeFunction('__recordReq', e => { rec2.push(e); });
  await page2.goto(`http://localhost:${PORT}${HARNESS_URL_PATH}`); await page2.waitForTimeout(400);
  const h2 = helpers(page2);
  await page2.evaluate(() => { window.__mock.a33 = true; window.nav('settings'); }); await h2.wait(300);
  await h2.click('#setCloseOpen'); await h2.wait(120);
  await h2.fill('#closePw', 'synthetic-password'); await h2.fill('#closePhrase', 'DELETE');
  await h2.click('#closeConfirm'); await h2.wait(400);
  await page2.keyboard.press('Escape');
  await page2.waitForURL(/\/sol\/$/, { timeout: 5000 }).catch(() => {});
  T('C3 close (PR #33, 200): Escape from the summary also signs out', rec2.some(r => r.url === '/auth/logout' && r.method === 'POST') && /\/sol\/$/.test(page2.url()));
  await ctx.close();
}

async function publicPages(browser, leaks) {
  const ctx = await safeContext(browser, leaks);
  const open = async (path, opts = {}) => {
    const page = await ctx.newPage();
    const logs = []; const perrs = []; const recorded = [];
    page.on('console', m => logs.push(m.text()));
    page.on('pageerror', e => perrs.push(String(e)));
    await page.exposeFunction('__recordReq', e => { recorded.push(e); });
    await page.addInitScript({ content: publicMockScript({ flags: opts.flags || {}, over: opts.over || {} }) });
    if (opts.consentOn) {
      await page.route(/\/sol\/index\.html/, async r => { const res = await r.fetch(); const body = (await res.text()).replace('signup_consent: false', 'signup_consent: true'); await r.fulfill({ response: res, body }); });
    }
    await page.goto(`http://localhost:${PORT}${path}`);
    await page.waitForTimeout(300);
    return { page, logs, perrs, recorded, ...helpers(page) };
  };
  const storageHas = (page, v) => page.evaluate(x => (JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage })).includes(x), v).catch(() => false);

  // ── [3a] forgot password in the sign-in modal (POST /auth/forgot-password, BASE api/auth.py:124-132) ──
  const NEUTRAL = 'If an account exists for that address, we sent a link.';
  const forgot = async (opts = {}) => {
    const o = await open('/sol/index.html', opts);
    await o.page.click('header nav .btn-primary, nav .btn-primary', { timeout: 2000 }).catch(() => {});
    await o.wait(150);
    const hasLink = await o.vis('#forgotLink');
    await o.click('#forgotLink'); await o.wait(120);
    const formShown = await o.vis('#forgotForm');
    const focusInForm = await o.page.evaluate(() => document.activeElement && document.activeElement.id === 'forgotEmail');
    const axMsg = await axNode(o.page, '#forgotMsg');
    await o.fill('#forgotEmail', 'member@example.invalid'); await o.click('#forgotBtn'); await o.wait(250);
    return { o, hasLink, formShown, focusInForm, axMsg, msg: (await o.text('#forgotMsg')).trim(), err: (await o.text('#forgotErr')).trim() };
  };
  let f = await forgot();
  T('3a forgot: the sign-in form has a "Forgot password?" control', f.hasLink && /forgot password/i.test(await f.o.text('#forgotLink')));
  T('3a forgot: it opens a small email form with focus on the email field', f.formShown && f.focusInForm);
  const sent = f.o.recorded.filter(r => r.url === '/auth/forgot-password');
  T('3a forgot: sends POST /auth/forgot-password with exactly {email}', sent.length === 1 && exactKeys(sent[0].body, ['email']) && sent[0].body.email === 'member@example.invalid');
  T('3a forgot: shows the neutral message', f.msg === NEUTRAL);
  T('A11Y-3 forgot: the empty status region is in the accessibility tree before the message arrives', f.axMsg.inTree && f.axMsg.role === 'status');
  // Keyboard: Enter on "Send reset link" while the answer takes 150 ms keeps focus in the modal (A11Y-2).
  await f.o.page.evaluate(() => { window.__mock.delay = 150; });
  await f.o.page.focus('#forgotBtn').catch(() => {}); await f.o.page.keyboard.press('Enter');
  await f.o.wait(50);
  const fMid = await ev(f.o.page, () => !!document.activeElement && document.activeElement !== document.body && !!document.activeElement.closest('#authModal'));
  await f.o.wait(400);
  const fEnd = await ev(f.o.page, () => !!document.activeElement && document.activeElement !== document.body && !!document.activeElement.closest('#authModal'));
  T('A11Y-2 forgot: focus stays in the modal while "Send reset link" runs and after', fMid === true && fEnd === true);
  await f.o.page.evaluate(() => { window.__mock.delay = 0; });
  reportAudit('6c a11y landing page (sign-in modal open, forgot form): labels, names, one h1, landmarks, no positive tabindex, alt text', await f.o.page.evaluate(auditPage, 'doc'));
  T('6b landing modal: focus stays inside the open modal on Tab', await (async () => { for (let i = 0; i < 12; i++) await f.o.page.keyboard.press('Tab'); return f.o.page.evaluate(() => !!document.activeElement.closest('#authModal')); })());
  await f.o.page.keyboard.press('Escape'); await f.o.wait(120);
  T('6b landing modal: Escape closes it and focus returns to the Sign in button', await f.o.page.evaluate(() => !document.getElementById('authModal').classList.contains('open') && !!document.activeElement && /sign in/i.test(document.activeElement.textContent) && !document.activeElement.closest('#authModal')));
  T('3a forgot: no page errors', f.o.perrs.length === 0);
  for (const [status, body] of [[500, { detail: 'Internal Server Error' }], [422, { detail: [{ type: 'value_error', loc: ['body', 'email'], msg: 'value is not a valid email address' }] }], [404, { detail: 'Not Found' }]]) {
    const g = await forgot({ over: { 'POST /auth/forgot-password': { status, body } } });
    T(`3a forgot: a ${status} answer shows the same neutral message (reveals nothing)`, g.msg === NEUTRAL && g.err === '');
    await g.o.page.close();
  }
  const lim = await forgot({ over: { 'POST /auth/forgot-password': { status: 429, body: { error: 'Rate limit exceeded: 5 per 15 minute' } } } });
  T('3a forgot: a 429 says to try again later', /try again later/i.test(lim.err) && lim.msg !== NEUTRAL);
  await lim.o.page.close(); await f.o.page.close();
  const fq = await open('/sol/index.html?forgot=1');
  T('3a forgot: /sol/?forgot opens the forgot-password form (the reset page links here)', await fq.vis('#forgotForm'));
  await fq.page.close();
  // Keyboard order on the landing page.
  const kl = await open('/sol/index.html');
  await keyboardOrder(kl.page, 'landing page', 'header nav');
  reportAudit('6c a11y landing page (modal closed): labels, names, one h1, landmarks, no positive tabindex, alt text', await kl.page.evaluate(auditPage, 'doc'));
  await kl.page.close();

  // ── two-factor sign-in: 428 {"detail":{"totp_required":true,"challenge_token":…}} (BASE services/auth.py:176-182) ──
  const tl = await open('/sol/index.html');
  await tl.page.click('header nav .btn-primary, nav .btn-primary', { timeout: 2000 }).catch(() => {});
  await tl.fill('#loginEmail', 'totp-member@example.invalid'); await tl.fill('#loginPassword', 'synthetic-password');
  await tl.page.click('#loginBtn').catch(() => {}); await tl.wait(250);
  T('sign-in: a 428 two-factor answer shows the code step', await tl.vis('#totpForm'));
  T('sign-in: the challenge token is never shown on the page', !(await ev(tl.page, () => document.body.innerText.includes('synthetic-challenge-token') || document.body.innerHTML.includes('synthetic-challenge-token'))));
  T('sign-in: the code field also takes a backup code (up to 12 characters)', await ev(tl.page, () => { const i = document.getElementById('totpCode'); return !!i && (i.maxLength === -1 || i.maxLength >= 12) && !(i.pattern && !new RegExp('^(?:' + i.pattern + ')$').test('a1b2-c3d4-e5')); }));
  await tl.fill('#totpCode', '123456'); await tl.page.click('#totpBtn').catch(() => {});
  await tl.page.waitForURL(/\/sol\/app$/, { timeout: 3000 }).catch(() => {});
  const tt = tl.recorded.filter(r => r.url === '/auth/login/totp');
  T('sign-in: the code goes to POST /auth/login/totp with the challenge, then the app opens', tt.length === 1 && exactKeys(tt[0].body, ['challenge_token', 'code']) && tt[0].body.challenge_token === 'synthetic-challenge-token' && /\/sol\/app$/.test(tl.page.url()));
  await tl.page.close();

  // ── [3e] consent at sign-up (off by default; PR #34 shape when on) ──
  const signup = async (opts, tick, beforeSubmit) => {
    const o = await open('/sol/index.html', opts);
    await o.page.evaluate(() => window.openModal && window.openModal('register'));
    await o.wait(100);
    const box = await o.vis('#regConsent');
    await o.fill('#regName', 'Test Member'); await o.fill('#regEmail', 'new-member@example.invalid'); await o.fill('#regPassword', 'synthetic-pass-1');
    if (tick) await o.page.check('#regConsent', { timeout: 1000 }).catch(() => {});
    if (beforeSubmit) await o.page.evaluate(beforeSubmit);
    await o.page.click('#regBtn').catch(() => {});
    await o.page.waitForURL(/\/sol\/app$/, { timeout: 2500 }).catch(() => {});
    return { o, box, bodies: o.recorded.filter(r => r.url === '/auth/signup').map(r => r.body) };
  };
  let su = await signup({}, false);
  T('3e consent off (default): no consent checkbox', !su.box);
  T('3e consent off: the sign-up body is exactly {email, password, full_name}', su.bodies.length === 1 && exactKeys(su.bodies[0], ['email', 'password', 'full_name']));
  await su.o.page.close();
  // Switch on. The member agrees to the texts GET /legal/documents returns (C34 api/legal.py:13-16),
  // the same versions sign-up records; /terms.html and /privacy.html are another product's pages
  // (frontend/terms.html, frontend/privacy.html) and are never linked (CONTRACT-C2, SECURITY-SEC-3).
  const co = await open('/sol/index.html', { consentOn: true, flags: { c34: true } });
  await co.page.evaluate(() => window.openModal && window.openModal('register')); await co.wait(150);
  T('3e consent on, PR #34: a required, unticked checkbox', await ev(co.page, () => { const c = document.getElementById('regConsent'); return !!c && c.type === 'checkbox' && c.required === true && c.checked === false && c.offsetParent !== null; }));
  const shownDocs = await ev(co.page, () => [...document.querySelectorAll('#regConsentDocs details')].map(d => ({ title: (d.querySelector('summary') || {}).textContent, text: (d.querySelector('.consent-doc__text') || {}).textContent })));
  T('C2 consent on, PR #34: the terms, privacy policy and e-sign disclosure are shown with the exact titles and texts of GET /legal/documents', Array.isArray(shownDocs) && JSON.stringify(shownDocs) === JSON.stringify([
    { title: 'Sol Terms of Service', text: 'SYNTHETIC TERMS TEXT.\n\nSecond paragraph of the synthetic terms.' },
    { title: 'Sol Privacy Policy', text: 'SYNTHETIC PRIVACY TEXT.' },
    { title: 'Consent to Electronic Records and Signatures', text: 'SYNTHETIC E-SIGN TEXT.' }]));
  T('C2 consent on: no link to /terms.html or /privacy.html (another product\'s pages)', await ev(co.page, () => !document.querySelector('#registerForm a[href*="terms.html"], #registerForm a[href*="privacy.html"]')));
  T('C2 consent on: the checkbox label names the three documents', await ev(co.page, () => { const l = document.querySelector('label[for="regConsent"]'); const t = l ? l.textContent : ''; return /Sol Terms of Service/.test(t) && /Sol Privacy Policy/.test(t) && /Consent to Electronic Records and Signatures/.test(t); }));
  await co.page.click('#regConsentDocs summary').catch(() => {}); await co.wait(80);
  reportAudit('6c a11y landing page (register form, consent on, a document open): labels, names, one h1, landmarks, no positive tabindex, alt text', await co.page.evaluate(auditPage, 'doc'));
  await co.page.close();
  su = await signup({ consentOn: true, flags: { c34: true } }, false);
  T('3e consent on: an unticked box blocks sign-up (no request)', su.bodies.length === 0);
  await su.o.page.close();
  su = await signup({ consentOn: true }, true);
  T('C2 consent on, deployed base (GET /legal/documents 404): no checkbox, since nothing could be recorded', su.box === false);
  T('3e consent on, deployed base (GET /legal/documents 404): sign-up still works with the base body', su.bodies.length === 1 && exactKeys(su.bodies[0], ['email', 'password', 'full_name']));
  await su.o.page.close();
  su = await signup({ consentOn: true, flags: { c34: true } }, true);
  T('3e consent on, PR #34: the body adds accepted_terms_version, accepted_privacy_version and esign_consent', su.bodies.length === 1 && exactKeys(su.bodies[0], ['email', 'password', 'full_name', 'accepted_terms_version', 'accepted_privacy_version', 'esign_consent']) && su.bodies[0].accepted_terms_version === '2026-11-22-draft-1' && su.bodies[0].accepted_privacy_version === '2026-11-22-draft-1' && su.bodies[0].esign_consent === true);
  await su.o.page.close();
  // A document changes between showing it and signing up (the e-sign disclosure here: the body has
  // no version for it, PR #34 records the current one): nothing is sent, the new text is shown and
  // the member is asked to agree again.
  su = await signup({ consentOn: true, flags: { c34: true } }, true, () => { window.__mock.versions = { esign: '2026-11-23-draft-2' }; });
  T('C2 consent on, PR #34: a document that changed before sign-up sends nothing and asks the member to agree again', su.bodies.length === 0 && /changed/i.test(await su.o.text('#regErr')) && await ev(su.o.page, () => document.getElementById('regConsent').checked === false));
  await su.o.page.check('#regConsent', { timeout: 1000 }).catch(() => {});
  await su.o.page.click('#regBtn').catch(() => {});
  await su.o.page.waitForURL(/\/sol\/app$/, { timeout: 2500 }).catch(() => {});
  const su2 = su.o.recorded.filter(r => r.url === '/auth/signup').map(r => r.body);
  T('C2 consent on, PR #34: agreeing again then signs up', su2.length === 1 && su2[0].esign_consent === true && su2[0].accepted_terms_version === '2026-11-22-draft-1');
  await su.o.page.close();
  su = await signup({ consentOn: true, flags: { c34: true }, over: { 'POST /auth/signup': { status: 422, body: { detail: { code: 'consent_required', problems: { terms: 'not_current' }, current_versions: { terms: '2026-11-23-draft-2', privacy: '2026-11-22-draft-1', esign: '2026-11-22-draft-1' } } } } } }, true);
  T('3e consent on, PR #34 422 consent_required: a plain message, no raw JSON', /terms|review/i.test(await su.o.text('#regErr')) && !/consent_required|\{"/.test(await su.o.text('#regErr')));
  await su.o.page.close();

  // ── [3b] reset password page (the link is APP_BASE_URL/reset-password?token=, BASE services/email.py:142) ──
  const rp = await open(`/sol/reset-password.html?token=${RESET_TOKEN}&from=mail`);
  T('3b reset: the page exists with one h1', (await ev(rp.page, () => document.querySelectorAll('h1').length)) === 1 && !(await ev(rp.page, () => /404|not found/i.test(document.title))));
  T('3b reset: the token is removed from the address bar at once (other parameters kept)', !rp.page.url().includes(RESET_TOKEN) && /from=mail/.test(rp.page.url()) && !rp.page.url().includes('token='));
  T('3b reset: the token is not stored', !(await storageHas(rp.page, RESET_TOKEN)));
  reportAudit('6c a11y reset page: labels, names, one h1, landmarks, no positive tabindex, alt text', await rp.page.evaluate(auditPage, 'doc'));
  await rp.fill('#resetPassword', 'short'); await rp.fill('#resetConfirm', 'short'); await rp.click('#resetBtn'); await rp.wait(150);
  T('3b reset: a password under 8 characters is refused before any request', rp.recorded.filter(r => r.url === '/auth/reset-password').length === 0 && /8/.test(await rp.text('#resetErr')));
  await rp.fill('#resetPassword', 'synthetic-new-pass'); await rp.fill('#resetConfirm', 'synthetic-new-paSS'); await rp.click('#resetBtn'); await rp.wait(150);
  T('3b reset: passwords that do not match are refused before any request', rp.recorded.filter(r => r.url === '/auth/reset-password').length === 0 && /match/i.test(await rp.text('#resetErr')));
  await rp.fill('#resetConfirm', 'synthetic-new-pass'); await rp.click('#resetBtn'); await rp.wait(250);
  const rr = rp.recorded.filter(r => r.url === '/auth/reset-password');
  T('3b reset: sends POST /auth/reset-password with exactly {token, new_password}', rr.length === 1 && exactKeys(rr[0].body, ['token', 'new_password']) && rr[0].body.token === RESET_TOKEN && rr[0].body.new_password === 'synthetic-new-pass');
  T('3b reset: success shows a link to sign in', await rp.vis('#resetDone') && await ev(rp.page, () => [...document.querySelectorAll('#resetDone a[href]')].some(a => /sign in/i.test(a.textContent) && /^\/sol\//.test(a.getAttribute('href')))));
  T('3b reset: the token never reaches the console', !rp.logs.some(t => t.includes(RESET_TOKEN)));
  T('3b reset: no page errors', rp.perrs.length === 0);
  await rp.page.close();
  const ri = await open(`/sol/reset-password.html?token=${RESET_TOKEN}`, { over: { 'POST /auth/reset-password': { status: 400, body: { detail: 'Invalid or expired token' } } } });
  await ri.fill('#resetPassword', 'synthetic-new-pass'); await ri.fill('#resetConfirm', 'synthetic-new-pass'); await ri.click('#resetBtn'); await ri.wait(250);
  T('3b reset (400): a clear expired-link message with a way to request a new link', await ri.vis('#resetInvalid') && /expired|already used/i.test(await ri.text('#resetInvalid')) && await ev(ri.page, () => [...document.querySelectorAll('#resetInvalid a[href]')].some(a => /forgot/.test(a.getAttribute('href')))));
  await ri.page.close();
  const rl = await open(`/sol/reset-password.html?token=${RESET_TOKEN}`, { over: { 'POST /auth/reset-password': { status: 429, body: { error: 'Rate limit exceeded: 10 per 1 minute' } } } });
  await rl.fill('#resetPassword', 'synthetic-new-pass'); await rl.fill('#resetConfirm', 'synthetic-new-pass'); await rl.click('#resetBtn'); await rl.wait(250);
  T('3b reset (429): says to try again later, the form stays', /try again/i.test(await rl.text('#resetErr')) && await rl.vis('#resetForm'));
  await rl.page.close();
  const rm = await open('/sol/reset-password.html');
  T('3b reset: without a token, says the link is incomplete and offers a new one', await rm.vis('#resetInvalid') && !(await rm.vis('#resetForm')));
  await keyboardOrder(rm.page, 'reset page', 'header nav');
  await rm.page.close();

  // ── [3c] verify email page (APP_BASE_URL/verify?token=, BASE services/email.py:129; POST /auth/verify-email?token=) ──
  const vp = await open(`/sol/verify.html?token=${VERIFY_TOKEN}`);
  await vp.wait(200);
  const vr = vp.recorded.filter(r => r.url.startsWith('/auth/verify-email'));
  T('3c verify: calls POST /auth/verify-email?token=… with the token in the query and no body', vr.length === 1 && vr[0].method === 'POST' && vr[0].url === '/auth/verify-email?token=' + VERIFY_TOKEN && vr[0].body === null);
  T('3c verify: the token is removed from the address bar and not stored', !vp.page.url().includes(VERIFY_TOKEN) && !(await storageHas(vp.page, VERIFY_TOKEN)));
  T('3c verify: success says so and links to the app', await vp.vis('#verifyDone') && /verified/i.test(await vp.text('#verifyDone')) && await ev(vp.page, () => [...document.querySelectorAll('#verifyDone a[href]')].some(a => a.getAttribute('href') === '/sol/app')));
  T('3c verify: the token never reaches the console', !vp.logs.some(t => t.includes(VERIFY_TOKEN)));
  reportAudit('6c a11y verify page: labels, names, one h1, landmarks, no positive tabindex, alt text', await vp.page.evaluate(auditPage, 'doc'));
  await vp.page.close();
  const vi = await open(`/sol/verify.html?token=${VERIFY_TOKEN}`, { over: { 'POST /auth/verify-email': { status: 400, body: { detail: 'Invalid or expired token' } } } });
  T('3c verify (400): an expired-link message that says how to get a new one', await vi.vis('#verifyInvalid') && /expired|already used/i.test(await vi.text('#verifyInvalid')) && /resend/i.test(await vi.text('#verifyInvalid')));
  await vi.page.close();
  const vl = await open(`/sol/verify.html?token=${VERIFY_TOKEN}`, { over: { 'POST /auth/verify-email': { status: 429, body: { error: 'Rate limit exceeded: 10 per 1 minute' } } } });
  T('3c verify (429): says to try again later', /try again/i.test(await vl.text('main')));
  await vl.page.close();
  const vn = await open(`/sol/verify.html?token=${VERIFY_TOKEN}`, { over: { 'POST /auth/verify-email': { status: 405, body: { detail: 'Method Not Allowed' } } } });
  T('3c verify (405): says it is not available yet', /not available yet/i.test(await vn.text('main')));
  await vn.page.close();
  const vm2 = await open('/sol/verify.html');
  T('3c verify: without a token, no request and a clear message', vm2.recorded.filter(r => r.url.startsWith('/auth/verify-email')).length === 0 && await vm2.vis('#verifyInvalid'));
  await keyboardOrder(vm2.page, 'verify page', 'header nav');
  await vm2.page.close();
  await ctx.close();
}

main().catch(e => { console.error(e); process.exit(1); });
