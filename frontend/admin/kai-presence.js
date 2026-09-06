// ============================================================================
// KAI Presence — the ONE frontend provider for KAI across the admin shell (P11/P12 + Phase 7b).
// Buildless ES module: any admin page includes it with
//   <script type="module" src="/admin/kai-presence.js"></script>
//
// It is the single canonical KAI state store (§P14) with three presentations:
//   MINIMIZED  — a small always-on orb reflecting KAI's state
//   ASSISTANT  — a contextual drawer that streams the governed brain
//   NEXUS      — the ONE immersive view (§69): /admin/mission-nexus hosts THIS provider by exposing
//                [data-kai-slot] mount points (messages/subtitles/voice/avatar); no second overlay.
//
// Governed by the merge spine: it talks to the same-origin bridge
// POST /admin/kai/kai-chat/stream (owner-only kai.ultra, SSE), carries the
// operator session cookie (credentials:'include'), and sends only the
// descriptive page-context envelope. No second identity, no second brain.
//
// Phase 7b VOICE (§5/§6/§7, PRIVACY-CRITICAL):
//   • The whole voice surface renders DISABLED WITH REASON unless the backend says KAI_VOICE_ENABLED,
//     the session is owner, the browser has speech recognition, and the owner picked a mode.
//   • Mic default OFF. Default mode PUSH_TO_TALK. The recognizer starts ONLY from an explicit owner
//     press (pointer/keyboard on the mic button). This file never calls getUserMedia — grep it.
//   • WAKE_WORD_LOCAL renders UNAVAILABLE unless a genuinely LOCAL engine is reported (never cloud).
//   • Unmistakable indicators: fixed MIC OPEN banner (+ REC when audio is captured, + a network
//     indicator whenever audio leaves the device), orb badge, aria-live status.
//   • Only the FINAL transcript TEXT is POSTed (→ /admin/kai/holding/command/stream, §91 events);
//     interim text is ephemeral and never sent or stored; raw audio never leaves the page except via
//     the browser's own speech provider; nothing is persisted here.
//   • kai-barge-in.js is the ONE cancellation authority (§52): Stop button, typed/spoken
//     "stop/pause/enough", barge-in, new turn and nav ALL route through stopAll(); if it cannot load,
//     mic + speech are DISABLED WITH REASON (CANCEL_UNAVAILABLE) — there is no shadow controller.
//   • ask() is the ONE dispatcher: every governed turn (typed, chip, page action, voice) goes to the holding
//     command router first and falls through to the governed chat brain only when the router says it is not
//     a holding intent. Voice changes interaction_mode and nothing else. KAI.ready resolves once mounted.
//   • A ?q= deep link only PREFILLS the input — URL text is never auto-submitted.
//   • A voice-channel approval is POSTed with interaction_mode=voice and is REFUSED by policy (§75);
//     the refusal is surfaced and the owner is routed to the typed, durable approval.
//
// Phase 8 CAMERA + GESTURE (§8/§94, PRIVACY-CRITICAL):
//   • Camera OFF by default. It opens ONLY from the explicit §67 control ('Enable camera for this session —
//     local only'), inside that click's user activation, and ONLY when the backend says camera AVAILABLE_SESSION
//     (KAI_CAMERA_ENABLED). The ONE getUserMedia call lives in kai-gesture.js (lazy-loaded) — this file never calls it.
//   • The session flag is memory-only (settings always persist camera_enabled=false). A fixed CAMERA ON banner +
//     orb badge are mandatory while open. Closed on KAI.stop, tab hidden, pagehide, sign-out, mute, settings
//     toggle off — never auto-restarted. KAI.gesture.start() from the API is always refused (NOT_EXPLICIT).
//   • No recognizer is shipped (RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED): no frame is ever read. Gesture events map
//     through the backend's closed vocabulary to non-consequential helpers only (KAI.stop, drawer, chip focus) —
//     never to ask / holdingCommand / postConfirm; the gesture channel carries no authority (§75).
// ============================================================================

// ---- tiny pub/sub -----------------------------------------------------------
const subs = new Map();
function on(evt, fn) { (subs.get(evt) ?? subs.set(evt, new Set()).get(evt)).add(fn); return () => subs.get(evt)?.delete(fn); }
function emit(evt, p) { subs.get(evt)?.forEach(fn => { try { fn(p); } catch (e) { console.error(e); } }); }

// ---- §72 lazy loader: the certified UMD voice/embodiment suite loads on demand, never up front ----
const _scripts = new Map();
function loadScript(src) {
  if (_scripts.has(src)) return _scripts.get(src);
  const p = new Promise((res, rej) => {
    const s = document.createElement('script'); s.src = src; s.async = true;
    s.onload = () => res(true);
    s.onerror = () => { _scripts.delete(src); rej(new Error('load failed: ' + src)); };
    document.head.appendChild(s);
  });
  _scripts.set(src, p); return p;
}
function loadSeq(list) { return list.reduce((p, s) => p.then(() => loadScript(s)), Promise.resolve()); }
const VOICE_LIBS = ['/admin/kai-nexus-pulse.js', '/admin/kai-speech-input.js', '/admin/kai-tts-provider.js', '/admin/kai-subtitles.js'];
const AVATAR_LIBS = ['/admin/kai-viseme-mapper.js', '/admin/kai-avatar-driver.js', '/admin/kai-nexus-embodiment.js'];
let _voiceLibs = null;
function ensureVoiceLibs() { return _voiceLibs || (_voiceLibs = loadSeq(VOICE_LIBS).then(warmVoices).catch(e => { _voiceLibs = null; throw e; })); }
// Chrome reports an EMPTY voice list until 'voiceschanged' — wait for it once, bounded (≤500 ms), so the first
// speak() resolves a REAL voice and the network indicator is honest instead of guessing.
function warmVoices() {
  return new Promise(res => {
    const synth = window.speechSynthesis;
    if (!synth || (synth.getVoices && synth.getVoices().length)) return res();
    const t = setTimeout(res, 500);
    synth.addEventListener('voiceschanged', () => { clearTimeout(t); res(); }, { once: true });
  });
}

// ---- §67 settings — privacy-preserving defaults, persisted in localStorage (try/catch) --------
const SETTINGS_KEY = 'kai.presence.settings';
const PRIVACY_MODES = ['VOICE_OFF', 'PUSH_TO_TALK', 'WAKE_WORD_LOCAL', 'SESSION_LISTENING'];
const SETTINGS_DEFAULTS = Object.freeze({
  privacy_mode: 'PUSH_TO_TALK',      // §6 default (operator choice) — mic only while the control is held
  muted: false,                      // §68 hard mute: mic off, nothing processed, nothing spoken
  greeting: '',                      // '' = "Welcome back." (no personalised auto-greeting by default)
  display_arrival: true, spoken_arrival: false,   // §66 arrival brief: shown, not spoken, by default
  voice_name: '', speed: 1.0,        // '' = provider default (masculine ranking in kai-tts-provider.js)
  speak_responses: 'nexus',          // never | nexus | always — answers to TYPED questions (voice turns always answer aloud)
  auto_speak_critical: true,         // only critical severity may auto-speak through quiet hours
  wake_word_enabled: false,          // requires a genuinely LOCAL engine — none exists → stays false
  gesture_enabled: false, camera_enabled: false,   // §8/§94: NEVER persisted as on — the camera enable is per-session, in memory only (kai-gesture.js)
  quiet_hours: { enabled: false, start: 22, end: 7 },   // local hours
  notification_severity: 'high',     // critical | high | medium | all — gates toast + spoken arrival
});
function loadSettings() {
  let raw = null;
  try { raw = JSON.parse(localStorage.getItem(SETTINGS_KEY) || 'null'); } catch { raw = null; }
  if (!raw || typeof raw !== 'object') raw = {};
  const s = { ...SETTINGS_DEFAULTS, ...raw, quiet_hours: { ...SETTINGS_DEFAULTS.quiet_hours, ...(raw.quiet_hours || {}) } };
  if (!PRIVACY_MODES.includes(s.privacy_mode)) s.privacy_mode = 'PUSH_TO_TALK';
  if (!['never', 'nexus', 'always'].includes(s.speak_responses)) s.speak_responses = 'nexus';
  if (!['critical', 'high', 'medium', 'all'].includes(s.notification_severity)) s.notification_severity = 'high';
  s.speed = Math.min(2, Math.max(0.5, Number(s.speed) || 1));
  s.gesture_enabled = false; s.camera_enabled = false;    // seams only — never persisted as ON
  s.quiet_hours.start = Math.min(23, Math.max(0, +s.quiet_hours.start || 0));
  s.quiet_hours.end = Math.min(23, Math.max(0, +s.quiet_hours.end || 0));
  if (!s.voice_name) { try { s.voice_name = localStorage.getItem('kai.voice') || ''; } catch {} }   // reuse the Avatar Lab audition pick
  return s;
}
function saveSettings() { try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(state.settings)); } catch {} emit('settings', state.settings); }
function withinQuietHours() {
  const q = state.settings.quiet_hours; if (!q || !q.enabled) return false;
  const h = new Date().getHours(), a = +q.start, b = +q.end;
  return a <= b ? (a <= h && h < b) : (h >= a || h < b);
}
const SEV_RANK = { critical: 4, sev1: 4, 'sev-1': 4, p0: 4, high: 3, medium: 2, low: 1, info: 0 };
const sevRank = s => SEV_RANK[String(s || 'info').toLowerCase()] ?? 0;
const isCritical = s => sevRank(s) >= 4;

// ---- canonical state (§P14) -------------------------------------------------
const state = {
  principal: null,          // {role, scopes} from /admin/session/whoami
  flags: {},                // /admin/ui-config
  conversationId: null,     // set below (localStorage guarded)
  messages: [],             // {role, text, body}
  kaiState: 'offline',      // offline|online|listening|thinking|working|speaking|waiting|degraded|alert
  presenceMode: 'minimized',// minimized|assistant|nexus
  context: null,            // descriptive page context envelope
  connectionState: 'idle',  // idle|streaming
  streamState: null,        // AbortController while streaming
  forcedEntity: null,       // entity passed to KAI.ask() for this turn
  settings: null,           // §67 (loaded at module eval below)
  voiceCaps: null,          // backend truth from /admin/kai/holding/voice/capabilities (null = not probed)
  gestureCaps: null,        // backend truth from /admin/kai/holding/gesture/capabilities (null = not probed)
};
try { state.conversationId = localStorage.getItem('kai.conv') || null; } catch { state.conversationId = null; }
state.settings = loadSettings();

// Voice runtime — nothing here is persisted; interim text lives only until the next paint.
const voice = {
  listening: false,   // recognizer started = MIC OPEN
  capturing: false,   // audio actively captured (onaudiostart…onaudioend) = REC
  mode: null,         // the privacy mode the open session was started under
  interim: '',        // ephemeral interim transcript — displayed, never sent, never stored
  stt: null,          // KaiSpeechInputProvider (browser STT, BROWSER_LIMITED)
  tts: null,          // KaiTTSProvider (web-speech)
  subs: null,         // KaiSubtitleBuffer
  cancel: null,       // THE KaiSpeechCancellationController (§52) — single stop path; null = CANCEL_UNAVAILABLE
  pttHeld: false,     // push-to-talk control physically held (press→release) — re-checked after every await
  speakingNetwork: false,   // the active TTS voice is not known to be local (audio may be synthesized off-device)
  ttsVoice: null,     // the voice speak() resolved (null = provider unknown)
  pendingApproval: null,    // {pending_action_id, required_confirmation, card}
  sessionTimer: null,
  note: '', noteErr: false, // noteErr: the note is a real failure (permission denied, load failure) → amber
};
const avatar = { driver: null, glb: null, host: null, mode: 'NONE' };
const cam = { session: null, note: '' };   // §8/§94 KaiCameraSession (lazy) — the ON flag lives inside it, in memory only; never persisted

