/* KAI — Avatar Driver abstraction (Phase 12, §5/§6). Pure UMD (DOM via injected callbacks).
 *
 * ONE interface so Nexus components NEVER touch GLB morph targets directly (§5). Three
 * drivers, each reporting capabilities TRUTHFULLY (§6 — "Do not pretend"):
 *   - GLB  : production target; reports ASSET_UNAVAILABLE until the rigged .glb exists.
 *   - VIDEO: the current MP4 fallback; lip_sync/visemes/facial_rig/gaze/blink/head/
 *            breathing = false. Honest.
 *   - LAB  : a dev rig (SVG/canvas via an injected `apply` callback) that DOES support
 *            visemes/blink/gaze/expression, used to validate the engines. Labeled DEV.
 * The renderer (rAF loop, audio clock, morph application) lives at the call site and is
 * injected as callbacks, keeping this module DOM-free + deterministically testable.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(require('./kai-viseme-mapper.js'));
  else root.KaiAvatarDriver = factory(root.KaiVisemeMapper);
})(typeof self !== 'undefined' ? self : this, function (Mapper) {
  'use strict';

  var CAP_KEYS = ['state', 'lip_sync', 'visemes', 'facial_rig', 'gaze', 'blink', 'head_pose', 'breathing', 'expression'];
  function caps(overrides) {
    var c = {}; for (var i = 0; i < CAP_KEYS.length; i++) c[CAP_KEYS[i]] = false;
    return Object.assign(c, overrides || {});
  }
  var VIDEO_CAPS = caps({ state: true });   // only idle↔speak clip swap is real
  var GLB_CAPS = caps({ state: true, lip_sync: true, visemes: true, facial_rig: true, gaze: true, blink: true, head_pose: true, breathing: true, expression: true });
  var LAB_CAPS = caps({ state: true, visemes: true, blink: true, gaze: true, expression: true });   // dev harness; no true 3D head/breath

  var STATE_CLIP = { speaking: 'speak' };   // every other state → idle clip (video only has two)
  function stateToClip(s) { return STATE_CLIP[String(s || '').toLowerCase()] || 'idle'; }

  // ── VIDEO fallback ─────────────────────────────────────────────────────────
  function videoDriver(opts) {
    opts = opts || {};
    var diag = { kind: 'VIDEO', mode: 'FALLBACK_VIDEO', clip: 'idle', unsupportedCalls: {}, loaded: false };
    function unsupported(name) { diag.unsupportedCalls[name] = (diag.unsupportedCalls[name] || 0) + 1; }  // record, never fake
    return {
      kind: 'VIDEO',
      load: function () { diag.loaded = true; return Promise.resolve(); },
      unload: function () { diag.loaded = false; },
      setState: function (s) { var clip = stateToClip(s); diag.clip = clip; if (opts.setClip) opts.setClip(clip); },
      setViseme: function () { unsupported('setViseme'); },       // a video has no mouth rig — honest no-op
      applyCoeffs: function () { unsupported('applyCoeffs'); },    // sampled coeffs can't drive a video — recorded no-op, never throws
      setExpression: function () { unsupported('setExpression'); },
      blink: function () { unsupported('blink'); },
      setGaze: function () { unsupported('setGaze'); },
      setHeadPose: function () { unsupported('setHeadPose'); },
      setBreathing: function () { unsupported('setBreathing'); },
      returnToNeutral: function () { diag.clip = 'idle'; if (opts.setClip) opts.setClip('idle'); },
      getCapabilities: function () { return Object.assign({}, VIDEO_CAPS); },
      getDiagnostics: function () { return Object.assign({}, diag); },
    };
  }

  // ── LAB dev rig (drives an injected 2D face via opts.apply(coeffs)) ─────────
  function labDriver(opts) {
    opts = opts || {};
    var diag = { kind: 'LAB', mode: 'DEV_AVATAR', label: 'DEV AVATAR — NOT KAI PRODUCTION ASSET', loaded: false, lastViseme: 'REST', coeffs: {} };
    function apply() { if (opts.apply) opts.apply(diag.coeffs); }
    function merge(part) { for (var k in part) if (Object.prototype.hasOwnProperty.call(part, k)) diag.coeffs[k] = part[k]; }
    return {
      kind: 'LAB',
      load: function () { diag.loaded = true; return Promise.resolve(); },
      unload: function () { diag.loaded = false; },
      setState: function (s) { diag.state = s; },
      setViseme: function (v, weight) {
        diag.lastViseme = v;
        var base = Mapper ? Mapper.visemeToCoefficients(v) : {}, w = (weight == null ? 1 : weight);
        var c = {}; for (var k in base) c[k] = base[k] * w; diag.coeffs = c; apply();
      },
      applyCoeffs: function (coeffs) { diag.coeffs = Object.assign({}, coeffs); apply(); },   // for the viseme-engine sample output
      setExpression: function (name, weight) { var e = {}; /* expression coeffs merged by caller via idle-life */ if (opts.expression) { e = opts.expression(name, weight); merge(e); apply(); } diag.expression = name; },
      blink: function (side) { diag.lastBlink = side || 'both'; if (opts.blink) opts.blink(side); },
      setGaze: function (t) { diag.gaze = t; if (opts.gaze) opts.gaze(t); },
      setHeadPose: function (y, p, r) { diag.head = { yaw: y, pitch: p, roll: r }; if (opts.head) opts.head(y, p, r); },
      setBreathing: function (a) { diag.breathing = a; },
      returnToNeutral: function () { diag.coeffs = Mapper ? Mapper.visemeToCoefficients('REST') : {}; diag.lastViseme = 'REST'; apply(); },
      getCapabilities: function () { return Object.assign({}, LAB_CAPS); },
      getDiagnostics: function () { return Object.assign({}, diag); },
    };
  }

  // ── GLB production target (reports ASSET_UNAVAILABLE until the rigged .glb exists) ──
  function glbDriver(opts) {
    opts = opts || {};
    var hasAsset = !!opts.assetUrl;
    var diag = { kind: 'GLB', mode: hasAsset ? 'GLB' : 'ASSET_UNAVAILABLE', loaded: false, assetUrl: opts.assetUrl || null };
    return {
      kind: 'GLB',
      load: function () {
        if (!hasAsset) { diag.mode = 'ASSET_UNAVAILABLE'; return Promise.reject(new Error('ASSET_UNAVAILABLE')); }
        // loaded reflects a REAL successful load — never claim success before the loader resolves (§6)
        return Promise.resolve(opts.load ? opts.load(opts.assetUrl) : undefined).then(
          function (r) { diag.loaded = true; diag.mode = 'GLB'; return r; },
          function (e) { diag.loaded = false; diag.mode = 'ASSET_UNAVAILABLE'; throw e; });
      },
      unload: function () { diag.loaded = false; if (opts.unload) opts.unload(); },
      setState: function (s) { diag.state = s; if (opts.setState) opts.setState(s); },
      setViseme: function (v, w, t) { if (opts.setViseme) opts.setViseme(v, w, t); },
      applyCoeffs: function (c) { if (opts.applyCoeffs) opts.applyCoeffs(c); },
      setExpression: function (n, w) { if (opts.setExpression) opts.setExpression(n, w); },
      blink: function (s) { if (opts.blink) opts.blink(s); },
      setGaze: function (t) { if (opts.setGaze) opts.setGaze(t); },
      setHeadPose: function (y, p, r) { if (opts.setHeadPose) opts.setHeadPose(y, p, r); },
      setBreathing: function (a) { if (opts.setBreathing) opts.setBreathing(a); },
      returnToNeutral: function () { if (opts.returnToNeutral) opts.returnToNeutral(); },
      // capabilities are UNKNOWN until the asset loads + the inspector runs → all false when unavailable
      getCapabilities: function () { return hasAsset ? Object.assign({}, GLB_CAPS) : caps({}); },
      getDiagnostics: function () { return Object.assign({}, diag); },
    };
  }

  function createDriver(kind, opts) {
    switch (String(kind || '').toLowerCase()) {
      case 'glb': return glbDriver(opts);
      case 'lab': return labDriver(opts);
      case 'video': default: return videoDriver(opts);
    }
  }

  return {
    CAP_KEYS: CAP_KEYS, VIDEO_CAPS: VIDEO_CAPS, GLB_CAPS: GLB_CAPS, LAB_CAPS: LAB_CAPS,
    stateToClip: stateToClip, createDriver: createDriver,
    videoDriver: videoDriver, labDriver: labDriver, glbDriver: glbDriver,
  };
});
