// ============================================================================
// KAI ADAPTIVE MISSION NEXUS — controller (Phase 1 + event bus §38 + mission §7-10)
//
// ONE provider (§1/§38): when served inside the admin shell, kai-presence.js is
// injected first and exposes window.KAI (identity, session, governed streaming,
// kaiState). This controller EXTENDS that provider — it does NOT create a second
// identity/brain/session. Standalone (file:// for QA) it runs a minimal local
// shim so the shell is renderable + screenshot-verifiable.
//
// Data honesty (§39): every datum carries a provenance tag — REAL | DERIVED |
// DEMO | UNAVAILABLE. The DEV/DEMO scenario driver activates ONLY on explicit
// ?scenario=… and shows a persistent DEMO banner. Production never shows DEMO
// as live.
// ============================================================================
(() => {
  'use strict';
  const HOST = (typeof window !== 'undefined' && window.KAI) ? window.KAI : null;
  const IN_APP = !!HOST && location.protocol.startsWith('http');
  const params = new URLSearchParams(location.search);
  const SCENARIO = params.get('scenario');           // idle|latency|research|security|approval
  const DEMO = !!SCENARIO;                            // DEMO only on explicit opt-in (§39)

  // ── canonical event bus (extends kai-presence pub/sub) ────────────────────
  const subs = new Map();
  function on(topic, fn) { (subs.get(topic) ?? subs.set(topic, new Set()).get(topic)).add(fn); return () => subs.get(topic)?.delete(fn); }
  function emit(topic, payload = {}) {
    const ev = { topic, payload, ts: Date.now() };
    subs.get(topic)?.forEach(fn => { try { fn(ev); } catch (e) { console.error(e); } });
    subs.get('*')?.forEach(fn => { try { fn(ev); } catch (e) { console.error(e); } });
  }
  if (HOST && HOST.on) HOST.on('kaiState', s => { store.kaiState = s; emit('kai.' + s); paintKai(); });

  // ── store ─────────────────────────────────────────────────────────────────
  const store = {
    kaiState: (HOST && HOST.state && HOST.state.kaiState) || 'online',
    kaiSub: 'What can I do for you?',
    mode: 'command', env: 'idle',
    missions: [], activeId: null,
    systems: [], signals: [], activity: [], alerts: [],
  };
  const el = (id) => document.getElementById(id);
  const prov = (kind) => { const s = document.createElement('span'); s.className = 'nx-prov ' + kind; s.textContent = kind; return s; };
  const fmtClock = (d) => d.toISOString().slice(11, 19);
  const nowClock = () => fmtClock(new Date());

  // ── mission model (§7) ──────────────────────────────────────────────────────
  function mission(m) {
    return Object.assign({
      id: 'M' + String(Math.floor(1000 + (store.missions.length + 1) * 37)).padStart(5, '0'),
      title: 'Mission', type: 'general', status: 'ACTIVE', priority: 'MEDIUM',
      created_at: Date.now(), current_step: '', progress: 0,
      agents: [], tools: [], timeline: [], provenance: DEMO ? 'DEMO' : 'REAL',
    }, m);
  }
  const activeMission = () => store.missions.find(m => m.id === store.activeId) || null;

  // ── adaptive state (§25) ─────────────────────────────────────────────────────
  function setMode(mode) { store.mode = mode; document.querySelector('.nx-shell')?.setAttribute('data-mode', mode); renderNav(); }
  function setEnv(env) { store.env = env; document.querySelector('.nx-shell')?.setAttribute('data-env', env); }
  function setKai(state, sub) {
    store.kaiState = state; if (sub != null) store.kaiSub = sub;
    if (HOST && HOST.state) HOST.state.kaiState = state;   // keep the one provider in sync
    paintKai();
  }
  function paintKai() {
    const halo = el('nx-halo'); if (halo) halo.dataset.state = store.kaiState;
    const st = el('nx-kai-state'); if (st) st.textContent = store.kaiState.toUpperCase();
    const sub = el('nx-kai-sub'); if (sub) sub.textContent = store.kaiSub;
    const cmd = el('nx-cmd-state'); if (cmd) cmd.textContent = ({ online: 'READY', idle: 'READY', thinking: 'THINKING', researching: 'RESEARCHING', speaking: 'SPEAKING', listening: 'LISTENING', alert: 'ATTENTION', offline: 'OFFLINE' })[store.kaiState] || 'READY';
    const hv = el('nx-h-kai'); if (hv) hv.textContent = store.kaiState.toUpperCase();
  }

  // ── renderers ─────────────────────────────────────────────────────────────
  function setHeader(fields) { for (const [k, v] of Object.entries(fields)) { const n = el('nx-h-' + k); if (n) { n.textContent = v.text; n.className = 'nx-hstat-v ' + (v.cls || ''); } } }

  function renderSystemStack() {
    const box = el('nx-syslist'); if (!box) return; box.replaceChildren();
    for (const s of store.systems) {
      const row = document.createElement('div'); row.className = 'nx-stat';
      const k = document.createElement('span'); k.className = 'nx-stat-k';
      const dot = document.createElement('span'); dot.className = 'nx-dot ' + s.status;
      const label = document.createElement('span'); label.textContent = s.label;
      k.append(dot, label);
      const v = document.createElement('span'); v.className = 'nx-stat-v'; v.textContent = s.value != null ? s.value : s.status.toUpperCase();
      v.append(prov(s.prov));
      row.append(k, v); box.append(row);
    }
  }

  function renderMissionHead() {
    const m = activeMission(); const head = el('nx-mission-head');
    if (!head) return;
    if (!m) { head.hidden = true; return; }
    head.hidden = false;
    el('nx-mh-id').textContent = 'MISSION ' + m.id;
    el('nx-mh-name').textContent = m.title;
    el('nx-mh-step').textContent = m.current_step || '—';
    el('nx-mh-status').textContent = m.status;
    el('nx-mh-status').className = 'nx-mh-v ' + (m.status === 'ACTIVE' ? 'ok' : m.status === 'BLOCKED' || m.status === 'APPROVAL_REQUIRED' ? 'warn' : '');
    el('nx-mh-prio').textContent = m.priority;
    el('nx-mh-elapsed').textContent = fmtElapsed(m.started_at || m.created_at);
    el('nx-mh-agents').textContent = m.agents.length ? m.agents.join(' · ') : '—';
  }
  function fmtElapsed(from) { const s = Math.max(0, Math.floor((Date.now() - from) / 1000)); return String(Math.floor(s / 60)).padStart(2, '0') + ':' + String(s % 60).padStart(2, '0'); }

  function renderQueue() {
    const box = el('nx-queue'); if (!box) return; box.replaceChildren();
    const glyph = { ACTIVE: '●', WAITING: '◐', QUEUED: '○', BLOCKED: '■', APPROVAL_REQUIRED: '■', SUCCESS: '✓', FAILED: '✕' };
    const cls = { ACTIVE: 'active', WAITING: 'waiting', QUEUED: '', BLOCKED: 'blocked', APPROVAL_REQUIRED: 'blocked' };
    for (const m of store.missions) {
      const it = document.createElement('div'); it.className = 'nx-q-item ' + (cls[m.status] || '');
      const g = document.createElement('span'); g.className = 'nx-q-glyph'; g.textContent = glyph[m.status] || '○';
      const mid = document.createElement('div');
      const t = document.createElement('div'); t.className = 'nx-q-title'; t.textContent = m.title;
      const sub = document.createElement('div'); sub.className = 'nx-q-sub'; sub.textContent = m.status.replace('_', ' ') + (m.blocked_reason ? ' · ' + m.blocked_reason : '');
      mid.append(t, sub);
      const meta = document.createElement('span'); meta.className = 'nx-q-meta'; meta.textContent = m.status === 'ACTIVE' ? fmtElapsed(m.started_at || m.created_at) : '';
      it.append(g, mid, meta);
      it.addEventListener('click', () => { store.activeId = m.id; renderMissionHead(); renderTimeline(); });
      box.append(it);
    }
  }

  function renderTimeline() {
    const box = el('nx-timeline'); const m = activeMission(); if (!box) return; box.replaceChildren();
    if (!m || !m.timeline.length) { const e = document.createElement('div'); e.className = 'nx-tl-body'; e.style.color = 'var(--nx-text-faint)'; e.style.padding = '10px 0'; e.textContent = 'No active mission. KAI is idle.'; box.append(e); return; }
    for (const ev of m.timeline) {
      const row = document.createElement('div'); row.className = 'nx-tl-row'; row.dataset.sev = ev.sev || 'info';
      const time = document.createElement('div'); time.className = 'nx-tl-time'; time.textContent = ev.time;
      const rail = document.createElement('div'); rail.className = 'nx-tl-rail'; const node = document.createElement('div'); node.className = 'nx-tl-node'; rail.append(node);
      const body = document.createElement('div');
      const actor = document.createElement('div'); actor.className = 'nx-tl-actor'; actor.textContent = ev.actor || 'system';
      const text = document.createElement('div'); text.className = 'nx-tl-body'; text.textContent = ev.text;
      body.append(actor, text);
      row.append(time, rail, body); box.append(row);
    }
    box.scrollTop = box.scrollHeight;
  }

  function renderIntel() {
    const box = el('nx-intel'); if (!box) return; box.replaceChildren();
    if (!store.signals.length) { const e = document.createElement('div'); e.className = 'nx-sig-meta'; e.style.padding = '12px'; e.textContent = IN_APP ? 'No live intelligence source configured.' : 'Intelligence feed inactive.'; box.append(e); return; }
    for (const s of store.signals) {
      const it = document.createElement('div'); it.className = 'nx-signal';
      const cat = document.createElement('div'); cat.className = 'nx-sig-cat'; cat.textContent = s.cat;
      const h = document.createElement('div'); h.className = 'nx-sig-head'; h.textContent = s.head;
      const meta = document.createElement('div'); meta.className = 'nx-sig-meta';
      const src = document.createElement('span'); src.textContent = s.source;
      const when = document.createElement('span'); when.textContent = s.published;
      meta.append(src, when, prov(s.prov));
      it.append(cat, h, meta); box.append(it);
    }
  }

  function renderActivity() {
    const box = el('nx-activity'); if (!box) return; box.replaceChildren();
    for (const a of store.activity.slice(-40)) {
      const row = document.createElement('div'); row.className = 'nx-stat';
      const k = document.createElement('span'); k.className = 'nx-stat-k'; k.style.gap = '8px';
      const t = document.createElement('span'); t.style.color = 'var(--nx-text-faint)'; t.style.fontVariantNumeric = 'tabular-nums'; t.textContent = a.ts;
      const txt = document.createElement('span'); txt.textContent = a.text;
      k.append(t, txt); row.append(k); box.append(row);
    }
    box.scrollTop = box.scrollHeight;
  }
  function logActivity(text) { store.activity.push({ ts: nowClock(), text }); renderActivity(); }

  function renderAlerts() {
    const box = el('nx-alerts-strip'); if (!box) return; box.replaceChildren();
    for (const a of store.alerts) {
      const d = document.createElement('div'); d.className = 'nx-alert ' + a.sev;
      const t = document.createElement('strong'); t.textContent = a.title;
      const sp = document.createElement('span'); sp.textContent = a.detail || '';
      d.append(t, sp); box.append(d);
    }
    const hv = el('nx-h-alerts'); if (hv) { const crit = store.alerts.filter(a => a.sev === 'critical').length; hv.textContent = crit ? crit + ' CRITICAL' : store.alerts.length ? store.alerts.length + ' ACTIVE' : 'CLEAR'; hv.className = 'nx-hstat-v ' + (crit ? 'crit' : store.alerts.length ? 'warn' : 'ok'); }
  }

  function renderNav() {
    document.querySelectorAll('.nx-nav-item').forEach(b => b.classList.toggle('active', b.dataset.mode === store.mode));
  }

  // ── command bar ─────────────────────────────────────────────────────────────
  function wireCommand() {
    const input = el('nx-cmd-input'); const send = el('nx-cmd-send'); const stop = el('nx-cmd-stop');
    const submit = () => {
      const text = (input.value || '').trim(); if (!text) return; input.value = '';
      logActivity('You: ' + text);
      if (IN_APP && HOST && typeof HOST.ask === 'function' && !DEMO) {
        // REAL governed path — reuse the one provider's governed streaming.
        setKai('thinking', 'Working on it…'); HOST.ask(text);
      } else {
        demoRespond(text);   // DEMO / standalone QA only
      }
    };
    send?.addEventListener('click', submit);
    input?.addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } });
    stop?.addEventListener('click', () => { if (HOST && HOST.state && HOST.state.streamState) HOST.state.streamState.abort(); setKai('online', 'Stopped.'); });
  }

  // ── DEV/DEMO scenario driver (§47) — labeled, opt-in only ────────────────────
  function demoRespond(text) {
    setKai('thinking', 'Analyzing your request…');
    setTimeout(() => { setKai('speaking', 'Here is what I found.'); logActivity('KAI: (DEMO) response to “' + text.slice(0, 40) + '”'); }, 900);
    setTimeout(() => setKai('online', 'What else can I do?'), 2600);
  }

  const SCENARIOS = {
    idle() {
      setMode('command'); setEnv('idle'); setKai('online', 'What can I do for you?');
      store.systems = demoSystems(); store.missions = []; store.activeId = null;
      store.signals = []; store.alerts = [];
      renderAll();
    },
    latency() {
      setMode('mission'); setEnv('warning'); setKai('thinking', 'Investigating API latency.');
      store.systems = demoSystems({ 'core-api': 'caution', postgres: 'warning' });
      const m = mission({ id: 'M00291', title: 'API Latency Investigation', type: 'infrastructure', status: 'ACTIVE', priority: 'HIGH', started_at: Date.now() - 102000, current_step: 'Comparing DB latency against previous deployment.', agents: ['Infrastructure', 'Research'], tools: ['Railway', 'Logs', 'Postgres'] });
      m.timeline = tl([['06:41:02', 'user', 'Request accepted'], ['06:41:03', 'kai', 'Mission created'], ['06:41:05', 'kai', 'Infrastructure agent activated'], ['06:41:09', 'agent:infra', 'Railway metrics loaded'], ['06:41:14', 'agent:infra', 'Postgres latency anomaly detected', 'warning'], ['06:41:19', 'kai', 'Verification started'], ['06:41:28', 'agent:research', 'Connection-pool saturation confirmed', 'warning']]);
      store.missions = [m, mission({ id: 'M00290', title: 'SOL settlement certification', status: 'WAITING', blocked_reason: 'provider sandbox' }), mission({ id: 'M00288', title: 'Security dependency review', status: 'QUEUED' })];
      store.activeId = 'M00291';
      store.alerts = [{ sev: 'warning', title: 'Postgres latency', detail: 'p95 up 3.2× vs last deploy' }];
      store.signals = demoSignals(); renderAll();
    },
    research() {
      setMode('intelligence'); setEnv('idle'); setKai('researching', 'Gathering intelligence.');
      store.systems = demoSystems();
      const m = mission({ id: 'M00293', title: 'Competitive AI Landscape Scan', type: 'research', status: 'ACTIVE', priority: 'MEDIUM', started_at: Date.now() - 41000, current_step: 'Correlating signals across sources.', agents: ['Research'], tools: ['Web', 'Memory'] });
      m.timeline = tl([['09:12:00', 'user', 'Request accepted'], ['09:12:01', 'kai', 'Mission created'], ['09:12:03', 'agent:research', 'Research agent activated'], ['09:12:11', 'agent:research', '17 signals retrieved'], ['09:12:20', 'kai', 'Relevance ranking']]);
      store.missions = [m]; store.activeId = 'M00293';
      store.signals = demoSignals(); store.alerts = []; renderAll();
    },
    security() {
      setMode('security'); setEnv('critical'); setKai('alert', 'Security event under review.');
      store.systems = demoSystems({ stripe: 'warning' });
      const m = mission({ id: 'M00295', title: 'Payment Reconciliation Mismatch', type: 'security', status: 'APPROVAL_REQUIRED', priority: 'CRITICAL', started_at: Date.now() - 63000, current_step: 'Awaiting operator decision on payout hold.', agents: ['Security', 'Finance'], tools: ['Ledger', 'Stripe'] });
      m.timeline = tl([['11:03:00', 'user', 'Request accepted'], ['11:03:01', 'kai', 'Mission created'], ['11:03:04', 'agent:security', 'Ledger scan started'], ['11:03:12', 'agent:finance', 'Variance $500 detected', 'critical'], ['11:03:20', 'kai', 'Remediation prepared — payout hold', 'warning'], ['11:03:21', 'kai', 'Waiting for operator approval', 'warning']]);
      store.missions = [m]; store.activeId = 'M00295';
      store.alerts = [{ sev: 'critical', title: 'Reconciliation mismatch', detail: 'Expected $8,450 · Observed $7,950 · Δ $500' }];
      store.signals = demoSignals(); renderAll();
    },
    approval() {
      setMode('mission'); setEnv('warning'); setKai('online', 'A mission is waiting for your approval.');
      store.systems = demoSystems();
      const m = mission({ id: 'M00297', title: 'Production Deployment', type: 'deployment', status: 'APPROVAL_REQUIRED', priority: 'HIGH', started_at: Date.now() - 30000, current_step: 'Step 7/10 — Operator approval required.', agents: ['DevOps'], tools: ['Railway', 'GitHub'] });
      m.timeline = tl([['14:20:00', 'user', 'Request accepted'], ['14:20:02', 'kai', 'Readiness checks passed'], ['14:20:05', 'kai', 'Rollback verified'], ['14:20:06', 'kai', 'Waiting for operator approval', 'warning']]);
      store.missions = [m]; store.activeId = 'M00297';
      store.alerts = [{ sev: 'caution', title: 'Approval required', detail: 'Deploy production release abc123' }];
      store.signals = demoSignals(); renderAll();
    },
  };
  const tl = (rows) => rows.map(([time, actor, text, sev]) => ({ time, actor, text, sev: sev || 'info' }));
  function demoSystems(overrides = {}) {
    const base = [['core-api', 'Core API'], ['kai-brain', 'KAI Brain'], ['postgres', 'Postgres'], ['redis', 'Redis'], ['railway', 'Railway'], ['ollama', 'Ollama'], ['openai', 'OpenAI'], ['stripe', 'Stripe']];
    return base.map(([key, label]) => ({ key, label, status: overrides[key] || 'nominal', value: (overrides[key] || 'nominal').toUpperCase(), prov: 'demo' }));
  }
  function demoSignals() {
    return [
      { cat: 'AI', head: 'New frontier model released with 1M-token context', source: 'DEMO wire', published: '2m', prov: 'demo' },
      { cat: 'CYBER', head: 'Critical CVE in widely-used auth library', source: 'DEMO wire', published: '18m', prov: 'demo' },
      { cat: 'MARKETS', head: 'Semiconductor index up 2.4% on demand outlook', source: 'DEMO wire', published: '31m', prov: 'demo' },
    ];
  }

  function renderAll() { renderSystemStack(); renderMissionHead(); renderQueue(); renderTimeline(); renderIntel(); renderActivity(); renderAlerts(); renderNav(); paintKai(); }

  // ── init ─────────────────────────────────────────────────────────────────
  function init() {
    document.querySelector('.nx-shell')?.setAttribute('data-mode', store.mode);
    // header baseline
    setHeader({
      mission: { text: '—' }, system: { text: 'NOMINAL', cls: 'ok' }, model: { text: IN_APP ? '—' : 'DEMO' },
      env: { text: DEMO ? 'DEMO' : (IN_APP ? 'production' : 'standalone') }, security: { text: 'CLEAR', cls: 'ok' }, alerts: { text: 'CLEAR', cls: 'ok' },
    });
    el('nx-h-kai') && (el('nx-h-kai').textContent = store.kaiState.toUpperCase());
    // clock
    const clock = el('nx-h-clock'); if (clock) setInterval(() => { clock.textContent = nowClock(); if (activeMission()) { renderMissionHead(); const q = el('nx-queue'); if (q) renderQueue(); } }, 1000);
    // nav
    document.querySelectorAll('.nx-nav-item').forEach(b => b.addEventListener('click', () => setMode(b.dataset.mode)));
    wireCommand();
    // provenance banner
    const banner = el('nx-demo-banner'); if (banner) banner.hidden = !DEMO;

    if (DEMO && SCENARIOS[SCENARIO]) { SCENARIOS[SCENARIO](); logActivity('DEMO scenario “' + SCENARIO + '” loaded'); }
    else if (DEMO) { SCENARIOS.idle(); }
    else if (IN_APP) { bootLive(); }
    else { SCENARIOS.idle(); store.systems = store.systems.map(s => ({ ...s, prov: 'unavailable', value: 'UNKNOWN', status: 'unknown' })); renderAll(); }
  }

  // ── live boot (§39 REAL/DERIVED) — only when served in-app ──────────────────
  async function bootLive() {
    store.missions = []; store.activeId = null; store.signals = []; store.alerts = [];
    setMode('command'); setEnv('idle');
    // real config
    try { const r = await fetch('/admin/ui-config', { credentials: 'include' }); if (r.ok) { const c = await r.json(); setHeader({ model: { text: c.model || 'governed' } }); } } catch {}
    // real system status — probe a curated set of /api/*/status (REAL), fail-soft
    const probes = [['core-api', '/api/v2/narai/health'], ['market', '/api/market/status'], ['factory', '/api/factory/status']];
    const systems = [];
    for (const [label, url] of probes) {
      try { const r = await fetch(url, { credentials: 'include' }); systems.push({ key: label, label, status: r.ok ? 'nominal' : 'degraded', value: r.ok ? 'NOMINAL' : ('HTTP ' + r.status), prov: 'real' }); }
      catch { systems.push({ key: label, label, status: 'unknown', value: 'UNREACHABLE', prov: 'unavailable' }); }
    }
    store.systems = systems.length ? systems : [{ key: 'x', label: 'Telemetry', status: 'unknown', value: 'UNAVAILABLE', prov: 'unavailable' }];
    renderAll();
    logActivity('Live boot — governed provider ' + (HOST ? 'attached' : 'absent'));
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
  // expose for debugging + future phases (single namespace)
  window.KAINexus = { on, emit, store, setMode, setKai, setEnv };
})();
