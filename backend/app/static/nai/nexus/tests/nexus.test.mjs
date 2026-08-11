// KAI Nexus tests (§42). Pure-JS invariants runnable without a browser:
// state machine, data-freshness honesty, and the §6 CRITICAL RULE (no fixture
// news may look VERIFIED). Run: node tests/nexus.test.mjs
import assert from 'node:assert';

// ---- minimal DOM stub so the browser modules import in Node ----------------
globalThis.document = {
  documentElement: { dataset: {}, style: {} },
  hidden: false,
  addEventListener() {},
  createElement: tag => ({ tagName: tag, className: '', textContent: '', title: '',
    _a: {}, setAttribute(k, v) { this._a[k] = v; }, append() {}, appendChild() {} }),
};
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });

let pass = 0; const t = (name, fn) => { try { fn(); console.log('  ok  ' + name); pass++; }
  catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } };
const wait = ms => new Promise(r => setTimeout(r, ms));

const { KAI, STATES, bus } = await import('../js/state.js');
const { dataFreshness, FRESH } = await import('../js/shared/dataFreshness.js');
const { data } = await import('../js/data.js');

console.log('state machine (§13):');
t('canonical states include understanding + sleep', () => {
  assert(STATES.includes('understanding') && STATES.includes('sleep'));
  assert.equal(STATES.length, 11);
});
t('set reflects on <html data-kai> and KAI.state', () => {
  KAI.set('listening');
  assert.equal(document.documentElement.dataset.kai, 'listening');
  assert.equal(KAI.state, 'listening');
});
t('state event fires with greeting', () => {
  let got = null; const off = bus.on('state', p => (got = p)); KAI.set('thinking'); off();
  assert.equal(got.state, 'thinking'); assert.ok(got.greeting.length > 0);
});

console.log('transient auto-settle:');
await (async () => {
  KAI.set('listening');                 // a stable state
  KAI.transient('success', 40);
  t('transient enters the flashed state', () => assert.equal(KAI.state, 'success'));
  await wait(80);
  t('transient settles back to the prior stable state', () => assert.equal(KAI.state, 'listening'));
})();

console.log('data honesty (§36):');
t('unknown domain defaults to DEMO', () => assert.equal(dataFreshness.level('nope'), FRESH.DEMO));
t('badge renders a visible DEMO pill', () => {
  const b = dataFreshness.badge('news');
  assert.ok(b.className.includes('fresh-demo')); assert.equal(b.textContent, 'DEMO');
});
t('setting a live feed flips level + anyReal()', () => {
  dataFreshness.set('system', FRESH.LIVE);
  assert.equal(dataFreshness.level('system'), FRESH.LIVE);
  assert.ok(dataFreshness.anyReal());
});

console.log('§6 CRITICAL RULE — no fixture news looks verified:');
t('every news fixture is marked DEMO (never VERIFIED)', () => {
  const news = data.get('news');
  assert.ok(news.length > 0);
  for (const n of news) assert.equal(n.verification, 'DEMO', `"${n.title}" must be DEMO, got ${n.verification}`);
});

setTimeout(() => { console.log(`\n${pass} passed${process.exitCode ? ' — with failures' : ''}`); process.exit(process.exitCode || 0); }, 120);
