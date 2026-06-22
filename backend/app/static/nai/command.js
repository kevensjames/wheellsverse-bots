// KAI Command bridge — wires the procedural robot (avatar.js) into the
// operator dashboard: feeds it live system state so it visibly "feels" the
// system, and runs the full voice loop (speak replies + listen via mic).
//
// Reuses admin.js globals (it's a classic deferred script, so these are on
// window): adminChatPost(), apiGet(), getToken(), fmtUSD(). Falls back
// gracefully if any are absent. Purely additive — admin.js is untouched.

import { KaiAvatar } from './avatar.js?v=cyborg4';

const $ = (s) => document.querySelector(s);
const token = () => (window.getToken ? window.getToken() : '') || '';
const usd = (n) => (window.fmtUSD ? window.fmtUSD(n) : `$${Number(n || 0).toFixed(2)}`);

let kai = null;
let pollTimer = null;

// ── live state → HUD + avatar ──────────────────────────────────
async function apiGet(path) {
  if (window.apiGet) return window.apiGet(path); // admin.js: adds token + AuthError
  const r = await fetch(path, { headers: { 'X-Admin-Token': token() } });
  if (!r.ok) throw new Error(`${path} ${r.status}`);
  return r.json();
}

function setHud(key, value, tone) {
  const el = $(`#kai-hud-${key}`);
  if (el) el.textContent = value;
  const tile = el && el.closest('.kai-orbit');
  if (tile) { if (tone) tile.dataset.tone = tone; else tile.removeAttribute('data-tone'); }
}

const paneVisible = () => {
  const p = $('#admin-pane-command');
  return !!p && !p.hidden && p.offsetParent !== null;
};

async function poll() {
  if (!paneVisible() || !token()) return;
  const settled = await Promise.allSettled([
    apiGet('/admin/spend'),
    apiGet('/admin/planning/stats'),
    apiGet('/admin/security/summary'),
    apiGet('/admin/eq/stats'),
    apiGet('/admin/stats'),
  ]);
  const v = (i) => (settled[i].status === 'fulfilled' ? settled[i].value : null);
  const sp = v(0), pl = v(1), se = v(2), eq = v(3), st = v(4);

  // Spend + alerts (24h failures)
  setHud('spend', sp ? usd(sp.last_7d_total_usd) : '—');
  const alerts = sp ? (sp.failures_24h || 0) : 0;
  setHud('alerts', sp ? String(alerts) : '—', alerts >= 3 ? 'critical' : alerts >= 1 ? 'alert' : 'good');

  // Active plans
  const plansActive = pl ? (pl.active || 0) : 0;
  setHud('plans', pl ? `${plansActive}/${pl.total ?? plansActive}` : '—', plansActive >= 1 ? 'good' : '');

  // Security score
  let secScore = null;
  if (se) {
    if (se.status === 'no-data') setHud('security', 'no scan');
    else {
      secScore = se.score && se.score.overall != null ? se.score.overall : null;
      setHud('security', secScore != null ? `${secScore}/100` : '—',
        secScore == null ? '' : secScore < 40 ? 'critical' : secScore < 70 ? 'alert' : 'good');
    }
  }

  // Operator mood (info) + users
  setHud('mood', eq && eq.latest_mood ? eq.latest_mood : '—');
  setHud('users', st && st.users ? String(st.users.total ?? '—') : '—');

  // Feed the robot — its colour/energy reflect system health (it "feels" it).
  if (kai) kai.setState({ securityScore: secScore, alerts, plansActive });
}

// ── voice: speak replies ───────────────────────────────────────
const synth = window.speechSynthesis || null;
let preferredVoice = null;
function pickVoice() {
  if (!synth) return null;
  const voices = synth.getVoices() || [];
  if (!voices.length) return null;
  // Prefer a deep/neutral English voice for a "robot" feel.
  const byName = (re) => voices.find((v) => re.test(v.name));
  preferredVoice =
    byName(/Daniel|Google UK English Male|Microsoft (Guy|David)|Arthur|Oliver/i) ||
    voices.find((v) => /^en[-_]/i.test(v.lang)) || voices[0];
  return preferredVoice;
}
if (synth) { synth.onvoiceschanged = pickVoice; pickVoice(); }

