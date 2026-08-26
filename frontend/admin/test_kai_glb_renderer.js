/* Node tests for kai-glb-renderer.js — mock THREE + mock GLTFLoader (no WebGL, no real GLB).
 * Run: node test_kai_glb_renderer.js */
const assert = require('assert');
const R = require('./kai-glb-renderer.js');

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

function makeTHREE() {
  function Vec() {} Vec.prototype.set = function () { return this; };
  function Renderer(o) { this.o = o; this.disposed = 0; } Renderer.prototype.dispose = function () { this.disposed++; };
  function Scene() { this.children = []; }
  Scene.prototype.add = function (x) { this.children.push(x); };
  Scene.prototype.remove = function (x) { const i = this.children.indexOf(x); if (i !== -1) this.children.splice(i, 1); };
  function Cam() { this.position = new Vec(); }
  function DLight() { this.position = new Vec(); }
  function ALight() {}
  return { WebGLRenderer: Renderer, Scene: Scene, PerspectiveCamera: Cam, DirectionalLight: DLight, AmbientLight: ALight };
}
function makeCanvas() {
  return {
    _l: {}, addEventListener: function (t, fn) { this._l[t] = fn; },
    removeEventListener: function (t, fn) { if (this._l[t] === fn) delete this._l[t]; },
    fire: function (t, e) { this._l[t] && this._l[t](e || { preventDefault: function () {} }); },
  };
}
function tex() { return { disposed: 0, dispose: function () { this.disposed++; } }; }
function morphMesh(dict, infl, materialExtra) {
  const material = Object.assign({ disposed: 0, dispose: function () { this.disposed++; }, map: tex() }, materialExtra || {});
  return { morphTargetDictionary: dict, morphTargetInfluences: infl, geometry: { disposed: 0, dispose: function () { this.disposed++; } }, material: material };
}
function plainMesh() { return { geometry: { disposed: 0, dispose: function () { this.disposed++; } }, material: { disposed: 0, dispose: function () { this.disposed++; } } }; }
function gltfWith(nodes) { return { scene: { traverse: function (cb) { nodes.forEach(cb); } } }; }
function bone(name) { return { isBone: true, name: name }; }
function loaderFactory(gltf, mode) {
  return function () { this.load = function (url, onLoad, onProg, onErr) { if (mode === 'error') onErr(new Error('net')); else onLoad(gltf); }; };
}
// a loader that DEFERS onLoad until the test fires it (to exercise dispose-during-load)
function deferredLoader() {
  const box = { fire: null };
  const F = function () { this.load = function (url, onLoad) { box.fire = function () { onLoad(box.gltf); }; }; };
  F.box = box;
  return F;
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
  const mesh = morphMesh({ jawOpen: 0, mouthClose: 1 }, [0, 0]);
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(gltfWith([mesh, bone('head'), bone('leftEye')])) }).init();
  await r.load('kai.glb');
  assert.strictEqual(r.state, 'READY');
  assert.strictEqual(r.morphRegistry.byCoeff.jawOpen.status, 'EXACT');
  assert.strictEqual(r.boneRegistry.hasHead, true);
});
test('a GLB with NO blendshapes → FAILED (refuses to fake a lip-syncable avatar)', async () => {
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(gltfWith([plainMesh(), bone('head')])) }).init();
  await assert.rejects(r.load('empty.glb'));
  assert.strictEqual(r.state, 'FAILED');
  assert.strictEqual(r.error, 'no_morph_mesh');
});
test('a morph mesh with an EMPTY dict is not a fake bind → no_morph_mesh, not READY', async () => {
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(gltfWith([morphMesh({}, []), bone('head')])) }).init();
  await assert.rejects(r.load('degenerate.glb'));
  assert.strictEqual(r.state, 'FAILED');
});
test('a morph mesh with only NON-critical shapes → no_critical_morphs (no fake READY)', async () => {
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(gltfWith([morphMesh({ browOuterUpLeft: 0, noseSneerLeft: 1 }, [0, 0])])) }).init();
  await assert.rejects(r.load('nocrit.glb'));
  assert.strictEqual(r.error, 'no_critical_morphs');
});
test('the FACE mesh (most critical morphs) wins over a teeth/eyelash morph mesh ordered first', async () => {
  const teeth = morphMesh({ browInnerUp: 0 }, [0]);                // 1 non-critical morph, traversed FIRST
  const face = morphMesh({ jawOpen: 0, mouthClose: 1, eyeBlinkLeft: 2, eyeBlinkRight: 3 }, [0, 0, 0, 0]);
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(gltfWith([teeth, face])) }).init();
  await r.load('kai.glb');
  assert.strictEqual(r.mesh, face, 'the mesh binding the most critical morphs is chosen');
  assert.strictEqual(r.morphRegistry.byCoeff.jawOpen.status, 'EXACT');
});
test('loader error → FAILED, not READY', async () => {
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(null, 'error') }).init();
  await assert.rejects(r.load('x.glb'));
  assert.strictEqual(r.state, 'FAILED');
});

// ── §11 invariant ──────────────────────────────────────────────────────────
test('applyCoeffs writes morph influences only when READY; no-op otherwise', async () => {
  const infl = [0, 0];
  const mesh = morphMesh({ jawOpen: 0, mouthClose: 1 }, infl);
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(gltfWith([mesh])) }).init();
  assert.strictEqual(r.applyCoeffs({ jawOpen: 0.9 }), false, 'no influence before READY');
  await r.load('kai.glb');
  assert.strictEqual(r.applyCoeffs({ jawOpen: 0.9, mouthClose: 0.2 }), true);
  assert.strictEqual(infl[0], 0.9);
  assert.strictEqual(infl[1], 0.2);
});

