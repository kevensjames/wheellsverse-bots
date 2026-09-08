// KAI Computer Operations panel contract. Runs the REAL renderers lifted out of
// computer-ops.html -- no browser, no network -- and proves the panel cannot mislead an
// operator about what the machine is doing.
//
// The properties under test are the ones a dashboard gets wrong in exactly the ways this
// project has already had to correct: inventing a value when the backend did not answer,
// showing READY because something is installed, and blurring "the worker says it worked"
// into "it worked".
//
// Run: node test_computer_ops_panel.js
const assert = require('assert');
const fs = require('fs');

const HTML = fs.readFileSync(__dirname + '/computer-ops.html', 'utf8');
const slice = (start, end) => {
  const i = HTML.indexOf(start);
  assert.ok(i >= 0, 'computer-ops.html no longer contains: ' + start);
  return HTML.slice(i, HTML.indexOf(end, i) + end.length);
};
const fn = name => slice('function ' + name + '(', '\n}\n');

const SRC = [
  // esc spans two lines; slice to the end of its expression, not the first newline.
  slice('const esc = s =>', "}[c]));"),
  slice('const failed = d =>', '\n'),
  slice('const STATE = {', '\n};'),
  slice('const ICON = {', '\n'),
  fn('badge'), fn('unavailable'),
  slice('const row = (k,v)', '\n'), slice('const mono = v', '\n'),
  fn('renderOverview'), fn('renderReadiness'), fn('renderSecurity'), fn('renderDevices'), fn('renderMissions'),
].join('\n');

let DEVICES = [], MISSIONS = [];
const ctx = new Function('DEVICES', 'MISSIONS', SRC + `
  return {badge, unavailable, renderOverview, renderReadiness, renderSecurity, renderDevices, renderMissions};
`)(DEVICES, MISSIONS);

let pass = 0, fail = 0;
const t = (name, f) => { try { f(); console.log('  ok  ' + name); pass++; }
                         catch (e) { console.log('  FAIL ' + name + '  -> ' + e.message); fail++; } };

// ---------------------------------------------------------------- honesty
t('unavailable backend never renders data, and says why', () => {
  const out = ctx.renderOverview({ __unavailable: true, __http: 403 });
  assert.ok(/FORBIDDEN \(403\)/.test(out), out.slice(0, 120));
  assert.ok(!/READY/.test(out), 'rendered READY for a failed response');
});

t('feature disabled renders as disabled, not empty', () => {
  const out = ctx.renderOverview({ __unavailable: true, __http: 404 });
  assert.ok(/FEATURE DISABLED/.test(out));
  assert.ok(/KAI_COMPUTER_OPS_ENABLED/.test(out), 'does not name the flag');
});

t('network failure is distinguished from an auth failure', () => {
  assert.ok(/OFFLINE/.test(ctx.renderOverview({ __unavailable: true, __err: 'timeout' })));
  assert.ok(/NOT AUTHORISED/.test(ctx.renderOverview({ __unavailable: true, __http: 401 })));
});

t('panel never invents READY -- it echoes the server feature_state', () => {
  const degraded = ctx.renderOverview({
    feature_state: 'DEGRADED', degradation_reason: 'local model UNAVAILABLE',
    backend_state: 'READY', connector_state: 'OFFLINE', harness: {}, model: {}, containment: {} });
  assert.ok(/DEGRADED/.test(degraded));
  assert.ok(/local model UNAVAILABLE/.test(degraded), 'degradation reason not shown');
});

t('containment caveat is always rendered with the containment type', () => {
  const out = ctx.renderOverview({ feature_state: 'READY', harness: {}, model: {},
    containment: { type: 'macOS Seatbelt + per-mission APFS volume',
                   caveat: 'NOT A HYPERVISOR BOUNDARY' } });
  assert.ok(/NOT A HYPERVISOR BOUNDARY/.test(out), 'caveat missing');
});

