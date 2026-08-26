/* Node tests for kai-speech-input.js — injected SpeechRecognition, honest BROWSER_LIMITED caps.
 * Run: node test_kai_speech_input.js */
const assert = require('assert');
const SI = require('./kai-speech-input.js');

let pass = 0;
function test(name, fn) { try { fn(); console.log('  ok  ' + name); pass++; } catch (e) { console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; } }

function makeSR() {
  function SR() { this.started = false; this.aborted = false; SR.last = this; }
  SR.prototype.start = function () { this.started = true; };
  SR.prototype.abort = function () { this.aborted = true; };
  return SR;
}
function resultEvent(transcript, isFinal) {
  const group = [{ transcript: transcript, confidence: 0.9 }];
  group.isFinal = !!isFinal;
  return { results: [group] };
}

// ── honest capability reporting ──────────────────────────────────────────────
test('no SpeechRecognition API → UNAVAILABLE, availability false, start refuses', () => {
  const p = new SI.KaiSpeechInputProvider({ SpeechRecognition: null });
  assert.strictEqual(p.getCapabilities().status, 'UNAVAILABLE');
  assert.strictEqual(p.availability().available, false);
  assert.strictEqual(p.start().started, false);
  assert.strictEqual(p.getState().state, 'ERROR');
});
test('SpeechRecognition present → status is BROWSER_LIMITED (never asserted universal)', () => {
  const p = new SI.KaiSpeechInputProvider({ SpeechRecognition: makeSR() });
  const c = p.getCapabilities();
  assert.strictEqual(c.status, 'BROWSER_LIMITED');
  assert.strictEqual(c.recognition, true);
  assert.strictEqual(p.availability().reason, 'BROWSER_LIMITED');
});

// ── listening lifecycle ──────────────────────────────────────────────────────
test('start() enters LISTENING and starts the recognizer', () => {
  const SR = makeSR();
  const p = new SI.KaiSpeechInputProvider({ SpeechRecognition: SR });
  const r = p.start();
  assert.strictEqual(r.started, true);
  assert.strictEqual(p.getState().state, 'LISTENING');
  assert.strictEqual(SR.last.started, true);
});
test('onerror moves to ERROR and reports the reason', () => {
  const SR = makeSR();
  let errs = [];
  const p = new SI.KaiSpeechInputProvider({ SpeechRecognition: SR, onError: (e) => errs.push(e) });
  p.start();
  SR.last.onerror({ error: 'not-allowed' });   // permission denied
  assert.strictEqual(p.getState().state, 'ERROR');
  assert.deepStrictEqual(errs, ['not-allowed']);
});
test('stop() aborts the recognizer and settles to STOPPED', () => {
  const SR = makeSR();
  const p = new SI.KaiSpeechInputProvider({ SpeechRecognition: SR });
  p.start();
  const rec = SR.last;
  p.stop();
  assert.strictEqual(rec.aborted, true);
  assert.strictEqual(p.getState().state, 'STOPPED');
});

// ── input-side barge-in (P0, §13) — armed, fires ONCE ─────────────────────────
test('armed barge-in: first speech onset fires onSpeechStart exactly once', () => {
  const SR = makeSR();
  let onsets = [];
  let t = 100;
  const p = new SI.KaiSpeechInputProvider({ SpeechRecognition: SR, onSpeechStart: (m) => onsets.push(m), now: () => (t += 5) });
  p.armBargeIn(true);
  p.start();
  SR.last.onspeechstart();
  SR.last.onspeechstart();   // a second onset in the same session must NOT re-fire
  SR.last.onresult(resultEvent('stop talking', false));   // result-inferred onset also must NOT re-fire
  assert.strictEqual(onsets.length, 1, 'onset fires once per listening session');
  assert.ok(onsets[0].detected_at > 0);
});
test('NOT armed: speech onset does not trigger barge-in (only delivers results)', () => {
  const SR = makeSR();
  let onsets = [], results = [];
  const p = new SI.KaiSpeechInputProvider({ SpeechRecognition: SR, onSpeechStart: (m) => onsets.push(m), onResult: (r) => results.push(r) });
  p.start();                 // armBargeIn NOT called
  SR.last.onspeechstart();
  SR.last.onresult(resultEvent('hello there', true));
  assert.strictEqual(onsets.length, 0, 'no barge-in when disarmed');
  assert.strictEqual(results.length, 1);
  assert.strictEqual(results[0].transcript, 'hello there');
  assert.strictEqual(results[0].isFinal, true);
});
test('a fresh start() re-arms the onset (once per session, not once per lifetime)', () => {
  const SR = makeSR();
  let onsets = [];
  const p = new SI.KaiSpeechInputProvider({ SpeechRecognition: SR, onSpeechStart: () => onsets.push(1), now: () => 1 });
  p.armBargeIn(true);
  p.start(); SR.last.onspeechstart(); p.stop();
  p.start(); SR.last.onspeechstart();   // new session → onset allowed again
  assert.strictEqual(onsets.length, 2);
});

console.log('\n' + pass + ' passed');