// ── WebGL context loss ───────────────────────────────────────────────────────
test('context loss fires the fallback exactly once', () => {
  let calls = [];
  const canvas = makeCanvas();
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: canvas, onFallback: (why) => calls.push(why) }).init();
  canvas.fire('webglcontextlost');
  canvas.fire('webglcontextlost');
  assert.deepStrictEqual(calls, ['webgl_context_lost']);
  assert.strictEqual(r.getState().contextLost, true);
});
test('context loss AFTER dispose does not fire fallback (listener removed)', () => {
  let calls = [];
  const canvas = makeCanvas();
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: canvas, onFallback: (why) => calls.push(why) }).init();
  r.dispose();
  canvas.fire('webglcontextlost');   // listener should be gone; even if not, _onContextLost guards on DISPOSED
  assert.deepStrictEqual(calls, [], 'a disposed renderer never fires fallback');
});

// ── velocity-limited, clamped head/eye control ────────────────────────────────
test('approach() eases toward target under the velocity cap and never overshoots', () => {
  assert.strictEqual(R.approach(0, 1, 2.5, 0.1), 0.25);
  assert.strictEqual(R.approach(0.9, 1, 2.5, 0.1), 1);
  assert.strictEqual(R.approach(0, -1, 2.5, 0.1), -0.25);
});
test('setHeadTarget/setGazeTarget clamp to plausible ranges; tick eases, no jump', () => {
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas() }).init();
  r.setHeadTarget(10, 10);
  assert.strictEqual(r._target.headYaw, R.LIMITS.headYaw);
  assert.strictEqual(r._target.headPitch, R.LIMITS.headPitch);
  const p1 = r.tick(16);
  assert.ok(p1.headYaw > 0 && p1.headYaw < R.LIMITS.headYaw, 'eases, not a jump');
  for (let i = 0; i < 200; i++) r.tick(16);
  assert.ok(Math.abs(r._pose.headYaw - R.LIMITS.headYaw) < 1e-6, 'converges to clamped target');
});

// ── disposal accounting ────────────────────────────────────────────────────────
test('dispose() releases every tracked resource once + removes root; idempotent', async () => {
  const mesh = morphMesh({ jawOpen: 0 }, [0]);
  const scene = makeTHREE();
  const r = new R.KaiGLBRenderer({ THREE: scene, canvas: makeCanvas(), GLTFLoader: loaderFactory(gltfWith([mesh])) }).init();
  await r.load('kai.glb');
  const rootAdded = r.scene.children.length;
  const n = r.dispose();             // renderer + geometry + material + material.map = 4
  assert.strictEqual(n, 4);
  assert.strictEqual(r.state, 'DISPOSED');
  assert.strictEqual(mesh.geometry.disposed, 1);
  assert.strictEqual(mesh.material.disposed, 1);
  assert.strictEqual(mesh.material.map.disposed, 1);
  assert.ok(rootAdded > 0, 'root was added');
  assert.strictEqual(r.applyCoeffs({ jawOpen: 1 }), false, 'no apply after dispose');
  assert.strictEqual(r.dispose(), 4, 'double dispose does not double-count');
});
test('dispose() releases ALL PBR texture maps + ALL meshes, not just .map of the face', async () => {
  const nMap = tex(), rMap = tex(), eMap = tex();
  const face = morphMesh({ jawOpen: 0 }, [0], { normalMap: nMap, roughnessMap: rMap, emissiveMap: eMap });
  const sibling = plainMesh();       // a second mesh added to the scene must also be released
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(gltfWith([face, sibling])) }).init();
  await r.load('kai.glb');
  r.dispose();
  assert.strictEqual(nMap.disposed, 1, 'normalMap disposed');
  assert.strictEqual(rMap.disposed, 1, 'roughnessMap disposed');
  assert.strictEqual(eMap.disposed, 1, 'emissiveMap disposed');
  assert.strictEqual(face.material.map.disposed, 1, 'base map disposed');
  assert.strictEqual(sibling.geometry.disposed, 1, 'sibling geometry disposed');
  assert.strictEqual(sibling.material.disposed, 1, 'sibling material disposed');
});
test('shared textures are disposed once, not per-referencing-material', async () => {
  const shared = tex();
  const face = morphMesh({ jawOpen: 0 }, [0], { normalMap: shared });
  face.material.map = shared;        // same texture used by two slots
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: loaderFactory(gltfWith([face])) }).init();
  await r.load('kai.glb');
  r.dispose();
  assert.strictEqual(shared.disposed, 1, 'a shared texture is disposed exactly once');
});

// ── async-dispose race (dispose while a load is in flight) ─────────────────────
test('dispose during an in-flight load: DISPOSED stays terminal, resources freed, no READY', async () => {
  const L = deferredLoader();
  const mesh = morphMesh({ jawOpen: 0 }, [0]);
  L.box.gltf = gltfWith([mesh]);
  const r = new R.KaiGLBRenderer({ THREE: makeTHREE(), canvas: makeCanvas(), GLTFLoader: L }).init();
  const p = r.load('kai.glb');       // LOADING, onLoad deferred
  r.dispose();                       // teardown before the loader resolves
  L.box.fire();                      // the loader finally resolves → hits the DISPOSED branch → rejects
  await assert.rejects(p);           // the pending load rejects with 'disposed'
  assert.strictEqual(r.getState().state, 'DISPOSED', 'a late onLoad must NOT resurrect to READY');
  assert.strictEqual(mesh.geometry.disposed, 1, 'resources bound by the late onLoad are still freed (no leak)');
});

console.log('\n' + pass + ' passed');