// Public API — the ONE provider, reusable by the Nexus shell and by page actions.
let _readyResolve;
export const KAI = {
  state, on,
  ready: new Promise(r => { _readyResolve = r; }),   // resolves at the END of boot() (mounted); ask() queues on it
  open: () => openDrawer(),
  ask: (t, o) => ask(t, o),                      // the ONE dispatcher; o = {entity_type, entity_id, mode} or 'voice'
  setState: s => setKaiState(s),                 // the nexus shell keeps ONE state path through this
  stop: r => { stopListening('user'); stopCamera(r || 'user-stop'); return stopAll(r || 'user-stop'); },   // §52 the ONE stop: mic + camera closed, TTS/stream cancelled
  speak: t => speak(t),
  // trigger-blind: the public API can never name a trusted trigger ('ptt-press'/'session-button' are reachable only from the internal mic handlers)
  voice: { status: () => voiceStatus(), start: () => startListening('api'), stop: () => stopListening('user'), setMode: m => setPrivacyMode(m), mute: b => setMuted(!!b) },
  settings: { get: () => ({ ...state.settings }), set: patch => { Object.assign(state.settings, patch || {}); state.settings = loadSettingsFrom(state.settings); saveSettings(); if (state.settings.muted) KAI.stop('user-stop'); paintVoice(); } },
  // §8/§94 camera + gesture seam. start() from the API is ALWAYS refused (NOT_EXPLICIT): only the §67 control opens the camera.
  // registerRecognizer is gated on BACKEND truth (gesture_policy.recognizer_status.available) — the browser seam alone can never
  // declare a recognizer certified; without backend availability the call is refused (false) and no frame is ever handed out.
  gesture: { status: () => gestureStatus(), start: () => startCamera('api'), stop: r => stopCamera(r || 'user'), registerRecognizer: fn => recognizerCertified() ? ensureGesture().then(s => s.registerRecognizer(fn)) : Promise.resolve(false) },
  // Phase 8 seams (live read-only descriptors): nothing here opens a camera or reads a frame.
  seams: Object.freeze({
    get gesture() { const g = gestureStatus(); return { built: true, phase: 8, authority: 'NONE', recognizer: g.recognizer, camera: g.camera, inference: 'LOCAL_ONLY', biometrics: 'NONE', approval_by_gesture: 'REFUSED', note: 'gestures never authorize actions (§75)' }; },
    get camera() { return { status: gestureStatus().camera, pipeline: 'NONE', note: 'opens only from the explicit per-session owner control (§67); local only; never persisted' }; },
  }),
};
function loadSettingsFrom(obj) { try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(obj)); } catch {} return loadSettings(); }
if (typeof window !== 'undefined') window.KAI = KAI;   // 'kai:ready' is dispatched by boot() once mounted — never at module eval

function setKaiState(s) {
  if (state.kaiState === s) return;          // idempotent: the nexus shell echoes state back through KAI.setState
  state.kaiState = s; emit('kaiState', s); paintOrb();
}
function setMode(m) { state.presenceMode = m; emit('mode', m); }
// §64 never-fake presence: settle back to what is REALLY happening (mic open? approval pending? signed in?).
function _realState(s) {
  if (s !== 'online' && s !== 'idle') return s;
  if (voice.listening) return 'listening';
  if (voice.pendingApproval) return 'waiting';
  return state.principal ? 'online' : 'offline';
}
const isOwner = () => !!(state.principal && (state.principal.scopes || []).includes('kai.ultra'));

// ---- page context (§P7): descriptive-only, never secrets --------------------
function buildContext() {
  const el = document.querySelector('[data-kai-entity-id]');
  const fe = state.forcedEntity;
  return {
    route: location.pathname,
    module: (document.body.dataset.kaiModule) || _moduleFromPath(),
    surface: state.presenceMode === 'nexus' ? 'nexus' : 'drawer',
    entity_type: fe?.entity_type || el?.dataset.kaiEntityType || null,
    entity_id: fe?.entity_id || el?.dataset.kaiEntityId || null,
    environment: /localhost|127\.0\.0\.1/.test(location.hostname) ? 'dev' : 'production',
  };
}
function _moduleFromPath() {
  const seg = location.pathname.split('/').filter(Boolean);
  const i = seg.indexOf('admin');
  return (i >= 0 && seg[i + 1]) ? seg[i + 1] : 'overview';
}

// ---- P15 contextual actions: module-derived suggestions (no per-page edits) --
const SUGGESTIONS = {
  overview:   ['What needs my attention right now?', 'Summarize system + business health.', "How's the holding doing?"],
  hub:        ['What needs my attention right now?', 'What should I work on next?', "How's the holding doing?"],
  siteboost:  ['Explain SiteBoost launch readiness.', 'What is blocking outbound sends?'],
  portfolio:  ['Explain the portfolio status.', 'Which business needs attention?'],
  shopify:    ['Summarize merchant + MRR health.', 'Any merchants at risk?'],
  scoreboard: ['Explain the revenue scoreboard.', 'Where is spend vs revenue off?'],
  leadgen:    ['Explain lead-gen campaign health.', 'Which niche is underperforming?'],
  security:   ['Explain the top security finding.', 'Prepare a remediation plan.'],
  agents:     ['What are the agents doing?', 'Why is any agent blocked?'],
};
function suggestionsFor(mod) { return SUGGESTIONS[mod] || SUGGESTIONS.overview; }

// ---- boot -------------------------------------------------------------------
async function boot() {
  try {
    const r = await fetch('/admin/ui-config', { credentials: 'include' });
    if (r.ok) state.flags = await r.json();
  } catch {}
  await refreshPrincipal();
  await ensureCancel();               // the ONE stop controller is armed before any control can be pressed
  if (document.body.dataset.kaiMode === 'nexus') {
    state.presenceMode = 'nexus';
    mountNexus();          // §69: embed into the host shell's [data-kai-slot]s — same provider, no overlay
  } else {
    mountOrb();
    mountDrawer();
  }
  // P15: any element with data-kai-ask="<prompt>" fires a governed action, using
  // its own data-kai-entity-{type,id} (if any) as context.
  document.addEventListener('click', e => {
    const t = e.target.closest && e.target.closest('[data-kai-ask]');
    if (!t) return;
    e.preventDefault();
    ask(t.dataset.kaiAsk, { entity_type: t.dataset.kaiEntityType || null, entity_id: t.dataset.kaiEntityId || null });
  });
  // §71 keyboard alternative for every voice action: Esc always closes the mic.
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && voice.listening) { stopListening('user'); e.stopPropagation(); } });
  // Privacy lifecycle: a hidden tab never listens; leaving the page tears everything down (single path).
  document.addEventListener('visibilitychange', () => { if (document.hidden && voice.listening) stopListening('hidden'); });
  addEventListener('pagehide', () => stopAll('teardown'));
  setKaiState(state.principal ? 'online' : 'offline'); paintOrb();
  await refreshVoiceCaps();
  paintVoice();
  arrival();                          // §66 — one greeting per session, only with real data
  prefillFromUrl();
  // H1 readiness contract: mounted + probed. Queued ask()s run now; the mission-nexus shell binds late on this.
  _readyResolve(KAI);
  try { window.dispatchEvent(new CustomEvent('kai:ready', { detail: KAI })); } catch {}
}
// M1: a ?q= deep link only PREFILLS the input and focuses it — URL text is never auto-submitted (no timer, no click).
function prefillFromUrl() {
  let q = ''; try { q = (new URLSearchParams(location.search).get('q') || '').trim(); } catch {}
  const inp = inputEl || document.querySelector('[data-kai-slot="input"], #nx-cmd-input');
  if (!q || !inp) return;
  inp.value = q;
  if (drawerEl) openDrawer(); else { try { inp.focus(); } catch {} }
}

async function refreshPrincipal() {
  try {
    const r = await fetch('/admin/session/whoami', { credentials: 'include' });
    if (r.ok) {
      const w = await r.json();
      state.principal = w.authenticated ? { role: w.role, scopes: w.scopes || [] } : null;
    }
  } catch { state.principal = null; }
  emit('principal', state.principal);
}

// ---- owner session login/logout (certified /admin/session/*) ----------------
// The secret lives only transiently in the request body over HTTPS — it is never
// stored, never logged, never placed in a URL. The real session cookie is HttpOnly.
// Returns {ok, reason} — the reason distinguishes the failure modes an operator can actually act on.
// A pasted key routinely carries surrounding whitespace (copying from a CLI table, a wrapped line, or a
// double-click selection); the server compares EXACTLY, so an untrimmed value is a 401 that looks
// identical to a wrong key. Trim before sending, and report which failure actually happened.
async function login(secret) {
  let ok = false, reason = '';
  const clean = String(secret == null ? '' : secret).trim();
  if (!clean) {
    reason = 'Enter the owner access key.';
  } else {
    try {
      const r = await fetch('/admin/session/login', {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ secret: clean }),
      });
      ok = r.ok;
      if (!ok) {
        if (r.status === 401 || r.status === 403) reason = 'That key was not accepted (HTTP ' + r.status + '). Check you are using THIS deployment’s owner key — staging and production have different keys.';
        else if (r.status === 422) reason = 'The sign-in request was malformed (HTTP 422) — this is a client bug, not your key.';
        else if (r.status === 404) reason = 'Owner sign-in is not available on this deployment (HTTP 404).';
        else reason = 'Sign-in failed (HTTP ' + r.status + ').';
      }
    } catch (e) { ok = false; reason = 'Could not reach the sign-in endpoint (network or CORS).'; }
  }
  await refreshPrincipal();
  setKaiState(state.principal ? 'online' : 'offline');
  await refreshVoiceCaps(); paintVoice();
  if (ok && state.principal) arrival();
  // A 200 that yields no principal means the cookie was set but not returned to us (third-party-cookie
  // blocking, or a Secure cookie on a non-HTTPS origin) — name that instead of blaming the key.
  if (ok && !state.principal) reason = 'The key was accepted, but the session cookie was not stored by the browser — check that this page is HTTPS and that cookies are not blocked for this site.';
  return { ok: ok && !!state.principal, reason };
}
async function logout() {
  stopAll('teardown'); stopCamera('logout');
  try { await fetch('/admin/session/logout', { method: 'POST', credentials: 'same-origin' }); } catch {}
  state.principal = null; state.voiceCaps = null; state.gestureCaps = null; emit('principal', state.principal);
  setKaiState('offline'); paintVoice();
}

function canGovernedChat() {
  return !!(state.flags.kai_bridge_enabled && isOwner());
}

// ---- MINIMIZED: the orb (§P11) ---------------------------------------------
let orbEl;
function mountOrb() {
  orbEl = document.createElement('button');
  orbEl.className = 'kaip-orb';
  orbEl.type = 'button';
  orbEl.title = 'KAI (⌘K)';
  orbEl.setAttribute('aria-label', 'Open KAI');
  orbEl.innerHTML = '<span class="kaip-orb-dot"></span><span class="kaip-orb-label">KAI</span><span class="kaip-orb-mic" aria-hidden="true">● MIC</span><span class="kaip-orb-cam" aria-hidden="true">● CAM</span>';
  orbEl.addEventListener('click', () => openDrawer());
  document.body.appendChild(orbEl);
  paintOrb();
}
const ORB_TEXT = { offline: 'OFFLINE', online: 'ONLINE', listening: 'LISTENING', thinking: 'THINKING', working: 'WORKING', speaking: 'SPEAKING', waiting: 'AWAITING APPROVAL', degraded: 'DEGRADED', alert: 'ATTENTION' };
function paintOrb() {
  if (!orbEl) return;
  orbEl.dataset.state = state.kaiState;
  orbEl.dataset.mic = voice.listening ? '1' : '0';
  orbEl.dataset.cam = cam.session && cam.session.on ? '1' : '0';   // §8 badge: driven by the REAL session flag
  orbEl.querySelector('.kaip-orb-label').textContent = 'KAI ' + (ORB_TEXT[state.kaiState] || '');
}

