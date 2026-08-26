/* KAI — Viseme Mapper (Phase 12, §3/§4). Pure UMD, no DOM, driver-agnostic.
 *
 * Converts phonemes → visemes and visemes → NORMALIZED ARKit-compatible facial
 * coefficients (the §4 option-B "weighted combination of ARKit mouth shapes"
 * approach), so ANY KaiAvatarDriver (GLB blendshapes, or a 2D Lab rig) consumes the
 * same numbers. The GLB is plug-and-play: it maps these coefficient names to its own
 * morph targets. Coefficients are 0..1. Physical behavior (§12): MBP closes the lips
 * (jaw shut), FV tucks the lower lip to the upper teeth, O/U round the lips, A/AH
 * opens the jaw, REST rests the mouth closed.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.KaiVisemeMapper = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // Conceptual viseme classes (§4).
  var VISEMES = ['REST', 'A_AH', 'E', 'I', 'O', 'U', 'MBP', 'FV', 'TH', 'L', 'R', 'SZ', 'SH_CH_J', 'W_Q'];

  // The ARKit-compatible coefficient names a viseme may touch (§3 mouth/jaw subset).
  var COEFF_KEYS = ['jawOpen', 'mouthClose', 'mouthFunnel', 'mouthPucker',
    'mouthStretchLeft', 'mouthStretchRight', 'mouthUpperUpLeft', 'mouthUpperUpRight',
    'mouthLowerDownLeft', 'mouthLowerDownRight', 'mouthRollLower', 'mouthRollUpper',
    'mouthPressLeft', 'mouthPressRight', 'mouthShrugUpper'];

  function _z() { var o = {}; for (var i = 0; i < COEFF_KEYS.length; i++) o[COEFF_KEYS[i]] = 0; return o; }
  function _set(o, pairs) { for (var k in pairs) if (Object.prototype.hasOwnProperty.call(pairs, k)) o[k] = pairs[k]; return o; }
  function _sym(v) { return { mouthStretchLeft: v, mouthStretchRight: v }; }

  // viseme → coefficient preset (normalized). Tuned for the physical signatures above.
  var VISEME_COEFF = {
    REST: _z(),
    A_AH: _set(_z(), { jawOpen: 0.85, mouthLowerDownLeft: 0.25, mouthLowerDownRight: 0.25 }),
    E: _set(_z(), { jawOpen: 0.35, mouthStretchLeft: 0.55, mouthStretchRight: 0.55 }),
    I: _set(_z(), { jawOpen: 0.18, mouthStretchLeft: 0.7, mouthStretchRight: 0.7, mouthUpperUpLeft: 0.2, mouthUpperUpRight: 0.2 }),
    O: _set(_z(), { jawOpen: 0.5, mouthFunnel: 0.6, mouthPucker: 0.45 }),
    U: _set(_z(), { jawOpen: 0.22, mouthPucker: 0.85, mouthFunnel: 0.35 }),
    MBP: _set(_z(), { jawOpen: 0.0, mouthClose: 0.9, mouthPressLeft: 0.5, mouthPressRight: 0.5 }),   // lips visibly close
    FV: _set(_z(), { jawOpen: 0.12, mouthLowerDownLeft: 0.35, mouthLowerDownRight: 0.35, mouthRollLower: 0.6, mouthUpperUpLeft: 0.15, mouthUpperUpRight: 0.15 }), // lower lip → upper teeth
    TH: _set(_z(), { jawOpen: 0.28, mouthLowerDownLeft: 0.2, mouthLowerDownRight: 0.2, mouthRollLower: 0.25 }),
    L: _set(_z(), { jawOpen: 0.4, mouthUpperUpLeft: 0.25, mouthUpperUpRight: 0.25 }),
    R: _set(_z(), { jawOpen: 0.3, mouthFunnel: 0.3, mouthPucker: 0.25 }),
    SZ: _set(_z(), { jawOpen: 0.12, mouthStretchLeft: 0.4, mouthStretchRight: 0.4, mouthShrugUpper: 0.2 }),
    SH_CH_J: _set(_z(), { jawOpen: 0.2, mouthFunnel: 0.5, mouthPucker: 0.5 }),
    W_Q: _set(_z(), { jawOpen: 0.18, mouthPucker: 0.9, mouthFunnel: 0.3 }),
  };

  function visemeToCoefficients(viseme) {
    var base = VISEME_COEFF[viseme] || VISEME_COEFF.REST;
    var out = {};
    for (var k in base) if (Object.prototype.hasOwnProperty.call(base, k)) out[k] = base[k];
    return out;
  }

  // ARPABET-ish phoneme → viseme. Text→phoneme is a separate heuristic; this maps the
  // phoneme once you have it (from a provider timing or a grapheme heuristic).
  var PHONEME_VISEME = {
    // vowels
    AA: 'A_AH', AH: 'A_AH', AE: 'A_AH', AO: 'O', AW: 'O', AY: 'A_AH',
    EH: 'E', ER: 'R', EY: 'E', IH: 'I', IY: 'I', OW: 'O', OY: 'O', UH: 'U', UW: 'U',
    // consonants
    B: 'MBP', P: 'MBP', M: 'MBP',
    F: 'FV', V: 'FV',
    TH: 'TH', DH: 'TH',
    L: 'L', R: 'R', W: 'W_Q', Y: 'I',
    S: 'SZ', Z: 'SZ',
    SH: 'SH_CH_J', ZH: 'SH_CH_J', CH: 'SH_CH_J', JH: 'SH_CH_J',
    T: 'SZ', D: 'SZ', N: 'SZ', K: 'SZ', G: 'SZ', HH: 'A_AH', NG: 'SZ',
  };

  function phonemeToViseme(ph) {
    if (ph == null) return 'REST';
    var key = String(ph).toUpperCase().replace(/[0-9]/g, '');   // strip ARPABET stress digits
    return PHONEME_VISEME[key] || 'REST';
  }

  return {
    VISEMES: VISEMES, COEFF_KEYS: COEFF_KEYS,
    visemeToCoefficients: visemeToCoefficients, phonemeToViseme: phonemeToViseme,
  };
});