t('pin drift is shown loudly', () => {
  const out = ctx.renderOverview({ feature_state: 'DEGRADED', model: {}, containment: {},
    harness: { state: 'DEGRADED', pinned_sha: 'c389f96bf3a9', actual_sha: 'deadbeef' } });
  assert.ok(/PIN DRIFT/.test(out), 'drift not surfaced');
});

// ------------------------------------------------- worker claim vs KAI verdict
t('a worker success claim is never rendered as verified completion', () => {
  const out = ctx.renderMissions({ missions: [{
    mission_id: 'cop-1', status: 'RUNNING', autonomy_mode: 'OBSERVE', device_id: 'devabc123',
    objective: 'x', worker_claimed_success: true, kai_verified_complete: false }] });
  assert.ok(/CLAIMED SUCCESS/.test(out), 'claim not shown');
  assert.ok(/NOT VERIFIED/.test(out), 'unverified state not shown');
  assert.ok(out.indexOf('CLAIMED SUCCESS') !== out.indexOf('VERIFIED'), 'claim and verdict conflated');
});

t('KAI verified completion renders distinctly', () => {
  const out = ctx.renderMissions({ missions: [{
    mission_id: 'cop-2', status: 'COMPLETED', autonomy_mode: 'OBSERVE', device_id: 'd',
    objective: 'x', worker_claimed_success: true, kai_verified_complete: true }] });
  assert.ok(/VERIFIED/.test(out));
});

// --------------------------------------------------------------- escaping
t('hostile mission text cannot inject markup', () => {
  const out = ctx.renderMissions({ missions: [{
    mission_id: '<img src=x onerror=alert(1)>', status: 'RUNNING', autonomy_mode: 'OBSERVE',
    device_id: 'd', objective: '"><script>alert(2)</script>',
    worker_claimed_success: false, kai_verified_complete: false }] });
  assert.ok(!/<img src=x/.test(out), 'raw img tag survived escaping');
  assert.ok(!/<script>alert\(2\)/.test(out), 'raw script survived escaping');
  assert.ok(/&lt;img/.test(out) && /&lt;script&gt;/.test(out), 'not escaped as entities');
});

t('hostile device fields cannot inject markup', () => {
  const out = ctx.renderDevices({ devices: [{
    device_id: 'd1', name: '<b>pwn</b>', status: 'ACTIVE', fingerprint: 'A-B-C-D',
    os: '<i>x</i>', arch: 'arm64', granted_scopes: ['<script>x</script>'],
    credential_age_seconds: 10 }], elevated_scopes: [] });
  assert.ok(!/<b>pwn<\/b>/.test(out) && !/<script>x/.test(out), 'markup survived');
});

// --------------------------------------------------------------- devices
t('no device renders an explicit empty state that explains enrollment', () => {
  const out = ctx.renderDevices({ devices: [], elevated_scopes: [] });
  assert.ok(/No device enrolled/.test(out));
  assert.ok(/grants no desktop/.test(out), 'does not state that enrollment grants nothing');
});

t('a pending device shows the fingerprint comparison instruction', () => {
  const out = ctx.renderDevices({ devices: [{
    device_id: 'd1', name: 'Mac', status: 'PENDING_CONFIRMATION', fingerprint: 'AAAA-BBBB',
    granted_scopes: [], credential_age_seconds: 0 }], elevated_scopes: [] });
  assert.ok(/Compare this fingerprint/.test(out), 'no comparison instruction');
  assert.ok(/Confirm enrollment/.test(out));
});

t('elevated scopes are offered individually, never as a bundle', () => {
  const elevated = ['computer.desktop.observe', 'computer.desktop.interact', 'computer.workspace.write'];
  const out = ctx.renderDevices({ devices: [{
    device_id: 'd1', name: 'Mac', status: 'ACTIVE', fingerprint: 'A-B',
    granted_scopes: ['computer.health.read'], credential_age_seconds: 0 }],
    elevated_scopes: elevated });
  elevated.forEach(s => assert.ok(out.includes('Activate ' + s), 'missing individual activation for ' + s));
  assert.ok(!/Activate all/i.test(out), 'offers a bundle activation');
});