// ---- ASSISTANT: the drawer (§P12) ------------------------------------------
let drawerEl, msgsEl, inputEl, sendBtn, stopBtn, ctxEl, stateEl, subsEl, voiceEl;
function mountDrawer() {
  drawerEl = document.createElement('aside');
  drawerEl.className = 'kaip-drawer';
  drawerEl.setAttribute('aria-hidden', 'true');
  drawerEl.setAttribute('aria-label', 'KAI assistant');
  drawerEl.innerHTML = `
    <div class="kaip-head">
      <div class="kaip-title"><span class="kaip-title-dot"></span>KAI<span class="kaip-state" id="kaip-state" role="status" aria-live="polite">online</span><span class="kaip-role-badge" id="kaip-role-badge" hidden>OWNER · GOVERNED</span></div>
      <div class="kaip-head-actions">
        <button class="kaip-logout" id="kaip-logout" type="button" title="Sign out" hidden>Sign out</button>
        <a class="kaip-nexus-link" href="/admin/mission-nexus" title="Enter Nexus — same KAI, immersive">⤢ Nexus</a>
        <button class="kaip-x" id="kaip-close" type="button" aria-label="Close">×</button>
      </div>
    </div>
    <div class="kaip-auth" id="kaip-auth" hidden>
      <div class="kaip-auth-sys" id="kaip-auth-sys"></div>
      <form class="kaip-auth-form" id="kaip-auth-form" autocomplete="off">
        <input class="kaip-auth-input" id="kaip-auth-secret" type="password" autocomplete="off"
               autocapitalize="off" autocorrect="off" spellcheck="false"
               placeholder="Owner access key" aria-label="Owner access key">
        <button class="kaip-auth-btn" id="kaip-auth-btn" type="submit">Sign in as owner</button>
        <div class="kaip-auth-msg" id="kaip-auth-msg" role="status" aria-live="polite"></div>
      </form>
    </div>
    <div class="kaip-ctx" id="kaip-ctx"></div>
    <div id="kaip-voice-host"></div>
    <div class="kaip-suggest" id="kaip-suggest"></div>
    <div class="kaip-msgs" id="kaip-msgs" role="log" aria-live="polite" aria-relevant="additions"></div>
    <div class="kaip-subtitles" id="kaip-subtitles" aria-live="polite" aria-label="KAI captions"></div>
    <div class="kaip-input-wrap">
      <textarea class="kaip-input" id="kaip-input" rows="1" placeholder="Ask KAI about this page… (type “stop” to interrupt)" aria-label="Message KAI"></textarea>
      <div class="kaip-row">
        <span class="kaip-hint"><kbd>Enter</kbd> send · <kbd>Esc</kbd> close/stop mic</span>
        <span>
          <button class="kaip-stop" id="kaip-stop" type="button" hidden>Stop</button>
          <button class="kaip-send" id="kaip-send" type="button" aria-label="Send">↑</button>
        </span>
      </div>
    </div>`;
  document.body.appendChild(drawerEl);
  const backdrop = document.createElement('div');
  backdrop.className = 'kaip-backdrop'; backdrop.id = 'kaip-backdrop';
  document.body.appendChild(backdrop);

  msgsEl = drawerEl.querySelector('#kaip-msgs');
  for (const m of state.messages) if (!m.el.isConnected) msgsEl.appendChild(m.el);   // H1: render anything queued before mount
  inputEl = drawerEl.querySelector('#kaip-input');
  sendBtn = drawerEl.querySelector('#kaip-send');
  stopBtn = drawerEl.querySelector('#kaip-stop');
  ctxEl = drawerEl.querySelector('#kaip-ctx');
  stateEl = drawerEl.querySelector('#kaip-state');
  subsEl = drawerEl.querySelector('#kaip-subtitles');
  renderVoiceBar(drawerEl.querySelector('#kaip-voice-host'), false);

  drawerEl.querySelector('#kaip-close').addEventListener('click', closeDrawer);
  backdrop.addEventListener('click', closeDrawer);
  sendBtn.addEventListener('click', submit);
  stopBtn.addEventListener('click', () => KAI.stop('user-stop'));
  inputEl.addEventListener('input', () => { inputEl.style.height = 'auto'; inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + 'px'; });
  inputEl.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  });
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); toggleDrawer(); }
    if (e.key === 'Escape' && !voice.listening && drawerEl.classList.contains('open')) closeDrawer();
  });
  on('kaiState', s => { if (stateEl) stateEl.textContent = s; paintVoice(); });
  stateEl.textContent = state.kaiState;   // paint the REAL state now (the template default is not a state)

  drawerEl.querySelector('#kaip-auth-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const inp = drawerEl.querySelector('#kaip-auth-secret');
    const msg = drawerEl.querySelector('#kaip-auth-msg');
    const secret = inp.value;
    inp.value = '';                    // clear the field immediately — never persisted
    if (!secret.trim()) { msg.textContent = 'Enter the owner access key.'; return; }
    msg.textContent = 'Signing in…';
    const { ok, reason } = await login(secret);
    msg.textContent = ok ? '' : reason;   // the specific cause, not a single catch-all line
    renderAuthState();
    if (ok && canGovernedChat()) addMessage('kai', "I'm KAI. Ask me about this page — I'll stream a governed answer.");
  });
  drawerEl.querySelector('#kaip-logout').addEventListener('click', async () => { await logout(); renderAuthState(); });
  on('principal', renderAuthState);
  renderAuthState();
  if (canGovernedChat()) addMessage('kai', "I'm KAI. Ask me about this page — I'll stream a governed answer.");
}

// Paint the drawer for the current system + session state — honest separation of
// SYSTEM HEALTH from SESSION AUTHORIZATION (§ owner session UI).
function renderAuthState() {
  if (!drawerEl) return;
  const authEl = drawerEl.querySelector('#kaip-auth');
  const formEl = drawerEl.querySelector('#kaip-auth-form');
  const sysEl = drawerEl.querySelector('#kaip-auth-sys');
  const inputWrap = drawerEl.querySelector('.kaip-input-wrap');
  const logoutBtn = drawerEl.querySelector('#kaip-logout');
  const roleBadge = drawerEl.querySelector('#kaip-role-badge');
  const sysHealthy = !!(state.flags.operator_session_enabled && state.flags.kai_bridge_enabled);
  const authed = !!state.principal;
  if (logoutBtn) logoutBtn.hidden = !authed;
  if (roleBadge) roleBadge.hidden = !canGovernedChat();
  if (canGovernedChat()) {
    authEl.hidden = true; inputWrap.hidden = false; renderSuggestions();
  } else if (!sysHealthy) {
    authEl.hidden = false; formEl.hidden = true; inputWrap.hidden = true;
    if (sysEl) sysEl.textContent = 'KAI is not enabled on this deployment.';
  } else if (!authed) {
    authEl.hidden = false; formEl.hidden = false; inputWrap.hidden = true;
    if (sysEl) sysEl.textContent = 'KAI system online. Sign in as owner to use governed chat.';
  } else {
    authEl.hidden = false; formEl.hidden = true; inputWrap.hidden = true;
    if (sysEl) sysEl.textContent = `Signed in as ${state.principal.role}. Owner access is required for governed KAI.`;
  }
  paintVoice();
}

function openDrawer() { if (!drawerEl) return; drawerEl.classList.add('open'); document.getElementById('kaip-backdrop').classList.add('show'); drawerEl.setAttribute('aria-hidden', 'false'); setMode('assistant'); ctxEl.textContent = _ctxLabel(buildContext()); renderSuggestions(); setTimeout(() => inputEl.focus(), 250); }

function renderSuggestions() {
  const wrap = document.querySelector('#kaip-suggest');
  if (!wrap) return;
  wrap.replaceChildren();
  if (!canGovernedChat()) return;
  for (const s of suggestionsFor(buildContext().module)) {
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'kaip-chip'; b.textContent = s;
    b.addEventListener('click', () => ask(s));
    wrap.appendChild(b);
  }
}

// The ONE dispatcher (M6): every governed turn — typed, chip, page action, voice — enters here.
// stop phrase → holding command router (§90/§91) → when the router says "not an authorized holding intent"
// the SAME text falls through to the governed chat brain. Voice changes interaction_mode only; §51 follow-ups,
// approval cards and summary-first speech apply uniformly. Queues until boot() has mounted (H1).
async function ask(text, opts) {
  await KAI.ready;
  const o = typeof opts === 'string' ? { mode: opts } : (opts || {});
  const mode = o.mode === 'voice' ? 'voice' : 'text';
  const t = String(text || '').trim();
  if (!t) return;
  if (isStopPhrase(t) && (isActive() || mode === 'voice')) { KAI.stop('user-stop'); setVoiceNote(mode === 'voice' ? 'Stopped (spoken).' : 'Stopped (typed).'); return; }   // §52 — a stop phrase is never POSTed
  if (o.entity_type || o.entity_id) state.forcedEntity = o;
  if (drawerEl && !drawerEl.classList.contains('open')) openDrawer();  // nexus has no drawer
  document.querySelector('#kaip-suggest')?.replaceChildren();
  const r = await holdingCommand(t, mode);
  if (r && r.fallthrough) await streamGoverned(t, r);
  state.forcedEntity = null;
}
function closeDrawer() { drawerEl.classList.remove('open'); document.getElementById('kaip-backdrop').classList.remove('show'); drawerEl.setAttribute('aria-hidden', 'true'); setMode('minimized'); }
function toggleDrawer() { drawerEl.classList.contains('open') ? closeDrawer() : openDrawer(); }
function _ctxLabel(c) { return 'Context · ' + [c.module, c.entity_type && `${c.entity_type} ${c.entity_id || ''}`].filter(Boolean).join(' · '); }

// ---- NEXUS (§69): mount INTO the host shell's slots — same provider, session, conversation ----
function mountNexus() {
  const host = document.querySelector('[data-kai-slot="messages"]');
  if (!host) { state.presenceMode = 'minimized'; mountOrb(); mountDrawer(); return; }   // no host shell → normal presence
  msgsEl = host; inputEl = null; sendBtn = null; stopBtn = null;     // the shell owns the input + Stop (→ KAI.ask / KAI.stop)
  for (const m of state.messages) if (!m.el.isConnected) msgsEl.appendChild(m.el);   // H1: render anything queued before mount
  ctxEl = document.querySelector('[data-kai-slot="ctx"]');
  stateEl = document.querySelector('[data-kai-slot="state"]');
  subsEl = document.querySelector('[data-kai-slot="subtitles"]');
  const vh = document.querySelector('[data-kai-slot="voice"]'); if (vh) renderVoiceBar(vh, true);
  const ah = document.querySelector('[data-kai-slot="avatar"]'); if (ah) mountAvatar(ah);   // §72 lazy; §10/§49 embodiment
  on('kaiState', s => { if (stateEl) stateEl.textContent = s; paintVoice(); });
  if (stateEl) stateEl.textContent = state.kaiState;
  if (ctxEl) ctxEl.textContent = _ctxLabel(buildContext());
  renderSuggestions();
  addMessage('kai', canGovernedChat()
    ? "I'm KAI. This is the immersive view — same session, same conversation. Ask me anything."
    : "KAI governed chat is not enabled for this session.");
}

function addMessage(role, text, opts) {
  const el = document.createElement('div');
  el.className = 'kaip-msg ' + (role === 'user' ? 'user' : 'kai');
  const b = document.createElement('div'); b.className = 'kaip-msg-role';
  b.textContent = (role === 'user' ? 'You' : 'KAI') + (opts && opts.voice ? ' · 🎙 voice' : '') + (opts && opts.arrival ? ' · arrival brief' : '');
  const body = document.createElement('div'); body.className = 'kaip-msg-body'; body.textContent = text;
  el.append(b, body);
  if (msgsEl) { msgsEl.appendChild(el); msgsEl.scrollTop = msgsEl.scrollHeight; }
  const rec = { role, text, body, el };
  state.messages.push(rec);
  return rec;
}
// §24 defense-in-depth: never render/speak a reasoning model's inline <think> scratchpad.
const _REASON_RE_CLOSED = /<(think|thinking|reasoning|scratchpad|reflection)(?:\s[^>]*)?>[\s\S]*?<\/\1>/gi;
const _REASON_RE_OPEN = /<(think|thinking|reasoning|scratchpad|reflection)(?:\s[^>]*)?>[\s\S]*$/i;
function _stripReason(text, finalized) {
  if (text == null) return '';
  if (typeof window !== 'undefined' && window.NexusPulse && window.NexusPulse.stripReasoning) return window.NexusPulse.stripReasoning(text, { finalized: !!finalized });
  let out = String(text).replace(_REASON_RE_CLOSED, '');
  if (!finalized) out = out.replace(_REASON_RE_OPEN, '');
  return out;
}
function renderInto(rec, finalized) { rec.body.textContent = _stripReason(rec.text, finalized); if (msgsEl) msgsEl.scrollTop = msgsEl.scrollHeight; }

// ---- SSE reader shared by the governed chat stream and the §91 command stream ----
async function readSSE(res, onEvent) {
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const frames = buf.split('\n\n');
    buf = frames.pop() || '';
    for (const f of frames) {
      const line = f.split('\n').find(l => l.startsWith('data: '));
      if (!line) continue;
      let ev; try { ev = JSON.parse(line.slice(6)); } catch { continue; }
      onEvent(ev);
    }
  }
}

