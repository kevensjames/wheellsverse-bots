/* KAI — GLB Asset Validator (Phase 12, §21). Pure UMD, no Three.js, no DOM.
 *
 * validateKaiAvatarAsset(inventory) → a TRUTHFUL PASS/PARTIAL/FAIL report + a FINAL verdict
 * (PRODUCTION_READY / DEVELOPMENT_ONLY / REJECTED). A critical missing control never produces
 * a fake PASS (§8). `inventory` is the plain data a GLB loader yields (so this is testable
 * against mock inventories): { loaded, meshCount, triangles, materials, textures, boneNames[],
 * morphTargetDictionary{}, animations[] }.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./kai-morph-registry.js'));
  else root.KaiGLBValidator = factory(root.KaiMorphRegistry);
})(typeof self !== 'undefined' ? self : this, function (MR) {
  'use strict';

  var TRI_HIGH = 150000, TRI_WARN = 350000, TRI_MAX = 900000;

  function _present(reg, name) { var s = reg.byCoeff[name]; return !!(s && s.status !== 'MISSING'); }
  function _tri(v) { return v <= TRI_HIGH ? 'PASS' : v <= TRI_WARN ? 'WARN' : v <= TRI_MAX ? 'WARN' : 'FAIL'; }
  function _bar(n, total, hi, mid) { var f = total ? n / total : 0; return f >= hi ? 'PASS' : f >= mid ? 'PARTIAL' : 'FAIL'; }

  function validateKaiAvatarAsset(inv) {
    inv = inv || {};
    var out = { load: inv.loaded ? 'PASS' : 'FAIL' };
    if (!inv.loaded) return Object.assign(out, { final: 'REJECTED', reason: 'asset did not load' });

    var morph = MR.buildMorphRegistry(inv.morphTargetDictionary || {});
    var bone = MR.buildBoneRegistry(inv.boneNames || []);

    out.meshes = inv.meshCount || 0;
    out.triangles = inv.triangles || 0;
    out.materials = inv.materials || 0;
    out.textures = inv.textures || 0;
    out.bonesFound = Object.keys(bone.byBone).filter(function (b) { return bone.byBone[b].status !== 'MISSING'; }).length;
    out.morphsBound = morph.boundCount;
    out.duplicates = Object.keys(morph.byCoeff).filter(function (c) { return morph.byCoeff[c].status === 'DUPLICATE'; });

    // eyes: either eye bones OR eyeLook morphs give gaze
    var eyeBonesOk = bone.hasEyes;
    var blinkL = _present(morph, 'eyeBlinkLeft'), blinkR = _present(morph, 'eyeBlinkRight');
    out.blink = (blinkL && blinkR) ? 'PASS' : (blinkL || blinkR) ? 'PARTIAL' : 'FAIL';
    out.eyes = (eyeBonesOk || (blinkL && blinkR)) ? 'PASS' : (eyeBonesOk || blinkL || blinkR) ? 'PARTIAL' : 'FAIL';
    out.jaw = _present(morph, 'jawOpen') ? 'PASS' : 'FAIL';

    var mouthSet = ['mouthClose', 'mouthFunnel', 'mouthPucker', 'mouthSmileLeft', 'mouthSmileRight',
      'mouthUpperUpLeft', 'mouthUpperUpRight', 'mouthLowerDownLeft', 'mouthLowerDownRight'];
    var mouthN = mouthSet.filter(function (m) { return _present(morph, m); }).length;
    out.mouth = _bar(mouthN, mouthSet.length, 0.7, 0.4);

    out.head = bone.hasHead ? 'PASS' : 'FAIL';
    var upper = ['spine', 'chest'].filter(function (b) { return bone.byBone[b].status !== 'MISSING'; }).length;
    out.upperBody = upper === 2 ? 'PASS' : upper === 1 ? 'PARTIAL' : 'FAIL';

    var critN = MR.CRITICAL_MORPHS.length - morph.missingCritical.length;
    out.arkit = _bar(critN, MR.CRITICAL_MORPHS.length, 0.9, 0.5);
    // viseme capability: needs jaw + close + a rounding shape + most of the mouth set
    var visemeCore = _present(morph, 'jawOpen') && _present(morph, 'mouthClose') && (_present(morph, 'mouthFunnel') || _present(morph, 'mouthPucker'));
    out.viseme = (visemeCore && out.mouth === 'PASS') ? 'PASS' : (visemeCore ? 'PARTIAL' : 'FAIL');
    out.performance = _tri(out.triangles);

    // FINAL — a REJECTED gate on any hard-missing critical capability (no fake PASS)
    var hardFail = out.jaw === 'FAIL' || out.blink === 'FAIL' || out.mouth === 'FAIL' || out.arkit === 'FAIL' || out.performance === 'FAIL';
    var anyPartial = [out.eyes, out.mouth, out.head, out.upperBody, out.arkit, out.viseme].indexOf('PARTIAL') !== -1;
    var allCorePass = out.blink === 'PASS' && out.jaw === 'PASS' && out.mouth === 'PASS' && out.eyes === 'PASS' && out.head === 'PASS' && out.arkit === 'PASS' && out.viseme === 'PASS';
    out.final = hardFail ? 'REJECTED' : (allCorePass && out.performance === 'PASS') ? 'PRODUCTION_READY' : (anyPartial || out.performance === 'WARN') ? 'DEVELOPMENT_ONLY' : 'DEVELOPMENT_ONLY';
    out.missingCritical = morph.missingCritical;
    return out;
  }

  return { validateKaiAvatarAsset: validateKaiAvatarAsset, TRI_HIGH: TRI_HIGH, TRI_WARN: TRI_WARN };
});
