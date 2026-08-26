/* KAI — Morph Target + Bone Registry (Phase 12, §6-9). Pure UMD, no Three.js, no DOM.
 *
 * Resolves the ARKit coefficient names the viseme/idle engines emit to the ACTUAL morph
 * targets / bones a loaded GLB exposes, via EXPLICIT versioned aliases (Blender/export
 * pipelines rename freely). No fuzzy matching for critical facial controls (§7) — a
 * critical control is EXACT, ALIASED, MISSING, or DUPLICATE; never silently mis-bound.
 * Consumes plain data (morphTargetDictionary object, bone-name array) so it is fully
 * node-testable against mock GLTF inventories; the GLB renderer plugs the real data in.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.KaiMorphRegistry = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Critical facial controls a production KAI asset must support (§8).
  var CRITICAL_MORPHS = ['eyeBlinkLeft', 'eyeBlinkRight', 'jawOpen', 'mouthClose', 'mouthFunnel',
    'mouthPucker', 'mouthSmileLeft', 'mouthSmileRight', 'mouthFrownLeft', 'mouthFrownRight',
    'mouthUpperUpLeft', 'mouthUpperUpRight', 'mouthLowerDownLeft', 'mouthLowerDownRight', 'cheekPuff'];

  // Explicit, versioned aliases (§7). Lowercased comparison; the canonical name is first.
  var MORPH_ALIASES = {
    eyeBlinkLeft: ['eyeblink_l', 'blink_l', 'eyeblinkleft', 'eye_blink_left', 'eyes_closed_l'],
    eyeBlinkRight: ['eyeblink_r', 'blink_r', 'eyeblinkright', 'eye_blink_right', 'eyes_closed_r'],
    jawOpen: ['jaw_open', 'mouthopen', 'mouth_open', 'aa'],
    mouthClose: ['mouth_close', 'mouthclosed'],
    mouthFunnel: ['mouth_funnel'], mouthPucker: ['mouth_pucker', 'oo'],
    mouthSmileLeft: ['mouth_smile_l', 'smile_l', 'mouthsmileleft'],
    mouthSmileRight: ['mouth_smile_r', 'smile_r', 'mouthsmileright'],
    mouthFrownLeft: ['mouth_frown_l', 'frown_l'], mouthFrownRight: ['mouth_frown_r', 'frown_r'],
    mouthUpperUpLeft: ['mouth_upper_up_l'], mouthUpperUpRight: ['mouth_upper_up_r'],
    mouthLowerDownLeft: ['mouth_lower_down_l'], mouthLowerDownRight: ['mouth_lower_down_r'],
    mouthRollLower: ['mouth_roll_lower'], mouthRollUpper: ['mouth_roll_upper'],
    mouthStretchLeft: ['mouth_stretch_l'], mouthStretchRight: ['mouth_stretch_r'],
    mouthPressLeft: ['mouth_press_l'], mouthPressRight: ['mouth_press_r'],
    mouthShrugUpper: ['mouth_shrug_upper'], mouthShrugLower: ['mouth_shrug_lower'],
    cheekPuff: ['cheek_puff'], cheekSquintLeft: ['cheek_squint_l'], cheekSquintRight: ['cheek_squint_r'],
    browInnerUp: ['brow_inner_up'], browDownLeft: ['brow_down_l'], browDownRight: ['brow_down_r'],
    browOuterUpLeft: ['brow_outer_up_l'], browOuterUpRight: ['brow_outer_up_r'],
    noseSneerLeft: ['nose_sneer_l'], noseSneerRight: ['nose_sneer_r'],
  };

  function _lc(s) { return String(s).toLowerCase().replace(/\s+/g, ''); }

  // dict: { morphName: index } (Three.js morphTargetDictionary). Returns per-ARKit-name
  // { status: EXACT|ALIASED|MISSING|DUPLICATE, morph, index } + summaries.
  function buildMorphRegistry(dict, extraAliases) {
    dict = dict || {};
    var lcMap = {};        // lowercased morph name → [realNames...] (detect duplicates)
    Object.keys(dict).forEach(function (name) { var k = _lc(name); (lcMap[k] = lcMap[k] || []).push(name); });
    var aliases = Object.assign({}, MORPH_ALIASES);
    if (extraAliases) for (var a in extraAliases) aliases[a] = (aliases[a] || []).concat(extraAliases[a]);

    var byCoeff = {};
    var allCoeffs = Object.keys(aliases);
    // ensure every critical + aliased coeff is considered
    CRITICAL_MORPHS.forEach(function (c) { if (allCoeffs.indexOf(c) === -1) allCoeffs.push(c); });

    allCoeffs.forEach(function (coeff) {
      var lcCoeff = _lc(coeff);
      if (lcMap[lcCoeff]) {
        var real = lcMap[lcCoeff];
        byCoeff[coeff] = { status: real.length > 1 ? 'DUPLICATE' : 'EXACT', morph: real[0], index: dict[real[0]] };
        return;
      }
      var alts = aliases[coeff] || [];
      for (var i = 0; i < alts.length; i++) {
        var la = _lc(alts[i]);
        if (lcMap[la]) { var r = lcMap[la]; byCoeff[coeff] = { status: r.length > 1 ? 'DUPLICATE' : 'ALIASED', morph: r[0], index: dict[r[0]], via: alts[i] }; return; }
      }
      byCoeff[coeff] = { status: 'MISSING', morph: null, index: -1 };
    });

    var missingCritical = CRITICAL_MORPHS.filter(function (c) { return !byCoeff[c] || byCoeff[c].status === 'MISSING'; });
    var bound = Object.keys(byCoeff).filter(function (c) { return byCoeff[c].status !== 'MISSING'; }).length;
    return { byCoeff: byCoeff, missingCritical: missingCritical, boundCount: bound, criticalTotal: CRITICAL_MORPHS.length };
  }

  // Apply an ARKit coefficient frame into a morphTargetInfluences array (clamped [0,1]).
  // Missing coeffs are simply skipped — never mis-bound to another morph.
  function applyCoeffs(registry, coeffs, influences) {
    coeffs = coeffs || {};
    for (var coeff in coeffs) {
      var slot = registry.byCoeff[coeff];
      if (slot && slot.index >= 0 && slot.index < influences.length) {
        var v = coeffs[coeff]; influences[slot.index] = v < 0 ? 0 : (v > 1 ? 1 : v);
      }
    }
    return influences;
  }

  // ── bones (§9) ──────────────────────────────────────────────────────────────
  var CRITICAL_BONES = ['root', 'spine', 'chest', 'neck', 'head', 'leftEye', 'rightEye'];
  var BONE_ALIASES = {
    root: ['hips', 'armature', 'root_bone'], spine: ['spine', 'spine01', 'spine_01', 'spine1'],
    chest: ['chest', 'spine2', 'spine_02', 'upperchest', 'upper_chest'], neck: ['neck', 'neck_01'],
    head: ['head', 'head_01'], leftEye: ['lefteye', 'eye_l', 'eye.l', 'l_eye'], rightEye: ['righteye', 'eye_r', 'eye.r', 'r_eye'],
  };
  function buildBoneRegistry(boneNames, extraAliases) {
    var lcMap = {}; (boneNames || []).forEach(function (n) { lcMap[_lc(n)] = n; });
    var aliases = Object.assign({}, BONE_ALIASES);
    if (extraAliases) for (var a in extraAliases) aliases[a] = (aliases[a] || []).concat(extraAliases[a]);
    var byBone = {};
    CRITICAL_BONES.forEach(function (bone) {
      var lc = _lc(bone);
      if (lcMap[lc]) { byBone[bone] = { status: 'FOUND', bone: lcMap[lc] }; return; }
      var alts = aliases[bone] || [];
      for (var i = 0; i < alts.length; i++) { if (lcMap[_lc(alts[i])]) { byBone[bone] = { status: 'ALIASED', bone: lcMap[_lc(alts[i])], via: alts[i] }; return; } }
      byBone[bone] = { status: 'MISSING', bone: null };
    });
    return { byBone: byBone, hasHead: byBone.head.status !== 'MISSING', hasEyes: byBone.leftEye.status !== 'MISSING' && byBone.rightEye.status !== 'MISSING' };
  }

  return {
    CRITICAL_MORPHS: CRITICAL_MORPHS, MORPH_ALIASES: MORPH_ALIASES, CRITICAL_BONES: CRITICAL_BONES, BONE_ALIASES: BONE_ALIASES,
    buildMorphRegistry: buildMorphRegistry, applyCoeffs: applyCoeffs, buildBoneRegistry: buildBoneRegistry,
  };
});