function stripMd(t) {
  return String(t).replace(/```[\s\S]*?```/g, ' code block. ')
    .replace(/[*_`#>]/g, '').replace(/\[(.*?)\]\(.*?\)/g, '$1')
    .replace(/\s+/g, ' ').trim();
}

let _audioCtx = null;
function _ctx() {
  if (!_audioCtx) {
    try { _audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch (_) { _audioCtx = null; }
  }
  return _audioCtx;
}

// Fallback: browser SpeechSynthesis, tuned warmer/slower (storyteller pace).
// Used only when /admin/tts is unavailable (no token / no OpenAI key / error).
function speakBrowser(clean) {
  if (!synth) return;
  try { synth.cancel(); } catch (_) {}
  const u = new SpeechSynthesisUtterance(clean);
  u.rate = 0.95; u.pitch = 1.0;
  const voice = preferredVoice || pickVoice();
  if (voice) u.voice = voice;
  u.onstart = () => kai && kai.setSpeaking(true);
  u.onboundary = () => kai && kai.pulseMouth(0.7 + Math.random() * 0.3);
  u.onend = () => { if (kai) { kai.setSpeaking(false); kai.setVoiceLevel && kai.setVoiceLevel(0); } };
  u.onerror = () => kai && kai.setSpeaking(false);
  synth.speak(u);
}

// Primary: KAI's warm storyteller voice via /admin/tts (Piper local, else
// OpenAI TTS-1 'fable'), played through Web Audio so the live amplitude drives
// the avatar's mouth + equalizer (audio-reactive lip-sync).
async function speak(text) {
  const toggle = $('#kai-speak-toggle');
  if (toggle && !toggle.checked) return;
  const clean = stripMd(text).slice(0, 800);
  if (!clean) return;
  const tok = token();
  const ctx = _ctx();
  if (!tok || !ctx) return speakBrowser(clean);
  try {
    const r = await fetch('/admin/tts', {
      method: 'POST',
      headers: { 'X-Admin-Token': tok, 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: clean }),
    });
    if (!r.ok) throw new Error('tts ' + r.status);
    const audio = await ctx.decodeAudioData(await r.arrayBuffer());
    try { await ctx.resume(); } catch (_) {}
    const src = ctx.createBufferSource();
    src.buffer = audio;
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    src.connect(analyser);
    analyser.connect(ctx.destination);
    const buf = new Uint8Array(analyser.frequencyBinCount);
    if (kai) kai.setSpeaking(true);
    let raf = 0;
    const tick = () => {
      analyser.getByteTimeDomainData(buf);
      let sum = 0;
      for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
      const level = Math.min(1, Math.sqrt(sum / buf.length) * 3.4); // live mouth opening
      if (kai && kai.setVoiceLevel) kai.setVoiceLevel(level);
      raf = requestAnimationFrame(tick);
    };
    tick();
    src.onended = () => {
      cancelAnimationFrame(raf);
      if (kai) { kai.setVoiceLevel && kai.setVoiceLevel(0); kai.setSpeaking(false); }
    };
    src.start();
  } catch (e) {
    speakBrowser(clean); // any failure → browser voice, still speaks
  }
}

// ── voice: listen via mic ──────────────────────────────────────
const SR = window.SpeechRecognition || window.webkitSpeechRecognition || null;
let rec = null, listening = false;
function toggleMic() {
  const btn = $('#kai-mic');
  if (!SR) { setStatus('Voice input not supported in this browser — type instead.'); return; }
  if (listening) { try { rec.stop(); } catch (_) {} return; }
  rec = new SR();
  rec.lang = 'en-US'; rec.interimResults = true; rec.maxAlternatives = 1;
  rec.onstart = () => { listening = true; btn && btn.classList.add('is-listening'); setStatus('Listening…'); };
  rec.onerror = (e) => setStatus(`mic: ${e.error}`);
  rec.onend = () => { listening = false; btn && btn.classList.remove('is-listening'); };
  rec.onresult = (e) => {
    let t = '';
    for (const r of e.results) t += r[0].transcript;
    const input = $('#kai-voice-input');
    if (input) input.value = t;
    if (e.results[e.results.length - 1].isFinal) send();
  };
  try { rec.start(); } catch (_) {}
}

// ── send a turn ────────────────────────────────────────────────
function setCaption(t) { const c = $('#kai-caption'); if (c) c.textContent = t; }
function setStatus(t) { const s = $('#kai-voice-status'); if (s) s.textContent = t; }

// Quick chat for the ◉ KAI voice bar. Forces prefer_local (Ollama) + no tools
// so KAI replies even with NO cloud LLM key — using tools would force a cloud
// adapter, which fails without a key (that was the "nothing happens" bug).
async function kaiChat(text) {
  const r = await fetch('/admin/kai-chat', {
    method: 'POST',
    headers: { 'X-Admin-Token': token(), 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: text, use_tools: false, prefer_local: true, max_tokens: 800 }),
  });
  if (!r.ok) {
    const t = await r.text().catch(() => '');
    throw new Error(`chat ${r.status}${t ? ': ' + t.slice(0, 160) : ''}`);
  }
  return r.json();
}

async function send() {
  const input = $('#kai-voice-input');
  const text = (input && input.value.trim()) || '';
  if (!text) return;
  if (!token()) { setCaption('Unlock with your admin token first (top of the page).'); return; }
  if (input) input.value = '';
  setCaption(`You: ${text}`);
  setStatus('KAI is thinking…');
  if (kai) kai.setThinking(true);
  try {
    const resp = await kaiChat(text);
    const reply = (resp && resp.message && resp.message.content) || '(no reply)';
    if (kai) kai.setThinking(false);
    setCaption(reply.length > 260 ? `${reply.slice(0, 260)}…` : reply);
    speak(reply);
    setStatus('');
  } catch (e) {
    if (kai) kai.setThinking(false);
    setCaption(`Error: ${e.message || e}`);
    setStatus('');
  }
}

// ── visibility (start/stop render + polling with the tab) ──────
function onVisibility() {
  if (paneVisible()) {
    if (kai) kai.start();
    poll();
    if (!pollTimer) pollTimer = setInterval(poll, 15000);
  } else {
    if (kai) kai.stop();
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }
}

function showFallback(err) {
  const stage = $('#kai-stage');
  if (!stage) return;
  const div = document.createElement('div');
  div.style.cssText = 'position:absolute;inset:0;display:flex;align-items:center;justify-content:center;text-align:center;color:#8295bf;padding:24px;font-size:14px;';
  div.textContent = '3D avatar unavailable in this browser (WebGL/Three.js failed to load). The voice loop and dashboard still work.';
  stage.appendChild(div);
  console.error('[KAI avatar]', err);
}

function init() {
  const canvas = $('#kai-avatar-canvas');
  if (canvas && !kai) {
    try { kai = new KaiAvatar(canvas); }
    catch (e) { showFallback(e); }
  }

  const form = $('#kai-voiceform');
  if (form) form.addEventListener('submit', (e) => { e.preventDefault(); send(); });
  const mic = $('#kai-mic');
  if (mic) mic.addEventListener('click', toggleMic);

  // React to tab switches (activateTab toggles pane.hidden) and to auth unlock
  // (refresh() unhides #admin-body).
  const pane = $('#admin-pane-command');
  if (pane) new MutationObserver(onVisibility).observe(pane, { attributes: true, attributeFilter: ['hidden'] });
  const body = $('#admin-body');
  if (body) new MutationObserver(onVisibility).observe(body, { attributes: true, attributeFilter: ['hidden'] });

  setCaption('KAI online. Click the mic and talk, or type below.');
  onVisibility();
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
else init();
