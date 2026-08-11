// ============================================================================
// Dev Avatar Lab (§22) — developer-only control panel to exercise embodiment.
// Toggle: press Alt+L, or load with #lab. Hidden in production by default.
// Drives REAL systems (state machine, gaze, halo, TTS, interruption). Blink/
// viseme posing is a rig-only capability (the avatar is a driven VIDEO, so its
// blink/mouth come from the clip, not a poseable rig) — those buttons emit the
// bus events a future GLB rig would consume, and are labelled accordingly.
// ============================================================================
import { STATES } from '../state.js';

const PHRASES = [
  "Good morning. I'm KAI. Everything is online and ready.",
  "What would you like me to work on?",
  "The research agent found three relevant results. I can compare them for you.",
  "Maybe we should probably begin with memory.",     // §24 — exposes M/B/P closure
];

export function mountAvatarLab({ bus, KAI, avatar, speak, cancelSpeech, listVoices, setVoice, currentVoice }) {
  const el = (t, c, txt) => { const n = document.createElement(t); if (c) n.className = c; if (txt != null) n.textContent = txt; return n; };
  const panel = el('div', 'avatar-lab'); panel.hidden = !location.hash.includes('lab');
  const h = el('div', 'lab-h', 'KAI · Avatar Lab'); const close = el('button', 'lab-x', '✕'); close.type = 'button';
  close.onclick = () => (panel.hidden = true); h.appendChild(close); panel.appendChild(h);

  const group = (title, buttons) => {
    const g = el('div', 'lab-g'); g.appendChild(el('div', 'lab-t', title));
    const row = el('div', 'lab-row');
    for (const [label, fn] of buttons) { const b = el('button', 'lab-b', label); b.type = 'button'; b.onclick = fn; row.appendChild(b); }
    g.appendChild(row); return g;
  };

  panel.appendChild(group('States', STATES.map(s => [s, () => KAI.set(s)])));
  panel.appendChild(group('Gaze', [['user', () => bus.emit('gaze', 'camera')], ['up', () => bus.emit('gaze', 'up')],
    ['input', () => bus.emit('gaze', 'input')]]));
  panel.appendChild(group('Halo subsystems', ['reasoning', 'memory', 'research', 'tools', 'agents', 'security', 'market', 'infra']
    .map(s => [s, () => avatar.litHalo(s)])));

  // Voice
  const vg = el('div', 'lab-g'); vg.appendChild(el('div', 'lab-t', 'Voice (masculine)'));
  const sel = el('select', 'lab-sel');
  const fillVoices = () => { sel.replaceChildren(); for (const v of listVoices()) { const o = el('option', null, `${v.name} (${v.lang})`); o.value = v.name; sel.appendChild(o); } if (currentVoice()) sel.value = currentVoice(); };
  fillVoices(); bus.on('voices', fillVoices);
  sel.onchange = () => setVoice(sel.value);
  const vrow = el('div', 'lab-row');
  const testBtn = el('button', 'lab-b', 'Test phrases'); testBtn.type = 'button';
  testBtn.onclick = () => { KAI.set('speaking'); PHRASES.forEach((p, i) => setTimeout(() => speak(p), i * 3200)); setTimeout(() => KAI.settle(), PHRASES.length * 3200); };
  const intBtn = el('button', 'lab-b', 'Interruption test'); intBtn.type = 'button';
  intBtn.onclick = () => { KAI.set('speaking'); speak("This is a long sentence that you should be able to interrupt at any moment without waiting."); setTimeout(() => { cancelSpeech(); KAI.set('listening'); }, 1200); };
  vrow.append(testBtn, intBtn); vg.append(sel, vrow); panel.appendChild(vg);

  // Rig-only note + readout
  panel.appendChild(group('Rig-only (emit for future GLB)', [['BLINK', () => bus.emit('viseme', { v: 'rest', open: 0 })],
    ['TEST VISEMES', () => ['A', 'E', 'I', 'O', 'U', 'M', 'F', 'L', 'rest'].forEach((v, i) => setTimeout(() => bus.emit('viseme', { v, open: v === 'rest' ? 0 : .7 }), i * 300))]]));
  const read = el('div', 'lab-read'); panel.appendChild(read);
  document.body.appendChild(panel);

  // live readout (state · voice · fps)
  let last = performance.now(), frames = 0, fps = 0;
  (function tick(t) { frames++; if (t - last >= 500) { fps = Math.round(frames * 1000 / (t - last)); frames = 0; last = t;
    read.textContent = `state ${KAI.state} · voice ${currentVoice() || '—'} · ${fps} fps`; } requestAnimationFrame(tick); })(last);

  addEventListener('keydown', e => { if (e.altKey && (e.key === 'l' || e.key === 'L')) panel.hidden = !panel.hidden; });
  return { toggle: () => (panel.hidden = !panel.hidden) };
}