// -------------------------------------------------------------- security
t('security panel reports desktop and browser truthfully', () => {
  const out = ctx.renderSecurity({
    desktop: { state: 'DESKTOP_CONTROL_NOT_VERIFIED', tcc_granted: false,
               executable_identity_acceptable: false, required_bundle_id: 'com.wheellsverse.kai.desktopbridge' },
    browser: { state: 'UNAVAILABLE', reason: 'ModuleNotFoundError', display: 'UNAVAILABLE - LOCAL CONNECTOR PLAYWRIGHT NOT INSTALLED' },
    voice: { state: 'VOICE_ENTRY_UNAVAILABLE' }, stop: { engaged: false } });
  assert.ok(/DESKTOP_CONTROL_NOT_VERIFIED/.test(out));
  assert.ok(/IDENTITY REFUSED/.test(out), 'refused helper identity not surfaced');
  assert.ok(/NOT GRANTED/.test(out), 'TCC state not surfaced');
  assert.ok(/PLAYWRIGHT NOT INSTALLED/.test(out));
  assert.ok(/VOICE_ENTRY_UNAVAILABLE/.test(out));
});

t('engaged STOP is unmistakable', () => {
  const out = ctx.renderSecurity({ desktop: {}, browser: {}, voice: {},
                                   stop: { engaged: true, reason: 'operator' } });
  assert.ok(/ENGAGED/.test(out));
});

// ------------------------------------------------------- static contract
t('every badge carries an icon as well as colour', () => {
  ['READY', 'FAILED', 'DEGRADED', 'QUEUED'].forEach(s => {
    assert.ok(/aria-hidden="true"/.test(ctx.badge(s)), 'badge ' + s + ' has no icon');
  });
});

t('STOP control lives outside the mission view and is always in the DOM', () => {
  assert.ok(/class="stopbar"/.test(HTML), 'no fixed stop bar');
  assert.ok(HTML.indexOf('btn-stop') < HTML.indexOf('id="mission-detail"') ||
            /position:fixed/.test(slice('.stopbar{', '}')), 'stop bar is not fixed');
});

t('page declares accessibility affordances', () => {
  assert.ok(/class="skip"/.test(HTML), 'no skip link');
  assert.ok(/:focus-visible/.test(HTML), 'no visible focus style');
  assert.ok(/aria-labelledby/.test(HTML), 'sections not labelled');
  assert.ok(/role="status"/.test(HTML), 'no live region for loading');
  assert.ok(/@media \(max-width:900px\)/.test(HTML), 'no mobile layout');
});

