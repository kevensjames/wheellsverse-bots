// ============================================================================
// KAI avatar  (Increments 2·3·5·6·7·26)
// A 2.5D canvas presence: humanoid head, the signature layered luminous eyes,
// a neural halo, particle "wings", and continuous micro-motion (breathing,
// blinking, saccades, gaze, head-tilt) + idle presence behaviours.
//
// SEAM (Increment 2, full photoreal): swap this canvas presence for a rigged
// GLB/VRM head in WebGL and drive the SAME controller API (setGaze/state/etc.).
// The eyes read --accent from the design system, so state colour is automatic.
// ============================================================================
import { bus, KAI } from './state.js';

const TAU = Math.PI * 2;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const rand = (a, b) => a + Math.random() * (b - a);

function parseColor(str) {
  str = str.trim();
  if (str[0] === '#') {
    const h = str.slice(1);
    const n = parseInt(h.length === 3 ? h.replace(/./g, c => c + c) : h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const m = str.match(/[\d.]+/g);
  return m ? [+m[0], +m[1], +m[2]] : [63, 140, 255];
}
const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;

// halo sectors — each maps to a KAI subsystem (Increment 7)
const SECTORS = ['reasoning', 'memory', 'tools', 'agents', 'research', 'security', 'market', 'infra'];

export function mountAvatar(canvas) {
  const ctx = canvas.getContext('2d');
  let W = 0, H = 0, DPR = 1;
  const lowMotion = () => document.documentElement.dataset.motion === 'off'
    || matchMedia('(prefers-reduced-motion: reduce)').matches;

  function resize() {
    DPR = Math.min(devicePixelRatio || 1, document.documentElement.dataset.q === 'low' ? 1 : 2);
    const size = canvas.clientWidth || 420;
    W = canvas.width = size * DPR; H = canvas.height = size * DPR;
  }
  new ResizeObserver(resize).observe(canvas); resize();

  // ---- animated model ------------------------------------------------------
  const m = {
    accent: [63, 140, 255],
    illum: 0.5, illumT: 0.5,       // iris illumination (state-driven)
    tilt: 0, tiltT: 0,             // head tilt (rad)
    breath: 0,
    blink: 0, nextBlink: 1200,     // 0 open → 1 closed
    gaze: { x: 0, y: 0 }, gazeT: { x: 0, y: 0 },
    sacc: 0,
    exec: 0, execT: 0,             // concentric iris pattern intensity
    wings: 0, wingsT: 0,           // particle wings opacity
    haloLit: new Map(),            // sector -> decaying intensity
    haloSpin: 0,
    presenceAt: 0,
  };

  // gaze targets, in normalized head space (-1..1). App sets these via bus.
  let gazeTarget = 'camera';
  const GAZE = { camera: [0, 0.02], input: [0, 0.5], up: [0, -0.42], left: [-0.6, 0], right: [0.6, 0] };

  function pickAccent() { m.accent = parseColor(getComputedStyle(document.documentElement).getPropertyValue('--accent') || '#3f8cff'); }
  pickAccent();

  // react to state
  bus.on('state', ({ state }) => {
    pickAccent();
    m.illumT = { idle: .42, listening: .6, thinking: .82, speaking: .7, executing: .9, researching: .78, warning: .7, critical: .95, success: 1 }[state] ?? .5;
    m.tiltT  = { thinking: -0.05, researching: 0.04, critical: 0.02 }[state] ?? 0;
    m.execT  = (state === 'executing' || state === 'thinking') ? 1 : 0;
    gazeTarget = { listening: 'camera', speaking: 'camera', thinking: 'up', researching: 'up', idle: 'camera' }[state] ?? 'camera';
    if (state === 'success') { m.wingsT = 1; setTimeout(() => (m.wingsT = 0), 1700); }
  });
  bus.on('gaze', t => { if (GAZE[t]) gazeTarget = t; });
  bus.on('halo', sector => { if (SECTORS.includes(sector)) m.haloLit.set(sector, 1); });

  // ---- eye (the signature) -------------------------------------------------
  function drawEye(cx, cy, r, blink, side) {
    const c = m.accent;
    const gx = m.gaze.x * r * 0.36 + m.sacc * side, gy = m.gaze.y * r * 0.34;

    // socket shadow
    ctx.save();
    ctx.beginPath(); ctx.ellipse(cx, cy, r * 1.5, r * 1.15, 0, 0, TAU);
    ctx.fillStyle = 'rgba(3,6,14,.6)'; ctx.filter = `blur(${r * .18}px)`; ctx.fill(); ctx.restore();

    // volumetric bloom
    const bloom = ctx.createRadialGradient(cx, cy, 0, cx, cy, r * 2.4);
    bloom.addColorStop(0, rgba(c, .35 * (0.4 + m.illum))); bloom.addColorStop(1, rgba(c, 0));
    ctx.fillStyle = bloom; ctx.beginPath(); ctx.arc(cx, cy, r * 2.4, 0, TAU); ctx.fill();

    // sclera hint
    ctx.beginPath(); ctx.ellipse(cx, cy, r * 1.18, r * 0.92, 0, 0, TAU);
    ctx.fillStyle = 'rgba(210,225,255,.06)'; ctx.fill();

    // iris — radial blue→cyan with fibers
    const ix = cx + gx, iy = cy + gy;
    const iris = ctx.createRadialGradient(ix, iy, r * .1, ix, iy, r);
    iris.addColorStop(0, rgba([c[0] + 40, c[1] + 40, 255], .95));
    iris.addColorStop(.55, rgba(c, .9));
    iris.addColorStop(1, rgba([c[0] * .4, c[1] * .5, c[2] * .8], .95));
    ctx.beginPath(); ctx.arc(ix, iy, r, 0, TAU); ctx.fillStyle = iris; ctx.fill();

    // cyan internal fibers
    ctx.save(); ctx.beginPath(); ctx.arc(ix, iy, r, 0, TAU); ctx.clip();
    ctx.strokeStyle = rgba([140, 243, 255], .35 * (0.5 + m.illum)); ctx.lineWidth = Math.max(1, r * .02);
    for (let i = 0; i < 26; i++) {
      const a = (i / 26) * TAU;
      ctx.beginPath(); ctx.moveTo(ix + Math.cos(a) * r * .28, iy + Math.sin(a) * r * .28);
      ctx.lineTo(ix + Math.cos(a) * r * .96, iy + Math.sin(a) * r * .96); ctx.stroke();
    }
    // concentric rotating pattern when executing/thinking
    if (m.exec > .02) {
      ctx.strokeStyle = rgba([180, 245, 255], .5 * m.exec);
      for (let k = 1; k <= 3; k++) {
        ctx.beginPath();
        for (let a = 0; a <= TAU + .1; a += .3) {
          const rr = r * (.3 + k * .2) + Math.sin(a * 6 + m.haloSpin * 3 * k) * r * .03;
          const px = ix + Math.cos(a) * rr, py = iy + Math.sin(a) * rr;
          a === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py);
        }
        ctx.stroke();
      }
    }
    ctx.restore();

    // luminous pupil + ring
    ctx.beginPath(); ctx.arc(ix, iy, r * .34, 0, TAU); ctx.fillStyle = '#03060e'; ctx.fill();
    ctx.beginPath(); ctx.arc(ix, iy, r * .34, 0, TAU);
    ctx.strokeStyle = rgba([200, 245, 255], .8 * (.5 + m.illum)); ctx.lineWidth = Math.max(1.2, r * .04); ctx.stroke();
    ctx.beginPath(); ctx.arc(ix, iy, r * .1, 0, TAU); ctx.fillStyle = rgba([220, 250, 255], .9); ctx.fill();

    // physically-placed specular reflection
    ctx.beginPath(); ctx.arc(ix - r * .3, iy - r * .34, r * .12, 0, TAU); ctx.fillStyle = 'rgba(255,255,255,.85)'; ctx.fill();
    ctx.beginPath(); ctx.arc(ix + r * .18, iy + r * .28, r * .05, 0, TAU); ctx.fillStyle = 'rgba(255,255,255,.4)'; ctx.fill();

    // eyelids (blink) — cover from top & bottom
    if (blink > .01) {
      ctx.fillStyle = '#080b16';
      const cover = blink * r * 1.15;
      ctx.beginPath(); ctx.ellipse(cx, cy - r * 1.15 + cover, r * 1.3, cover, 0, 0, TAU); ctx.fill();
      ctx.beginPath(); ctx.ellipse(cx, cy + r * 1.15 - cover, r * 1.3, cover, 0, 0, TAU); ctx.fill();
    }
  }

  // ---- head presence -------------------------------------------------------
  function drawHead(cx, cy, s) {
    const c = m.accent;
    // volumetric glow behind head
    const g = ctx.createRadialGradient(cx, cy, s * .2, cx, cy, s * 1.7);
    g.addColorStop(0, rgba(c, .12 * (.6 + m.illum))); g.addColorStop(1, rgba(c, 0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(cx, cy, s * 1.7, 0, TAU); ctx.fill();

    // head silhouette (soft synthetic) — bezier oval, narrower jaw
    ctx.save(); ctx.translate(cx, cy); ctx.rotate(m.tilt);
    const hg = ctx.createLinearGradient(0, -s, 0, s);
    hg.addColorStop(0, 'rgba(24,34,60,.92)'); hg.addColorStop(.5, 'rgba(15,22,42,.94)'); hg.addColorStop(1, 'rgba(9,13,26,.96)');
    ctx.beginPath();
    ctx.moveTo(0, -s * .98);
    ctx.bezierCurveTo(s * .82, -s * .95, s * .78, s * .1, s * .5, s * .62);
    ctx.bezierCurveTo(s * .3, s * .98, -s * .3, s * .98, -s * .5, s * .62);
    ctx.bezierCurveTo(-s * .78, s * .1, -s * .82, -s * .95, 0, -s * .98);
    ctx.closePath(); ctx.fillStyle = hg; ctx.fill();
    ctx.strokeStyle = rgba(c, .18); ctx.lineWidth = 1.4; ctx.stroke();

    // subtle under-skin patterns (synthetic hint)
    ctx.strokeStyle = rgba(c, .07); ctx.lineWidth = 1;
    for (let i = 0; i < 5; i++) {
      ctx.beginPath();
      ctx.moveTo(-s * .5, -s * .3 + i * s * .18);
      ctx.quadraticCurveTo(0, -s * .1 + i * s * .18, s * .5, -s * .3 + i * s * .18);
      ctx.stroke();
    }
    // brow + nose bridge suggestion
    ctx.strokeStyle = rgba(c, .22); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(-s * .42, -s * .18); ctx.quadraticCurveTo(-s * .18, -s * .26, -s * .04, -s * .16); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(s * .42, -s * .18); ctx.quadraticCurveTo(s * .18, -s * .26, s * .04, -s * .16); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(0, -s * .12); ctx.lineTo(0, s * .18); ctx.strokeStyle = rgba(c, .12); ctx.stroke();
    // lips hint
    ctx.beginPath(); ctx.moveTo(-s * .16, s * .34); ctx.quadraticCurveTo(0, s * .4 + Math.sin(m.breath) * 1, s * .16, s * .34); ctx.strokeStyle = rgba(c, .2); ctx.stroke();
    ctx.restore();

    // eyes — human proportions: ~one eye-width apart, set on the face midline
    const er = s * .16;
    drawEye(cx - s * .28, cy - s * .04, er, m.blink, -1);
    drawEye(cx + s * .28, cy - s * .04, er, m.blink, 1);
  }

  // ---- neural halo (Increment 7) ------------------------------------------
  function drawHalo(cx, cy, R) {
    const c = m.accent;
    ctx.save(); ctx.translate(cx, cy);
    // base ring
    ctx.beginPath(); ctx.arc(0, 0, R, 0, TAU); ctx.strokeStyle = rgba(c, .12); ctx.lineWidth = 1.2; ctx.stroke();
    SECTORS.forEach((sec, i) => {
      const a0 = (i / SECTORS.length) * TAU + m.haloSpin, a1 = a0 + TAU / SECTORS.length * .82;
      const lit = m.haloLit.get(sec) || 0;
      ctx.beginPath(); ctx.arc(0, 0, R, a0, a1);
      ctx.strokeStyle = rgba(c, .16 + lit * .8); ctx.lineWidth = 2 + lit * 4; ctx.stroke();
      // node
      const mid = (a0 + a1) / 2, nx = Math.cos(mid) * R, ny = Math.sin(mid) * R;
      ctx.beginPath(); ctx.arc(nx, ny, 2.4 + lit * 3, 0, TAU);
      ctx.fillStyle = rgba([lerp(c[0], 180, lit), lerp(c[1], 245, lit), 255], .5 + lit * .5); ctx.fill();
    });
    ctx.restore();
  }

  // ---- particle wings (Increment 6) ---------------------------------------
  function drawWings(cx, cy, s) {
    if (m.wings < .01) return;
    const c = m.accent;
    ctx.save(); ctx.translate(cx, cy + s * .4);
    for (const dir of [-1, 1]) {
      for (let i = 0; i < 40; i++) {
        const t = i / 40, spread = t * s * 1.9 * dir;
        const droop = Math.sin(t * Math.PI) * s * .8;
        const x = spread, y = -droop + Math.sin(t * 10 + m.haloSpin * 4) * 4;
        ctx.beginPath(); ctx.arc(x, y, 1.6 * (1 - t * .5), 0, TAU);
        ctx.fillStyle = rgba([lerp(c[0], 200, .3), lerp(c[1], 245, .3), 255], m.wings * (.6 - t * .5)); ctx.fill();
        if (i % 4 === 0 && i > 0) { // faint neural connections
          ctx.beginPath(); ctx.moveTo(x, y);
          ctx.lineTo(spread * .7, -droop * .6); ctx.strokeStyle = rgba(c, m.wings * .12); ctx.stroke();
        }
      }
    }
    ctx.restore();
  }

  // ---- frame ---------------------------------------------------------------
  let raf = 0, last = performance.now(), blinkT = 0, saccT = 0;
  function frame(now) {
    const dt = Math.min(0.05, (now - last) / 1000); last = now;
    const still = lowMotion();

    // ease model toward targets
    m.illum = lerp(m.illum, m.illumT, still ? 1 : dt * 3);
    m.tilt = lerp(m.tilt, m.tiltT, still ? 1 : dt * 2);
    m.exec = lerp(m.exec, m.execT, dt * 3);
    m.wings = lerp(m.wings, m.wingsT, dt * 4);
    m.haloSpin += still ? 0 : dt * 0.08;

    if (!still) {
      m.breath += dt * 1.4;
      // blink scheduling (+ occasional double blink)
      blinkT += dt * 1000;
      if (blinkT > m.nextBlink) { m.blink = Math.min(1, m.blink + dt * 14); if (m.blink >= 1) { blinkT = 0; m.nextBlink = rand(2200, 5200); if (Math.random() < .12) m.nextBlink = 180; } }
      else if (m.blink > 0) m.blink = Math.max(0, m.blink - dt * 16);
      // saccades
      saccT += dt;
      if (saccT > rand(0.8, 2.2)) { saccT = 0; m.sacc = rand(-2, 2); }
      m.sacc = lerp(m.sacc, 0, dt * 3);
      // presence mode: idle wandering gaze (Increment 26)
      m.presenceAt += dt;
      if (KAI.state === 'idle' && m.presenceAt > 6) {
        m.presenceAt = 0; bus.emit('gaze', ['left', 'right', 'up', 'camera'][Math.floor(rand(0, 4))]);
        setTimeout(() => KAI.state === 'idle' && bus.emit('gaze', 'camera'), 1800);
      }
    } else { m.blink = 0; m.breath = 0; }

    // gaze easing toward target
    const g = GAZE[gazeTarget] || GAZE.camera;
    m.gaze.x = lerp(m.gaze.x, g[0], still ? 1 : dt * 4);
    m.gaze.y = lerp(m.gaze.y, g[1], still ? 1 : dt * 4);

    // decay halo sectors
    for (const [k, v] of m.haloLit) { const nv = v - dt * 0.6; nv <= 0 ? m.haloLit.delete(k) : m.haloLit.set(k, nv); }

    // ---- render ----
    ctx.clearRect(0, 0, W, H);
    ctx.save(); ctx.scale(DPR, DPR);
    const cw = W / DPR, ch = H / DPR, cx = cw / 2;
    const bob = still ? 0 : Math.sin(m.breath) * ch * .006;
    const cy = ch * .46 + bob;
    const s = cw * .2;
    drawHalo(cx, cy, s * 1.85);
    drawWings(cx, cy, s);
    drawHead(cx, cy, s);
    ctx.restore();

    raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);

  return {
    litHalo: sec => bus.emit('halo', sec),
    destroy: () => cancelAnimationFrame(raf),
  };
}
