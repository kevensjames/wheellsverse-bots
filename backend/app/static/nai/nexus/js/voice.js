// ============================================================================
// Voice control (Increment 18) — "voice becomes the UI".
// Uses the browser SpeechRecognition API when available; degrades gracefully to
// a disabled mic elsewhere. Recognized intents route to panel opens / state
// changes via the bus. Destructive intents ("fix the tests") only REQUEST an
// action and require the app's authorization gate — voice never auto-executes.
// ============================================================================
import { bus, KAI } from './state.js';

const INTENTS = [
  { re: /\b(security|secure|vulnerab)/,        cmd: { type: 'open', view: 'security' } },
  { re: /\b(agent|constellation)/,             cmd: { type: 'open', view: 'agents' } },
  { re: /\b(memory|knowledge|remember)/,       cmd: { type: 'open', view: 'memory' } },
  { re: /\b(infra|production|deployment|server)/, cmd: { type: 'open', view: 'infrastructure' } },
  { re: /\b(market|stocks|crypto|price)/,       cmd: { type: 'open', view: 'market' } },
  { re: /\b(mission|goal|progress|launch)/,     cmd: { type: 'open', view: 'mission' } },
  { re: /\b(news|intelligence|world|happening|overnight)/, cmd: { type: 'open', view: 'world' } },
  { re: /\b(fix|deploy|run|execute|audit)\b/,   cmd: { type: 'action', kind: 'gated' } },  // needs approval
  { re: /\b(thinking|working|status)/,          cmd: { type: 'open', view: 'thinking' } },
];

export function mountVoice(micBtn) {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  let rec = null, listening = false;

  if (!SR) {
    micBtn.title = 'Voice not supported in this browser';
    micBtn.classList.add('disabled');
    // keep the button as a manual "listening" toggle so the demo still feels alive
    micBtn.onclick = () => { KAI.transient('listening', 1400); bus.emit('sound:cue', 'listen'); };
    return { supported: false };
  }

  rec = new SR();
  rec.continuous = false; rec.interimResults = true; rec.lang = navigator.language || 'en-US';

  rec.onstart = () => { listening = true; micBtn.classList.add('on'); KAI.set('listening'); bus.emit('gaze', 'camera'); };
  rec.onend   = () => { listening = false; micBtn.classList.remove('on'); if (KAI.state === 'listening') KAI.settle(); };
  rec.onerror = () => { listening = false; micBtn.classList.remove('on'); };
  rec.onresult = e => {
    const txt = Array.from(e.results).map(r => r[0].transcript).join(' ').toLowerCase().trim();
    bus.emit('voice:text', txt);
    if (!e.results[e.results.length - 1].isFinal) return;
    const hit = INTENTS.find(i => i.re.test(txt));
    if (!hit) { bus.emit('voice:unrecognized', txt); return; }
    if (hit.cmd.type === 'open') bus.emit('cmd:open', hit.cmd.view);
    else if (hit.cmd.type === 'action') bus.emit('cmd:action', { text: txt, gated: true });
  };

  micBtn.onclick = () => { try { listening ? rec.stop() : rec.start(); } catch { /* already running */ } };
  return { supported: true, start: () => rec.start(), stop: () => rec.stop() };
}
