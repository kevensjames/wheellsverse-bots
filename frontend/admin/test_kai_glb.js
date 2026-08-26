/* Node tests for kai-morph-registry.js + kai-glb-validator.js (mock GLB inventories).
 * Run: node test_kai_glb.js */
const assert = require('assert');
const MR = require('./kai-morph-registry.js');
const V = require('./kai-glb-validator.js');

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

function dictFrom(names) { const d = {}; names.forEach((n, i) => { d[n] = i; }); return d; }
const FULL_MORPHS = ['eyeBlinkLeft', 'eyeBlinkRight', 'jawOpen', 'mouthClose', 'mouthFunnel', 'mouthPucker',
  'mouthSmileLeft', 'mouthSmileRight', 'mouthFrownLeft', 'mouthFrownRight', 'mouthUpperUpLeft', 'mouthUpperUpRight',
  'mouthLowerDownLeft', 'mouthLowerDownRight', 'cheekPuff'];
const FULL_BONES = ['root', 'spine', 'chest', 'neck', 'head', 'leftEye', 'rightEye'];

// ── morph registry ───────────────────────────────────────────────────────────
test('EXACT match binds jawOpen', () => {
  const r = MR.buildMorphRegistry(dictFrom(['jawOpen', 'mouthClose']));
  assert.strictEqual(r.byCoeff.jawOpen.status, 'EXACT');
  assert.strictEqual(r.byCoeff.jawOpen.index, 0);
});
test('ALIASED match resolves an exported rename (jaw_open → jawOpen)', () => {
  const r = MR.buildMorphRegistry(dictFrom(['jaw_open', 'eyeBlink_L', 'eyeBlink_R']));
  assert.strictEqual(r.byCoeff.jawOpen.status, 'ALIASED');
  assert.strictEqual(r.byCoeff.jawOpen.via, 'jaw_open');
  assert.strictEqual(r.byCoeff.eyeBlinkLeft.status, 'ALIASED');
});
test('MISSING when neither exact nor alias present (never mis-bound)', () => {
  const r = MR.buildMorphRegistry(dictFrom(['somethingElse']));
  assert.strictEqual(r.byCoeff.jawOpen.status, 'MISSING');
  assert.strictEqual(r.byCoeff.jawOpen.index, -1);
});
test('DUPLICATE when two case-variant morphs collide', () => {
  const r = MR.buildMorphRegistry({ jawOpen: 0, JawOpen: 1 });
  assert.strictEqual(r.byCoeff.jawOpen.status, 'DUPLICATE');
});
test('applyCoeffs writes only resolved indices, clamps [0,1], skips MISSING', () => {
  const r = MR.buildMorphRegistry(dictFrom(['jawOpen', 'mouthClose']));   // indices 0,1
  const inf = [0, 0];
  MR.applyCoeffs(r, { jawOpen: 0.8, mouthClose: 2.0, mouthPucker: 0.5 }, inf);   // pucker MISSING → skipped
  assert.strictEqual(inf[0], 0.8);
  assert.strictEqual(inf[1], 1);   // clamped from 2.0
});

// ── bone registry ────────────────────────────────────────────────────────────
test('bones: FOUND / ALIASED / MISSING', () => {
  const b = MR.buildBoneRegistry(['Head', 'Spine_01', 'Hips']);
  assert.strictEqual(b.byBone.head.status, 'FOUND');       // Head → head (case-insensitive)
  assert.strictEqual(b.byBone.spine.status, 'ALIASED');    // Spine_01 → spine alias
  assert.strictEqual(b.byBone.root.status, 'ALIASED');     // Hips → root alias
  assert.strictEqual(b.byBone.leftEye.status, 'MISSING');
  assert.strictEqual(b.hasHead, true);
  assert.strictEqual(b.hasEyes, false);
});

// ── validator ────────────────────────────────────────────────────────────────
test('a full ARKit rig → PRODUCTION_READY', () => {
  const rep = V.validateKaiAvatarAsset({ loaded: true, meshCount: 3, triangles: 90000, materials: 4, textures: 6, boneNames: FULL_BONES, morphTargetDictionary: dictFrom(FULL_MORPHS) });
  assert.strictEqual(rep.blink, 'PASS'); assert.strictEqual(rep.jaw, 'PASS'); assert.strictEqual(rep.viseme, 'PASS');
  assert.strictEqual(rep.final, 'PRODUCTION_READY');
});
test('a rig with exported/aliased names still → PRODUCTION_READY', () => {
  const aliased = ['eyeBlink_L', 'eyeBlink_R', 'jaw_open', 'mouth_close', 'mouth_funnel', 'mouth_pucker',
    'mouth_smile_l', 'mouth_smile_r', 'mouth_frown_l', 'mouth_frown_r', 'mouth_upper_up_l', 'mouth_upper_up_r',
    'mouth_lower_down_l', 'mouth_lower_down_r', 'cheek_puff'];
  const rep = V.validateKaiAvatarAsset({ loaded: true, triangles: 80000, boneNames: FULL_BONES, morphTargetDictionary: dictFrom(aliased) });
  assert.strictEqual(rep.final, 'PRODUCTION_READY');
});
test('missing blink → REJECTED (no fake PASS)', () => {
  const noBlk = FULL_MORPHS.filter((m) => m.indexOf('eyeBlink') !== 0);
  const rep = V.validateKaiAvatarAsset({ loaded: true, triangles: 80000, boneNames: FULL_BONES, morphTargetDictionary: dictFrom(noBlk) });
  assert.strictEqual(rep.blink, 'FAIL');
  assert.strictEqual(rep.final, 'REJECTED');
});
test('missing jaw → REJECTED', () => {
  const noJaw = FULL_MORPHS.filter((m) => m !== 'jawOpen');
  const rep = V.validateKaiAvatarAsset({ loaded: true, triangles: 80000, boneNames: FULL_BONES, morphTargetDictionary: dictFrom(noJaw) });
  assert.strictEqual(rep.jaw, 'FAIL'); assert.strictEqual(rep.final, 'REJECTED');
});
test('asset that did not load → REJECTED, short-circuit', () => {
  const rep = V.validateKaiAvatarAsset({ loaded: false });
  assert.strictEqual(rep.load, 'FAIL'); assert.strictEqual(rep.final, 'REJECTED');
});
test('a partial rig (no eye bones, jaw+blink ok, sparse mouth) → not PRODUCTION_READY, honest PARTIAL', () => {
  const partial = ['eyeBlinkLeft', 'eyeBlinkRight', 'jawOpen', 'mouthClose', 'mouthFunnel', 'mouthPucker'];
  const rep = V.validateKaiAvatarAsset({ loaded: true, triangles: 80000, boneNames: ['head', 'neck', 'spine'], morphTargetDictionary: dictFrom(partial) });
  assert.notStrictEqual(rep.final, 'PRODUCTION_READY');
  assert.strictEqual(rep.eyes, 'PASS');   // blink present gives eyes PASS even without eye bones
  assert.ok(['PARTIAL', 'FAIL'].includes(rep.mouth));
});
test('excessive triangles → performance FAIL → REJECTED', () => {
  const rep = V.validateKaiAvatarAsset({ loaded: true, triangles: 2000000, boneNames: FULL_BONES, morphTargetDictionary: dictFrom(FULL_MORPHS) });
  assert.strictEqual(rep.performance, 'FAIL'); assert.strictEqual(rep.final, 'REJECTED');
});

console.log('\n' + pass + ' passed');
