/* Node tests for kai-avatar-driver.js — the driver abstraction + TRUTHFUL capabilities.
 * Run: node test_kai_avatar_driver.js */
const assert = require('assert');
const D = require('./kai-avatar-driver.js');

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

// ── VIDEO fallback tells the truth (§6B — "Do not pretend") ──────────────────
test('video caps report NO lip-sync / visemes / rig / gaze / blink / head / breathing', () => {
  const c = D.VIDEO_CAPS;
  for (const k of ['lip_sync', 'visemes', 'facial_rig', 'gaze', 'blink', 'head_pose', 'breathing']) assert.strictEqual(c[k], false, k + ' must be false for video');
  assert.strictEqual(c.state, true);
});
test('video.setViseme is an honest NO-OP that records "unsupported" (never fakes lip-sync)', () => {
  let applied = null;
  const v = D.createDriver('video', { setClip: (clip) => { applied = clip; } });
  v.setViseme('MBP', 1); v.blink(); v.setGaze('USER');
  const diag = v.getDiagnostics();
  assert.ok(diag.unsupportedCalls.setViseme >= 1 && diag.unsupportedCalls.blink >= 1);
  assert.strictEqual(applied, null, 'no clip change from an unsupported call');
});
test('video.setState swaps the clip (speaking→speak, else idle)', () => {
  let clip = null; const v = D.createDriver('video', { setClip: (c) => { clip = c; } });
  v.setState('speaking'); assert.strictEqual(clip, 'speak');
  v.setState('thinking'); assert.strictEqual(clip, 'idle');
  v.returnToNeutral(); assert.strictEqual(clip, 'idle');
});

// ── LAB dev rig drives an injected 2D face + is clearly labeled DEV ──────────
test('lab caps support visemes/blink/gaze/expression; labeled DEV; drives apply()', () => {
  const c = D.LAB_CAPS;
  assert.ok(c.visemes && c.blink && c.gaze && c.expression);
  let coeffs = null; const lab = D.createDriver('lab', { apply: (x) => { coeffs = x; } });
  lab.setViseme('A_AH', 1);
  assert.ok(coeffs && coeffs.jawOpen >= 0.8, 'lab applies mapper coeffs');
  assert.ok(lab.getDiagnostics().label.indexOf('DEV') !== -1, 'must be labeled DEV — not production');
});

// ── GLB production target is honest about ASSET_UNAVAILABLE ───────────────────
test('glb with no asset → ASSET_UNAVAILABLE, load rejects, capabilities all false', () => {
  const g = D.createDriver('glb', {});
  assert.strictEqual(g.getDiagnostics().mode, 'ASSET_UNAVAILABLE');
  const caps = g.getCapabilities();
  for (const k of ['lip_sync', 'visemes', 'facial_rig', 'blink']) assert.strictEqual(caps[k], false);
  return g.load().then(() => { throw new Error('load should reject without an asset'); }, (e) => { assert.ok(/ASSET_UNAVAILABLE/.test(e.message)); });
});
test('glb WITH an asset reports full capabilities (plug-and-play)', () => {
  const g = D.createDriver('glb', { assetUrl: '/admin/nexus-assets/kai-avatar-v1.glb' });
  const caps = g.getCapabilities();
  for (const k of ['lip_sync', 'visemes', 'facial_rig', 'gaze', 'blink', 'head_pose', 'breathing']) assert.strictEqual(caps[k], true);
  assert.strictEqual(g.getDiagnostics().mode, 'GLB');
});
test('glb with an asset whose loader REJECTS must NOT claim loaded (no pretend)', () => {
  const g = D.createDriver('glb', { assetUrl: '/x.glb', load: () => Promise.reject(new Error('404')) });
  return g.load().then(() => { throw new Error('should reject'); }, () => {
    const diag = g.getDiagnostics();
    assert.strictEqual(diag.loaded, false, 'a failed load must not report loaded');
    assert.strictEqual(diag.mode, 'ASSET_UNAVAILABLE', 'a failed load reverts to ASSET_UNAVAILABLE');
  });
});
test('glb with an asset whose loader RESOLVES marks loaded only after success', () => {
  const g = D.createDriver('glb', { assetUrl: '/x.glb', load: () => Promise.resolve('ok') });
  assert.strictEqual(g.getDiagnostics().loaded, false, 'not loaded before load() resolves');
  return g.load().then(() => { assert.strictEqual(g.getDiagnostics().loaded, true); });
});
test('video.applyCoeffs is a recorded no-op (never throws when fed sampled coeffs)', () => {
  const v = D.createDriver('video', {});
  v.applyCoeffs({ jawOpen: 0.8 });   // must not throw
  assert.ok(v.getDiagnostics().unsupportedCalls.applyCoeffs >= 1);
});
test('createDriver dispatches by kind; default is video', () => {
  assert.strictEqual(D.createDriver('glb', { assetUrl: 'x' }).kind, 'GLB');
  assert.strictEqual(D.createDriver('lab', {}).kind, 'LAB');
  assert.strictEqual(D.createDriver('video', {}).kind, 'VIDEO');
  assert.strictEqual(D.createDriver(undefined, {}).kind, 'VIDEO');
});

console.log('\n' + pass + ' passed');
