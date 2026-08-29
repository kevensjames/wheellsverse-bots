// ============================================================================
// KAI Presence — the ONE frontend provider for KAI across the admin shell (P11/P12).
// Buildless ES module: any admin page includes it with
//   <script type="module" src="/admin/kai-presence.js"></script>
//
// It is the single canonical KAI state store (§P14) with three presentations:
//   MINIMIZED  — a small always-on orb reflecting KAI's state
//   ASSISTANT  — a contextual drawer that streams the governed brain
//   (NEXUS mode is mounted separately and boots this same provider)
//
// Governed by the merge spine: it talks to the same-origin bridge
// POST /admin/kai/kai-chat/stream (owner-only kai.ultra, SSE), carries the
// operator session cookie (credentials:'include'), and sends only the
// descriptive page-context envelope. No second identity, no second brain.
//
// The admin is a MULTI-PAGE static app, so "one conversation across navigation"
// is server-side: the conversation_id is persisted in localStorage and continued
// on every page; the governed endpoint appends to it.
// ============================================================================

// ---- tiny pub/sub -----------------------------------------------------------
const subs = new Map();
function on(evt, fn) { (subs.get(evt) ?? subs.set(evt, new Set()).get(evt)).add(fn); return () => subs.get(evt)?.delete(fn); }
function emit(evt, p) { subs.get(evt)?.forEach(fn => { try { fn(p); } catch (e) { console.error(e); } }); }

// ---- voice: browser TTS, masculine. Nexus only (§25/§32: quiet when minimized) --
const _MALE = ['Google UK English Male', 'Microsoft Guy', 'Microsoft David', 'Daniel', 'Arthur', 'Oliver', 'Alex', 'Google US English'];
const _FEMALE = /samantha|victoria|karen|moira|tessa|fiona|susan|zira|serena|allison|ava|female|woman/i;
let _voices = [], _voice = null;
function _pickVoice() {
  if (!_voices.length) return null;
  for (const n of _MALE) { const v = _voices.find(x => x.name.includes(n)); if (v) return v; }
  const en = _voices.filter(v => /^en/i.test(v.lang));
  return en.find(v => !_FEMALE.test(v.name)) || en[0] || _voices[0] || null;
}
function _refreshVoices() { if (!('speechSynthesis' in window)) return; _voices = speechSynthesis.getVoices() || []; _voice = _pickVoice(); }
if ('speechSynthesis' in window) { _refreshVoices(); speechSynthesis.addEventListener('voiceschanged', _refreshVoices); }
function speak(text) {
  if (!('speechSynthesis' in window) || !text) return;
  try {
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text.slice(0, 700));
    u.voice = _voice || _pickVoice(); u.rate = 0.98; u.pitch = 0.96;
    u.onstart = () => setKaiState('speaking');   // swaps the avatar to the speaking loop
    u.onend = () => setKaiState('online');
    speechSynthesis.speak(u);
  } catch {}
}
function stopSpeak() { try { if ('speechSynthesis' in window) speechSynthesis.cancel(); } catch {} }

// ---- canonical state (§P14) -------------------------------------------------
const state = {
  principal: null,          // {role, scopes} from /admin/session/whoami
  flags: {},                // /admin/ui-config
  conversationId: localStorage.getItem('kai.conv') || null,
  messages: [],             // {role, text, el}
  kaiState: 'offline',      // offline|online|listening|thinking|speaking|alert
  presenceMode: 'minimized',// minimized|assistant|nexus
  context: null,            // descriptive page context envelope
  connectionState: 'idle',  // idle|streaming
  streamState: null,        // AbortController while streaming
  forcedEntity: null,       // entity passed to KAI.ask() for this turn
};
// Public API — the ONE provider, reusable by a Nexus shell and by page actions.
export const KAI = { state, on, open: () => openDrawer(), ask: (t, e) => ask(t, e) };
if (typeof window !== 'undefined') window.KAI = KAI;

function setKaiState(s) { state.kaiState = s; emit('kaiState', s); paintOrb(); }
function setMode(m) { state.presenceMode = m; emit('mode', m); }

