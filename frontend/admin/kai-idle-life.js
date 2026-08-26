/* KAI — Idle Life Engine (Phase 12, §10-14). Pure UMD, no DOM, driver-agnostic.
 *
 * The asset-independent "feel alive" brain: blink / breathing / micro-saccade / gaze /
 * head-drift / micro-expression SCHEDULING as pure, seeded (deterministic) logic. A
 * driver (GLB or Lab) calls these to know WHEN/HOW MUCH to move; this module never
 * renders. Bounded + randomized so no recognizable loop emerges (§6/§10). Frame-rate
 * independent: everything is expressed in ms / normalized amounts, sampled by clock.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.KaiIdleLife = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // deterministic PRNG (mulberry32) — seeded so tests are exact and idle life is reproducible
  function makeRng(seed) {
    var a = (seed >>> 0) || 1;
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // ── blink (§11): 2.5–7.5s randomized; single/double/slow/partial; never overlap ──
  var BLINK_KINDS = ['single', 'double', 'slow', 'partial'];
  function nextBlink(rng) {
    var r = rng(), kind = r < 0.72 ? 'single' : r < 0.84 ? 'double' : r < 0.94 ? 'slow' : 'partial';
    return { delayMs: Math.round(2500 + rng() * 5000), kind: kind };
  }
  function blinkDurationMs(kind) { return { single: 120, double: 320, slow: 260, partial: 90 }[kind] || 120; }
  // eyelid closure 0..1 over a blink's progress (0..1) — a driver maps to eyeBlink coeffs
  function blinkClosure(kind, p) {
    if (p <= 0 || p >= 1) return 0;
    if (kind === 'partial') return Math.sin(Math.PI * p) * 0.55;
    if (kind === 'double') { var q = (p * 2) % 1; return Math.sin(Math.PI * q); }
    return Math.sin(Math.PI * p);   // single / slow: full closure at mid
  }

  // ── breathing (§12): 3.5–5.5s eased sinusoid, normalized 0..1 ────────────────
  function breathePeriod(rng) { return Math.round(3500 + rng() * 2000); }
  function breathe(tMs, periodMs) {
    if (!periodMs) return 0;
    return (1 - Math.cos((2 * Math.PI * tMs) / periodMs)) / 2;   // 0 at t=0 and t=period, 1 at mid
  }

  // ── micro-saccades (§10/§13): frequent tiny eye offsets ──────────────────────
  var MAX_SACCADE = 0.08;   // normalized eye offset
  function nextSaccade(rng) {
    return { delayMs: Math.round(200 + rng() * 1000), dx: (rng() * 2 - 1) * MAX_SACCADE, dy: (rng() * 2 - 1) * MAX_SACCADE };
  }

  // ── gaze (§13): bounded discrete targets → normalized yaw/pitch (-1..1) ───────
  var GAZE = {
    USER: { yaw: 0, pitch: 0.02 }, COMMAND: { yaw: 0, pitch: -0.35 },
    LEFT: { yaw: -0.6, pitch: 0 }, RIGHT: { yaw: 0.6, pitch: 0 }, UP: { yaw: 0, pitch: 0.5 }, DOWN: { yaw: 0, pitch: -0.4 },
    MISSION: { yaw: -0.3, pitch: -0.2 }, SYSTEMS: { yaw: 0.4, pitch: -0.15 }, INTELLIGENCE: { yaw: 0.5, pitch: 0.1 },
    SECURITY: { yaw: 0.55, pitch: -0.1 }, AGENTS: { yaw: -0.4, pitch: 0.1 }, MEMORY: { yaw: -0.5, pitch: -0.1 }, ALERT: { yaw: 0, pitch: 0.3 },
  };
  function gazeVector(target) { var g = GAZE[String(target || 'USER').toUpperCase()] || GAZE.USER; return { yaw: g.yaw, pitch: g.pitch }; }

  // ── head drift (§16): very small stabilization motion ────────────────────────
  var MAX_HEAD_DEG = 2.5;
  function nextHeadDrift(rng) {
    return {
      yaw: (rng() * 2 - 1) * MAX_HEAD_DEG, pitch: (rng() * 2 - 1) * MAX_HEAD_DEG, roll: (rng() * 2 - 1) * (MAX_HEAD_DEG * 0.5),
      durMs: Math.round(1500 + rng() * 2500),
    };
  }

  // ── micro-expressions (§14/§15): weighted facial-coefficient presets (eyes untouched) ──
  var EXPRESSIONS = {
    neutral: {},
    attentive: { browInnerUp: 0.15, browOuterUpLeft: 0.1, browOuterUpRight: 0.1 },
    curious: { browInnerUp: 0.25, browOuterUpLeft: 0.2, browOuterUpRight: 0.05, mouthSmileLeft: 0.08 },
    focused: { browDownLeft: 0.2, browDownRight: 0.2, mouthPressLeft: 0.15, mouthPressRight: 0.15 },
    warm: { mouthSmileLeft: 0.35, mouthSmileRight: 0.35, cheekSquintLeft: 0.2, cheekSquintRight: 0.2 },
    confident: { mouthSmileLeft: 0.18, mouthSmileRight: 0.18, browInnerUp: 0.05 },
    concerned: { browInnerUp: 0.4, browDownLeft: 0.1, browDownRight: 0.1, mouthFrownLeft: 0.15, mouthFrownRight: 0.15 },
    serious: { browDownLeft: 0.25, browDownRight: 0.25, mouthPressLeft: 0.1, mouthPressRight: 0.1 },
  };
  function expressionCoefficients(name) {
    var base = EXPRESSIONS[String(name || 'neutral').toLowerCase()] || EXPRESSIONS.neutral, out = {};
    for (var k in base) if (Object.prototype.hasOwnProperty.call(base, k)) out[k] = base[k];
    return out;
  }
  function expressionNames() { return Object.keys(EXPRESSIONS); }

  return {
    makeRng: makeRng,
    BLINK_KINDS: BLINK_KINDS, nextBlink: nextBlink, blinkDurationMs: blinkDurationMs, blinkClosure: blinkClosure,
    breathePeriod: breathePeriod, breathe: breathe,
    MAX_SACCADE: MAX_SACCADE, nextSaccade: nextSaccade,
    gazeVector: gazeVector, MAX_HEAD_DEG: MAX_HEAD_DEG, nextHeadDrift: nextHeadDrift,
    expressionCoefficients: expressionCoefficients, expressionNames: expressionNames,
  };
});
