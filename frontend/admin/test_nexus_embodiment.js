/* Node tests for kai-nexus-embodiment.js — the authoritative embodiment state machine.
 * Run: node test_nexus_embodiment.js   (no framework, assert-based) */
const assert = require('assert');
const E = require('./kai-nexus-embodiment.js');

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

// ── resolve: lifecycle from kaiState ─────────────────────────────────────────
test('kaiState maps to the lifecycle embodiment states', () => {
  assert.strictEqual(E.resolve({ kaiState: 'offline' }), 'sleep');
  assert.strictEqual(E.resolve({ kaiState: 'online' }), 'idle');
  assert.strictEqual(E.resolve({ kaiState: 'thinking' }), 'thinking');
  assert.strictEqual(E.resolve({ kaiState: 'researching' }), 'researching');
  assert.strictEqual(E.resolve({ kaiState: 'speaking' }), 'speaking');
  assert.strictEqual(E.resolve({ kaiState: 'listening' }), 'listening');
});
test('event hints express states kaiState alone cannot', () => {
  assert.strictEqual(E.resolve({ kaiState: 'thinking', hint: 'executing' }), 'executing');
  assert.strictEqual(E.resolve({ kaiState: 'online', hint: 'understanding' }), 'understanding');
  assert.strictEqual(E.resolve({ kaiState: 'online', hint: 'waiting' }), 'waiting');
  assert.strictEqual(E.resolve({ kaiState: 'online', hint: 'success' }), 'success');
});

// ── env overlays — but NEVER interrupt an active speaking turn (§7) ──────────
test('env criticality resolves to warning/critical when not mid-utterance', () => {
  assert.strictEqual(E.resolve({ kaiState: 'online', env: 'critical' }), 'critical');
  assert.strictEqual(E.resolve({ kaiState: 'online', env: 'warning' }), 'warning');
  assert.strictEqual(E.resolve({ kaiState: 'alert' }), 'warning');
});
test('SPEAKING is not interrupted by an env overlay (KAI keeps talking; env reddens separately)', () => {
  assert.strictEqual(E.resolve({ kaiState: 'speaking', env: 'critical' }), 'speaking');
  // but the environment override is still available to the shell via the critical path elsewhere
});

// ── spec: every state has a complete, identity-preserving descriptor ─────────
test('every declared state has a spec; eyes are ALWAYS blue (identity §7)', () => {
  for (const s of E.STATES) {
    const sp = E.spec(s);
    assert.ok(sp, 'missing spec for ' + s);
    assert.ok(['idle', 'online', 'thinking', 'researching', 'speaking', 'listening', 'alert', 'offline'].includes(sp.halo), 'bad halo for ' + s);
    assert.ok(String(sp.eyes).startsWith('blue'), 'eyes must stay blue for ' + s + ' (got ' + sp.eyes + ')');
    assert.strictEqual(typeof sp.voice, 'boolean');
    assert.strictEqual(typeof sp.subtitle, 'boolean');
    assert.ok(typeof sp.label === 'string' && sp.label.length);
  }
});
test('only the speaking state vocalizes + shows subtitles', () => {
  assert.strictEqual(E.spec('speaking').voice, true);
  assert.strictEqual(E.spec('speaking').subtitle, true);
  assert.strictEqual(E.spec('speaking').video, 'speak');
  for (const s of E.STATES) {
    if (s !== 'speaking') { assert.strictEqual(E.spec(s).voice, false, s + ' must not vocalize'); assert.strictEqual(E.spec(s).video, 'idle', s + ' video should be idle'); }
  }
});
test('spec reuses the Phase 10 halo vocabulary (no rewrite) and maps env overlays', () => {
  assert.strictEqual(E.spec('critical').env, 'critical');
  assert.strictEqual(E.spec('warning').env, 'warning');
  assert.strictEqual(E.spec('success').env, 'success');
  assert.strictEqual(E.spec('speaking').env, null);   // don't force an env while speaking
});

// ── easeThrough: don't snap between distant states ───────────────────────────
test('easeThrough returns natural intermediate states (no hard snap)', () => {
  assert.deepStrictEqual(E.easeThrough('speaking', 'idle'), ['attentive']);
  assert.deepStrictEqual(E.easeThrough('listening', 'speaking'), ['understanding', 'thinking']);
  assert.deepStrictEqual(E.easeThrough('idle', 'idle'), []);
});

// ── resolver is a pure function of its inputs (no hidden state / randomness) ──
test('resolve is deterministic and pure', () => {
  const inp = { kaiState: 'thinking', env: 'warning', hint: '' };
  assert.strictEqual(E.resolve(inp), E.resolve(inp));
  assert.strictEqual(E.resolve({}), 'idle');   // sane default
});

console.log('\n' + pass + ' passed');
