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
// NOTE: the real Sol backend is a separate repo, so this runs against the
// enriched mock. A real-backend authenticated E2E remains a future addition.
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join, normalize } from 'node:path';
import { generateHarness, HARNESS_URL_PATH, IDS } from './harness.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = join(HERE, '..', '..', '..');   // repo/frontend
const PORT = 8891;
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
  const page = await browser.newPage();
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

  const errs = await page.evaluate(() => window.__errs || []);
  T('no page errors captured', errs.length === 0);
  T('no console errors', consoleErrors.length === 0);

  await browser.close();
  await new Promise(r => server.close(r));
  console.log(`\n${failures ? '✗ ' + failures + ' FAILURE(S)' : '✓ all journeys passed'}`);
  process.exit(failures ? 1 : 0);
}

main().catch(e => { console.error(e); process.exit(1); });
