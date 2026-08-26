/* Node tests for kai-glb-renderer.js — mock THREE + mock GLTFLoader (no WebGL, no real GLB).
 * Run: node test_kai_glb_renderer.js */
const assert = require('assert');
const R = require('./kai-glb-renderer.js');

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

function makeTHREE() {
  function Vec() {} Vec.prototype.set = function () { return this; };
  function Renderer(o) { this.o = o; this.disposed = 0; } Renderer.prototype.dispose = function () { this.disposed++; };
  function Scene() { this.children = []; } Scene.prototype.add = function (x) { this.children.push(x); };
  function Cam() { this.position = new Vec(); }
  function DLight() { this.position = new Vec(); }
  function ALight() {}
  return { WebGLRenderer: Renderer, Scene: Scene, PerspectiveCamera: Cam, DirectionalLight: DLight, AmbientLight: ALight };
}
function makeCanvas() {
  return { _l: {}, addEventListener: function (t, fn) { this._l[t] = fn; }, fire: function (t, e) { this._l[t] && this._l[t](e || { preventDefault: function () {} }); } };
}
function morphMesh(dict, infl) {
  return {
    morphTargetDictionary: dict, morphTargetInfluences: infl,
    geometry: { disposed: 0, dispose: function () { this.disposed++; } },
    material: { disposed: 0, dispose: function () { this.disposed++; }, map: { disposed: 0, dispose: function () { this.disposed++; } } },
  };
}
function gltfWith(mesh, bones) {
  var nodes = []; if (mesh) nodes.push(mesh); (bones || []).forEach(function (b) { nodes.push({ isBone: true, name: b }); });
  return { scene: { traverse: function (cb) { nodes.forEach(cb); } } };
}
function loaderFactory(gltf, mode) {
  return function () { this.load = function (url, onLoad, onProg, onErr) { if (mode === 'error') onErr(new Error('net')); else onLoad(gltf); }; };
}

// ── state machine ────────────────────────────────────────────────────────────
test('no THREE/canvas → init FAILED (never a silent partial scene)', () => {
  const r = new R.KaiGLBRenderer({ THREE: null, canvas: null }).init();
  assert.strictEqual(r.state, 'FAILED');
});
test('init builds the scene but stays UNINITIALIZED until a GLB binds (no premature READY)', () => {
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas() }).init();
  assert.strictEqual(r.state, 'UNINITIALIZED');
  assert.ok(r.scene && r.renderer && r.camera);
});
test('load success → READY only after a morph-bearing mesh binds; registries populated', async () => {
  const infl = [0, 0];
  const mesh = morphMesh({ jawOpen: 0, mouthClose: 1 }, infl);
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(gltfWith(mesh, ['head', 'leftEye'])) }).init();
  await r.load('kai.glb');
  assert.strictEqual(r.state, 'READY');
  assert.strictEqual(r.morphRegistry.byCoeff.jawOpen.status, 'EXACT');
  assert.strictEqual(r.boneRegistry.hasHead, true);
});
test('a GLB with NO blendshapes → FAILED (refuses to fake a lip-syncable avatar)', async () => {
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(gltfWith(null, ['head'])) }).init();
  await assert.rejects(r.load('empty.glb'));
  assert.strictEqual(r.state, 'FAILED');
  assert.strictEqual(r.error, 'no_morph_mesh');
});
test('loader error → FAILED, not READY', async () => {
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(null, 'error') }).init();
  await assert.rejects(r.load('x.glb'));
  assert.strictEqual(r.state, 'FAILED');
});

// ── §11 invariant: the same coeff frame drives influences via the registry ──────
test('applyCoeffs writes morph influences only when READY; no-op otherwise', async () => {
  const infl = [0, 0];
  const mesh = morphMesh({ jawOpen: 0, mouthClose: 1 }, infl);
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(gltfWith(mesh, [])) }).init();
  assert.strictEqual(r.applyCoeffs({ jawOpen: 0.9 }), false, 'no influence before READY');
  await r.load('kai.glb');
  assert.strictEqual(r.applyCoeffs({ jawOpen: 0.9, mouthClose: 0.2 }), true);
  assert.strictEqual(infl[0], 0.9);   // same numbers the Lab would apply
  assert.strictEqual(infl[1], 0.2);
});

// ── WebGL context loss → fallback to the video avatar ──────────────────────────
test('context loss fires the fallback exactly once', () => {
  let calls = [];
  const canvas = makeCanvas();
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: canvas, onFallback: (why) => calls.push(why) }).init();
  canvas.fire('webglcontextlost');
  canvas.fire('webglcontextlost');   // a second event must not re-trigger
  assert.deepStrictEqual(calls, ['webgl_context_lost']);
  assert.strictEqual(r.getState().contextLost, true);
});

// ── velocity-limited, clamped head/eye control (no snapping) ────────────────────
test('approach() eases toward target under the velocity cap and never overshoots', () => {
  assert.strictEqual(R.approach(0, 1, 2.5, 0.1), 0.25);        // one step = rate*dt
  assert.strictEqual(R.approach(0.9, 1, 2.5, 0.1), 1);         // within a step → lands exactly (no overshoot)
  assert.strictEqual(R.approach(0, -1, 2.5, 0.1), -0.25);
});
test('setHeadTarget/setGazeTarget clamp to plausible ranges; tick eases, no jump', () => {
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas() }).init();
  r.setHeadTarget(10, 10);           // absurd request
  assert.strictEqual(r._target.headYaw, R.LIMITS.headYaw);
  assert.strictEqual(r._target.headPitch, R.LIMITS.headPitch);
  const p1 = r.tick(16);             // ~1 frame
  assert.ok(p1.headYaw > 0 && p1.headYaw < R.LIMITS.headYaw, 'eases, not a jump to target');
  for (let i = 0; i < 200; i++) r.tick(16);   // enough frames to converge
  assert.ok(Math.abs(r._pose.headYaw - R.LIMITS.headYaw) < 1e-6, 'converges to clamped target');
});

// ── disposal accounting ────────────────────────────────────────────────────────
test('dispose() releases every tracked GPU resource exactly once and goes terminal', async () => {
  const mesh = morphMesh({ jawOpen: 0 }, [0]);
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(gltfWith(mesh, [])) }).init();
  await r.load('kai.glb');
  const n = r.dispose();             // renderer + geometry + material + material.map = 4
  assert.strictEqual(n, 4);
  assert.strictEqual(r.state, 'DISPOSED');
  assert.strictEqual(mesh.geometry.disposed, 1);
  assert.strictEqual(mesh.material.disposed, 1);
  assert.strictEqual(mesh.material.map.disposed, 1);
  assert.strictEqual(r.applyCoeffs({ jawOpen: 1 }), false, 'no apply after dispose');
  assert.strictEqual(r.dispose(), 4, 'double dispose does not double-count');
});

console.log('\n' + pass + ' passed');