// ---- governed streaming client (§4/§5) -------------------------------------
const STOP_RE = /^\s*(?:kai[,!]?\s+)?(stop|pause|enough|cancel|quiet|be quiet|hold on)\b[\s.!]*$/i;
const isStopPhrase = t => STOP_RE.test(t || '');
const isActive = () => state.connectionState === 'streaming' || state.kaiState === 'speaking' || voice.listening;
async function submit() {
  if (!inputEl) return;
  const text = inputEl.value.trim();
  if (!text) return;
  inputEl.value = ''; inputEl.style.height = 'auto';
  await ask(text);
}

// The governed chat brain — reached ONLY through ask() after the holding router declined the text (`prior` = that
// turn's result: its message record is reused, its interaction_mode decides the spoken form).
async function streamGoverned(text, prior) {
  if (state.connectionState === 'streaming' || state.kaiState === 'speaking') stopAll('user-stop');   // §52 ONE path
  const r = prior || { status: 'UNKNOWN', events: [], mode: 'text' };
  const asst = r.rec || addMessage('kai', '');
  asst.text = ''; renderInto(asst);
  setKaiState('thinking');
  state.connectionState = 'streaming';
  if (stopBtn) stopBtn.hidden = false;
  const ctrl = new AbortController();
  state.streamState = ctrl;
  try {
    const res = await fetch('/admin/kai/kai-chat/stream', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text, prefer_local: /localhost|127\.0\.0\.1/.test(location.hostname),
        conversation_id: state.conversationId, context: buildContext(),
      }),
      signal: ctrl.signal,
    });
    if (res.status === 403) { asst.text = '(You need owner access for governed KAI.)'; renderInto(asst); setKaiState('alert'); return; }
    if (res.status === 429) { asst.text = '(Rate limited — try again shortly.)'; renderInto(asst); setKaiState('alert'); return; }
    if (!res.ok || !res.body) { asst.text = `(KAI unavailable: ${res.status})`; renderInto(asst); setKaiState('degraded'); return; }
    await readSSE(res, ev => {
      if (ev.type === 'status') setKaiState(ev.state === 'thinking' ? 'thinking' : 'speaking');
      else if (ev.type === 'meta' && ev.conversation_id) { state.conversationId = ev.conversation_id; try { localStorage.setItem('kai.conv', ev.conversation_id); } catch {} }
      else if (ev.type === 'token') { if (state.kaiState !== 'speaking') setKaiState('speaking'); asst.text += (ev.text || ''); renderInto(asst); }
      else if (ev.type === 'error') { asst.text += ' [model unavailable]'; renderInto(asst); setKaiState('degraded'); }
    });
    if (!asst.text) { asst.text = '(no response)'; renderInto(asst); }
    renderInto(asst, true);
    r.status = 'CHAT'; renderFollowups(asst, text, r);   // §51 — the same affordances as a holding turn
    setKaiState(_realState('online'));
    if (shouldSpeak(r.mode === 'voice' ? 'voice-answer' : 'answer')) speak(_stripReason(asst.text, true));   // §50/§51 summary-first, never the reasoning
  } catch (e) {
    if (e.name === 'AbortError') { asst.text += ' ⏹'; renderInto(asst); setKaiState(_realState('online')); }
    else { asst.text += ' [link error]'; renderInto(asst); setKaiState('degraded'); }
  } finally {
    if (state.streamState === ctrl) { state.connectionState = 'idle'; state.streamState = null; if (stopBtn) stopBtn.hidden = true; }
    paintVoice();
  }
}

// ============================================================================
// §52 — THE single cancellation path. kai-barge-in.js is the authority; every stop control
// (Stop button, typed/spoken "stop", input-side barge-in, new turn, nav) calls stopAll().
// ============================================================================
const STOP_DEPS = {
  now: () => (performance && performance.now ? performance.now() : Date.now()),
  cancelTTS: () => { try { if (voice.tts) voice.tts.cancel(); else if ('speechSynthesis' in window) speechSynthesis.cancel(); } catch {} voice.speakingNetwork = false; },
  clearQueue: () => { /* one utterance at a time (summary-first) — nothing queued */ },
  clearVisemes: () => { try { avatar.driver && avatar.driver.returnToNeutral(); } catch {} },
  freezeSubtitles: () => { if (voice.subs) { voice.subs.interrupt(); paintSubtitles(); } },
  mouthToRest: () => {},
  cancelLLM: () => { if (state.streamState) state.streamState.abort(); },
  stopMic: () => { if (voice.stt) { voice.stt.stop(); _micClosed(); } },
  disposeTimers: () => { clearTimeout(voice.sessionTimer); },
  setState: s => setKaiState(_realState(s)),
};
// If kai-barge-in.js cannot load there is NO shadow controller: mic + speech are DISABLED WITH REASON
// (voiceStatus → CANCEL_UNAVAILABLE) and the only stop left is the raw governed-stream abort.
async function ensureCancel() {
  if (voice.cancel) return voice.cancel;
  try { await loadScript('/admin/kai-barge-in.js'); voice.cancel = new window.KaiBargeIn.KaiSpeechCancellationController(STOP_DEPS); }
  catch { voice.cancel = null; }
  return voice.cancel;
}
function stopAll(reason) {
  const c = voice.cancel;
  let m = { reason };
  if (!c) { if (state.streamState) state.streamState.abort(); }          // L5: nothing else can be running without the controller
  else if (reason === 'barge-in' && voice.listening) m = c.bargeIn();    // LISTENING only when the mic is really open (§64)
  else if (reason === 'teardown' || reason === 'nav') m = c.teardown(reason);
  else m = c.userStop();
  emit('stop', m); paintVoice();
  return m;
}

// ============================================================================
// §6/§7 VOICE — status truth, listening (browser STT), the command loop, TTS + subtitles
// ============================================================================
const hasSR = () => !!(window.SpeechRecognition || window.webkitSpeechRecognition);
// Backend truth, or an honest UNREACHABLE-with-reason — never a fabricated 'enabled'.
async function probeCaps(path, what) {
  const W = what[0].toUpperCase() + what.slice(1);
  try {
    const r = await fetch(path, { credentials: 'include' });
    if (r.ok) return await r.json();
    return { status: 'UNREACHABLE', enabled: false, reason:
      r.status === 404 ? `Holding command API is not enabled (KAI_HOLDING_COMMAND_ENABLED off) — ${what} has no backend.`
      : r.status === 403 ? `Owner access is required for ${what}.` : `${W} backend returned HTTP ${r.status}.` };
  } catch { return { status: 'UNREACHABLE', enabled: false, reason: `${W} backend unreachable (bridge or App B down).` }; }
}
async function refreshVoiceCaps() {
  if (!(state.flags.kai_bridge_enabled && isOwner())) { state.voiceCaps = null; state.gestureCaps = null; return; }
  [state.voiceCaps, state.gestureCaps] = await Promise.all([probeCaps('/admin/kai/holding/voice/capabilities', 'voice'), probeCaps('/admin/kai/holding/gesture/capabilities', 'the camera')]);
  emit('voice', state.voiceCaps); emit('gesture', state.gestureCaps);
}
// DISABLED-WITH-REASON, in governing order. ok=true only when EVERY gate is real.
function voiceStatus() {
  const s = state.settings, c = state.voiceCaps;
  if (!state.flags.kai_bridge_enabled) return { ok: false, code: 'BRIDGE_OFF', reason: 'KAI bridge is not enabled on this deployment — voice has no governed backend.' };
  if (!state.principal) return { ok: false, code: 'NO_SESSION', reason: 'Sign in as owner to use voice.' };
  if (!isOwner()) return { ok: false, code: 'NOT_OWNER', reason: `Signed in as ${state.principal.role}; owner access is required for voice.` };
  if (!c) return { ok: false, code: 'NOT_PROBED', reason: 'Voice backend not probed yet.' };
  if (c.status === 'UNREACHABLE') return { ok: false, code: 'BACKEND_UNREACHABLE', reason: c.reason || 'Voice backend unreachable.' };
  if (!c.enabled) return { ok: false, code: 'FLAG_OFF', reason: 'KAI_VOICE_ENABLED is off on the backend — no mic, no speech; voice never runs by default.' };
  if (!voice.cancel) return { ok: false, code: 'CANCEL_UNAVAILABLE', reason: 'kai-barge-in.js failed to load — without the single stop path the mic and speech stay disabled.' };
  if (!hasSR()) return { ok: false, code: 'BROWSER_UNAVAILABLE', reason: 'This browser has no speech recognition (Web Speech is Chrome/webkit-only).' };
  if (s.muted) return { ok: false, code: 'MUTED', reason: 'Muted (§68 hard mute) — mic off, nothing spoken. Unmute to use voice.' };
  if (s.privacy_mode === 'VOICE_OFF') return { ok: false, code: 'VOICE_OFF', reason: 'Privacy mode VOICE_OFF — pick PUSH_TO_TALK or SESSION_LISTENING to enable the mic.' };
  if (s.privacy_mode === 'WAKE_WORD_LOCAL') return { ok: false, code: 'WAKE_WORD_UNAVAILABLE', reason: (c.wake_word && c.wake_word.reason) || 'No on-device wake-word engine — a cloud continuous-audio fallback is forbidden (§6).' };
  return { ok: true, code: 'READY', reason: `${s.privacy_mode} · browser STT ${(c.transcription && c.transcription.status) || 'BROWSER_LIMITED'} (network-backed; on-device not guaranteed).` };
}
function wakeWordLocalAvailable() { const w = state.voiceCaps && state.voiceCaps.wake_word; return !!(w && w.available && w.is_local); }
function setPrivacyMode(m) {
  if (!PRIVACY_MODES.includes(m)) return;
  if (m === 'WAKE_WORD_LOCAL' && !wakeWordLocalAvailable()) { setVoiceNote('WAKE_WORD_LOCAL is UNAVAILABLE — no genuinely local engine; cloud fallback is forbidden.'); paintVoice(); return; }
  if (voice.listening) stopListening('mode-change');
  state.settings.privacy_mode = m; saveSettings(); paintVoice();
}
function setMuted(b) { state.settings.muted = !!b; if (b) KAI.stop('user-stop'); saveSettings(); paintVoice(); }
function setVoiceNote(t, err) { voice.note = t || ''; voice.noteErr = !!err; paintVoice(); }

