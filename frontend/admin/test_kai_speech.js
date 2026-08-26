/* Node tests for the Phase 12 speech engines: chunker, audio queue, tts ranking, barge-in.
 * Run: node test_kai_speech.js */
const assert = require('assert');
const C = require('./kai-speech-chunker.js');
const Q = require('./kai-audio-queue.js');
const T = require('./kai-tts-provider.js');
const B = require('./kai-barge-in.js');

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

// ── speech chunker ───────────────────────────────────────────────────────────
test('chunks on sentence boundaries', () => {
  assert.deepStrictEqual(C.chunkAll('Hello there. How are you today?'), ['Hello there.', 'How are you today?']);
});
test('does NOT break a decimal number', () => {
  assert.deepStrictEqual(C.chunkAll('The value is 3.14 for now.'), ['The value is 3.14 for now.']);
});
test('does NOT break abbreviations (Dr., p.m.)', () => {
  assert.deepStrictEqual(C.chunkAll('See Dr. Smith at 5 p.m. sharp today.'), ['See Dr. Smith at 5 p.m. sharp today.']);
});
test('does NOT break inside a URL', () => {
  assert.deepStrictEqual(C.chunkAll('Open https://kai.wheellsverse.com now please.'), ['Open https://kai.wheellsverse.com now please.']);
});
test('incremental push emits complete chunks; flush returns the tail', () => {
  const ch = new C.KaiSpeechChunker();
  const a = ch.push('Systems are online. Ready for '), b = ch.push('your command? Yes indeed.');
  const rest = ch.flush();
  const all = a.concat(b).concat(rest);
  assert.deepStrictEqual(all, ['Systems are online.', 'Ready for your command?', 'Yes indeed.']);
});
test('never emits one token per call (short fragments buffer to a real phrase)', () => {
  const ch = new C.KaiSpeechChunker();
  let out = [];
  for (const tok of ['The ', 'quick ', 'brown ', 'fox. ']) out = out.concat(ch.push(tok));
  assert.deepStrictEqual(out, ['The quick brown fox.']);
});
test('long run with no punctuation breaks at a bounded word boundary', () => {
  const long = 'word '.repeat(60).trim();   // 300 chars, no sentence end
  const chunks = C.chunkAll(long, { maxChars: 120 });
  assert.ok(chunks.length >= 2, 'should split a long run');
  assert.ok(chunks.every((c) => c.length <= 130), 'each chunk bounded');
});

// ── audio queue ──────────────────────────────────────────────────────────────
test('queue is FIFO by sequence with the full lifecycle', () => {
  let t = 0; const q = new Q.KaiAudioQueue({ now: () => ++t });
  const a = q.enqueue('one'), b = q.enqueue('two');
  assert.strictEqual(a.sequence < b.sequence, true);
  assert.strictEqual(q.next().id, a.id);
  q.markSynthesizing(a.id); q.markPlaying(a.id); assert.strictEqual(q.active().id, a.id);
  q.markComplete(a.id); assert.strictEqual(q.next().id, b.id);
  assert.ok(a.started_at && a.completed_at);
});
test('queue is bounded (rejects beyond maxLen, no unbounded growth)', () => {
  const q = new Q.KaiAudioQueue({ maxLen: 2 });
  assert.ok(q.enqueue('a') && q.enqueue('b'));
  assert.strictEqual(q.enqueue('c'), null, 'over cap → rejected');
  assert.strictEqual(q.pending(), 2);
});
test('cancelAll cancels the active item AND clears the future queue', () => {
  const q = new Q.KaiAudioQueue();
  const a = q.enqueue('a'), b = q.enqueue('b'), c = q.enqueue('c');
  q.markPlaying(a.id);
  const n = q.cancelAll();
  assert.strictEqual(n, 3);
  assert.ok([a, b, c].every((it) => it.status === 'CANCELLED'));
  assert.strictEqual(q.next(), null);
});

