/* KAI — Viseme / Coarticulation Engine (Phase 12, §8/§9). Pure UMD, no DOM.
 *
 * Turns a timed viseme/phoneme sequence into a coarticulated coefficient timeline, and
 * samples it at any time t → blended ARKit-compatible coefficients a KaiAvatarDriver
 * applies. Coarticulation model: each unit has a trapezoid weight (rise over `blend`
 * before its window, full during, fall over `blend` after) so adjacent units CROSS-FADE
 * — no snapping (§9). REST is the implicit zero baseline: the mouth relaxes to closed
 * whenever no unit is active (speech-end cleanup). Timing config lives in ONE place
 * (§9 — no magic numbers scattered in UI code).
 *
 * The rAF loop, audio clock, and coefficient→morph-target application live in the driver;
 * this module is pure so it is deterministically testable and GLB-agnostic.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./kai-viseme-mapper.js'));
  } else {
    root.KaiVisemeEngine = factory(root.KaiVisemeMapper);
  }
})(typeof self !== 'undefined' ? self : this, function (Mapper) {
  'use strict';

  var DEFAULT = { blendFrac: 0.45, minBlendMs: 25, maxBlendMs: 90 };

  function _clamp(v, lo, hi) { return v < lo ? lo : (v > hi ? hi : v); }
  function _blendMs(dur, cfg) { return _clamp(dur * cfg.blendFrac, cfg.minBlendMs, cfg.maxBlendMs); }

  // units: [{ viseme? | phoneme?, start(ms), dur(ms) }] → normalized timeline entries.
  function buildTimeline(units, opts) {
    var cfg = Object.assign({}, DEFAULT, opts || {});
    var out = [];
    for (var i = 0; i < (units || []).length; i++) {
      var u = units[i] || {};
      var vis = u.viseme || (Mapper ? Mapper.phonemeToViseme(u.phoneme) : 'REST');
      var dur = Math.max(1, u.dur || 0);
      out.push({
        viseme: vis,
        start: u.start || 0,
        dur: dur,
        blend: _blendMs(dur, cfg),
        coeffs: Mapper ? Mapper.visemeToCoefficients(vis) : {},
      });
    }
    return out;
  }

  // Even spacing helper: a bare viseme/phoneme list → timed units.
  function sequenceToUnits(seq, msEach, startAt) {
    var t = startAt || 0, out = [];
    for (var i = 0; i < (seq || []).length; i++) {
      var s = seq[i];
      var unit = (typeof s === 'string' && s === s.toUpperCase() && s.indexOf('_') === -1 && s.length <= 3 && Mapper && Mapper.VISEMES.indexOf(s) === -1)
        ? { phoneme: s } : (typeof s === 'string' ? { viseme: s } : s);
      unit.start = t; unit.dur = msEach; out.push(unit); t += msEach;
    }
    return out;
  }

  // trapezoid weight of a unit at time t (rise over blend before window, fall over blend after)
  function _weight(u, t) {
    var on = u.start, off = u.start + u.dur, b = u.blend;
    if (t <= on - b || t >= off + b) return 0;
    if (t < on) return (t - (on - b)) / b;        // rise
    if (t <= off) return 1;                         // full
    return 1 - (t - off) / b;                        // fall
  }

  function restCoeffs() { return Mapper ? Mapper.visemeToCoefficients('REST') : {}; }

  // Sample the timeline at t → { coeffs, viseme, active } (blended, REST-baselined).
  function sample(timeline, t) {
    var keys = Mapper ? Mapper.COEFF_KEYS : [];
    var ws = [], sum = 0, best = -1, bestW = 0;
    for (var i = 0; i < timeline.length; i++) {
      var w = _weight(timeline[i], t);
      ws.push(w); sum += w;
      if (w > bestW) { bestW = w; best = i; }
    }
    var scale = sum > 1 ? 1 / sum : 1;   // keep the additive blend within [0,1]
    var coeffs = {};
    for (var k = 0; k < keys.length; k++) {
      var key = keys[k], v = 0;
      for (var j = 0; j < timeline.length; j++) if (ws[j]) v += ws[j] * scale * (timeline[j].coeffs[key] || 0);
      coeffs[key] = _clamp(v, 0, 1);
    }
    return { coeffs: coeffs, viseme: bestW > 0 ? timeline[best].viseme : 'REST', active: bestW > 0 };
  }

  function timelineEnd(timeline) {
    var end = 0;
    for (var i = 0; i < timeline.length; i++) { var e = timeline[i].start + timeline[i].dur + timeline[i].blend; if (e > end) end = e; }
    return end;
  }

  return {
    DEFAULT: DEFAULT, buildTimeline: buildTimeline, sequenceToUnits: sequenceToUnits,
    sample: sample, restCoeffs: restCoeffs, timelineEnd: timelineEnd,
  };
});