// ============================================================================
// §8/§94 CAMERA + GESTURE — the presence-side policy gate and the lazy seam. This file never calls getUserMedia:
// the ONE capture call is kai-gesture.js#start, reachable only through startCamera('owner-click') from the §67 control.
// ============================================================================
// DISABLED-WITH-REASON, in governing order (mirrors voiceStatus). ok=true ONLY when the backend says AVAILABLE_SESSION.
function cameraStatus() {
  const c = state.gestureCaps;
  if (!state.flags.kai_bridge_enabled) return { ok: false, code: 'BRIDGE_OFF', reason: 'KAI bridge is not enabled on this deployment — the camera has no governed backend.' };
  if (!state.principal) return { ok: false, code: 'NO_SESSION', reason: 'Sign in as owner to enable the camera.' };
  if (!isOwner()) return { ok: false, code: 'NOT_OWNER', reason: `Signed in as ${state.principal.role}; owner access is required for the camera.` };
  if (!c) return { ok: false, code: 'NOT_PROBED', reason: 'Camera backend not probed yet.' };
  if (c.status === 'UNREACHABLE') return { ok: false, code: 'BACKEND_UNREACHABLE', reason: c.reason || 'Camera backend unreachable.' };
  if (c.camera !== 'AVAILABLE_SESSION') return { ok: false, code: 'FLAG_OFF', reason: 'KAI_CAMERA_ENABLED is off on the backend — the camera never opens by default.' };
  if (state.settings.muted) return { ok: false, code: 'MUTED', reason: 'Muted (§68 hard mute) — nothing is captured. Unmute to enable the camera.' };
  return { ok: true, code: 'AVAILABLE_SESSION', reason: 'Available for THIS session only (never persisted) — local only, nothing leaves this device; the CAMERA ON indicator is mandatory.' };
}
// Backend truth for the recognizer seam: only gesture_policy.recognizer_status() may say a recognizer is available/certified.
const recognizerCertified = () => !!(state.gestureCaps && state.gestureCaps.recognizer && state.gestureCaps.recognizer.available === true);
function gestureStatus() {
  const s = cam.session ? cam.session.status() : null, r = state.gestureCaps && state.gestureCaps.recognizer;
  const backendRec = (r && r.status) || 'RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED';
  // The session's 'REGISTERED' is reported only when the backend says the recognizer is available; otherwise backend truth wins.
  const recognizer = (s && s.recognizer === 'REGISTERED' && recognizerCertified()) ? 'REGISTERED' : backendRec;
  return { ...cameraStatus(), camera: s ? s.camera : 'OFF', recognizer, recognizer_certified: recognizerCertified(), approval_by_gesture: 'REFUSED', last: s ? s.last : null };
}
let _gesture = null;
// Lazy: kai-gesture.js loads only when the owner reaches a camera control. The injected actions are the ONLY things a
// gesture can do — non-consequential UI helpers; never ask / holdingCommand / postConfirm (test_kai_gesture.js scans this literal).
function ensureGesture() {
  return _gesture || (_gesture = loadScript('/admin/kai-gesture.js').then(() => {
    cam.session = new window.KaiGesture.KaiCameraSession({
      allowed: cameraStatus,
      actions: { stop: () => KAI.stop('gesture'), dismiss: () => dismissUI(), next: () => focusChip(1), previous: () => focusChip(-1), open_drawer: () => openDrawer() },
      onChange: ev => { cam.note = ev.on ? '' : `Camera closed (${ev.reason}).`; paintOrb(); syncSettingsForm(); emit('camera', ev); },
    });
    return cam.session;
  }).catch(e => { _gesture = null; throw e; }));
}
// Called ONLY from the §67 control's change handler (trigger 'owner-click', inside its user activation) and from
// KAI.gesture.start ('api' — always refused by the module). Every refusal is surfaced with its reason.
async function startCamera(trigger) {
  const st = cameraStatus();
  if (!st.ok) { syncSettingsForm(); return { started: false, code: st.code, reason: st.reason }; }
  let s;
  try { s = await ensureGesture(); } catch { cam.note = 'kai-gesture.js failed to load — camera unavailable.'; syncSettingsForm(); return { started: false, code: 'LOAD_FAILED', reason: cam.note }; }
  const r = await s.start(trigger);
  if (!r.started) cam.note = r.reason;
  syncSettingsForm();
  return r;
}
function stopCamera(reason) { if (cam.session) cam.session.stop(reason); }
// Gesture helpers — navigation only. next/previous move focus across the suggestion / follow-up chips.
function focusChip(dir) {
  const chips = [...document.querySelectorAll('.kaip-chip')];
  if (!chips.length) return;
  const i = chips.indexOf(document.activeElement);
  chips[(i + dir + chips.length) % chips.length].focus();
}
function dismissUI() { if (settingsEl && !settingsEl.hidden) closeSettings(); else if (drawerEl && drawerEl.classList.contains('open')) closeDrawer(); }

// The recognizer starts ONLY here, and this is called ONLY from explicit owner input handlers
// (mic button pointer/keyboard) or KAI.voice.start() invoked by a page action INSIDE a user activation. Never on boot.
async function startListening(trigger) {
  const st = voiceStatus();
  if (!st.ok) { setVoiceNote(st.reason); return false; }
  if (voice.listening) return true;
  const ua = navigator.userActivation;   // L1: an API start needs a live user activation; only the mic press/session button are explicit by construction
  if (ua && !ua.isActive && trigger !== 'ptt-press' && trigger !== 'session-button') { setVoiceNote('Mic requires an explicit press.'); return false; }
  try { await ensureVoiceLibs(); } catch { setVoiceNote('Voice libraries failed to load — voice unavailable.', true); return false; }
  const mode = state.settings.privacy_mode;
  if (mode === 'PUSH_TO_TALK' && !voice.pttHeld) return false;   // M2: released while the libs loaded — never open the mic after the fact
  if (voice.listening) return true;                              // a concurrent start already won
  if (state.kaiState === 'speaking' || state.connectionState === 'streaming') stopAll('user-stop');   // the owner is about to talk (§52)
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  voice.stt = new window.KaiSpeechInput.KaiSpeechInputProvider({
    SpeechRecognition: SR, now: STOP_DEPS.now,
    onSpeechStart: () => { if (state.kaiState === 'speaking') stopAll('barge-in'); },   // input-side barge-in (P0)
    onResult: r => {
      if (r.isFinal) { voice.interim = ''; paintVoice(); handleFinalTranscript(r.transcript); }
      else { voice.interim = r.transcript; paintVoice(); }             // interim: displayed only, never sent
    },
    onError: err => { setVoiceNote(err === 'not-allowed' || err === 'service-not-allowed' ? 'Microphone permission denied by the browser.' : err === 'no-speech' ? 'No speech detected.' : 'Speech recognition error: ' + err, err !== 'no-speech'); _micClosed(); },
    onEnd: () => { _micClosed(); },
    onAudioStart: () => { voice.capturing = true; paintVoice(); },
    onAudioEnd: () => { voice.capturing = false; paintVoice(); },
  });
  const r = voice.stt.start({ continuous: mode === 'SESSION_LISTENING', interim: true });
  if (!r.started) { setVoiceNote('Mic could not start: ' + r.reason, true); voice.stt = null; return false; }
  voice.listening = true; voice.mode = mode; voice.interim = ''; voice.note = '';
  voice.stt.armBargeIn(true);
  setKaiState('listening');
  if (mode === 'SESSION_LISTENING') { clearTimeout(voice.sessionTimer); voice.sessionTimer = setTimeout(() => { stopListening('session-cap'); setVoiceNote('Listening session ended (10-minute cap).'); }, 10 * 60 * 1000); }   // ponytail: fixed cap; make it a setting if a real need appears
  emit('listening', { on: true, mode, trigger });
  paintVoice();
  return true;
}
function stopListening(reason) {
  clearTimeout(voice.sessionTimer);
  if (!voice.stt) return;
  voice.stt.stop({ graceful: reason === 'ptt-release' });   // PTT release lets the pending FINAL result flush; onEnd closes the indicator
  if (reason !== 'ptt-release') _micClosed();
}
function _micClosed() {
  if (!voice.listening && !voice.stt) return;
  voice.listening = false; voice.capturing = false; voice.interim = ''; voice.stt = null; voice.mode = null;
  if (state.kaiState === 'listening') setKaiState(_realState('online'));
  emit('listening', { on: false });
  paintVoice();
}

// FINAL transcript only (§92): a spoken approval word is refused up front (§75); everything else is a normal turn
// through the ONE dispatcher — voice changes interaction_mode and nothing else.
function handleFinalTranscript(text) {
  const t = (text || '').trim();
  if (!t) return;
  if (voice.pendingApproval && /^(approve|yes|do it|confirm|go ahead|reject|no|deny|decline)\b/i.test(t)) { voiceConfirm(t); return; }
  ask(t, 'voice');
}

// §90/§91 — ONE governed transport for a command turn: the SSE stream (it carries the §91 event taxonomy,
// including the server's TRANSCRIPT_FINAL echo for voice). The JSON /command endpoint performs the SAME
// dispatch, so it is deliberately NOT also called (that would double-dispatch and double-audit a turn).
// Returns the turn result; `fallthrough` set ⇒ the router declined the text and ask() hands it to the chat brain.
async function holdingCommand(text, mode) {
  if (state.connectionState === 'streaming' || state.kaiState === 'speaking') stopAll('user-stop');
  const userRec = addMessage('user', text, { voice: mode === 'voice' });
  if (!canGovernedChat()) { addMessage('kai', 'Governed KAI is not enabled here.'); setKaiState('alert'); return null; }
  const asst = addMessage('kai', '');
  const body = {
    command: text,
    context: { conversation_id: state.conversationId || '', ...buildContext() },
    selected_company: '', selected_mission: '',
    interaction_mode: mode === 'voice' ? 'voice' : 'text',      // descriptive only — never authority
    client_capabilities: ['browser_stt', 'browser_tts', 'subtitles'],
  };
  const ctrl = new AbortController();
  state.streamState = ctrl; state.connectionState = 'streaming'; if (stopBtn) stopBtn.hidden = false;
  setKaiState('thinking');
  const result = { status: 'UNKNOWN', answer: '', events: [], mode, rec: asst, fallthrough: '' };
  try {
    const res = await fetch('/admin/kai/holding/command/stream', {
      method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body), signal: ctrl.signal,
    });
    if (res.status === 404 || res.status === 405) { result.fallthrough = 'COMMAND_API_OFF'; return result; }   // KAI_HOLDING_COMMAND_ENABLED off → the chat brain is the only governed brain here
    if (res.status === 403) { asst.text = '(Owner access is required for holding commands.)'; renderInto(asst, true); setKaiState('alert'); return result; }
    if (res.status === 429) { asst.text = '(Rate limited — try again shortly.)'; renderInto(asst, true); setKaiState('alert'); return result; }
    if (!res.ok || !res.body) { asst.text = `(Command API unavailable: ${res.status})`; renderInto(asst, true); setKaiState('degraded'); return result; }
    await readSSE(res, ev => applyCommandEvent(ev, asst, result));
    if (!result.done) { result.status = result.status === 'UNKNOWN' ? 'INCOMPLETE' : result.status; }
    if (result.transcript && result.transcript !== text) { userRec.text = result.transcript; renderInto(userRec, true); }   // the server's FINAL echo is authoritative
    if (result.status === 'UNKNOWN') { result.fallthrough = 'NOT_HOLDING_INTENT'; return result; }   // router: "Not an authorized holding intent — nothing ran." → same text to the chat brain
    asst.text = describeResult(result); renderInto(asst, true);
    let spoken;
    if (result.status === 'REQUIRE_APPROVAL') {
      renderApprovalCard(asst, result.approval, result.note);
      setKaiState('waiting');
      spoken = "This needs your explicit approval. I can't authorize it by voice.";
    } else {
      renderFollowups(asst, text, result);
      setKaiState(result.status === 'SYSTEM_DEGRADED' ? 'degraded' : _realState('online'));
      spoken = spokenForm(result.answer || describeResult(result));
    }
    const sev = result.severity || 'info';
    if (result.status !== 'SYSTEM_DEGRADED' && shouldSpeak(mode === 'voice' ? 'voice-answer' : 'answer', sev)) speak(spoken, { severity: sev });
  } catch (e) {
    if (e.name === 'AbortError') { asst.text += ' ⏹'; renderInto(asst, true); setKaiState(_realState('online')); }
    else { asst.text = (asst.text || '') + ' [link error]'; renderInto(asst, true); setKaiState('degraded'); }
  } finally {
    if (state.streamState === ctrl) { state.connectionState = 'idle'; state.streamState = null; if (stopBtn) stopBtn.hidden = true; }
    paintVoice();
  }
  return result;
}
// §91 taxonomy → state transitions on REAL events only (§64). Progressive display = depth on the dashboard.
function applyCommandEvent(ev, asst, r) {
  r.events.push(ev.type);
  switch (ev.type) {
    case 'KAI_PRESENCE': setKaiState(String(ev.state || '').toLowerCase() === 'thinking' ? 'thinking' : 'working'); break;
    case 'TRANSCRIPT_FINAL': r.transcript = ev.text || ''; break;
    case 'COMMAND_ACCEPTED': setKaiState('working'); r.intent = ev.intent; r.flags = ev.injection_flags || []; break;
    case 'CAPABILITY_SELECTED': r.selected = ev.selected || []; r.rationale = ev.rationale || ''; break;
    case 'APPROVAL_REQUIRED': r.status = 'REQUIRE_APPROVAL'; r.approval = ev.approval || null; r.note = ev.note || ''; break;
    case 'ACTION_RESULT':
      r.status = ev.status || r.status;
      r.answer = ev.answer || ev.note || (ev.evidence != null ? JSON.stringify(ev.evidence).slice(0, 1200) : '') || r.answer;
      r.evidence_refs = ev.evidence_refs || []; r.freshness = ev.freshness || null; r.provenance = ev.provenance || null;
      if (ev.severity) r.severity = ev.severity;
      break;
    case 'SYSTEM_DEGRADED': r.status = 'SYSTEM_DEGRADED'; r.answer = 'System degraded (' + (ev.error || 'internal_error') + ') — nothing ran, nothing spoken.'; break;
    case 'done': r.status = ev.status || r.status; r.done = true; break;
    default: break;   // CONTEXT_RESOLVED / MISSION_LINKED / WORKER_UPDATE / ACTION_COMPLETE — informational
  }
  asst.text = describeResult(r); renderInto(asst);
}
function describeResult(r) {
  if (r.status === 'REQUIRE_APPROVAL') {
    const p = r.approval || {};
    return "This needs your explicit approval and voice can't authorize it. "
      + `ACTION ${p.ACTION || p.action || '?'} · TARGET ${p.TARGET || p.target || '?'} · RISK ${p.RISK || p.action_class || p.risk || '?'}.`
      + (p.required_confirmation ? ` Type '${p.required_confirmation}' to authorize (voice can't).` : '')
      + (r.note ? ' ' + r.note : '');
  }
  let t = r.answer || '';
  if (!t && r.status === 'PREPARE_ONLY') t = 'Prepared only — capability execution is disabled (brake #1 off).' + (r.selected && r.selected.length ? ' Selected: ' + r.selected.join(', ') + '.' : '');
  if (!t && r.status === 'INCOMPLETE') t = '(stream ended before a result)';
  if (!t && r.status && r.status !== 'UNKNOWN') t = `(${r.status})`;
  if (!t && !r.events.length) t = '';
  return t;
}
// §51 affordances — spoken was the summary; these fetch depth or re-ask through the same governed channel.
function renderFollowups(rec, cmd, r) {
  const wrap = document.createElement('div'); wrap.className = 'kaip-followups';
  const mk = (label, fn) => { const b = document.createElement('button'); b.type = 'button'; b.className = 'kaip-chip'; b.textContent = label; b.addEventListener('click', fn); wrap.appendChild(b); };
  const det = document.createElement('details'); det.className = 'kaip-details';
  const sum = document.createElement('summary'); sum.textContent = 'Details'; det.appendChild(sum);
  const pre = document.createElement('pre'); pre.textContent = JSON.stringify({ status: r.status, intent: r.intent, provenance: r.provenance, freshness: r.freshness, evidence_refs: r.evidence_refs, selected: r.selected, rationale: r.rationale, injection_flags: r.flags, events: r.events }, null, 1);
  det.appendChild(pre);
  mk('Show details', () => { det.open = !det.open; });
  mk('Explain more', () => ask('Explain more: ' + cmd));
  mk('Technical version', () => ask('Technical version: ' + cmd));
  rec.el.append(wrap, det);
}