// ── tts voice ranking (masculine preference, honest) ─────────────────────────
test('rankVoices prefers an English masculine voice over a female one', () => {
  const voices = [
    { name: 'Samantha', lang: 'en-US', localService: true, default: true },
    { name: 'Daniel', lang: 'en-GB', localService: true },
    { name: 'Google US English', lang: 'en-US' },
  ];
  const top = T.pickVoice(voices);
  assert.strictEqual(top.name, 'Daniel');
});
test('masculine flag is honest metadata-based (male→true, female→false, unknown→false)', () => {
  assert.strictEqual(T.scoreVoice({ name: 'Alex', lang: 'en-US' }).masculine, true);
  assert.strictEqual(T.scoreVoice({ name: 'Victoria', lang: 'en-US' }).masculine, false);
  assert.strictEqual(T.scoreVoice({ name: 'Voice 3', lang: 'en-US' }).masculine, false);  // unknown is NOT asserted male
});
test('English is preferred over non-English', () => {
  const r = T.rankVoices([{ name: 'Xavier', lang: 'fr-FR' }, { name: 'Neutral', lang: 'en-US' }]);
  assert.strictEqual(r[0].voice.lang.indexOf('en'), 0);
});
test('web-speech provider reports NO viseme timing (honest §16) + speaks via injected synth', () => {
  const spoken = []; const fakeSynth = { getVoices: () => [{ name: 'Daniel', lang: 'en-GB' }], speak: (u) => { spoken.push(u); u.onstart && u.onstart(); u.onend && u.onend(); }, cancel: () => {} };
  const p = T.createProvider('web-speech', { synth: fakeSynth, makeUtterance: (t) => ({ text: t }) });
  const caps = p.getCapabilities();
  assert.strictEqual(caps.viseme_timestamps, false);
  assert.strictEqual(caps.word_timestamps, true);
  assert.ok(p.availability().available);
  p.speak('hello'); assert.strictEqual(spoken.length, 1);
});
test('web-speech provider is honest when speechSynthesis is unavailable', () => {
  const p = T.createProvider('web-speech', { synth: null, makeUtterance: null });
  assert.strictEqual(p.availability().available, false);
});

// ── barge-in / one cancellation path ─────────────────────────────────────────
function makeDeps() {
  const calls = []; let t = 100;
  return {
    calls, deps: {
      now: () => (t += 10),
      cancelTTS: () => calls.push('cancelTTS'), clearQueue: () => calls.push('clearQueue'),
      clearVisemes: () => calls.push('clearVisemes'), mouthToRest: () => calls.push('mouthToRest'),
      cancelLLM: () => calls.push('cancelLLM'), setState: (s) => calls.push('state:' + s),
    },
  };
}
test('barge-in cancels TTS+queue+visemes+mouth+LLM and goes to LISTENING with a reaction time', () => {
  const { calls, deps } = makeDeps();
  const ctl = new B.KaiSpeechCancellationController(deps);
  const m = ctl.bargeIn();
  for (const c of ['cancelTTS', 'clearQueue', 'clearVisemes', 'mouthToRest', 'cancelLLM', 'state:listening']) assert.ok(calls.includes(c), 'missing ' + c);
  assert.strictEqual(m.state, 'listening');
  assert.ok(typeof m.reaction_ms === 'number' && m.reaction_ms >= 0);
});
test('output STOP uses the SAME cancellation path (no divergent semantics §14)', () => {
  const { calls, deps } = makeDeps();
  const ctl = new B.KaiSpeechCancellationController(deps);
  const m = ctl.userStop();
  for (const c of ['cancelTTS', 'clearQueue', 'clearVisemes', 'mouthToRest', 'cancelLLM']) assert.ok(calls.includes(c));
  assert.strictEqual(m.state, 'online');   // stop settles to online, not listening
});
test('teardown (route change) stops speech + mic and settles to idle', () => {
  const stopped = []; const ctl = new B.KaiSpeechCancellationController({ now: () => 0, cancelTTS: () => stopped.push('tts'), stopMic: () => stopped.push('mic'), setState: (s) => stopped.push('s:' + s) });
  const m = ctl.teardown('nav');
  assert.ok(stopped.includes('tts') && stopped.includes('mic') && stopped.includes('s:idle'));
  assert.strictEqual(m.state, 'idle');
});

console.log('\n' + pass + ' passed');
