/* Node tests for kai-subtitles.js — bounded, §24-sanitized, interruption-consistent.
 * Run: node test_kai_subtitles.js */
const assert = require('assert');
const S = require('./kai-subtitles.js');

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

// a minimal streaming §24 stripper: removes closed <think>…</think>, holds an open block
// (suppresses its trailing text), and on flush drops any still-open reasoning remainder.
function thinkStripper() {
  let buf = '';
  return {
    push(d) {
      buf += (d || '');
      buf = buf.replace(/<think>[\s\S]*?<\/think>/g, '');   // closed reasoning removed
      const open = buf.indexOf('<think>');
      let out;
      if (open === -1) { out = buf; buf = ''; } else { out = buf.slice(0, open); buf = buf.slice(open); }
      return out;
    },
    flush() { const open = buf.indexOf('<think>'); const out = open === -1 ? buf : buf.slice(0, open); buf = ''; return out; },
    reset() { buf = ''; },
  };
}

// ── progressive accumulation + state machine ─────────────────────────────────
test('EMPTY → STREAMING → SETTLED across push/finalize', () => {
  const b = new S.KaiSubtitleBuffer();
  assert.strictEqual(b.getState(), 'EMPTY');
  b.begin();
  b.push('Systems are '); b.push('online.');
  assert.strictEqual(b.getState(), 'STREAMING');
  assert.strictEqual(b.finalize(), 'Systems are online.');
  assert.strictEqual(b.getState(), 'SETTLED');
});
test('rolling window bounds the visible tail at a word boundary', () => {
  const b = new S.KaiSubtitleBuffer({ maxChars: 20 });
  b.begin();
  b.push('one two three four five six seven eight');
  const v = b.visible();
  assert.ok(v.length <= 20, 'bounded to maxChars');
  assert.ok(!/^\S*\s/.test(' ' + v) || v[0] !== ' ', 'no leading space');
  assert.ok(b.fullText().length > 20, 'full text is retained even though the window is small');
});

// ── §24: reasoning never reaches the screen ───────────────────────────────────
test('a closed <think> block never appears in the visible subtitle', () => {
  const b = new S.KaiSubtitleBuffer({ sanitizer: thinkStripper() });
  b.begin();
  b.push('The answer is ');
  b.push('<think>the user probably wants X, let me hedge</think>');
  b.push('42.');
  const out = b.finalize();
  assert.strictEqual(out, 'The answer is 42.');
  assert.ok(out.indexOf('think') === -1 && out.indexOf('hedge') === -1, 'no reasoning leaked');
});
test('an OPEN <think> mid-stream is suppressed while streaming (not shown early)', () => {
  const b = new S.KaiSubtitleBuffer({ sanitizer: thinkStripper() });
  b.begin();
  b.push('Result: ');
  const mid = b.push('<think>still deliberating');
  assert.strictEqual(mid, 'Result: ', 'the open reasoning tail is held back, not painted');
});

// ── §14/§27: interruption consistency — no ghost text after STOP/barge-in ──────
test('interrupt() freezes subtitles; a later push is dropped (no ghost advance)', () => {
  const b = new S.KaiSubtitleBuffer();
  b.begin();
  b.push('All systems are ');
  const frozen = b.interrupt();
  assert.strictEqual(b.getState(), 'INTERRUPTED');
  b.push('online and ready and definitely still talking');   // late SSE delta after STOP
  assert.strictEqual(b.visible(), frozen, 'no text advanced past the interruption point');
});
test('a stale-epoch delta from a prior utterance is ignored', () => {
  const b = new S.KaiSubtitleBuffer();
  const e1 = b.begin();
  b.push('first utterance', e1);
  const e2 = b.begin();                 // new utterance → epoch bumped, buffer cleared
  b.push('late frame from utterance one', e1);   // stale epoch → ignored
  assert.strictEqual(b.fullText(), '');
  b.push('second utterance', e2);
  assert.strictEqual(b.fullText(), 'second utterance');
});
test('begin() resets after an interruption so the next utterance streams cleanly', () => {
  const b = new S.KaiSubtitleBuffer();
  b.begin(); b.push('interrupted mid'); b.interrupt();
  b.begin();                            // new utterance clears the freeze
  assert.strictEqual(b.getState(), 'EMPTY');
  b.push('fresh start');
  assert.strictEqual(b.visible(), 'fresh start');
});

console.log('\n' + pass + ' passed');
