/* Node tests for kai-viseme-mapper.js + kai-viseme-engine.js.
 * Run: node test_kai_viseme.js */
const assert = require('assert');
const M = require('./kai-viseme-mapper.js');
const E = require('./kai-viseme-engine.js');

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }
const inRange = (o) => Object.keys(o).every((k) => o[k] >= 0 && o[k] <= 1);

// ── mapper: physical viseme signatures (§12) ─────────────────────────────────
test('every viseme maps to coefficients in [0,1]', () => {
  for (const v of M.VISEMES) assert.ok(inRange(M.visemeToCoefficients(v)), 'out of range: ' + v);
});
test('MBP closes the lips (mouthClose high, jaw shut)', () => {
  const c = M.visemeToCoefficients('MBP');
  assert.ok(c.mouthClose >= 0.6, 'lips should close'); assert.strictEqual(c.jawOpen, 0);
});
test('A_AH opens the jaw', () => { assert.ok(M.visemeToCoefficients('A_AH').jawOpen >= 0.6); });
test('U and W_Q round/pucker the lips', () => {
  assert.ok(M.visemeToCoefficients('U').mouthPucker >= 0.6);
  assert.ok(M.visemeToCoefficients('W_Q').mouthPucker >= 0.6);
});
test('FV tucks the lower lip (lower-down + roll), jaw nearly shut', () => {
  const c = M.visemeToCoefficients('FV');
  assert.ok(c.mouthRollLower >= 0.4 && (c.mouthLowerDownLeft >= 0.2)); assert.ok(c.jawOpen <= 0.2);
});
test('REST relaxes the mouth (all zero)', () => {
  const c = M.visemeToCoefficients('REST'); assert.ok(Object.keys(c).every((k) => c[k] === 0));
});
test('phoneme → viseme mapping incl. ARPABET stress-digit stripping + unknown→REST', () => {
  assert.strictEqual(M.phonemeToViseme('M'), 'MBP');
  assert.strictEqual(M.phonemeToViseme('AA1'), 'A_AH');   // stress digit stripped
  assert.strictEqual(M.phonemeToViseme('F'), 'FV');
  assert.strictEqual(M.phonemeToViseme('UW'), 'U');
  assert.strictEqual(M.phonemeToViseme('S'), 'SZ');
  assert.strictEqual(M.phonemeToViseme('???'), 'REST');
  assert.strictEqual(M.phonemeToViseme(null), 'REST');
});

// ── engine: timeline + sampling ──────────────────────────────────────────────
test('buildTimeline maps phoneme units to visemes', () => {
  const tl = E.buildTimeline([{ phoneme: 'M', start: 0, dur: 100 }, { phoneme: 'AA', start: 100, dur: 100 }]);
  assert.strictEqual(tl[0].viseme, 'MBP'); assert.strictEqual(tl[1].viseme, 'A_AH');
});
test('sample at a lone unit center returns that viseme (weight 1)', () => {
  const tl = E.buildTimeline([{ viseme: 'A_AH', start: 0, dur: 200 }]);
  const s = E.sample(tl, 100);
  assert.strictEqual(s.viseme, 'A_AH');
  assert.ok(Math.abs(s.coeffs.jawOpen - 0.85) < 1e-9);
});
test('sample before/after the timeline is REST (mouth closes — speech-end cleanup)', () => {
  const tl = E.buildTimeline([{ viseme: 'A_AH', start: 100, dur: 100 }]);
  const before = E.sample(tl, 0), after = E.sample(tl, E.timelineEnd(tl) + 50);
  assert.ok(!before.active && before.coeffs.jawOpen === 0);
  assert.ok(!after.active && after.coeffs.jawOpen === 0);
});
test('COARTICULATION: MBP→A_AH crossfades (blends, never snaps)', () => {
  const tl = E.buildTimeline([{ viseme: 'MBP', start: 0, dur: 120 }, { viseme: 'A_AH', start: 120, dur: 120 }]);
  const s = E.sample(tl, 120);   // the boundary — both units partly weighted
  // jawOpen strictly between MBP(0) and A_AH(0.85); mouthClose strictly between MBP(0.9) and A_AH(0)
  assert.ok(s.coeffs.jawOpen > 0.01 && s.coeffs.jawOpen < 0.84, 'jaw should be mid-transition: ' + s.coeffs.jawOpen);
  assert.ok(s.coeffs.mouthClose > 0.01 && s.coeffs.mouthClose < 0.89, 'lips should be mid-transition: ' + s.coeffs.mouthClose);
});
test('no snapping: samples are continuous across a boundary', () => {
  const tl = E.buildTimeline([{ viseme: 'MBP', start: 0, dur: 120 }, { viseme: 'A_AH', start: 120, dur: 120 }]);
  const a = E.sample(tl, 119).coeffs.jawOpen, b = E.sample(tl, 121).coeffs.jawOpen;
  assert.ok(Math.abs(a - b) < 0.15, 'jawOpen should not jump across the boundary: ' + a + ' -> ' + b);
});
test('additive REST baseline: a single unit RAMPS in (smooth attack, not instant)', () => {
  const tl = E.buildTimeline([{ viseme: 'A_AH', start: 100, dur: 200 }]);
  const midRise = E.sample(tl, 100 - tl[0].blend / 2).coeffs.jawOpen;   // halfway up the rise
  const full = E.sample(tl, 200).coeffs.jawOpen;
  assert.ok(midRise > 0 && midRise < full, 'attack should ramp: ' + midRise + ' < ' + full);
});
test('overlapping units keep every coefficient within [0,1]', () => {
  const tl = E.buildTimeline([{ viseme: 'A_AH', start: 0, dur: 80 }, { viseme: 'O', start: 40, dur: 80 }, { viseme: 'U', start: 80, dur: 80 }]);
  for (let t = 0; t <= E.timelineEnd(tl); t += 7) {
    const c = E.sample(tl, t).coeffs;
    for (const k in c) assert.ok(c[k] >= 0 && c[k] <= 1, 'coeff out of range at t=' + t + ' ' + k + '=' + c[k]);
  }
});

console.log('\n' + pass + ' passed');
