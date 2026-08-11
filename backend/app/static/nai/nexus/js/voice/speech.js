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

// ── Voice selection (§6 — KAI is MALE; never fall back to the female default) ──
const MALE_PRIORITY = [
  'Google UK English Male', 'Microsoft Guy', 'Microsoft David', 'Microsoft Mark',
  'Daniel', 'Arthur', 'Oliver', 'Alex', 'Aaron', 'Rishi', 'Google US English',
];
const FEMALE = /samantha|victoria|karen|moira|tessa|fiona|susan|zira|serena|allison|ava|kathy|vicki|nicky|catherine|zoe|amelie|anna|paulina|female|woman/i;
let VOICES = [], CHOSEN = null;
function chooseVoice() {
  const saved = localStorage.getItem('kai.voice');
  if (saved) { const v = VOICES.find(x => x.name === saved); if (v) return v; }
  for (const name of MALE_PRIORITY) { const v = VOICES.find(x => x.name.includes(name)); if (v) return v; }
  const en = VOICES.filter(v => /^en/i.test(v.lang));
  return en.find(v => !FEMALE.test(v.name)) || VOICES.find(v => !FEMALE.test(v.name)) || en[0] || VOICES[0] || null;
}
function refreshVoices() {
  if (!('speechSynthesis' in window)) return;
  VOICES = speechSynthesis.getVoices() || []; CHOSEN = chooseVoice();
  bus.emit('voices', { list: VOICES.map(v => ({ name: v.name, lang: v.lang })), chosen: CHOSEN && CHOSEN.name });
}
if ('speechSynthesis' in window) { refreshVoices(); speechSynthesis.addEventListener('voiceschanged', refreshVoices); }
export function listVoices() { return VOICES.map(v => ({ name: v.name, lang: v.lang })); }
export function currentVoice() { return CHOSEN ? CHOSEN.name : null; }
export function setVoice(name) { localStorage.setItem('kai.voice', name); CHOSEN = chooseVoice(); return currentVoice(); }

let active = null;

export function speak(text, { rate = .98, pitch = .96 } = {}) {   // masculine, warm — not deep-narrator
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
    u.voice = CHOSEN || chooseVoice();   // masculine voice, never the female default
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