// ---- §75 approvals: voice REFUSED by policy; typed decision is the durable path ----
async function postConfirm(pid, reply, mode) {
  const r = await fetch('/admin/kai/holding/command/confirm', {
    method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pending_action_id: pid, reply, interaction_mode: mode }),
  });
  let j = {}; try { j = await r.json(); } catch {}
  return { http: r.status, ...j };
}
function renderApprovalCard(rec, approval, note) {
  const p = approval || {};
  const pid = String(p.pending_action_id || '');
  const conf = p.required_confirmation || (pid ? 'approve ' + pid : '');
  const card = document.createElement('div'); card.className = 'kaip-approval'; card.setAttribute('role', 'group'); card.setAttribute('aria-label', 'Approval required — typed decision');
  const head = document.createElement('div'); head.className = 'kaip-ap-head'; head.textContent = '⚠ APPROVAL REQUIRED — voice carries no authority (§75). Decide by typing.';
  const grid = document.createElement('dl'); grid.className = 'kaip-ap-grid';
  for (const [k, v] of [['Action', p.ACTION || p.action], ['Target', p.TARGET || p.target], ['Risk', p.RISK || p.action_class || p.risk], ['Pending id', pid || '(none returned)'], ['Note', note]]) {
    if (v == null || v === '') continue;
    const dt = document.createElement('dt'); dt.textContent = k; const dd = document.createElement('dd'); dd.textContent = String(v); grid.append(dt, dd);
  }
  const form = document.createElement('form'); form.className = 'kaip-ap-form'; form.autocomplete = 'off';
  const inp = document.createElement('input'); inp.type = 'text'; inp.className = 'kaip-ap-input'; inp.setAttribute('aria-label', 'Typed approval decision'); inp.placeholder = conf ? `Type exactly: ${conf}` : 'Type your decision';
  const btn = document.createElement('button'); btn.type = 'submit'; btn.className = 'kaip-vbtn'; btn.textContent = 'Submit typed decision';
  const msg = document.createElement('div'); msg.className = 'kaip-ap-msg'; msg.setAttribute('role', 'status'); msg.setAttribute('aria-live', 'polite');
  form.append(inp, btn);
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const reply = inp.value.trim(); if (!reply) return;
    msg.textContent = 'Submitting…';
    try {
      const out = await postConfirm(pid, reply, 'text');
      msg.textContent = `${out.status || 'HTTP ' + out.http}${out.reason ? ' — ' + out.reason : ''}`;
      if (out.status === 'APPROVED' || out.status === 'REJECTED') { voice.pendingApproval = null; inp.disabled = btn.disabled = true; setKaiState(_realState('online')); }
    } catch { msg.textContent = 'Confirm request failed (link error).'; }
  });
  card.append(head, grid, form, msg);
  rec.el.appendChild(card);
  voice.pendingApproval = { pending_action_id: pid, required_confirmation: conf, card, input: inp, msg };
}
async function voiceConfirm(words) {
  const pa = voice.pendingApproval;
  addMessage('user', words, { voice: true });
  let text;
  try {
    const out = await postConfirm(pa.pending_action_id, words, 'voice');   // will be REFUSED (§75) — surfaced, audited server-side
    text = `Voice approval REFUSED by policy (${out.status || 'HTTP ' + out.http}): ${out.reason || 'the voice channel carries no authority (§75).'} Type your decision in the approval card.`;
  } catch { text = 'Voice approval could not be sent (link error) — and it would be refused by policy anyway (§75). Type your decision in the approval card.'; }
  addMessage('kai', text);
  if (pa.msg) pa.msg.textContent = 'Voice decision refused — type it here.';
  try { pa.input.focus(); } catch {}
  if (shouldSpeak('voice-answer')) speak("I can't authorize that by voice. Please type your decision.");
}

