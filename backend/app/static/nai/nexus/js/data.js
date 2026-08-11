// ============================================================================
// Data layer — the "living system" engine.
// Emits data:<domain> events on the bus with fresh values so panels stay live
// without knowing where data comes from.
//
// REAL vs SIM: tryReal() polls backend endpoints that actually exist on the
// v1.0.0-foundation (/readyz, /health). Everything a real feed doesn't cover yet
// (news, markets, geo, per-agent telemetry) is SIMULATED and marked with a
// `seam` tag so the wiring point is obvious. Swap sim → fetch() per domain.
// ============================================================================
import { bus, KAI } from './state.js';

const jitter = (v, d, lo = -Infinity, hi = Infinity) => Math.max(lo, Math.min(hi, v + (Math.random() - 0.5) * d));
const pick = a => a[Math.floor(Math.random() * a.length)];
const now = () => new Date();
const hhmmss = d => d.toTimeString().slice(0, 8);

const store = {
  system:   { health: 98, cpu: 22, memPct: 41, redis: 'ok', db: 'ok', uptime: '14d', reqs: 128 },
  security: { score: 82, critical: 0, high: 1, medium: 3, low: 7,
              checks: { authentication: 'ok', secrets: 'ok', dependencies: 'warn', infrastructure: 'ok', payments: 'ok', agents: 'ok' } },
  costs:    { today: 4.82, month: 96.4, cap: 250, tokensToday: 1_284_000 },
  memory:   { episodic: 1240, semantic: 3860, project: 74, user: 22 },
  agents: [
    { id: 'research', name: 'Research', status: 'active',  task: 'Scanning 12 sources',        runtime: 151, tools: 4, findings: 3, confidence: 91, ang: 0.0 },
    { id: 'security', name: 'Security', status: 'active',  task: 'Auditing authentication',    runtime: 151, tools: 7, findings: 2, confidence: 94, ang: 0.9 },
    { id: 'code',     name: 'Code',     status: 'idle',    task: 'Awaiting task',              runtime: 0,   tools: 9, findings: 0, confidence: 0,  ang: 1.8 },
    { id: 'memory',   name: 'Memory',   status: 'active',  task: 'Indexing knowledge',        runtime: 620, tools: 3, findings: 0, confidence: 88, ang: 2.7 },
    { id: 'browser',  name: 'Browser',  status: 'idle',    task: 'Standby',                    runtime: 0,   tools: 5, findings: 0, confidence: 0,  ang: 3.6 },
    { id: 'market',   name: 'Market',   status: 'watching',task: 'Tracking NVDA · BTC',        runtime: 4300,tools: 2, findings: 1, confidence: 76, ang: 4.5 },
  ],
  market:   { sp: 0.72, nasdaq: 1.12, btc: -0.34, eth: 0.21, sentiment: 'BULLISH', volatility: 'MODERATE', regime: 'NORMAL',
              watch: [{ s: 'NVDA', v: 2.1 }, { s: 'MSFT', v: 0.6 }, { s: 'BTC', v: -0.3 }, { s: 'ETH', v: 0.2 }] },
  infra: {
    nodes: [
      { id: 'Cloudflare', status: 'ok', x: .5, y: .08 }, { id: 'KAI API', status: 'ok', x: .5, y: .3 },
      { id: 'Supabase', status: 'ok', x: .22, y: .55 }, { id: 'Redis', status: 'ok', x: .5, y: .55 },
      { id: 'Railway', status: 'ok', x: .78, y: .55 }, { id: 'Stripe', status: 'ok', x: .22, y: .82 },
      { id: 'Workers', status: 'ok', x: .78, y: .82 }, { id: 'Dwolla', status: 'warn', x: .22, y: 1.0 },
    ],
    edges: [['Cloudflare', 'KAI API'], ['KAI API', 'Supabase'], ['KAI API', 'Redis'], ['KAI API', 'Railway'],
            ['Supabase', 'Stripe'], ['Railway', 'Workers'], ['Stripe', 'Dwolla']],
  },
  mission: { name: 'Launch SOLCIRCLE', progress: 84, current: 'Validating payment infrastructure',
             agents: [{ name: 'Research', status: 'COMPLETE' }, { name: 'Security', status: 'COMPLETE' },
                      { name: 'Backend', status: 'ACTIVE' }, { name: 'Deployment', status: 'WAITING' }],
             blocker: 'Stripe production verification' },
  // SEAM: replace with a real news API + a KAI impact-scoring service.
  // Every item is fixture data → verification:'DEMO' (§6 CRITICAL RULE: sample data
  // must never look like verified live news). source/published/corroborations are
  // the provenance fields the real feed will populate.
  news: [
    { title: 'NVIDIA announces new inference architecture', category: 'AI', relevance: 92, impact: 'HIGH', infra: 'Potential inference savings', action: 'Benchmark new architecture', source: 'Sample feed', published: '3m ago', verification: 'DEMO', corroborations: 0 },
    { title: 'EU finalizes AI transparency rules', category: 'World', relevance: 71, impact: 'MED', infra: 'Compliance review', action: 'Audit model disclosures', source: 'Sample feed', published: '18m ago', verification: 'DEMO', corroborations: 0 },
    { title: 'New OAuth token-theft campaign observed', category: 'Cybersecurity', relevance: 88, impact: 'HIGH', infra: 'Refresh-token revocation', action: 'Verify logout revocation', source: 'Sample feed', published: '32m ago', verification: 'DEMO', corroborations: 0 },
    { title: 'Bitcoin ETF inflows hit monthly high', category: 'Finance', relevance: 64, impact: 'LOW', infra: 'None', action: 'Monitor treasury exposure', source: 'Sample feed', published: '1h ago', verification: 'DEMO', corroborations: 0 },
  ],
  world: [ // seam: real geo feed (news/cyber/traffic). lat/lng normalized to the SVG globe.
    { lng: -74, lat: 40.7, type: 'infra', label: 'US-East · Railway healthy' },
    { lng: 8.5, lat: 47.4, type: 'news', label: 'EU · AI regulation update' },
    { lng: 139.7, lat: 35.7, type: 'market', label: 'Asia markets open +0.9%' },
    { lng: 37.6, lat: 55.7, type: 'cyber', label: 'Cyber anomaly cleared' },
  ],
  thinking: { mode: 'idle', steps: [] },
  activity: [],   // recent stream, newest-first (seeded in start(); panel reads for first paint)
};