// ---- page context (§P7): descriptive-only, never secrets --------------------
function buildContext() {
  // Priority: an explicit entity passed to KAI.ask(), else a [data-kai-entity-*]
  // element on the page, else none. Descriptive-only; never authorization.
  const el = document.querySelector('[data-kai-entity-id]');
  const fe = state.forcedEntity;
  return {
    route: location.pathname,
    module: (document.body.dataset.kaiModule) || _moduleFromPath(),
    surface: 'drawer',
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
  overview:   ['What needs my attention right now?', 'Summarize system + business health.'],
  hub:        ['What needs my attention right now?', 'What should I work on next?'],
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
  if (document.body.dataset.kaiMode === 'nexus') {
    state.presenceMode = 'nexus';
    mountNexus();          // immersive full-screen — same provider, no corner orb
  } else {
    mountOrb();
    mountDrawer();
  }
  // P15: any element with data-kai-ask="<prompt>" fires a governed action, using
  // its own data-kai-entity-{type,id} (if any) as context. Pages opt in with one
  // attribute — no bespoke wiring per surface.
  document.addEventListener('click', e => {
    const t = e.target.closest && e.target.closest('[data-kai-ask]');
    if (!t) return;
    e.preventDefault();
    ask(t.dataset.kaiAsk, { entity_type: t.dataset.kaiEntityType || null, entity_id: t.dataset.kaiEntityId || null });
  });
  setKaiState(state.principal ? 'online' : 'offline');
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
// Establishes/clears the HttpOnly wv_session cookie via the certified endpoints.
// The secret lives only transiently in the request body over HTTPS — it is never
// stored (no localStorage/sessionStorage/JS-cookie/persistent var), never logged,
// never placed in a URL. The real session cookie is HttpOnly and invisible to JS.
async function login(secret) {
  let ok = false;
  try {
    const r = await fetch('/admin/session/login', {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ secret }),
    });
    ok = r.ok;
  } catch { ok = false; }
  await refreshPrincipal();            // server set the cookie; re-read identity server-side
  setKaiState(state.principal ? 'online' : 'offline');
  return ok && !!state.principal;
}
async function logout() {
  try { await fetch('/admin/session/logout', { method: 'POST', credentials: 'same-origin' }); } catch {}
  state.principal = null; emit('principal', state.principal);
  setKaiState('offline');
}

function canGovernedChat() {
  // Owner-only governed chat (kai.ultra) via the bridge. If the bridge/session
  // flags are off, the drawer degrades to a clear "not enabled" message.
  return !!(state.flags.kai_bridge_enabled && state.principal &&
            (state.principal.scopes || []).includes('kai.ultra'));
}

// ---- MINIMIZED: the orb (§P11) ---------------------------------------------
let orbEl;
function mountOrb() {
  orbEl = document.createElement('button');
  orbEl.className = 'kaip-orb';
  orbEl.type = 'button';
  orbEl.title = 'KAI';
  orbEl.innerHTML = '<span class="kaip-orb-dot"></span><span class="kaip-orb-label">KAI</span>';
  orbEl.addEventListener('click', () => openDrawer());
  document.body.appendChild(orbEl);
  paintOrb();
}
const ORB_TEXT = { offline: 'OFFLINE', online: 'ONLINE', listening: 'LISTENING', thinking: 'THINKING', speaking: 'SPEAKING', alert: 'ATTENTION' };
function paintOrb() {
  if (!orbEl) return;
  orbEl.dataset.state = state.kaiState;
  orbEl.querySelector('.kaip-orb-label').textContent = 'KAI ' + (ORB_TEXT[state.kaiState] || '');
}