// ---- §50/§51 spoken form: calm, concise, executive — summary first, depth stays on the dashboard ----
const SPOKEN_MAX = 350;   // mirrors voice_session._SPOKEN_SUMMARY_MAX
function spokenForm(text) {
  let t = String(text || '').replace(/```[\s\S]*?```/g, ' code block omitted ').replace(/https?:\/\/\S+/g, 'link')
    .replace(/[*_`#>]+/g, '').replace(/\s+/g, ' ').trim();
  if (t.length <= SPOKEN_MAX) return t;
  const parts = t.match(/[^.!?]+[.!?]+(\s|$)/g) || [t];
  let out = '';
  for (const p of parts) { if ((out + p).length > SPOKEN_MAX) break; out += p; }
  if (!out) out = t.slice(0, SPOKEN_MAX).replace(/\s\S*$/, '') + '…';
  return out.trim();
}
const voiceEnabled = () => !!(state.voiceCaps && state.voiceCaps.enabled);   // backend truth — BRIDGE_OFF/NOT_OWNER/FLAG_OFF/unreachable ⇒ false
function shouldSpeak(kind, severity) {
  const s = state.settings;
  if (!voiceEnabled()) return false;                    // M3: nothing is ever spoken unless the backend says KAI_VOICE_ENABLED
  if (s.muted || s.privacy_mode === 'VOICE_OFF') return false;
  if (s.speak_responses === 'never' && kind !== 'critical') return false;
  if (kind === 'answer' && s.speak_responses === 'nexus' && state.presenceMode !== 'nexus') return false;
  if (kind === 'arrival' && !s.spoken_arrival) return false;
  if (withinQuietHours()) return !!(s.auto_speak_critical && isCritical(severity));   // §68
  return true;
}
async function speak(text, opts) {
  const t = spokenForm(text);
  if (!t || !voiceEnabled() || state.settings.muted) return false;   // M3: the public KAI.speak() path is gated by backend truth too
  if (!voice.cancel) { setVoiceNote(voiceStatus().reason); return false; }   // L5: no single stop path → nothing may speak
  try { await ensureVoiceLibs(); } catch { setVoiceNote('TTS library failed to load — text only.', true); return false; }
  if (!voice.tts) voice.tts = window.KaiTTSProvider.createProvider('web-speech', { preferredVoiceName: state.settings.voice_name || null });
  if (!voice.tts.availability().available) { setVoiceNote('speechSynthesis unavailable in this browser — text only.', true); return false; }
  voice.cancel.stop('restart');   // replace any current utterance through the ONE path
  voice.tts.setPreferredVoice(state.settings.voice_name || null);
  const used = voice.tts.resolveVoice();   // M4: the SAME resolution the provider speaks with — no presence-side copy
  voice.ttsVoice = used; voice.speakingNetwork = !used || used.localService !== true;   // fail-honest: unknown voice ⇒ may be network-synthesized
  if (!voice.subs) voice.subs = new window.KaiSubtitles.KaiSubtitleBuffer({ maxChars: 240 });
  const epoch = voice.subs.begin(); let idx = 0; let sawBoundary = false;
  const pushTo = end => { if (end > idx) { voice.subs.push(t.slice(idx, end), epoch); idx = end; paintSubtitles(); } };
  voice.tts.speak(t, {
    rate: 0.98 * state.settings.speed, pitch: 0.96,
    onstart: () => { setKaiState('speaking'); if (voice.stt) voice.stt.armBargeIn(true); paintVoice(); setTimeout(() => { if (!sawBoundary && state.kaiState === 'speaking') pushTo(t.length); }, 600); },
    onboundary: e => { if (!e || typeof e.charIndex !== 'number') return; sawBoundary = true; const rest = t.slice(e.charIndex).search(/\s|$/); pushTo(e.charIndex + (e.charLength || (rest < 0 ? 0 : rest))); },
    onend: () => { pushTo(t.length); voice.subs.finalize(); paintSubtitles(); _spokeDone(); },
    onerror: err => { voice.subs.interrupt(); paintSubtitles(); if (err && err !== 'interrupted' && err !== 'canceled') setVoiceNote('TTS error: ' + err, true); _spokeDone(); },
  });
  return true;
}
function _spokeDone() {
  voice.speakingNetwork = false;
  if (state.kaiState === 'speaking') setKaiState(_realState('online'));
  paintVoice();
}
function paintSubtitles() {
  if (!subsEl || !voice.subs) return;
  const v = voice.subs.visible();
  subsEl.textContent = v;
  subsEl.dataset.state = voice.subs.getState();
}

// ---- the voice control cluster (§5/§6/§7) — ALWAYS visible; honest DISABLED WITH REASON ----
function renderVoiceBar(container, compact) {
  voiceEl = container;
  container.className = 'kaip-voice' + (compact ? ' compact' : '');
  container.setAttribute('role', 'group'); container.setAttribute('aria-label', 'KAI voice controls');
  // M7: mic + Stop listening + ⚙ only — privacy mode, mute and the camera disclosure live in the §67 settings panel.
  container.innerHTML = `
    <button type="button" class="kaip-mic" id="kaip-mic" aria-pressed="false" aria-describedby="kaip-voice-reason" aria-keyshortcuts="Space Enter" title="Push to talk — hold (pointer, or Space/Enter)">
      <span class="kaip-mic-ico" aria-hidden="true">🎙</span><span class="kaip-mic-label">Hold to talk</span></button>
    <button type="button" class="kaip-vbtn" id="kaip-stoplisten" title="Stop listening (Esc)">Stop listening</button>
    <button type="button" class="kaip-vbtn" id="kaip-settings-btn" aria-label="KAI presence settings: privacy mode, mute, voice, camera" title="Presence settings (§67): privacy mode, mute, voice, quiet hours, camera OFF">⚙</button>
    <div class="kaip-voice-reason" id="kaip-voice-reason" role="status" aria-live="polite"></div>`;
  const mic = container.querySelector('#kaip-mic');
  const press = e => {
    // Only a REAL press may mint the activation-exempt 'ptt-press'/'session-button' triggers (e === null is the
    // keyboard path, which its own handler guards). A synthetic pointerdown is refused here, at the DOM edge.
    if (e && e.isTrusted === false) return;
    if (e && e.button != null && e.button !== 0) return;
    if (e && e.preventDefault) e.preventDefault();
    if (state.settings.privacy_mode === 'SESSION_LISTENING') { voice.listening ? stopListening('user') : startListening('session-button'); return; }
    if (e && e.pointerId != null) { try { mic.setPointerCapture(e.pointerId); } catch {} }
    voice.pttHeld = true;            // M2: held from press to release; startListening re-checks it after every await
    startListening('ptt-press');
  };
  const release = () => { voice.pttHeld = false; if (state.settings.privacy_mode === 'SESSION_LISTENING') return; if (voice.listening && voice.mode === 'PUSH_TO_TALK') stopListening('ptt-release'); };
  const prewarm = () => { if (voiceStatus().ok) ensureVoiceLibs().catch(() => {}); };   // shrink the press→recognizer window (loads scripts only, opens nothing)
  mic.addEventListener('pointerenter', prewarm);
  mic.addEventListener('focus', prewarm);
  mic.addEventListener('pointerdown', press);
  mic.addEventListener('pointerup', release);
  mic.addEventListener('pointercancel', release);
  mic.addEventListener('lostpointercapture', release);
  mic.addEventListener('keydown', e => { if (e.isTrusted === false) return; if ((e.key === ' ' || e.key === 'Enter') && !e.repeat) { e.preventDefault(); press(null); } });
  mic.addEventListener('keyup', e => { if (e.key === ' ' || e.key === 'Enter') { e.preventDefault(); release(); } });
  mic.addEventListener('click', e => e.preventDefault());
  container.querySelector('#kaip-stoplisten').addEventListener('click', () => { stopListening('user'); setVoiceNote('Listening stopped.'); });
  container.querySelector('#kaip-settings-btn').addEventListener('click', () => openSettings());
  paintVoice();
}
let micBanner, toastEl;
function paintVoice() {
  const st = voiceStatus();
  if (voiceEl) {
    const mic = voiceEl.querySelector('#kaip-mic'), stopL = voiceEl.querySelector('#kaip-stoplisten'), reason = voiceEl.querySelector('#kaip-voice-reason');
    const session = state.settings.privacy_mode === 'SESSION_LISTENING';
    mic.disabled = !st.ok && !voice.listening;
    mic.dataset.on = voice.listening ? '1' : '0';
    mic.setAttribute('aria-pressed', voice.listening ? 'true' : 'false');
    const label = voice.listening ? (session ? 'Listening — click to stop' : 'Listening…') : (!st.ok ? 'Mic disabled' : (session ? 'Start listening session' : 'Hold to talk'));
    mic.querySelector('.kaip-mic-label').textContent = label;
    mic.setAttribute('aria-label', label);           // L3: the compact bar hides the visible label
    const parts = [st.ok ? 'VOICE READY' : 'VOICE DISABLED', st.reason];
    if (state.voiceCaps && state.voiceCaps.approval_by_voice === 'REFUSED') parts.push('Approvals by voice: REFUSED (§75) — type them.');
    if (voice.note) parts.push(voice.note);
    // Deduped at the ONE render point: several paths call setVoiceNote(st.reason) to surface the reason on
    // an interaction, but the reason is already the second part — without this the operator reads the same
    // sentence twice ("VOICE DISABLED · <reason> · <reason>"), which looks like two separate faults.
    const seen = new Set();
    reason.textContent = parts.filter(Boolean)
      .filter(p => { const k = String(p).trim(); if (seen.has(k)) return false; seen.add(k); return true; })
      .join(' · ');
    mic.title = !st.ok ? reason.textContent : (session ? 'Toggle an explicit listening session (indicator stays on)' : 'Push to talk — hold (pointer, or Space/Enter)');   // M7: the full reason rides on the mic (title + aria-describedby)
    stopL.disabled = !voice.listening;
    voiceEl.dataset.status = st.code;
    voiceEl.dataset.err = voice.noteErr ? '1' : '0';   // L4: amber only for real failures
  }
  // ---- unmistakable MIC / REC / NETWORK indicator (fixed, aria-live assertive) ----
  if (!micBanner) {
    micBanner = document.createElement('div'); micBanner.className = 'kaip-mic-banner'; micBanner.hidden = true;
    micBanner.setAttribute('role', 'status'); micBanner.setAttribute('aria-live', 'assertive');
    micBanner.innerHTML = '<span class="kaip-mic-dot" aria-hidden="true"></span><span class="kaip-mic-text" id="kaip-mic-text"></span><span class="kaip-mic-rec" id="kaip-mic-rec">REC ●</span><span class="kaip-mic-net" id="kaip-mic-net"></span><span class="kaip-mic-interim" id="kaip-mic-interim"></span><button type="button" class="kaip-mic-stop" id="kaip-mic-stopbtn" aria-label="Stop microphone and speech">Stop</button>';
    micBanner.querySelector('#kaip-mic-stopbtn').addEventListener('click', () => KAI.stop('user-stop'));
    document.body.appendChild(micBanner);
  }
  const speakingNet = state.kaiState === 'speaking' && voice.speakingNetwork;
  const show = voice.listening || speakingNet;
  micBanner.hidden = !show;
  micBanner.dataset.kind = voice.listening ? 'mic' : 'tts';
  micBanner.dataset.rec = voice.capturing ? '1' : '0';
  if (show) {
    micBanner.querySelector('#kaip-mic-text').textContent = voice.listening ? `MIC OPEN — KAI is listening (${voice.mode})` : 'KAI is speaking';
    micBanner.querySelector('#kaip-mic-rec').hidden = !voice.capturing;
    micBanner.querySelector('#kaip-mic-net').textContent = voice.listening
      ? '☁ audio leaves this device → browser speech provider (network-backed; on-device not guaranteed)'
      : (voice.ttsVoice ? '☁ TTS voice is network-synthesized' : '☁ voice provider unknown — may be network-synthesized');
    micBanner.querySelector('#kaip-mic-interim').textContent = voice.interim ? '“' + voice.interim + '”' : '';
  }
  if (stopBtn) stopBtn.hidden = !(state.connectionState === 'streaming' || state.kaiState === 'speaking' || voice.listening);
  paintOrb();
}
function toast(text) {
  if (!toastEl) { toastEl = document.createElement('div'); toastEl.className = 'kaip-toast'; toastEl.setAttribute('role', 'status'); toastEl.setAttribute('aria-live', 'polite'); document.body.appendChild(toastEl); }
  toastEl.textContent = text; toastEl.classList.add('show');
  clearTimeout(toastEl._t); toastEl._t = setTimeout(() => toastEl.classList.remove('show'), 8000);
}

// ---- §67 settings panel — privacy-preserving defaults; every change persists (try/catch) ----
let settingsEl, settingsOpener;
function openSettings() {
  if (!settingsEl) mountSettings();
  settingsOpener = document.activeElement;   // L3: focus returns here on close
  syncSettingsForm();
  settingsEl.hidden = false; settingsEl.setAttribute('aria-hidden', 'false');
  fillVoiceList();
  if (cameraStatus().ok) ensureGesture().catch(() => {});   // loads the seam script only (opens nothing) so the click→camera window stays short
  setTimeout(() => settingsEl.querySelector('#ks-greeting').focus(), 50);
}
function closeSettings() {
  if (!settingsEl || settingsEl.hidden) return;
  settingsEl.hidden = true; settingsEl.setAttribute('aria-hidden', 'true');
  try { settingsOpener && settingsOpener.focus(); } catch {} settingsOpener = null;
}
function mountSettings() {
  settingsEl = document.createElement('aside');
  settingsEl.className = 'kaip-settings'; settingsEl.hidden = true;
  settingsEl.setAttribute('role', 'dialog'); settingsEl.setAttribute('aria-modal', 'true'); settingsEl.setAttribute('aria-label', 'KAI presence settings'); settingsEl.setAttribute('aria-hidden', 'true');
  settingsEl.innerHTML = `
    <div class="kaip-set-head"><b>KAI presence settings (§67)</b><button class="kaip-x" id="ks-close" type="button" aria-label="Close settings">×</button></div>
    <div class="kaip-set-body">
      <label class="kaip-set-field">Greeting text<input id="ks-greeting" type="text" maxlength="120" placeholder="Welcome back."></label>
      <label class="kaip-set-row"><input id="ks-display_arrival" type="checkbox"> Show the arrival brief when the dashboard opens (§66)</label>
      <label class="kaip-set-row"><input id="ks-spoken_arrival" type="checkbox"> Speak the arrival brief</label>
      <fieldset><legend>Voice input · §6 privacy</legend>
        <label class="kaip-set-field">Privacy mode
          <select id="ks-privacy_mode">
            <option value="VOICE_OFF">VOICE_OFF</option>
            <option value="PUSH_TO_TALK">PUSH_TO_TALK (default)</option>
            <option value="WAKE_WORD_LOCAL">WAKE_WORD_LOCAL — UNAVAILABLE</option>
            <option value="SESSION_LISTENING">SESSION_LISTENING</option>
          </select></label>
        <div class="kaip-set-note" id="ks-wake-note"></div>
        <label class="kaip-set-row"><input id="ks-muted" type="checkbox"> Mute — hard mute (§68): mic off, nothing processed, nothing spoken</label>
        <div class="kaip-set-note">Push-to-talk: hold the mic button (pointer, or Space/Enter). The mic never opens without your press; a visible MIC OPEN / REC / network indicator is mandatory and cannot be turned off.</div>
      </fieldset>
      <fieldset><legend>Voice output · §50/§51</legend>
        <label class="kaip-set-field">Voice<select id="ks-voice_name"><option value="">Provider default (masculine ranking)</option></select></label>
        <label class="kaip-set-field">Speed <output id="ks-speed-out"></output><input id="ks-speed" type="range" min="0.5" max="2" step="0.05"></label>
        <label class="kaip-set-field">Speak answers to typed questions
          <select id="ks-speak_responses"><option value="never">Never (text only)</option><option value="nexus">In Nexus only</option><option value="always">Always</option></select></label>
        <label class="kaip-set-row"><input id="ks-auto_speak_critical" type="checkbox"> Auto-speak critical alerts (the only thing allowed through quiet hours)</label>
      </fieldset>
      <fieldset><legend>Quiet mode · §68</legend>
        <label class="kaip-set-row"><input id="ks-qh" type="checkbox"> Quiet hours (no non-critical speech)</label>
        <div class="kaip-set-inline"><label>from <input id="ks-qh-start" type="number" min="0" max="23" aria-label="Quiet hours start (hour)"></label><label>to <input id="ks-qh-end" type="number" min="0" max="23" aria-label="Quiet hours end (hour)"></label> local time</div>
        <label class="kaip-set-field">Notification severity
          <select id="ks-notification_severity"><option value="critical">Critical only</option><option value="high">High and above</option><option value="medium">Medium and above</option><option value="all">All</option></select></label>
      </fieldset>
      <fieldset><legend>Camera / gesture · §8/§94</legend>
        <label class="kaip-set-row"><input id="ks-camera_enabled" type="checkbox" disabled> Enable camera for this session — local only. Never persisted; a visible CAMERA ON indicator is mandatory; closes on Stop, tab hidden, sign-out, mute — never auto-restarts.</label>
        <div class="kaip-set-note" id="ks-cam-note" role="status" aria-live="polite"></div>
        <label class="kaip-set-row"><input id="ks-gesture_enabled" type="checkbox" disabled> Gesture — DISABLED: no certified local recognizer (RECOGNIZER_UNAVAILABLE_NOT_CERTIFIED); no frame is read. Gestures will never authorize actions (§75).</label>
        <label class="kaip-set-row"><input id="ks-wake_word_enabled" type="checkbox" disabled> Wake word — requires a genuinely on-device engine (none present); cloud fallback is forbidden.</label>
      </fieldset>
      <div class="kaip-set-note kaip-set-lock">🔒 Security settings cannot disable required critical audit: final commands and responses are audited server-side (§92) regardless of these preferences. Raw audio is never persisted or logged. Stored locally in this browser only.<span id="ks-lock-cam"></span></div>
      <div class="kaip-set-actions"><button type="button" id="ks-reset" class="kaip-vbtn">Reset to privacy defaults</button><span class="kaip-set-saved" id="ks-saved" role="status" aria-live="polite"></span></div>
    </div>`;
  document.body.appendChild(settingsEl);
  const q = id => settingsEl.querySelector('#' + id);
  q('ks-close').addEventListener('click', closeSettings);
  settingsEl.addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.stopPropagation(); closeSettings(); return; }
    if (e.key !== 'Tab') return;   // L3: minimal focus wrap inside the modal
    const f = [...settingsEl.querySelectorAll('button, input, select')].filter(x => !x.disabled);
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  const bind = (id, key, kind) => q(id).addEventListener('change', e => {
    const v = kind === 'bool' ? e.target.checked : kind === 'num' ? Number(e.target.value) : e.target.value;
    if (key === 'privacy_mode') { setPrivacyMode(v); syncSettingsForm(); return; }
    if (key === 'muted') { setMuted(v); saved(); return; }
    state.settings[key] = v; state.settings = loadSettingsFrom(state.settings); saveSettings(); saved(); paintVoice();
    if (key === 'voice_name' && voice.tts) voice.tts.setPreferredVoice(v || null);
  });
  bind('ks-greeting', 'greeting'); bind('ks-display_arrival', 'display_arrival', 'bool'); bind('ks-spoken_arrival', 'spoken_arrival', 'bool');
  bind('ks-privacy_mode', 'privacy_mode'); bind('ks-muted', 'muted', 'bool');
  bind('ks-voice_name', 'voice_name'); bind('ks-speak_responses', 'speak_responses'); bind('ks-auto_speak_critical', 'auto_speak_critical', 'bool');
  bind('ks-notification_severity', 'notification_severity');
  q('ks-speed').addEventListener('input', e => { state.settings.speed = Number(e.target.value); q('ks-speed-out').textContent = state.settings.speed.toFixed(2) + '×'; saveSettings(); saved(); });
  const qh = () => { state.settings.quiet_hours = { enabled: q('ks-qh').checked, start: +q('ks-qh-start').value || 0, end: +q('ks-qh-end').value || 0 }; state.settings = loadSettingsFrom(state.settings); saveSettings(); saved(); paintVoice(); };
  ['ks-qh', 'ks-qh-start', 'ks-qh-end'].forEach(id => q(id).addEventListener('change', qh));
  // §8/§94 the ONLY path that opens the camera: the owner's click on this control (its change event runs inside the user activation).
  // isTrusted: a script-forged change event is NOT an owner click — without this a page script could mint the
  // 'owner-click' trigger by dispatching on this control while piggybacking any unrelated real click's activation.
  q('ks-camera_enabled').addEventListener('change', e => { if (!e.isTrusted) return; if (e.target.checked) startCamera('owner-click'); else { stopCamera('settings-off'); syncSettingsForm(); } });
  q('ks-reset').addEventListener('click', () => { try { localStorage.removeItem(SETTINGS_KEY); } catch {} stopListening('reset'); stopCamera('reset'); state.settings = loadSettings(); saveSettings(); syncSettingsForm(); paintVoice(); saved('Reset to privacy defaults.'); });
  function saved(t) { q('ks-saved').textContent = t || 'Saved.'; clearTimeout(q('ks-saved')._t); q('ks-saved')._t = setTimeout(() => { q('ks-saved').textContent = ''; }, 1800); }
}
function syncSettingsForm() {
  if (!settingsEl) return;
  const s = state.settings, q = id => settingsEl.querySelector('#' + id);
  q('ks-greeting').value = s.greeting; q('ks-display_arrival').checked = s.display_arrival; q('ks-spoken_arrival').checked = s.spoken_arrival;
  q('ks-privacy_mode').value = s.privacy_mode; q('ks-muted').checked = s.muted;
  const ww = q('ks-privacy_mode').querySelector('[value="WAKE_WORD_LOCAL"]'); ww.disabled = !wakeWordLocalAvailable();
  q('ks-wake-note').textContent = wakeWordLocalAvailable() ? 'WAKE_WORD_LOCAL: on-device engine present.' : 'WAKE_WORD_LOCAL: UNAVAILABLE — ' + ((state.voiceCaps && state.voiceCaps.wake_word && state.voiceCaps.wake_word.reason) || 'no on-device wake-word engine; a cloud continuous-audio fallback is forbidden (§6).');
  q('ks-voice_name').value = s.voice_name; q('ks-speed').value = s.speed; q('ks-speed-out').textContent = s.speed.toFixed(2) + '×';
  q('ks-speak_responses').value = s.speak_responses; q('ks-auto_speak_critical').checked = s.auto_speak_critical;
  q('ks-qh').checked = s.quiet_hours.enabled; q('ks-qh-start').value = s.quiet_hours.start; q('ks-qh-end').value = s.quiet_hours.end;
  q('ks-notification_severity').value = s.notification_severity;
  // §8/§94: the control reflects the REAL in-memory session flag and is enabled ONLY when the backend says AVAILABLE_SESSION
  // (or to turn an open camera off). The honest reason is always shown; gesture stays disabled (no certified recognizer).
  const cs = cameraStatus(), camOn = !!(cam.session && cam.session.on);
  q('ks-camera_enabled').checked = camOn; q('ks-camera_enabled').disabled = !cs.ok && !camOn;
  q('ks-cam-note').textContent = [camOn ? 'CAMERA ON — this session only, local only, nothing leaves this device.' : (cs.ok ? 'CAMERA OFF · ' + cs.reason : 'CAMERA DISABLED — ' + cs.reason),
    'Recognizer: ' + gestureStatus().recognizer + ' (no frames read).', cam.note].filter(Boolean).join(' · ');
  q('ks-lock-cam').textContent = camOn ? ' Camera: ON for this session only — never persisted; closes on Stop, sign-out, mute, tab hidden.' : ' Camera: OFF — never persisted as on.';
  q('ks-gesture_enabled').checked = false; q('ks-wake_word_enabled').checked = false;
}
async function fillVoiceList() {
  if (!settingsEl) return;
  const sel = settingsEl.querySelector('#ks-voice_name');
  try { await ensureVoiceLibs(); } catch { return; }
  if (!voice.tts) voice.tts = window.KaiTTSProvider.createProvider('web-speech', { preferredVoiceName: state.settings.voice_name || null });
  const ranked = voice.tts.rankVoices();
  const cur = state.settings.voice_name;
  sel.replaceChildren();
  const def = document.createElement('option'); def.value = ''; def.textContent = 'Provider default (masculine ranking)'; sel.appendChild(def);
  for (const r of ranked) { const o = document.createElement('option'); o.value = r.voice.name; o.textContent = `${r.voice.name} · ${r.voice.lang || '?'}${r.masculine ? ' · ♂' : ''}${r.voice.localService === false ? ' · ☁ network' : ' · local'}`; sel.appendChild(o); }
  sel.value = ranked.some(r => r.voice.name === cur) ? cur : '';
}

// ---- §66 owner arrival — one greeting per session (§125), from REAL dashboard data only (§64) ----
const DASH_RE = /^\/admin\/?(index\.html|hub|holding|mission-nexus|command-center)?\/?$/;
async function arrival() {
  const s = state.settings;
  if (!DASH_RE.test(location.pathname) || !canGovernedChat()) return;
  if (!s.display_arrival && !s.spoken_arrival) return;
  const KEY = 'kai.arrival.greeted', LAST = 'kai.arrival.last';
  try { if (sessionStorage.getItem(KEY)) return; } catch {}                                       // this tab already greeted
  try { const last = +localStorage.getItem(LAST) || 0; if (Date.now() - last < 6 * 3600e3) return; } catch {}   // reload/nav within 6h = same meaningful session (whoami exposes no session id)
  let v = null;
  try { const r = await fetch('/admin/kai/holding/view', { credentials: 'include' }); if (r.ok) v = await r.json(); } catch {}
  if (!v || typeof v !== 'object') return;                                                         // no data → no greeting, never a fake "all good"
  const items = Array.isArray(v.today_for_you) ? v.today_for_you : [];
  const att = v.attention || {};
  const top = items[0] || null;
  const text = [
    s.greeting || 'Welcome back.',
    items.length ? `${items.length} item${items.length === 1 ? '' : 's'} need you.` : 'Nothing needs a decision right now.',
    top ? `Top: ${top.title || ''}${top.severity ? ' (' + top.severity + ')' : ''}${top.company ? ' · ' + top.company : ''}.` : '',
    att.summary && att.status !== 'UNAVAILABLE' && att.focus_state ? `Attention: ${att.summary}` : '',
  ].filter(Boolean).join(' ');
  try { sessionStorage.setItem(KEY, '1'); localStorage.setItem(LAST, String(Date.now())); } catch {}
  const sev = (top && top.severity) || 'info';
  const notable = !top || sevRank(sev) >= sevRank({ critical: 'critical', high: 'high', medium: 'medium', all: 'info' }[s.notification_severity]);
  if (s.display_arrival) { addMessage('kai', text, { arrival: true }); if (notable && drawerEl && !drawerEl.classList.contains('open')) toast('Arrival brief ready — open KAI (⌘K)'); }
  if (notable && shouldSpeak('arrival', sev)) speak(text, { severity: sev });
  emit('arrival', { text, items: items.length, severity: sev });
}

// ---- §10/§49 embodiment — the certified VIDEO fallback wired to presence state; GLB honestly ASSET_UNAVAILABLE ----
async function mountAvatar(host) {
  avatar.host = host;
  host.classList.add('kaip-av'); host.dataset.state = state.kaiState;
  host.innerHTML = `
    <video class="kaip-av-media" id="kaip-av-idle" loop muted playsinline preload="none" aria-hidden="true"></video>
    <video class="kaip-av-media" id="kaip-av-speak" loop muted playsinline preload="none" aria-hidden="true"></video>
    <img class="kaip-av-media" id="kaip-av-poster" alt="" aria-hidden="true" decoding="async">
    <span class="kaip-av-tag" id="kaip-av-tag" role="status" aria-live="polite">AVATAR · loading…</span>`;
  const vIdle = host.querySelector('#kaip-av-idle'), vSpeak = host.querySelector('#kaip-av-speak'), poster = host.querySelector('#kaip-av-poster'), tag = host.querySelector('#kaip-av-tag');
  const setClip = clip => { host.dataset.clip = clip; const v = clip === 'speak' ? vSpeak : vIdle; const p = v.play && v.play(); if (p) p.catch(() => {}); };
  // §72: media sources attach only after the shell painted (idle time) — the core UI never waits on video.
  const attach = () => {
    poster.src = '/admin/nexus-assets/kai.jpg'; vIdle.src = '/admin/nexus-assets/kai-idle.mp4'; vSpeak.src = '/admin/nexus-assets/kai-speak.mp4';
    [vIdle, vSpeak].forEach(v => { v.addEventListener('loadeddata', () => v.classList.add('ready'), { once: true }); v.addEventListener('error', () => v.classList.remove('ready')); v.load(); });
    setClip('idle');
  };
  ('requestIdleCallback' in window) ? requestIdleCallback(attach, { timeout: 2000 }) : setTimeout(attach, 300);
  addEventListener('pointerdown', () => setClip(host.dataset.clip || 'idle'), { once: true });   // autoplay unlock
  try { await loadSeq(AVATAR_LIBS); } catch { tag.textContent = 'AVATAR · driver libs failed to load — poster only'; return; }
  const AD = window.KaiAvatarDriver;
  avatar.glb = AD.createDriver('glb', {});                     // production target: no rigged .glb → ASSET_UNAVAILABLE (§6 honest)
  avatar.driver = AD.createDriver('video', { setClip });        // certified fallback: idle ⇄ speak clip swap only
  avatar.driver.load();
  avatar.mode = avatar.glb.getDiagnostics().mode;
  const caps = avatar.driver.getCapabilities();
  tag.textContent = `GLB ${avatar.mode} · VIDEO fallback · visemes=${caps.visemes} lip_sync=${caps.lip_sync} · no biometric/emotion inference`;
  on('kaiState', () => avatarState());
  avatarState();
}
const EMB_HINT = { working: 'executing', waiting: 'waiting', degraded: 'error' };
function avatarState() {
  if (!avatar.driver) return;
  const EMB = window.NexusEmbodiment;
  const emb = EMB ? EMB.resolve({ kaiState: state.kaiState, hint: EMB_HINT[state.kaiState] || '' }) : (state.kaiState === 'speaking' ? 'speaking' : 'idle');
  const spec = EMB ? EMB.spec(emb) : { video: emb === 'speaking' ? 'speak' : 'idle', label: emb };
  avatar.driver.setState(spec.video === 'speak' ? 'speaking' : emb);   // the video driver's only real capability: the clip swap
  if (avatar.host) { avatar.host.dataset.state = state.kaiState; avatar.host.dataset.embodiment = emb; }
  emit('embodiment', { state: emb, spec });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();
