// ============================================================================
// KAI NEXUS — bootstrap. Wires the presence, the panels, the conversation flow,
// the transforming workspace, voice, sound, settings and adaptive quality.
// ============================================================================
import { bus, KAI } from './state.js';
import { data } from './data.js';
import { mountKai } from './avatar/controller.js';
import { mountParticles } from './particles.js';
import { mountSound } from './sound.js';
import { mountVoice } from './voice.js';
import { mountWorkspace } from './transitions.js';
import { quality } from './shared/quality.js';
import { dataFreshness, FRESH } from './shared/dataFreshness.js';
import { speak } from './voice/speech.js';

quality.init();                                   // resolve render tier before mounting
const $ = s => document.querySelector(s);
const avatar   = mountKai($('#kai-stage'));
// §36 data honesty: everything is simulated until a real feed proves otherwise
['system', 'security', 'agents', 'memory', 'costs', 'market', 'infra', 'mission', 'news', 'world', 'activity', 'thinking']
  .forEach(d => dataFreshness.set(d, FRESH.DEMO));
const particles= mountParticles($('#bg-particles'));
const sound    = mountSound();
const workspace= mountWorkspace(document.body);
mountVoice($('#mic'));

const ctx = { bus, KAI, data, avatar, sound };

// ---- panel registry (dynamic → resilient to a missing/broken panel) --------
const P = {
  system:'system', intelligence:'intelligence', activity:'activity', thinking:'thinking',
  agents:'agents', mission:'mission', memory:'memory', tools:'tools',
  infrastructure:'infrastructure', security:'security', market:'market', world:'world',
};
async function makePanel(name, el) {
  try { const mod = await import(`./panels/${P[name]}.js`); return mod.create({ ...ctx, el }); }
  catch (e) {
    console.error(`[nexus] panel "${name}" failed`, e);
    const d = document.createElement('div'); d.className = 'panel';
    d.append(Object.assign(document.createElement('div'), { className: 'panel-h', textContent: name }));
    const p = document.createElement('div'); p.className = 'dim'; p.textContent = 'panel unavailable'; d.append(p);
    el.replaceChildren(d);
  }
}

// ---- column panels ---------------------------------------------------------
(async () => {
  await makePanel('system', $('#col-left'));
  const right = $('#col-right');
  for (const n of ['intelligence', 'thinking', 'activity']) {
    const slot = document.createElement('div'); right.appendChild(slot);
    await makePanel(n, slot);
  }
})();

// ---- tabs → transforming workspace ----------------------------------------
const TITLES = { thinking:'Live Thinking', agents:'Agent Constellation', mission:'Mission Control',
  memory:'KAI Memory', tools:'Capabilities', infrastructure:'Infrastructure',
  security:'Security Command Center', market:'Market Intelligence', world:'World Pulse' };

// each view casts a coloured rim-light on KAI + pulls his gaze toward it
const ENVLIGHT = { security:'#ffb020', critical:'#ff4d4d', market:'#46e6ff', infrastructure:'#35d0a8',
  memory:'#7a6bff', agents:'#35d0a8', world:'#4aa3ff', mission:'#3f8cff', thinking:'#7a6bff', tools:'#3f8cff' };
function lookAtEl(el) { if (!el) return; const r = el.getBoundingClientRect(); avatar.lookAt(r.left + r.width / 2, r.top + r.height / 2); }

function openView(view) {
  const opening = workspace.current !== view;
  workspace.open(view, TITLES[view] || view, host => makePanel(view, host));
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.view === view && workspace.current === view));
  if (opening) {
    bus.emit('env:light', { color: ENVLIGHT[view] || '#3f8cff', side: 1 });   // KAI catches the panel's colour
    requestAnimationFrame(() => lookAtEl(document.querySelector('.workspace .frame')));  // and looks at it
    setTimeout(() => bus.emit('gaze', 'camera'), 1400);                        // then back to the user
  }
  touch();
}
$('#tabs').addEventListener('click', e => {
  const t = e.target.closest('.tab'); if (!t) return;
  openView(t.dataset.view);
  avatar.litHalo({ thinking:'reasoning', agents:'agents', mission:'reasoning', memory:'memory', tools:'tools', infrastructure:'infra' }[t.dataset.view]);
});
bus.on('cmd:open', openView);                          // voice / text routing
bus.on('workspace:close', () => document.querySelectorAll('.tab').forEach(t => t.classList.remove('active')));