// ---- ASSISTANT: the drawer (§P12) ------------------------------------------
let drawerEl, msgsEl, inputEl, sendBtn, stopBtn, ctxEl, stateEl;
function mountDrawer() {
  drawerEl = document.createElement('aside');
  drawerEl.className = 'kaip-drawer';
  drawerEl.setAttribute('aria-hidden', 'true');
  drawerEl.innerHTML = `
    <div class="kaip-head">
      <div class="kaip-title"><span class="kaip-title-dot"></span>KAI<span class="kaip-state" id="kaip-state">online</span></div>
      <div class="kaip-head-actions">
        <button class="kaip-logout" id="kaip-logout" type="button" title="Sign out" hidden>Sign out</button>
        <a class="kaip-nexus-link" href="/admin/nexus" title="Enter Nexus — same KAI, immersive">⤢ Nexus</a>
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
    <div class="kaip-suggest" id="kaip-suggest"></div>
    <div class="kaip-msgs" id="kaip-msgs"></div>
    <div class="kaip-input-wrap">
      <textarea class="kaip-input" id="kaip-input" rows="1" placeholder="Ask KAI about this page…"></textarea>
      <div class="kaip-row">
        <span class="kaip-hint"><kbd>Enter</kbd> send · <kbd>Esc</kbd> close</span>
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
  inputEl = drawerEl.querySelector('#kaip-input');
  sendBtn = drawerEl.querySelector('#kaip-send');
  stopBtn = drawerEl.querySelector('#kaip-stop');
  ctxEl = drawerEl.querySelector('#kaip-ctx');
  stateEl = drawerEl.querySelector('#kaip-state');

  drawerEl.querySelector('#kaip-close').addEventListener('click', closeDrawer);
  backdrop.addEventListener('click', closeDrawer);
  sendBtn.addEventListener('click', submit);
  stopBtn.addEventListener('click', stopStream);
  inputEl.addEventListener('input', () => { inputEl.style.height = 'auto'; inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + 'px'; });
  inputEl.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); }
  });
  document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); toggleDrawer(); }
    if (e.key === 'Escape' && drawerEl.classList.contains('open')) closeDrawer();
  });
  on('kaiState', s => { if (stateEl) stateEl.textContent = s; });

  // owner session: wire the sign-in form + the sign-out button, then paint the
  // honest system/session state. Separates SYSTEM HEALTH (bridge/session enabled)
  // from CURRENT SESSION AUTHORIZATION (anonymous vs owner) — a signed-out browser
  // is "sign in required", never "system degraded".
  drawerEl.querySelector('#kaip-auth-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const inp = drawerEl.querySelector('#kaip-auth-secret');
    const msg = drawerEl.querySelector('#kaip-auth-msg');
    const secret = inp.value;
    inp.value = '';                    // clear the field immediately — never persisted
    if (!secret) { msg.textContent = 'Enter the owner access key.'; return; }
    msg.textContent = 'Signing in…';
    const ok = await login(secret);    // secret goes only into the request body, then out of scope
    msg.textContent = ok ? '' : 'Sign-in failed. Check the owner access key.';
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
  const sysHealthy = !!(state.flags.operator_session_enabled && state.flags.kai_bridge_enabled);
  const authed = !!state.principal;
  if (logoutBtn) logoutBtn.hidden = !authed;
  if (canGovernedChat()) {                         // owner + governed → normal chat
    authEl.hidden = true; inputWrap.hidden = false; renderSuggestions();
  } else if (!sysHealthy) {                         // real system state (not a session issue)
    authEl.hidden = false; formEl.hidden = true; inputWrap.hidden = true;
    if (sysEl) sysEl.textContent = 'KAI is not enabled on this deployment.';
  } else if (!authed) {                             // system healthy; just need to sign in
    authEl.hidden = false; formEl.hidden = false; inputWrap.hidden = true;
    if (sysEl) sysEl.textContent = 'KAI system online. Sign in as owner to use governed chat.';
  } else {                                          // signed in, but not owner
    authEl.hidden = false; formEl.hidden = true; inputWrap.hidden = true;
    if (sysEl) sysEl.textContent = `Signed in as ${state.principal.role}. Owner access is required for governed KAI.`;
  }
}

function openDrawer() { drawerEl.classList.add('open'); document.getElementById('kaip-backdrop').classList.add('show'); drawerEl.setAttribute('aria-hidden', 'false'); setMode('assistant'); ctxEl.textContent = _ctxLabel(buildContext()); renderSuggestions(); setTimeout(() => inputEl.focus(), 250); }

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

// Public API: pages can open the drawer or fire a governed prompt.
//   window.KAI.ask("Explain this finding", {entity_type:'finding', entity_id:'472'})
async function ask(text, entity) {
  if (entity && (entity.entity_type || entity.entity_id)) state.forcedEntity = entity;
  if (drawerEl && !drawerEl.classList.contains('open')) openDrawer();  // nexus has no drawer
  document.querySelector('#kaip-suggest')?.replaceChildren();
  addMessage('user', text);
  if (!canGovernedChat()) { addMessage('kai', 'Governed KAI is not enabled here.'); setKaiState('alert'); return; }
  await streamGoverned(text);
  state.forcedEntity = null;
}
function closeDrawer() { drawerEl.classList.remove('open'); document.getElementById('kaip-backdrop').classList.remove('show'); drawerEl.setAttribute('aria-hidden', 'true'); setMode('minimized'); }
function toggleDrawer() { drawerEl.classList.contains('open') ? closeDrawer() : openDrawer(); }
function _ctxLabel(c) { return 'Context · ' + [c.module, c.entity_type && `${c.entity_type} ${c.entity_id || ''}`].filter(Boolean).join(' · '); }

// ---- NEXUS: immersive full-screen (§P13) — same provider, session, conversation
function mountNexus() {
  const nx = document.createElement('div');
  nx.className = 'kaip-nexus';
  nx.innerHTML = `
    <div class="kaip-nx-top">
      <a class="kaip-nx-exit" href="/admin/hub" title="Back to admin">← Exit</a>
      <div class="kaip-nx-brand"><span class="kaip-title-dot"></span>KAI · COMMAND NEXUS <span class="kaip-state" id="kaip-state">online</span></div>
      <span class="kaip-nx-ctx" id="kaip-ctx"></span>
    </div>
    <div class="kaip-nx-core">
      <div class="kaip-av" id="kaip-av" data-state="online">
        <span class="kaip-av-ring" aria-hidden="true"></span>
        <video class="kaip-av-media" id="kaip-av-idle"  src="/admin/nexus-assets/kai-idle.mp4"  poster="/admin/nexus-assets/kai.jpg" loop muted playsinline autoplay preload="auto" aria-hidden="true"></video>
        <video class="kaip-av-media" id="kaip-av-speak" src="/admin/nexus-assets/kai-speak.mp4" loop muted playsinline preload="auto" aria-hidden="true"></video>
        <img   class="kaip-av-media" id="kaip-av-poster" src="/admin/nexus-assets/kai.jpg" alt="" aria-hidden="true" decoding="async">
      </div>
    </div>
    <div class="kaip-nx-conv">
      <div class="kaip-suggest" id="kaip-suggest"></div>
      <div class="kaip-msgs" id="kaip-msgs"></div>
      <div class="kaip-input-wrap">
        <textarea class="kaip-input" id="kaip-input" rows="1" placeholder="Ask KAI anything…"></textarea>
        <div class="kaip-row">
          <span class="kaip-hint"><kbd>Enter</kbd> send</span>
          <span><button class="kaip-stop" id="kaip-stop" type="button" hidden>Stop</button><button class="kaip-send" id="kaip-send" type="button" aria-label="Send">↑</button></span>
        </div>
      </div>
    </div>`;
  document.body.appendChild(nx);
  // Wire the SAME module-level handles the streaming client uses → one code path.
  msgsEl = nx.querySelector('#kaip-msgs');
  inputEl = nx.querySelector('#kaip-input');
  sendBtn = nx.querySelector('#kaip-send');
  stopBtn = nx.querySelector('#kaip-stop');
  ctxEl = nx.querySelector('#kaip-ctx');
  stateEl = nx.querySelector('#kaip-state');

  // Living avatar: idle-loop video by default; swaps to the speaking loop when
  // KAI is speaking. Driven by the shared provider's kaiState — no separate state
  // machine. mix-blend-mode composites the dark-navy video into the dark stage
  // (see CSS); the poster is the fallback if a clip can't load.
  const av = nx.querySelector('#kaip-av');
  const vIdle = nx.querySelector('#kaip-av-idle'), vSpeak = nx.querySelector('#kaip-av-speak');
  [vIdle, vSpeak].forEach(v => {
    v.addEventListener('loadeddata', () => v.classList.add('ready'), { once: true });
    v.addEventListener('error', () => v.classList.remove('ready'));
    const p = v.play && v.play(); if (p) p.catch(() => {});
  });
  addEventListener('pointerdown', () => { [vIdle, vSpeak].forEach(v => { const p = v.play && v.play(); if (p) p.catch(() => {}); }); }, { once: true });

  sendBtn.addEventListener('click', submit);
  stopBtn.addEventListener('click', stopStream);
  inputEl.addEventListener('input', () => { inputEl.style.height = 'auto'; inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + 'px'; });
  inputEl.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } });
  on('kaiState', s => {
    if (stateEl) stateEl.textContent = s;
    av.dataset.state = s;
    if (s === 'speaking') { const p = vSpeak.play && vSpeak.play(); if (p) p.catch(() => {}); }
  });

  ctxEl.textContent = _ctxLabel(buildContext());
  av.dataset.state = state.kaiState;
  renderSuggestions();
  addMessage('kai', canGovernedChat()
    ? "I'm KAI. This is the immersive view — same session, same conversation. Ask me anything."
    : "KAI governed chat is not enabled for this session.");
  setTimeout(() => inputEl.focus(), 200);
}

function addMessage(role, text) {
  const el = document.createElement('div');
  el.className = 'kaip-msg ' + (role === 'user' ? 'user' : 'kai');
  const b = document.createElement('div'); b.className = 'kaip-msg-role'; b.textContent = role === 'user' ? 'You' : 'KAI';
  const body = document.createElement('div'); body.className = 'kaip-msg-body'; body.textContent = text;
  el.append(b, body);
  msgsEl.appendChild(el); msgsEl.scrollTop = msgsEl.scrollHeight;
  const rec = { role, text, body };
  state.messages.push(rec);
  return rec;
}
// §24 defense-in-depth: never render/speak a reasoning model's inline <think> scratchpad.
// Strips closed reasoning blocks + an unclosed trailing one (mid-stream). No-op on a normal
// answer. Prefer the Nexus pulse util when present; fall back to a local copy so the shared
// provider is self-contained. The proper fix is backend (strip at the adapter) — see docs.
const _REASON_RE_CLOSED = /<(think|thinking|reasoning|scratchpad|reflection)(?:\s[^>]*)?>[\s\S]*?<\/\1>/gi;
const _REASON_RE_OPEN = /<(think|thinking|reasoning|scratchpad|reflection)(?:\s[^>]*)?>[\s\S]*$/i;
// finalized=true (stream done): preserve a lone literal <think> as content; only strip the
// unclosed-trailing block mid-stream to avoid flashing a partial scratchpad.
function _stripReason(text, finalized) {
  if (text == null) return '';
  if (typeof window !== 'undefined' && window.NexusPulse && window.NexusPulse.stripReasoning) return window.NexusPulse.stripReasoning(text, { finalized: !!finalized });
  let out = String(text).replace(_REASON_RE_CLOSED, '');
  if (!finalized) out = out.replace(_REASON_RE_OPEN, '');
  return out;
}
function renderInto(rec, finalized) { rec.body.textContent = _stripReason(rec.text, finalized); msgsEl.scrollTop = msgsEl.scrollHeight; }

// ---- governed streaming client (§4/§5) -------------------------------------
async function submit() {
  const text = inputEl.value.trim();
  if (!text || state.connectionState === 'streaming') return;
  inputEl.value = ''; inputEl.style.height = 'auto';
  addMessage('user', text);
  if (!canGovernedChat()) {
    addMessage('kai', 'Governed KAI is not enabled here.');
    setKaiState('alert');
    return;
  }
  await streamGoverned(text);
}

async function streamGoverned(text) {
  stopSpeak();               // barge-in: a new question stops any current speech
  const asst = addMessage('kai', '');
  setKaiState('thinking');
  state.connectionState = 'streaming';
  stopBtn.hidden = false;
  const ctrl = new AbortController();
  state.streamState = ctrl;
  try {
    const res = await fetch('/admin/kai/kai-chat/stream', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        message: text, prefer_local: true,
        conversation_id: state.conversationId, context: buildContext(),
      }),
      signal: ctrl.signal,
    });
    if (res.status === 403) { asst.text = '(You need owner access for governed KAI.)'; renderInto(asst); setKaiState('alert'); return; }
    if (res.status === 429) { asst.text = '(Rate limited — try again shortly.)'; renderInto(asst); setKaiState('alert'); return; }
    if (!res.ok || !res.body) { asst.text = `(KAI unavailable: ${res.status})`; renderInto(asst); setKaiState('alert'); return; }

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
        if (ev.type === 'status') setKaiState(ev.state === 'thinking' ? 'thinking' : 'speaking');
        else if (ev.type === 'meta' && ev.conversation_id) { state.conversationId = ev.conversation_id; localStorage.setItem('kai.conv', ev.conversation_id); }
        else if (ev.type === 'token') { if (state.kaiState !== 'speaking') setKaiState('speaking'); asst.text += (ev.text || ''); renderInto(asst); }
        else if (ev.type === 'error') { asst.text += ' [model unavailable]'; renderInto(asst); setKaiState('alert'); }
        else if (ev.type === 'done') { /* finalized server-side */ }
      }
    }
    if (!asst.text) { asst.text = '(no response)'; renderInto(asst); }
    renderInto(asst, true);   // final render: preserve a literal lone <think> in the completed answer
    setKaiState('online');
    if (state.presenceMode === 'nexus') speak(_stripReason(asst.text, true));  // speak the answer, never the reasoning (§24)
  } catch (e) {
    if (e.name === 'AbortError') { asst.text += ' ⏹'; renderInto(asst); setKaiState('online'); }
    else { asst.text += ' [link error]'; renderInto(asst); setKaiState('alert'); }
  } finally {
    state.connectionState = 'idle';
    state.streamState = null;
    stopBtn.hidden = true;
  }
}

// Barge-in / cancel: abort the fetch → closes the connection → the bridge and
// App B tear down → ollama generation stops (server-side cancellation).
function stopStream() { stopSpeak(); if (state.streamState) state.streamState.abort(); }

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();
