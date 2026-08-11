// ============================================================================
// KAI portrait presence (§21 image-presence hero)
// The hero face is a semi-photoreal generated portrait (assets/kai.jpg). This
// module keeps KAI ALIVE around it: a neural halo BEHIND the head, a particle
// energy-dissolve + subtle eye-glow + state colour washes IN FRONT, and
// breathing / gaze via CSS transforms on the image. All driven by the same
// state/gaze/halo/env bus, so swapping the portrait for a rigged GLB later is a
// one-component change behind the avatar controller.
// ============================================================================
import { bus, KAI } from '../state.js';

const TAU = Math.PI * 2;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const mix = (c1, c2, t) => [lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t)];
const rgba = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;
function parseColor(s) { s = (s || '').trim();
  if (s[0] === '#') { const h = s.slice(1); const n = parseInt(h.length === 3 ? h.replace(/./g, c => c + c) : h, 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
  const m = s.match(/[\d.]+/g); return m ? [+m[0], +m[1], +m[2]] : [77, 163, 255]; }
const ENERGY = [120, 214, 255];
const SECTORS = ['REASONING', 'MEMORY', 'RESEARCH', 'TOOLS', 'AGENTS', 'SECURITY', 'MARKETS', 'INFRA'];
const SECTOR_KEY = { reasoning: 0, memory: 1, research: 2, tools: 3, agents: 4, security: 5, market: 6, markets: 6, infra: 7 };

// approx feature positions in the portrait (fractions of the display box)
const EYE_L = [.43, .315], EYE_R = [.565, .315], CORE = [.5, .76];

export function mountPortrait({ stage, halo, fx, img }) {
  const hctx = halo.getContext('2d'), fctx = fx.getContext('2d');
  let W = 0, H = 0, DPR = 1;
  const lowMotion = () => document.documentElement.dataset.motion === 'off' || matchMedia('(prefers-reduced-motion: reduce)').matches;
  const lowQ = () => document.documentElement.dataset.q === 'low';

  function resize() {
    DPR = Math.min(devicePixelRatio || 1, lowQ() ? 1 : 2);
    const w = stage.clientWidth || 460, h = stage.clientHeight || 610;
    for (const c of [halo, fx]) { c.width = w * DPR; c.height = h * DPR; }
    W = w; H = h;
  }
  new ResizeObserver(resize).observe(stage); resize();

  const m = {
    accent: [77, 163, 255], illum: .3, illumT: .3, breath: 0,
    haloSpin: 0, haloLit: new Array(8).fill(0),
    gaze: { x: 0, y: 0 }, gazeT: { x: 0, y: 0 },
    env: { c: [77, 163, 255], side: 1, on: 0 }, eye: 0, eyeT: 0, core: .5,
  };
  let gazeMode = 'camera', gazePoint = null;
  const GAZE = { camera: [0, .02], input: [0, .5], up: [0, -.4] };
  const pickAccent = () => { m.accent = parseColor(getComputedStyle(document.documentElement).getPropertyValue('--accent')); };
  pickAccent();

  bus.on('state', ({ state }) => {
    pickAccent();
    m.illumT = { idle: .28, sleep: .12, listening: .5, understanding: .6, thinking: .85, researching: .72, speaking: .6, executing: .95, warning: .6, critical: 1, success: 1 }[state] ?? .3;
    m.eyeT = { thinking: .8, researching: .7, executing: 1, listening: .5, critical: 1, success: .8 }[state] ?? .12;
    gazeMode = { thinking: 'up', researching: 'up', listening: 'camera', speaking: 'camera', idle: 'camera' }[state] ?? 'camera';
    if (state === 'success' || state === 'listening') flash(state === 'success' ? ENERGY : m.accent);
  });
  bus.on('gaze', t => { if (GAZE[t]) { gazeMode = t; gazePoint = null; } });
  bus.on('gaze:point', p => { if (p && typeof p.x === 'number') { gazeMode = 'point'; gazePoint = p; } });
  bus.on('halo', sec => { const i = SECTOR_KEY[sec]; if (i != null) { m.haloLit[i] = 1; flows.push({ s: i, t: 0, sp: .6 + Math.random() * .3 }); } });
  bus.on('env:light', ({ color, side }) => { m.env.c = parseColor(color || '#4da3ff'); m.env.side = side ?? 1; m.env.on = 1; });

  let flows = [], chest = [], sweep = 0, sweepC = ENERGY;
  function seedChest() { const n = lowQ() ? 30 : 70; chest = Array.from({ length: n }, () => ({ a: Math.random(), t: Math.random(), sp: .1 + Math.random() * .22, r: .5 + Math.random() * 1.6 })); }
  seedChest();
  function flash(c) { sweep = 1; sweepC = c; }

  // resolve gaze to a small head-space vector
  function gaze(dt, still) {
    let tx, ty;
    if (gazeMode === 'point' && gazePoint) { const r = stage.getBoundingClientRect();
      tx = clamp((gazePoint.x - (r.left + r.width / 2)) / (innerWidth * .5), -1, 1);
      ty = clamp((gazePoint.y - (r.top + r.height * .4)) / (innerHeight * .5), -1, 1);
    } else { const g = GAZE[gazeMode] || GAZE.camera; tx = g[0]; ty = g[1]; }
    m.gaze.x = lerp(m.gaze.x, tx, still ? 1 : dt * 3); m.gaze.y = lerp(m.gaze.y, ty, still ? 1 : dt * 3);
  }

  // ---- halo (behind head) --------------------------------------------------
  function drawHalo() {
    const cx = W / 2, cy = H * .34, R = Math.min(W, H) * .42;
    hctx.setTransform(DPR, 0, 0, DPR, 0, 0); hctx.clearRect(0, 0, W, H);
    hctx.translate(cx, cy);
    hctx.beginPath(); hctx.arc(0, 0, R, 0, TAU); hctx.strokeStyle = rgba(m.accent, .1); hctx.lineWidth = 1; hctx.stroke();
    hctx.font = `${Math.max(8, R * .05)}px var(--mono,monospace)`; hctx.textAlign = 'center'; hctx.textBaseline = 'middle';
    for (let i = 0; i < 8; i++) {
      const a0 = (i / 8) * TAU - Math.PI / 2 + m.haloSpin, a1 = a0 + TAU / 8 * .82, lit = m.haloLit[i];
      hctx.beginPath(); hctx.arc(0, 0, R, a0, a1); hctx.strokeStyle = rgba(m.accent, .1 + lit * .8); hctx.lineWidth = 1.5 + lit * 4; hctx.stroke();
      const mid = (a0 + a1) / 2;
      hctx.fillStyle = rgba(mix(m.accent, ENERGY, lit), .13 + lit * .7);
      hctx.fillText(SECTORS[i], Math.cos(mid) * (R + R * .12), Math.sin(mid) * (R + R * .12));
    }
    for (const f of flows) { const a = (f.s / 8) * TAU - Math.PI / 2 + m.haloSpin + TAU / 16 * .8, rr = R * f.t;
      hctx.beginPath(); hctx.arc(Math.cos(a) * rr, Math.sin(a) * rr, 2 * (1 - f.t * .5), 0, TAU); hctx.fillStyle = rgba(ENERGY, (1 - f.t) * .7); hctx.fill(); }
    // soft blue separation glow behind the head
    const g = hctx.createRadialGradient(0, 0, R * .2, 0, 0, R * 1.2);
    g.addColorStop(0, rgba(m.accent, .12 * (.5 + m.illum))); g.addColorStop(1, rgba(m.accent, 0));
    hctx.fillStyle = g; hctx.beginPath(); hctx.arc(0, 0, R * 1.2, 0, TAU); hctx.fill();
  }

  // ---- fx (in front of portrait) -------------------------------------------
  function drawFx(still) {
    fctx.setTransform(DPR, 0, 0, DPR, 0, 0); fctx.clearRect(0, 0, W, H);
    // subtle eye energy (enhances the rendered eyes on active states)
    if (m.eye > .02) for (const [ex, ey] of [EYE_L, EYE_R]) {
      const x = ex * W, y = ey * H, r = W * .05 * (0.8 + m.eye * .5);
      const g = fctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, rgba(ENERGY, .5 * m.eye)); g.addColorStop(1, rgba(ENERGY, 0));
      fctx.fillStyle = g; fctx.beginPath(); fctx.arc(x, y, r, 0, TAU); fctx.fill();
    }
    // chest core pulse
    const cpx = CORE[0] * W, cpy = CORE[1] * H, cr = W * .12 * m.core;
    const cg = fctx.createRadialGradient(cpx, cpy, 0, cpx, cpy, cr);
    cg.addColorStop(0, rgba(mix(m.accent, ENERGY, .4), .35 * m.core)); cg.addColorStop(1, rgba(m.accent, 0));
    fctx.fillStyle = cg; fctx.beginPath(); fctx.arc(cpx, cpy, cr, 0, TAU); fctx.fill();
    // energy dissolve rising from the chest/base
    for (const p of chest) { if (!still) { p.t += p.sp * .016; if (p.t > 1) { p.t = 0; p.a = Math.random(); } }
      const x = (0.28 + p.a * 0.44) * W + Math.sin(p.t * 6 + p.a * 10) * W * .02;
      const y = H * (.98 - p.t * .5);
      fctx.beginPath(); fctx.arc(x, y, p.r * (1 - p.t) * .9, 0, TAU); fctx.fillStyle = rgba(mix(m.accent, ENERGY, .5), (1 - p.t) * .5); fctx.fill(); }
    // environmental colour wash on the active side
    if (m.env.on > .01) { const rl = fctx.createLinearGradient(m.env.side > 0 ? 0 : W, 0, m.env.side > 0 ? W : 0, 0);
      rl.addColorStop(0, rgba(m.env.c, 0)); rl.addColorStop(1, rgba(m.env.c, .16 * m.env.on));
      fctx.fillStyle = rl; fctx.fillRect(0, 0, W, H); }
    // success/listening light sweep
    if (sweep > .01) { const sy = (1 - sweep) * H; const sg = fctx.createLinearGradient(0, sy - H * .1, 0, sy + H * .1);
      sg.addColorStop(0, rgba(sweepC, 0)); sg.addColorStop(.5, rgba(sweepC, .22 * sweep)); sg.addColorStop(1, rgba(sweepC, 0));
      fctx.fillStyle = sg; fctx.fillRect(0, 0, W, H); }
  }

  // ---- frame ---------------------------------------------------------------
  let raf = 0, last = performance.now();
  function frame(now) {
    if (document.hidden) { raf = requestAnimationFrame(frame); return; }
    const dt = Math.min(.05, (now - last) / 1000); last = now; const still = lowMotion();
    m.illum = lerp(m.illum, m.illumT, dt * 3);
    m.eye = lerp(m.eye, m.eyeT, dt * 3);
    m.haloSpin += still ? 0 : dt * .05;
    m.env.on = Math.max(0, m.env.on - dt * .12);
    sweep = Math.max(0, sweep - dt * .7);
    m.core = .45 + (still ? 0 : Math.sin(m.breath * 1.1) * .12) + m.illum * .3;
    if (!still) m.breath += dt * 1.2;
    for (let i = 0; i < 8; i++) m.haloLit[i] = Math.max(0, m.haloLit[i] - dt * .55);
    for (let i = flows.length - 1; i >= 0; i--) { flows[i].t += dt * flows[i].sp; if (flows[i].t >= 1) flows.splice(i, 1); }
    gaze(dt, still);

    // breathing + gaze on the portrait itself
    const bs = still ? 0 : Math.sin(m.breath) * .006;
    img.style.transform = `scale(${1.02 + bs}) translate(${m.gaze.x * 1.2}%, ${m.gaze.y * 1 + (still ? 0 : Math.sin(m.breath) * .3)}%)`;

    drawHalo(); drawFx(still);
    raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);

  return { litHalo: s => bus.emit('halo', s), lookAt: (x, y) => bus.emit('gaze:point', { x, y }), destroy: () => cancelAnimationFrame(raf) };
}