// ---- command dock + KAI conversation flow ---------------------------------
const cmd = $('#cmd'), greet = $('#greet'), chip = $('#statechip-label'), dockMode = $('#dock-mode'), dock = $('#dock');
cmd.addEventListener('focus', () => { bus.emit('gaze', 'input'); dock.classList.add('hot'); });
cmd.addEventListener('blur',  () => { bus.emit('gaze', 'camera'); dock.classList.remove('hot'); });
cmd.addEventListener('input', () => bus.emit('gaze', cmd.value ? 'input' : 'camera'));

function submit(text) {
  text = (text || '').trim(); if (!text) return;
  cmd.value = '';
  // voice-style routing first: does it name a view?
  bus.emit('cmd:action', { text });
  // scripted reasoning → visible operational status (Increment 8), not hidden CoT
  const steps = [
    { label: 'Understanding request', state: 'active' },
    { label: 'Searching memory', state: 'pending' },
    { label: 'Researching sources', state: 'pending' },
    { label: 'Comparing evidence', state: 'pending' },
    { label: 'Preparing response', state: 'pending' },
  ];
  const emit = () => bus.emit('data:thinking', { mode: 'working', title: text, steps: steps.map(s => ({ ...s })) });
  KAI.set('understanding'); dockMode.textContent = 'Understanding';
  setTimeout(() => { KAI.set('thinking'); dockMode.textContent = 'Thinking'; emit(); avatar.litHalo('reasoning'); }, 380);
  const seq = [
    [650,  () => { steps[0].state='done'; steps[1].state='active'; avatar.litHalo('memory'); emit(); }],
    [1300, () => { steps[1].state='done'; steps[2].state='active'; KAI.set('researching'); avatar.litHalo('research'); emit(); }],
    [2200, () => { steps[2].state='done'; steps[3].state='active'; avatar.litHalo('reasoning'); emit(); }],
    [3000, () => { steps[3].state='done'; steps[4].state='active'; KAI.set('executing'); avatar.litHalo('tools'); dockMode.textContent='Executing'; emit(); }],
    [3800, () => { steps[4].state='done'; emit(); KAI.transient('success', 1500); toast('Response ready'); }],
    [4100, () => { const r = reply(text); KAI.set('speaking'); greet.textContent = r; dockMode.textContent='Speaking';
                   if (sound.mode !== 'silent') speak(r);          // real browser TTS + viseme lip-sync
                   setTimeout(() => { KAI.settle(); dockMode.textContent='Ready'; bus.emit('data:thinking', { mode:'idle', steps:[] }); }, 2600); }],
  ];
  seq.forEach(([t, fn]) => setTimeout(fn, t));
}
function reply(t) {
  const l = t.toLowerCase();
  if (/secur/.test(l)) return 'Security posture is stable — 1 high, 3 medium. Opening the command center.';
  if (/deploy|production|infra/.test(l)) return 'Production is healthy across all services. Dwolla is degraded.';
  if (/status|overnight|happen/.test(l)) return '6 autonomous actions overnight. All checks green.';
  return 'Understood. Here is what I found.';
}
$('#send').onclick = () => submit(cmd.value);
cmd.addEventListener('keydown', e => { if (e.key === 'Enter') submit(cmd.value); });

// voice/text intent → open a view or request a gated action
bus.on('cmd:action', ({ text, gated }) => {
  const l = (text || '').toLowerCase();
  const view = ['security','agents','memory','infrastructure','market','mission','world','thinking']
    .find(v => new RegExp(v.slice(0, 5)).test(l) || (v==='infrastructure' && /production|deploy|server/.test(l)) || (v==='world' && /news|overnight|happen/.test(l)));
  if (view) setTimeout(() => openView(view), gated ? 200 : 600);
  if (gated && /\b(fix|deploy|run|execute|audit)\b/.test(l)) toast('⛔ Requires approval — action gated', 'warn');
});

// ---- state → greet + chip --------------------------------------------------
const CHIP = { idle:'Idle', listening:'Listening', thinking:'Thinking', speaking:'Speaking',
  executing:'Executing', researching:'Researching', warning:'Warning', critical:'Critical', success:'Success' };
bus.on('state', ({ state, greeting }) => {
  chip.textContent = CHIP[state] || state;
  if (state !== 'speaking' && greeting) greet.textContent = greeting;
  $('#kai-status').textContent = state === 'critical' ? 'alert' : state === 'warning' ? 'watch' : 'online';
});

