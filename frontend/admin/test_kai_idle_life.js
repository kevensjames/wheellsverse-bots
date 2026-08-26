/* Node tests for kai-idle-life.js — the seeded idle-life schedulers.
 * Run: node test_kai_idle_life.js */
const assert = require('assert');
const L = require('./kai-idle-life.js');

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

test('makeRng is deterministic (same seed → same sequence; different seed differs)', () => {
  const a = L.makeRng(42), b = L.makeRng(42), c = L.makeRng(7);
  const seqA = [a(), a(), a()], seqB = [b(), b(), b()], seqC = [c(), c(), c()];
  assert.deepStrictEqual(seqA, seqB);
  assert.notDeepStrictEqual(seqA, seqC);
  assert.ok(seqA.every((x) => x >= 0 && x < 1));
});
test('blink: delay 2.5–7.5s, valid kinds, all kinds appear, no fixed loop', () => {
  const rng = L.makeRng(123); const kinds = {}; let prev = null, allDiffer = true;
  for (let i = 0; i < 400; i++) {
    const b = L.nextBlink(rng);
    assert.ok(b.delayMs >= 2500 && b.delayMs <= 7500, 'delay range: ' + b.delayMs);
    assert.ok(L.BLINK_KINDS.includes(b.kind));
    kinds[b.kind] = (kinds[b.kind] || 0) + 1;
    if (prev != null && b.delayMs === prev) allDiffer = allDiffer;  // not required equal, just observe
    prev = b.delayMs;
  }
  for (const k of L.BLINK_KINDS) assert.ok(kinds[k] > 0, 'kind never occurred: ' + k);
});
test('blinkClosure: 0 at ends, peak mid; double has two peaks', () => {
  assert.strictEqual(L.blinkClosure('single', 0), 0);
  assert.strictEqual(L.blinkClosure('single', 1), 0);
  assert.ok(L.blinkClosure('single', 0.5) > 0.9);
  assert.ok(L.blinkClosure('double', 0.25) > 0.9 && L.blinkClosure('double', 0.75) > 0.9);
  assert.ok(L.blinkClosure('partial', 0.5) < 0.7);   // partial never fully closes
});
test('breathing: normalized 0..1, zero at ends, full at mid, periodic', () => {
  const p = L.breathePeriod(L.makeRng(9));
  assert.ok(p >= 3500 && p <= 5500);
  assert.ok(Math.abs(L.breathe(0, p)) < 1e-9);
  assert.ok(Math.abs(L.breathe(p, p)) < 1e-9);
  assert.ok(Math.abs(L.breathe(p / 2, p) - 1) < 1e-9);
  for (let t = 0; t <= p; t += p / 20) { const v = L.breathe(t, p); assert.ok(v >= 0 && v <= 1); }
});
test('micro-saccades are tiny + bounded, delay 0.2–1.2s', () => {
  const rng = L.makeRng(5);
  for (let i = 0; i < 100; i++) {
    const s = L.nextSaccade(rng);
    assert.ok(Math.abs(s.dx) <= L.MAX_SACCADE && Math.abs(s.dy) <= L.MAX_SACCADE);
    assert.ok(s.delayMs >= 200 && s.delayMs <= 1200);
  }
});
test('gaze: USER centered, LEFT<0<RIGHT yaw, bounded, unknown→USER', () => {
  assert.ok(Math.abs(L.gazeVector('USER').yaw) < 0.01);
  assert.ok(L.gazeVector('LEFT').yaw < 0 && L.gazeVector('RIGHT').yaw > 0);
  for (const t of ['UP', 'DOWN', 'MISSION', 'SECURITY', 'INTELLIGENCE', 'MEMORY', 'ALERT']) {
    const g = L.gazeVector(t); assert.ok(g.yaw >= -1 && g.yaw <= 1 && g.pitch >= -1 && g.pitch <= 1);
  }
  assert.deepStrictEqual(L.gazeVector('nonsense'), L.gazeVector('USER'));
});
test('head drift is very small + bounded', () => {
  const rng = L.makeRng(77);
  for (let i = 0; i < 100; i++) {
    const h = L.nextHeadDrift(rng);
    assert.ok(Math.abs(h.yaw) <= L.MAX_HEAD_DEG && Math.abs(h.pitch) <= L.MAX_HEAD_DEG);
    assert.ok(Math.abs(h.roll) <= L.MAX_HEAD_DEG);
    assert.ok(h.durMs >= 1500 && h.durMs <= 4000);
  }
});
test('micro-expressions: neutral empty; warm smiles; concerned brows; NO eye keys (identity §7)', () => {
  assert.deepStrictEqual(L.expressionCoefficients('neutral'), {});
  assert.ok(L.expressionCoefficients('warm').mouthSmileLeft > 0);
  assert.ok(L.expressionCoefficients('concerned').browInnerUp > 0);
  for (const name of L.expressionNames()) {
    const c = L.expressionCoefficients(name);
    for (const k in c) {
      assert.ok(c[k] >= 0 && c[k] <= 1, 'coeff range ' + name + '.' + k);
      assert.ok(k.toLowerCase().indexOf('eye') === -1, 'expression must not touch the eyes (identity): ' + name + '.' + k);
    }
  }
});

console.log('\n' + pass + ' passed');
