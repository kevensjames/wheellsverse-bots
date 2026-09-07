// §7-10 Deployments panel contract. Runs the REAL renderDeploy() lifted out of holding.html and proves
// the flag state an operator READS can never mislead them:
//   1. every flag-gated feature renders its own deployed-vs-enabled row (a flag with no row has no state)
//   2. a near-miss env var (KAI_VOICE_ENABLE, silently dropped by Settings' extra="ignore") is shown
//      LOUDLY, above the registry, naming the flag it was meant to be and its real effective value
//   3. with no misconfiguration the panel is unchanged — no warning is invented
// Run: node test_deploy_panel.js
const assert = require('assert');
const fs = require('fs');

const HTML = fs.readFileSync(__dirname + '/holding.html', 'utf8');
const slice = (start, end) => {
  const i = HTML.indexOf(start);
  assert.ok(i >= 0, 'holding.html no longer contains: ' + start);
  return HTML.slice(i, HTML.indexOf(end, i) + end.length);
};
const fn = name => slice('function ' + name + '(', '\n}\n');

// the panel plus exactly the helpers it renders through — no browser, no network
const SRC = [slice('const esc = s =>', '\n'), slice('const arr = v =>', '\n'),
             slice('const failed = d =>', '\n'), slice('const STATE_META = {', '\n};'),
             fn('badge'), fn('honest'), fn('renderDeploy')].join('\n');

let html = '';
const $ = () => ({ set innerHTML(v) { html = v; } });
const renderDeploy = new Function('$', SRC + '\nreturn renderDeploy;')($);