// ---- security → topbar SECURE label + toast --------------------------------
bus.on('data:security', s => {
  const lbl = $('#secure-label');
  lbl.textContent = s.critical > 0 ? 'Breach' : s.high > 2 ? 'Elevated' : 'Secure';
});

// ---- toasts ----------------------------------------------------------------
function toast(text, kind) {
  const t = document.createElement('div'); t.className = 'toast'; t.textContent = text;
  if (kind === 'warn') t.style.borderColor = 'var(--warn)';
  $('#toasts').appendChild(t);
  // KAI notices the notification, then returns to the user
  requestAnimationFrame(() => lookAtEl(t));
  if (kind === 'warn') bus.emit('env:light', { color: 'var(--warn)', side: 1 });
  setTimeout(() => bus.emit('gaze', 'camera'), 1600);
  setTimeout(() => { t.style.opacity = '0'; setTimeout(() => t.remove(), 400); }, 3600);
}
bus.on('toast', ({ text, kind }) => toast(text, kind));

// ---- settings: motion + sound ---------------------------------------------
$('#seg-motion').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  document.documentElement.dataset.motion = b.dataset.motion === 'off' ? 'off' : 'on';
  [...e.currentTarget.children].forEach(x => x.classList.toggle('on', x === b));
});
$('#seg-sound').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  sound.setMode(b.dataset.sound);
  [...e.currentTarget.children].forEach(x => x.classList.toggle('on', x === b));
});
// reflect stored sound mode
document.querySelectorAll('#seg-sound button').forEach(b => b.classList.toggle('on', b.dataset.sound === sound.mode));
// render quality (§34)
$('#seg-quality').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  quality.apply(b.dataset.q);
  [...e.currentTarget.children].forEach(x => x.classList.toggle('on', x === b));
});
document.querySelectorAll('#seg-quality button').forEach(b => b.classList.toggle('on', b.dataset.q === quality.tier));

// §36 global demo-data flag — visible whenever nothing is a real feed
function updateDemoFlag() { const f = $('#demoflag'); if (f) f.hidden = dataFreshness.anyReal(); }
bus.on('freshness', updateDemoFlag); updateDemoFlag();

// ---- clock -----------------------------------------------------------------
setInterval(() => { $('#clock').textContent = new Date().toTimeString().slice(0, 8); }, 1000);
$('#clock').textContent = new Date().toTimeString().slice(0, 8);

// ---- mobile KPI cards ------------------------------------------------------
const MC = $('#mobile-cards');
MC.innerHTML = '';
const mcMap = [['Security','sec'],['Agents','agt'],['Spend','spend']];
for (const [lbl, id] of mcMap) {
  const c = document.createElement('div'); c.className = 'mc';
  c.append(Object.assign(document.createElement('div'), { className:'lbl', textContent: lbl }));
  const v = document.createElement('div'); v.className = 'v'; v.id = 'mc-' + id; v.textContent = '—'; c.append(v);
  MC.appendChild(c);
}
bus.on('data:security', s => $('#mc-sec') && ($('#mc-sec').textContent = s.score));
bus.on('data:agents', a => $('#mc-agt') && ($('#mc-agt').textContent = a.filter(x => x.status !== 'idle').length));
bus.on('data:costs', c => $('#mc-spend') && ($('#mc-spend').textContent = '$' + c.today));

// ---- adaptive quality: drop to low if the frame budget slips ---------------
(function fpsMonitor() {
  let last = performance.now(), acc = 0, n = 0, low = 0;
  function tick(t) {
    const fps = 1000 / (t - last); last = t;
    if (fps < 45) low++; else low = Math.max(0, low - 1);
    if (low > 90 && document.documentElement.dataset.q !== 'low') { document.documentElement.dataset.q = 'low'; console.info('[nexus] adaptive quality → low'); }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
})();

// ---- sleep / wake cycle: KAI dozes after inactivity, wakes on interaction --
let lastTouch = performance.now();
function touch() { lastTouch = performance.now(); if (KAI.state === 'sleep') { KAI.set('idle'); bus.emit('sound:cue', 'wake'); } }
['pointerdown', 'keydown', 'focusin'].forEach(e => addEventListener(e, touch, { passive: true }));
setInterval(() => { if (KAI.state === 'idle' && performance.now() - lastTouch > 60000) KAI.set('sleep'); }, 5000);

// ---- go --------------------------------------------------------------------
data.start();
bus.emit('sound:cue', 'wake');
console.info('[nexus] KAI Command Nexus online');
