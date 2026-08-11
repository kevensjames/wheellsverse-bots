// ============================================================================
// Voice embodiment (§20, Phase 2) — real browser TTS + viseme-driven mouth.
//
// WHAT'S REAL: speak() uses the browser SpeechSynthesis API (actual audio) and
// drives the avatar mouth from word-boundary events via coarse letter→viseme
// mapping, emitted on the 'viseme' bus channel (the canvas mouth + the gltf
// blendshapes both consume it). Prosody: word cadence → jaw activity.
//
// HONEST LIMIT: SpeechSynthesis exposes word/char boundaries, NOT phoneme/viseme
// timestamps, so lip-sync is approximate. Phoneme-accurate visemes need a TTS
// service that emits viseme timing (Azure Speech, ElevenLabs, Rhubarb offline).
// The pipeline (text → audio → viseme events → blendshapes) is in place; swap the
// engine in speak() to upgrade accuracy without touching the avatar.
// ============================================================================
import { bus, KAI } from '../state.js';

// letter → viseme + mouth openness (0..1) / width bias
const VISEME = {
  a: ['A', .9], e: ['E', .6], i: ['I', .5], o: ['O', .8], u: ['U', .45],
  m: ['M', 0], b: ['M', 0], p: ['M', 0], f: ['F', .2], v: ['F', .2], l: ['L', .35],
};
function visemeFor(ch) { return VISEME[ch] || (/[a-z]/.test(ch) ? ['C', .3] : ['rest', 0]); }

let active = null;

export function speak(text, { rate = 1, pitch = 1 } = {}) {
  cancel();
  const clean = (text || '').trim();
  if (!clean) return { cancel };

  const emit = (v, open) => bus.emit('viseme', { v, open, O: v === 'O' ? open : 0, A: v === 'A' ? open : 0, E: v === 'E' ? open : 0, I: v === 'I' ? open : 0, U: v === 'U' ? open : 0 });
  const rest = () => bus.emit('viseme', { v: 'rest', open: 0 });

  // drive a word's vowels as a short viseme burst on its onset
  function driveWord(word) {
    const letters = word.toLowerCase().replace(/[^a-z]/g, '').split('');
    letters.forEach((ch, k) => {
      const [v, open] = visemeFor(ch);
      active && active.timers.push(setTimeout(() => emit(v, open), k * 55));
    });
    active && active.timers.push(setTimeout(rest, letters.length * 55 + 40));
  }

  active = { timers: [], synth: null };

  if ('speechSynthesis' in window) {
    const u = new SpeechSynthesisUtterance(clean); u.rate = rate; u.pitch = pitch;
    // slightly cooler, steadier voice if one is available
    const vs = speechSynthesis.getVoices();
    u.voice = vs.find(v => /Daniel|Google UK English|Samantha|Alex/.test(v.name)) || vs[0] || null;
    u.onboundary = e => { if (e.name === 'word' || e.charIndex != null) driveWord(clean.slice(e.charIndex).split(/\s+/)[0] || ''); };
    u.onend = () => { rest(); active = null; };
    u.onerror = () => { rest(); active = null; };
    active.synth = u;
    try { speechSynthesis.cancel(); speechSynthesis.speak(u); } catch { timedFallback(clean, driveWord); }
  } else {
    timedFallback(clean, driveWord);
  }
  return { cancel };
}

// no SpeechSynthesis → animate visemes over an estimated duration (still real
// mouth motion, just silent)
function timedFallback(text, driveWord) {
  const words = text.split(/\s+/);
  words.forEach((w, i) => active && active.timers.push(setTimeout(() => driveWord(w), i * 320)));
  active && active.timers.push(setTimeout(() => { bus.emit('viseme', { v: 'rest', open: 0 }); active = null; }, words.length * 320 + 200));
}

export function cancel() {
  if (!active) return;
  active.timers.forEach(clearTimeout);
  if ('speechSynthesis' in window) try { speechSynthesis.cancel(); } catch {}
  bus.emit('viseme', { v: 'rest', open: 0 });
  active = null;
}

// stop speaking if KAI leaves the speaking state (e.g., interrupted)
bus.on('state', ({ state }) => { if (state !== 'speaking') cancel(); });