const render = deployment => { html = ''; renderDeploy({ deployment: deployment }); return html; };
const textOf = h => h.replace(/<[^>]*>/g, ' ').replace(/&#39;/g, "'").replace(/&amp;/g, '&')
                     .replace(/\s+/g, ' ').trim();
// badge() writes the state into BOTH a title attribute and the label, so count the title (one per badge)
const badges = (h, state) => (h.match(new RegExp('title="' + state + '"', 'g')) || []).length;

let pass = 0, total = 0;
const test = (n, f) => { total++; try { f(); pass++; console.log('  ok  ' + n); }
                         catch (e) { console.error('FAIL  ' + n + '\n      ' + e.message); process.exitCode = 1; } };

// the nine authority flags, exactly as backend feature_registry() emits them
const FEATURES = [
  ['holding_api', 'Holding read-only API (/admin/holding)', 'KAI_HOLDING_ENABLED'],
  ['holding_command', 'Holding Command API (§90)', 'KAI_HOLDING_COMMAND_ENABLED'],
  ['holding_watch', 'Continuous watch loop', 'KAI_HOLDING_WATCH_ENABLED'],
  ['holding_cycle', 'Bounded holding cycle beat (§30)', 'KAI_HOLDING_CYCLE_ENABLED'],
  ['holding_briefing', 'Daily morning briefing', 'KAI_HOLDING_BRIEFING_ENABLED'],
  ['holding_delivery', 'Briefing/alert delivery to Telegram', 'KAI_HOLDING_DELIVERY_ENABLED'],
  ['proactive_engine', 'ProactiveBriefingEngine funnel (§11)', 'KAI_PROACTIVE_ENABLED'],
  ['voice_command', 'Voice Command Center (§7)', 'KAI_VOICE_ENABLED'],
  ['camera_gesture', 'Camera + gesture (§8/§94)', 'KAI_CAMERA_ENABLED'],
].map(([id, name, flag]) => ({ feature_id: id, name: name, risk_class: 'P1', certification: 'cert',
                               runtime_flag: flag, runtime_enabled: false, flag_state: 'DISABLED',
                               deployed: true, deployment_state: 'LIVE_PROD', deployment_reason: '' }));

const BASE = { environment: 'production', this_app_sha: 'abcdef123456', money_mode: 'MOCK',
               drift: { state: 'IN_SYNC' }, shas: { source_head: 'abcdef123456' }, features: FEATURES };

const MISCONFIG = {
  env_var: 'KAI_VOICE_ENABLE', suspected_flag: 'KAI_VOICE_ENABLED', state: 'SUSPECTED_MISCONFIGURATION',
  effective_value: false,
  detail: "KAI_VOICE_ENABLE is set in the environment but is NOT a declared setting — Settings uses " +
          "extra='ignore', so it is SILENTLY DROPPED and enables nothing. KAI_VOICE_ENABLED is unchanged " +
          "at its effective value False. Rename the variable to KAI_VOICE_ENABLED or unset it.",
};

const CLEAN = render(Object.assign({}, BASE, { flag_misconfigurations: [] }));
const WARNED = render(Object.assign({}, BASE, { flag_misconfigurations: [MISCONFIG] }));

test('every one of the nine authority flags renders its own deployed-vs-enabled row', () => {
  for (const f of FEATURES) assert.ok(CLEAN.includes(f.name), 'missing feature row: ' + f.name);
  assert.equal(badges(CLEAN, 'DISABLED'), FEATURES.length);
});

test('a flag that is ON renders ENABLED, one that is OFF renders DISABLED (deployed ≠ enabled)', () => {
  const on = FEATURES.map(f => { const e = f.runtime_flag === 'KAI_VOICE_ENABLED';
    return Object.assign({}, f, { runtime_enabled: e, flag_state: e ? 'ENABLED' : 'DISABLED' }); });
  const h = render(Object.assign({}, BASE, { features: on }));
  assert.equal(badges(h, 'ENABLED'), 1);
  assert.equal(badges(h, 'DISABLED'), FEATURES.length - 1);
});

test('a near-miss env var is surfaced LOUDLY — named, with the flag it was meant to be', () => {
  const t = textOf(WARNED);
  assert.ok(t.includes('CONFIG WARNING'), 'no CONFIG WARNING shown');
  assert.ok(t.includes('KAI_VOICE_ENABLE') && t.includes('KAI_VOICE_ENABLED'));
  assert.ok(t.includes('binds to nothing'));
  assert.ok(t.includes('SILENTLY DROPPED'), 'the detail explaining WHY it had no effect is not rendered');
});

test('the warning sits ABOVE the feature registry, so DISABLED is never read unexplained', () => {
  assert.ok(WARNED.indexOf('CONFIG WARNING') < WARNED.indexOf('Feature registry'),
            'warning renders below the registry it explains');
});

test('the warning states the flag is STILL OFF — it can never read as "took effect"', () => {
  assert.ok(textOf(WARNED).includes('KAI_VOICE_ENABLED still OFF'));
  assert.ok(!textOf(WARNED).includes('KAI_VOICE_ENABLED still ON'));
});

test('a misconfiguration never flips a feature row to ENABLED (fail closed in the UI too)', () => {
  assert.equal(badges(WARNED, 'ENABLED'), 0);
  assert.ok(WARNED.includes('Voice Command Center (§7)'));
});

test('no misconfiguration → no warning invented, and the panel is otherwise identical', () => {
  assert.ok(!CLEAN.includes('CONFIG WARNING'));
  assert.equal(CLEAN, render(Object.assign({}, BASE)));   // key absent behaves like []
});

test('the env var VALUE is never rendered (it may be a secret) — names only', () => {
  const h = render(Object.assign({}, BASE, { flag_misconfigurations: [
    Object.assign({}, MISCONFIG, { value: 's3cr3t' }) ] }));
  assert.ok(!h.includes('s3cr3t'));
});

test('the rendered warning is escaped — a hostile env var name cannot inject markup', () => {
  const h = render(Object.assign({}, BASE, { flag_misconfigurations: [
    Object.assign({}, MISCONFIG, { env_var: '<img src=x onerror=alert(1)>' }) ] }));
  assert.ok(!h.includes('<img src=x'), 'env var name rendered unescaped');
  assert.ok(h.includes('&lt;img'));
});

// ── Deployment state is READ from the payload, never assumed by the renderer ──────────────────────
// The panel used to print badge('READY','deployed') on every row unconditionally, so a build that had
// never been released anywhere still rendered as deployed. These pin the state to the backend's answer.
const withState = (state, over) => render(Object.assign({}, BASE, over || {}, {
  deployment_state: state,
  features: FEATURES.map(f => Object.assign({}, f, { deployment_state: state,
    deployed: state === 'LIVE_STAGING' || state === 'LIVE_PROD',
    deployment_reason: state === 'PRE_DEPLOY' ? 'no hosted route of this build has served a request yet' : '' })) }));

test('a PRE_DEPLOY build never renders as deployed or READY', () => {
  const h = withState('PRE_DEPLOY', { environment: 'development' });
  assert.equal(badges(h, 'READY'), 0, 'the panel still claims READY for an unreleased build');
  for (const claim of ['READY', 'LIVE_STAGING', 'LIVE_PROD'])
    assert.equal(badges(h, claim), 0, 'an unreleased build renders an affirmative claim: ' + claim);
  assert.ok(textOf(h).includes('not deployed here'), 'the row does not say it is undeployed');
  assert.equal(badges(h, 'PRE_DEPLOY'), FEATURES.length + 1, 'each row plus the header must show PRE_DEPLOY');
});

test('a PRE_DEPLOY row states WHY it is not deployed, so it is not read as an outage', () => {
  assert.ok(textOf(withState('PRE_DEPLOY')).includes('no hosted route of this build has served a request'));
});

test('a staging release is never rendered as a production one', () => {
  const h = withState('LIVE_STAGING', { environment: 'staging' });
  assert.equal(badges(h, 'LIVE_STAGING'), FEATURES.length + 1);
  assert.equal(badges(h, 'LIVE_PROD'), 0, 'a staging build renders as production');
});

test('a row with no deployment_state falls back to UNAVAILABLE, never to deployed', () => {
  const bare = FEATURES.map(f => { const c = Object.assign({}, f); delete c.deployment_state;
                                   delete c.deployed; return c; });
  const h = render(Object.assign({}, BASE, { features: bare }));
  assert.equal(badges(h, 'UNAVAILABLE'), FEATURES.length + 1);   // every row, plus the header
  assert.equal(badges(h, 'READY'), 0);
});

test('a flag that binds to nothing renders NOT_DECLARED, distinct from a real DISABLED', () => {
  const rows = FEATURES.map((f, i) => Object.assign({}, f,
    { flag_state: i === 0 ? 'NOT_DECLARED' : 'DISABLED', runtime_enabled: false }));
  const h = render(Object.assign({}, BASE, { features: rows }));
  assert.equal(badges(h, 'NOT_DECLARED'), 1);
  assert.equal(badges(h, 'DISABLED'), FEATURES.length - 1);
  assert.equal(badges(h, 'ENABLED'), 0, 'an undeclared flag must never render as enabled');
});

test('the header reports the release state beside the environment', () => {
  assert.ok(textOf(withState('LIVE_PROD', { environment: 'production' })).includes('release'));
});

console.log('\nDEPLOY PANEL (§7-10 flag state) TESTS: ' + pass + '/' + total + ' — ' + (pass === total ? 'PASS' : 'FAIL'));
if (pass !== total) process.exitCode = 1;