t('destructive actions require confirmation', () => {
  const js = slice("document.addEventListener('click'", '\n});');
  ['btn-stop', 'd.revoke', 'd.cancel', 'd.scopeDev'].forEach(k =>
    assert.ok(js.includes(k), 'handler missing for ' + k));
  assert.ok((js.match(/confirmed\(/g) || []).length >= 5, 'not enough confirmation gates');
});

t('the panel never marks a mission complete client-side', () => {
  const js = slice('"use strict";', '</script>');
  assert.ok(!/kai_verified_complete\s*=/.test(js), 'panel assigns verification locally');
  assert.ok(!/status\s*=\s*['"]COMPLETED/.test(js), 'panel sets COMPLETED locally');
});


// ------------------------------------------------------------- live events
t('SSE is preferred but polling is a real fallback, not a stub', () => {
  const js = slice('function startStream(', '\n}\n');
  assert.ok(/EventSource/.test(js), 'no SSE path');
  assert.ok(/typeof EventSource === 'undefined'/.test(js), 'no unsupported-browser fallback');
  assert.ok(/setInterval\(\(\) => pollEvents/.test(js), 'no polling fallback');
});

t('a stream error falls back rather than retrying silently', () => {
  const js = slice('function startStream(', '\n}\n');
  assert.ok(/es\.onerror/.test(js), 'no error handler');
  assert.ok(/es\.close\(\)/.test(js), 'does not close the failed stream');
  assert.ok(/STREAM_MODE = 'error'/.test(js), 'does not surface the error state');
});

t('the stream mode is always visible to the operator', () => {
  const js = slice('function streamStatusLine(', '\n}\n');
  ['LIVE (SSE)', 'POLLING FALLBACK', 'STREAM ERROR'].forEach(l =>
    assert.ok(js.includes(l), 'missing state label: ' + l));
});

t('a missed-events window is reported, never hidden', () => {
  const js = slice('function appendEvents(', '\n}\n');
  assert.ok(/Replay window exceeded/.test(js), 'truncation not surfaced');
  assert.ok(/class = 'err'/.test(js) || /className = 'err'/.test(js), 'not surfaced as an error');
});

t('the cursor only ever advances', () => {
  const js = slice('function appendEvents(', '\n}\n');
  assert.ok(/e\.seq > STREAM_CURSOR/.test(js), 'cursor can move backwards');
});

t('event payloads are escaped before display', () => {
  const js = slice('function appendEvents(', '\n}\n');
  assert.ok(/esc\(e\.type\)/.test(js) && /esc\(JSON\.stringify/.test(js),
            'event fields rendered unescaped');
});

t('the event log is a live region for assistive tech', () => {
  assert.ok(/id="event-log"[^>]*aria-live="polite"/.test(HTML) ||
            /aria-live="polite"[^>]*id="event-log"/.test(HTML) ||
            /role="log"/.test(HTML), 'event log is not announced');
});


// ---------------------------------------------------------- readiness axes
t('readiness is seven separate axes, never one badge', () => {
  const out = ctx.renderReadiness({
    readiness: {backend:'READY', connector:'READY', signed_helper:'BLOCKED_CODESIGNING_IDENTITY',
                tcc:'NOT_GRANTED', computer_control:'DEVICE_CONTROL_NOT_VERIFIED',
                stop:'RELEASED', staging:'STAGING_NOT_DEPLOYED'},
    computer_control: {blockers:['signed helper not verified','TCC not granted'], note:'n'},
    signed_helper: {adhoc:true}});
  ['Backend','Connector','Signed helper','TCC','Computer control','STOP','Staging']
    .forEach(a => assert.ok(out.includes(a), 'missing axis: ' + a));
});

t('a live connector does NOT make computer control green', () => {
  const out = ctx.renderReadiness({
    readiness: {backend:'READY', connector:'READY', signed_helper:'BLOCKED_CODESIGNING_IDENTITY',
                tcc:'NOT_GRANTED', computer_control:'DEVICE_CONTROL_NOT_VERIFIED',
                stop:'RELEASED', staging:'STAGING_NOT_DEPLOYED'},
    computer_control: {blockers:['signed helper not verified','TCC not granted'], note:'n'},
    signed_helper: {adhoc:true}});
  assert.ok(/DEVICE_CONTROL_NOT_VERIFIED/.test(out), 'control state not shown');
  assert.ok(!/DEVICE_CONTROL_VERIFIED</.test(out.replace(/DEVICE_CONTROL_NOT_VERIFIED/g,'')),
            'showed verified control while blocked');
  assert.ok(/blocked by/.test(out), 'blockers not listed');
});

t('a cdhash-pinned helper is called out as unsafe to grant', () => {
  const out = ctx.renderReadiness({
    readiness:{}, computer_control:{blockers:[],note:''},
    signed_helper:{adhoc:true, cdhash_pinned:true, designated_requirement:'# designated => cdhash H"abc"'}});
  assert.ok(/cdhash/.test(out), 'DR not surfaced');
  assert.ok(/Do not grant TCC/.test(out), 'no explicit warning against granting TCC');
});

t('staging status is reported, never assumed', () => {
  const out = ctx.renderReadiness({readiness:{staging:'STAGING_NOT_DEPLOYED'},
                                   computer_control:{blockers:[],note:''}, signed_helper:{}});
  assert.ok(/STAGING_NOT_DEPLOYED/.test(out));
});

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
