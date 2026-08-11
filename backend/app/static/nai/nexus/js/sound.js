// ============================================================================
// Sound design (Increment 24) — subtle, synthesized on the fly with WebAudio
// (no external asset files, so it works offline / in a single-file preview).
// Modes: silent · ambient · cinematic (user-selectable). Cues are short and
// quiet — activation, listening, task-complete, alert, agent-deploy, wake.
// ============================================================================
import { bus } from './state.js';

const CUES = {
  wake:     [{ f: 320, t: 0, d: .18 }, { f: 540, t: .08, d: .22 }],
  listen:   [{ f: 660, t: 0, d: .1 }],
  send:     [{ f: 520, t: 0, d: .06 }, { f: 780, t: .05, d: .08 }],
  success:  [{ f: 620, t: 0, d: .1 }, { f: 820, t: .09, d: .12 }, { f: 1040, t: .18, d: .16 }],
  deploy:   [{ f: 440, t: 0, d: .12 }, { f: 660, t: .1, d: .14 }],
  alert:    [{ f: 300, t: 0, d: .16 }, { f: 260, t: .16, d: .2 }],
  tick:     [{ f: 900, t: 0, d: .03 }],
};

export function mountSound() {
  let mode = localStorage.getItem('kai.sound') || 'ambient';   // silent | ambient | cinematic
  let actx = null;
  const gain = () => (mode === 'cinematic' ? .18 : mode === 'ambient' ? .08 : 0);

  function ensure() { if (!actx) actx = new (window.AudioContext || window.webkitAudioContext)(); return actx; }

  function cue(name) {
    if (mode === 'silent' || !CUES[name]) return;
    try {
      const a = ensure(); if (a.state === 'suspended') a.resume();
      for (const n of CUES[name]) {
        const o = a.createOscillator(), g = a.createGain();
        o.type = 'sine'; o.frequency.value = n.f;
        const t0 = a.currentTime + n.t;
        g.gain.setValueAtTime(0, t0);
        g.gain.linearRampToValueAtTime(gain(), t0 + .01);
        g.gain.exponentialRampToValueAtTime(.0001, t0 + n.d);
        o.connect(g).connect(a.destination); o.start(t0); o.stop(t0 + n.d + .02);
      }
    } catch { /* audio blocked until first gesture — fine */ }
  }

  // map states → cues
  bus.on('state', ({ state }) => {
    if (state === 'listening') cue('listen');
    else if (state === 'success') cue('success');
    else if (state === 'executing') cue('deploy');
    else if (state === 'critical' || state === 'warning') cue('alert');
  });
  bus.on('sound:cue', cue);

  function setMode(mo) { mode = mo; localStorage.setItem('kai.sound', mo); if (mo !== 'silent') cue('tick'); }
  return { cue, setMode, get mode() { return mode; } };
}