export const data = {
  get: k => store[k],
  all: () => store,

  // ---- real-endpoint seam ------------------------------------------------
  async tryReal() {
    try {
      const r = await fetch('/readyz', { headers: { accept: 'application/json' } });
      if (r.ok) {
        const j = await r.json().catch(() => ({}));
        if (j.checks) {
          store.system.db = j.checks.db ?? store.system.db;
          store.system.redis = j.checks.redis ?? store.system.redis;
        }
        store.system.health = r.ok ? Math.max(store.system.health, 96) : 60;
        bus.emit('data:system', store.system);
      }
    } catch { /* offline / static preview → stay simulated */ }
  },

  // ---- simulated real-time loop -----------------------------------------
  start() {
    // fast tick — numbers drift so the dashboard breathes.
    // (§33: idle when the tab is hidden; the rAF render loops already pause there.)
    setInterval(() => {
      if (document.hidden) return;
      const s = store.system;
      s.cpu = Math.round(jitter(s.cpu, 6, 8, 96)); s.memPct = Math.round(jitter(s.memPct, 3, 20, 90));
      s.reqs = Math.round(jitter(s.reqs, 24, 40, 400));
      bus.emit('data:system', s);

      const m = store.market;
      for (const w of m.watch) w.v = +jitter(w.v, 0.25, -6, 6).toFixed(2);
      m.sp = +jitter(m.sp, .12).toFixed(2); m.nasdaq = +jitter(m.nasdaq, .14).toFixed(2);
      m.btc = +jitter(m.btc, .3).toFixed(2); m.eth = +jitter(m.eth, .3).toFixed(2);
      bus.emit('data:market', m);

      store.costs.today = +jitter(store.costs.today, 0.04, 0).toFixed(2);
      bus.emit('data:costs', store.costs);
    }, 2200);

    // agent runtimes advance
    setInterval(() => {
      for (const a of store.agents) if (a.status === 'active' || a.status === 'watching') a.runtime += 3;
      bus.emit('data:agents', store.agents);
      // random inter-agent comms → light a halo sector + constellation link
      if (Math.random() < 0.5) {
        const a = pick(store.agents), b = pick(store.agents);
        if (a !== b) bus.emit('agents:link', [a.id, b.id]);
      }
    }, 3000);

    // activity stream (Increment 10) — new entries slide in
    const ACT = [
      ['Research agent started', 'research'], ['GitHub repository scanned', 'tools'],
      ['Security anomaly cleared', 'security'], ['Memory updated', 'memory'],
      ['Stripe health check passed', 'infra'], ['Railway deployment healthy', 'infra'],
      ['Dependency advisory triaged', 'security'], ['Market snapshot recorded', 'market'],
      ['Knowledge graph reindexed', 'memory'], ['Inference batch completed', 'reasoning'],
    ];
    // seed a few recent entries so the feed is alive on first paint
    store.activity = ACT.slice(0, 5).map(([text, sector], i) =>
      ({ time: hhmmss(new Date(Date.now() - (i + 1) * 47000)), text, sector }));
    setInterval(() => {
      const [text, sector] = pick(ACT);
      const ev = { time: hhmmss(now()), text, sector };
      store.activity.unshift(ev); store.activity = store.activity.slice(0, 14);
      bus.emit('data:activity:new', ev);
      bus.emit('halo', sector);            // avatar halo reacts to autonomous activity
    }, 4200);

    // occasional security drift (drives KAI warning/critical states)
    setInterval(() => {
      const sec = store.security;
      if (Math.random() < 0.12) {
        sec.high = Math.max(0, sec.high + (Math.random() < .5 ? 1 : -1));
        sec.score = Math.max(40, Math.min(99, 82 - sec.high * 4 - sec.critical * 20));
        sec.checks.dependencies = sec.high > 1 ? 'warn' : 'ok';
        bus.emit('data:security', sec);
        if (sec.critical > 0) KAI.transient('critical', 2600);
        else if (sec.high > 2 && KAI.state === 'idle') KAI.transient('warning', 2200);
      }
    }, 9000);

    // first paint
    for (const k of ['system', 'security', 'costs', 'agents', 'market', 'memory', 'infra', 'mission', 'news', 'world'])
      bus.emit('data:' + k, store[k]);
    this.tryReal();
  },
};
