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
test('glb caps are NOT advertised from a mere assetUrl — only after a verified load (§6/§8)', () => {
  const g = D.createDriver('glb', { assetUrl: '/admin/nexus-assets/kai-avatar-v1.glb', load: () => Promise.resolve('ok') });
  const before = g.getCapabilities();
  for (const k of ['lip_sync', 'visemes', 'facial_rig']) assert.strictEqual(before[k], false, 'no caps before a verified load');
  return g.load().then(() => {
    const caps = g.getCapabilities();
    for (const k of ['lip_sync', 'visemes', 'facial_rig', 'gaze', 'blink', 'head_pose', 'breathing']) assert.strictEqual(caps[k], true);
    assert.strictEqual(g.getDiagnostics().mode, 'GLB');
  });
});
test('glb with an assetUrl but NO loader/renderer → refuses to claim loaded (no_loader)', () => {
  const g = D.createDriver('glb', { assetUrl: '/x.glb' });   // nothing can actually load it
  assert.strictEqual(g.getCapabilities().lip_sync, false);
  return g.load().then(() => { throw new Error('should reject'); }, () => {
    assert.strictEqual(g.getDiagnostics().loaded, false);
    assert.strictEqual(g.getDiagnostics().mode, 'ASSET_UNAVAILABLE');
  });
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

// ── GLB driver bound to a KaiGLBRenderer (production drop-in contract) ─────────
function fakeRenderer(mode) {
  return {
    state: 'UNINITIALIZED', applied: [], disposed: 0, gaze: null, head: null,
    getState: function () { return { state: this.state }; },
    load: function (url) { var self = this; return mode === 'fail' ? Promise.reject(new Error('load_error')) : Promise.resolve().then(function () { self.state = 'READY'; self._url = url; }); },
    applyCoeffs: function (c) { this.applied.push(c); return this.state === 'READY'; },
    setGazeTarget: function (x, y) { this.gaze = { x: x, y: y }; },
    setHeadTarget: function (y, p) { this.head = { yaw: y, pitch: p }; },
    dispose: function () { this.disposed++; this.state = 'DISPOSED'; },
  };
}
test('glb+renderer: caps all-false until READY, then only what the renderer DELIVERS (no dead caps)', () => {
  const rnd = fakeRenderer();
  const g = D.createDriver('glb', { assetUrl: '/kai.glb', renderer: rnd });
  assert.strictEqual(g.getCapabilities().lip_sync, false, 'no caps before a real bind');
  assert.strictEqual(g.getDiagnostics().renderer, true);
  return g.load().then(() => {
    const caps = g.getCapabilities();
    // morph-coefficient caps the renderer genuinely applies:
    for (const k of ['lip_sync', 'visemes', 'facial_rig', 'blink', 'expression']) assert.strictEqual(caps[k], true, k + ' delivered via applyCoeffs');
    // bone-driven caps NOT wired in the renderer yet → honestly false (§8, no advertised-but-dead cap):
    for (const k of ['gaze', 'head_pose', 'breathing']) assert.strictEqual(caps[k], false, k + ' must not be advertised');
    assert.strictEqual(g.getDiagnostics().loaded, true);
    assert.strictEqual(g.getDiagnostics().mode, 'GLB');
  });
});
test('glb+renderer: applyCoeffs / setViseme / setGaze / setHeadPose route to the renderer (§11)', () => {
  const rnd = fakeRenderer();
  const g = D.createDriver('glb', { assetUrl: '/kai.glb', renderer: rnd });
  return g.load().then(() => {
    g.applyCoeffs({ jawOpen: 0.7 });
    assert.deepStrictEqual(rnd.applied[rnd.applied.length - 1], { jawOpen: 0.7 });
    g.setViseme('MBP', 1);                       // renderer path: setViseme is REAL (mapped → applyCoeffs), not a no-op
    const last = rnd.applied[rnd.applied.length - 1];
    assert.ok(last && Object.keys(last).length > 0 && last.jawOpen !== 0.7, 'setViseme drove morphs via the renderer');
    g.setGaze({ x: 0.5, y: -0.2 });
    g.setHeadPose(0.3, 0.1, 0);
    assert.deepStrictEqual(rnd.gaze, { x: 0.5, y: -0.2 });
    assert.deepStrictEqual(rnd.head, { yaw: 0.3, pitch: 0.1 });
    g.unload();
    assert.strictEqual(rnd.disposed, 1, 'unload disposes the renderer');
  });
});
test('glb+renderer: a renderer load failure keeps loaded=false / ASSET_UNAVAILABLE (no fake success)', () => {
  const g = D.createDriver('glb', { assetUrl: '/kai.glb', renderer: fakeRenderer('fail') });
  return g.load().then(() => { throw new Error('should reject'); }, () => {
    assert.strictEqual(g.getDiagnostics().loaded, false);
    assert.strictEqual(g.getDiagnostics().mode, 'ASSET_UNAVAILABLE');
    assert.strictEqual(g.getCapabilities().visemes, false);
  });
});

console.log('\n' + pass + ' passed');
