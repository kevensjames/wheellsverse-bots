// ============================================================================
// KAI Presence Engine  (Phase 1)
// A persistent digital person at the center of the Nexus: upper-body figure
// (head · neck · shoulders) dissolving into particles at the chest so KAI reads
// as embedded in the OS — with anatomical eyes, procedural facial life, spatial
// gaze that looks at real panels/events, a meaningful Intelligence Halo with
// particle flows, barely-visible particle wings, and environmental rim-light.
//
// Balance target ≈ 75% human · 10% celestial · 10% synthetic · 5% machine.
// Rendered procedurally in canvas 2.5D. SEAM (#2): swap the figure/face render
// for a rigged GLB/VRM head in WebGL and keep this exact controller API
// (state, gaze point, halo, env light) — nothing else in the app needs to change.
// ============================================================================
import { bus, KAI } from './state.js';

const TAU = Math.PI * 2;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const lerp = (a, b, t) => a + (b - a) * t;
const rand = (a, b) => a + Math.random() * (b - a);
const mix = (c1, c2, t) => [lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t)];
const rgba = (c, a) => `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`;

function parseColor(str) {
  str = (str || '').trim();
  if (str[0] === '#') {
    const h = str.slice(1);
    const n = parseInt(h.length === 3 ? h.replace(/./g, c => c + c) : h, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }
  const m = str.match(/[\d.]+/g);
  return m ? [+m[0], +m[1], +m[2]] : [63, 140, 255];
}

// Natural iris blue + the restrained "inner energy" cyan — kept distinct from
// the state accent so eyes read human until KAI actually engages.
const IRIS_BLUE = [46, 92, 168];
const IRIS_EDGE = [18, 34, 74];
const ENERGY    = [120, 214, 255];
const SKIN      = [150, 168, 205];   // cool synthetic skin midtone

// halo sectors → KAI subsystems (labels shown dim, brighten when lit)
const SECTORS = ['REASONING', 'MEMORY', 'RESEARCH', 'TOOLS', 'AGENTS', 'SECURITY', 'MARKETS', 'INFRA'];
const SECTOR_KEY = { reasoning: 0, memory: 1, research: 2, tools: 3, agents: 4, security: 5, market: 6, markets: 6, infra: 7 };

export function mountAvatar(canvas) {
  const ctx = canvas.getContext('2d');
  let W = 0, H = 0, DPR = 1, rect = canvas.getBoundingClientRect();
  const lowMotion = () => document.documentElement.dataset.motion === 'off'
    || matchMedia('(prefers-reduced-motion: reduce)').matches;
  const lowQ = () => document.documentElement.dataset.q === 'low';

  function resize() {
    DPR = Math.min(devicePixelRatio || 1, lowQ() ? 1 : 2);
    const size = canvas.clientWidth || 440;
    W = canvas.width = size * DPR; H = canvas.height = size * DPR;
    rect = canvas.getBoundingClientRect();
  }
  new ResizeObserver(resize).observe(canvas); resize();
  addEventListener('scroll', () => (rect = canvas.getBoundingClientRect()), { passive: true });

  // ---- animated model ------------------------------------------------------
  const m = {
    accent: [63, 140, 255],
    illum: .35, illumT: .35,          // iris inner-energy intensity
    eyeShift: 0, eyeShiftT: 0,        // 0 = natural blue, 1 = fully accent (warning/critical)
    bright: 1, brightT: 1,            // overall presence brightness (sleep dims)
    tilt: 0, tiltT: 0,               // head roll
    turn: 0,                         // head yaw toward gaze (rad, small)
    breath: 0, shoulder: 0,
    blink: 0, nextBlink: 1400,
    pupil: 0, pupilT: 0,             // extra contraction (thinking)
    brow: 0, browT: 0,               // eyebrow raise
    jaw: 0, mouthT: 0, visemeAt: 0,  // mouth open (viseme-driven while speaking)
    exec: 0, execT: 0,
    wings: 0, wingsT: 0,
    gaze: { x: 0, y: .02 }, gazeT: { x: 0, y: .02 },
    sacc: 0, micro: 0, microT: 0,
    haloLit: new Array(8).fill(0),
    haloSpin: 0,
    env: { c: [63, 140, 255], side: 0, on: 0 },   // environmental rim light
    presenceAt: 0,
  };

  // gaze: named presets in head space (-1..1) OR a live screen point
  let gazeMode = 'camera';                 // 'camera'|'input'|'up'|'point'
  let gazePoint = null;                    // {x,y} client coords when mode='point'
  const GAZE = { camera: [0, .04], input: [0, .5], up: [0, -.42] };

  function pickAccent() { m.accent = parseColor(getComputedStyle(document.documentElement).getPropertyValue('--accent')); }
  pickAccent();

  bus.on('state', ({ state }) => {
    pickAccent();
    m.illumT     = { idle:.32, sleep:.12, listening:.5, understanding:.62, thinking:.85, researching:.72, speaking:.62, executing:.9, warning:.7, critical:1, success:1 }[state] ?? .35;
    m.eyeShiftT  = { warning:.6, critical:.92 }[state] ?? 0;
    m.brightT    = state === 'sleep' ? .4 : 1;
    m.tiltT      = { thinking:-.05, researching:.04, understanding:-.03, critical:.02 }[state] ?? 0;
    m.pupilT     = { thinking:.35, executing:.3, critical:.4 }[state] ?? 0;
    m.browT      = { listening:.7, understanding:.9, warning:.6, critical:.5, speaking:.3 }[state] ?? 0;
    m.execT      = (state === 'executing' || state === 'thinking') ? 1 : 0;
    gazeMode     = { listening:'camera', understanding:'camera', speaking:'camera', thinking:'up', researching:'up', idle:'camera', sleep:'up' }[state] ?? 'camera';
    if (state === 'success') { m.wingsT = 1; setTimeout(() => (m.wingsT = 0), 1600); }
  });
  bus.on('gaze', t => { if (GAZE[t]) { gazeMode = t; gazePoint = null; } });
  bus.on('gaze:point', p => { if (p && typeof p.x === 'number') { gazeMode = 'point'; gazePoint = p; } });
  bus.on('halo', sec => { const i = SECTOR_KEY[sec]; if (i != null) { m.haloLit[i] = 1; flows.push(makeFlow(i)); } });
  bus.on('env:light', ({ color, side }) => { m.env.c = parseColor(color || '#3f8cff'); m.env.side = side ?? 0; m.env.on = 1; });
  bus.on('viseme', v => { m.mouthT = (v && v.open) || 0; m.visemeAt = performance.now(); });  // lip-sync feed

  // ---- particle systems ----------------------------------------------------
  let chest = [], flows = [];
  function seedChest() {
    const n = lowQ() ? 26 : 64;
    chest = Array.from({ length: n }, () => ({ a: rand(-1, 1), t: Math.random(), sp: rand(.06, .2), r: rand(.5, 1.8) }));
  }
  seedChest();
  function makeFlow(sectorIdx) {
    return { s: sectorIdx, t: 0, sp: rand(.5, .9), r: rand(1, 2.2) };
  }

  // ---- anatomical eye (more sclera, smaller iris → calm & human) -----------
  function drawEye(cx, cy, r, side) {
    const ir = r * .58;                                // iris radius, leaves visible whites
    const gx = m.gaze.x * r * .3 + m.sacc * side, gy = m.gaze.y * r * .28;
    const ix = cx + gx, iy = cy + gy;
    const irisC = mix(IRIS_BLUE, m.accent, m.eyeShift * .85);
    const edgeC = mix(IRIS_EDGE, [m.accent[0] * .4, m.accent[1] * .4, m.accent[2] * .5], m.eyeShift);

    ctx.save();
    // soft socket shadow
    ctx.beginPath(); ctx.ellipse(cx, cy, r * 1.3, r * .82, 0, 0, TAU);
    ctx.fillStyle = 'rgba(4,7,16,.32)'; ctx.filter = `blur(${r * .1}px)`; ctx.fill(); ctx.filter = 'none';

    // sclera almond (clipped)
    ctx.save();
    ctx.beginPath(); ctx.ellipse(cx, cy, r * 1.12, r * .66, 0, 0, TAU); ctx.clip();
    const sc = ctx.createLinearGradient(cx, cy - r, cx, cy + r);
    sc.addColorStop(0, 'rgba(212,224,242,.95)'); sc.addColorStop(1, 'rgba(160,178,208,.9)');
    ctx.fillStyle = sc; ctx.fillRect(cx - r * 1.3, cy - r, r * 2.6, r * 2);
    ctx.fillStyle = 'rgba(20,30,55,.14)';
    ctx.fillRect(cx - r * 1.3, cy - r, r * .4, r * 2); ctx.fillRect(cx + r * .9, cy - r, r * .4, r * 2);

    // iris
    const iris = ctx.createRadialGradient(ix, iy, ir * .08, ix, iy, ir);
    iris.addColorStop(0, rgba(mix(irisC, ENERGY, .2 + m.illum * .28), 1));
    iris.addColorStop(.6, rgba(irisC, 1));
    iris.addColorStop(1, rgba(edgeC, 1));
    ctx.beginPath(); ctx.arc(ix, iy, ir, 0, TAU); ctx.fillStyle = iris; ctx.fill();
    ctx.strokeStyle = rgba(mix(irisC, ENERGY, .5), .18 + m.illum * .2); ctx.lineWidth = Math.max(.5, r * .012);
    for (let i = 0; i < 26; i++) { const a = (i / 26) * TAU + Math.sin(i) * .1;
      ctx.beginPath(); ctx.moveTo(ix + Math.cos(a) * ir * .3, iy + Math.sin(a) * ir * .3);
      ctx.lineTo(ix + Math.cos(a) * ir * .92, iy + Math.sin(a) * ir * .92); ctx.stroke(); }
    ctx.beginPath(); ctx.arc(ix, iy, ir, 0, TAU); ctx.strokeStyle = rgba(edgeC, .85); ctx.lineWidth = ir * .1; ctx.stroke();
    if (m.exec > .02) { ctx.strokeStyle = rgba(ENERGY, .4 * m.exec); ctx.lineWidth = Math.max(1, ir * .06);
      ctx.beginPath();
      for (let a = 0; a <= TAU + .1; a += .35) { const rr = ir * (.45 + Math.sin(a * 5 + m.haloSpin * 4) * .06);
        const px = ix + Math.cos(a) * rr, py = iy + Math.sin(a) * rr; a === 0 ? ctx.moveTo(px, py) : ctx.lineTo(px, py); }
      ctx.stroke(); }
    const pr = ir * (.42 - m.pupil * .12);
    const eg = ctx.createRadialGradient(ix, iy, 0, ix, iy, pr * 2.2);
    eg.addColorStop(0, rgba(ENERGY, .45 * m.illum)); eg.addColorStop(1, rgba(ENERGY, 0));
    ctx.fillStyle = eg; ctx.beginPath(); ctx.arc(ix, iy, pr * 2.2, 0, TAU); ctx.fill();
    ctx.beginPath(); ctx.arc(ix, iy, pr, 0, TAU); ctx.fillStyle = '#050810'; ctx.fill();
    ctx.beginPath(); ctx.arc(ix, iy, pr * .5, 0, TAU); ctx.fillStyle = rgba(ENERGY, .3 + m.illum * .4); ctx.fill();
    ctx.restore();

    // cornea reflections (sharp specular)
    ctx.beginPath(); ctx.arc(ix - ir * .32, iy - ir * .36, ir * .18, 0, TAU); ctx.fillStyle = 'rgba(255,255,255,.9)'; ctx.fill();
    ctx.beginPath(); ctx.arc(ix + ir * .24, iy + ir * .26, ir * .08, 0, TAU); ctx.fillStyle = 'rgba(255,255,255,.4)'; ctx.fill();

    // eyelids (skin) — blink + resting upper-lid line
    const lidTop = -r * .66 + m.blink * r * 1.34, lidBot = r * .66 - m.blink * r * .8;
    ctx.fillStyle = rgba(mix(SKIN, m.accent, .04 * m.bright), 1);
    ctx.beginPath(); ctx.moveTo(cx - r * 1.3, cy - r); ctx.lineTo(cx + r * 1.3, cy - r);
    ctx.lineTo(cx + r * 1.3, cy + lidTop); ctx.quadraticCurveTo(cx, cy + lidTop - r * .12, cx - r * 1.3, cy + lidTop); ctx.closePath(); ctx.fill();
    ctx.beginPath(); ctx.moveTo(cx - r * 1.3, cy + r); ctx.lineTo(cx + r * 1.3, cy + r);
    ctx.lineTo(cx + r * 1.3, cy + lidBot); ctx.quadraticCurveTo(cx, cy + lidBot + r * .1, cx - r * 1.3, cy + lidBot); ctx.closePath(); ctx.fill();
    ctx.strokeStyle = 'rgba(10,16,30,.42)'; ctx.lineWidth = Math.max(1, r * .04);
    ctx.beginPath(); ctx.moveTo(cx - r * 1.05, cy + lidTop); ctx.quadraticCurveTo(cx, cy + lidTop - r * .11, cx + r * 1.05, cy + lidTop); ctx.stroke();
    ctx.restore();
  }

  // ---- eyebrow (thin, higher, gentle natural arch — never "angry") --------
  function drawBrow(cx, cy, r, side) {
    const lift = m.brow * r * .4 + (side < 0 ? m.micro : -m.micro) * r * .2;
    ctx.strokeStyle = rgba(mix(SKIN, [42, 54, 82], .5), .45); ctx.lineWidth = r * .09; ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(cx - r * 1.0 * side, cy - r * .1 - lift * .3);                            // inner (raised → not a frown)
    ctx.quadraticCurveTo(cx + r * .15 * side, cy - r * .3 - lift, cx + r * 1.18 * side, cy - r * .12 - lift * .5); // arch → outer
    ctx.stroke();
  }

  // ---- face + figure -------------------------------------------------------
  function drawFigure(cx, cy, s) {
    const skin = mix(SKIN, m.accent, .05);
    ctx.save(); ctx.translate(cx, cy); ctx.rotate(m.tilt);

    // shoulders + neck (dissolve into particles below)
    const shY = s * 1.35, shW = s * 2.1;
    const shg = ctx.createLinearGradient(0, s * .7, 0, s * 2.2);
    shg.addColorStop(0, rgba(mix(skin, [10, 15, 30], .3), .9 * m.bright));
    shg.addColorStop(1, rgba([8, 12, 26], 0));
    ctx.beginPath();
    ctx.moveTo(-s * .34, s * .6); ctx.quadraticCurveTo(-shW * .5, shY * .82, -shW * .5, s * 2.2);
    ctx.lineTo(shW * .5, s * 2.2); ctx.quadraticCurveTo(shW * .5, shY * .82, s * .34, s * .6);
    ctx.closePath(); ctx.fillStyle = shg; ctx.fill();
    // neck
    const ng = ctx.createLinearGradient(0, s * .4, 0, s * 1); ng.addColorStop(0, rgba(mix(skin, [0, 0, 0], .35), m.bright)); ng.addColorStop(1, rgba(skin, .9 * m.bright));
    ctx.beginPath(); ctx.moveTo(-s * .28, s * .5); ctx.lineTo(-s * .3, s * .95); ctx.lineTo(s * .3, s * .95); ctx.lineTo(s * .28, s * .5); ctx.closePath(); ctx.fillStyle = ng; ctx.fill();
    // jaw/chin shadow under neck
    ctx.beginPath(); ctx.ellipse(0, s * .52, s * .34, s * .12, 0, 0, TAU); ctx.fillStyle = 'rgba(6,10,22,.5)'; ctx.fill();

    // head — shaded form
    const hg = ctx.createRadialGradient(-s * .3, -s * .5, s * .1, 0, 0, s * 1.25);
    hg.addColorStop(0, rgba(mix(skin, [255, 255, 255], .12), m.bright));
    hg.addColorStop(.5, rgba(skin, m.bright));
    hg.addColorStop(1, rgba(mix(skin, [6, 10, 22], .55), m.bright));
    ctx.beginPath();
    ctx.moveTo(0, -s * 1.02);
    ctx.bezierCurveTo(s * .8, -s * .98, s * .74, s * .05, s * .46, s * .5);
    ctx.bezierCurveTo(s * .3, s * .82, -s * .3, s * .82, -s * .46, s * .5);
    ctx.bezierCurveTo(-s * .74, s * .05, -s * .8, -s * .98, 0, -s * 1.02);
    ctx.closePath(); ctx.fillStyle = hg; ctx.fill();

    // volume: cheekbone highlights, brow-ridge & nose shadow, jaw
    const hi = (x, y, rx, ry, a) => { const g = ctx.createRadialGradient(x, y, 0, x, y, rx);
      g.addColorStop(0, rgba(mix(skin, [255, 255, 255], .5), a * m.bright)); g.addColorStop(1, rgba(skin, 0));
      ctx.save(); ctx.beginPath(); ctx.ellipse(x, y, rx, ry, 0, 0, TAU); ctx.fillStyle = g; ctx.fill(); ctx.restore(); };
    hi(-s * .42, s * .12, s * .3, s * .24, .5); hi(s * .42, s * .12, s * .3, s * .24, .5);  // cheeks
    hi(0, -s * .55, s * .35, s * .22, .4);                                                  // forehead
    const sh = (x, y, rx, ry, a) => { const g = ctx.createRadialGradient(x, y, 0, x, y, rx);
      g.addColorStop(0, rgba([6, 10, 22], a)); g.addColorStop(1, rgba([6, 10, 22], 0));
      ctx.save(); ctx.beginPath(); ctx.ellipse(x, y, rx, ry, 0, 0, TAU); ctx.fillStyle = g; ctx.fill(); ctx.restore(); };
    sh(0, s * .02, s * .1, s * .24, .28);              // nose bridge shadow (kept off the glabella → no frown)
    sh(-s * .1, s * .12, s * .09, s * .12, .3);         // nostril hint
    sh(s * .1, s * .12, s * .09, s * .12, .3);
    // nose highlight
    ctx.strokeStyle = rgba(mix(skin, [255, 255, 255], .4), .35 * m.bright); ctx.lineWidth = s * .04; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(0, -s * .28); ctx.lineTo(-s * .02, s * .1); ctx.stroke();

    // lips (jaw opens on speaking)
    const mo = m.jaw * s * .14;
    ctx.strokeStyle = rgba(mix(skin, [120, 70, 90], .35), .6 * m.bright); ctx.lineWidth = s * .035;
    ctx.beginPath(); ctx.moveTo(-s * .16, s * .32); ctx.quadraticCurveTo(0, s * .3, s * .16, s * .32); ctx.stroke();
    if (mo > .3) { ctx.fillStyle = 'rgba(20,10,18,.55)'; ctx.beginPath(); ctx.ellipse(0, s * .34 + mo * .4, s * .12, mo, 0, 0, TAU); ctx.fill(); }
    ctx.beginPath(); ctx.moveTo(-s * .14, s * .36 + mo); ctx.quadraticCurveTo(0, s * .42 + mo * 1.2, s * .14, s * .36 + mo); ctx.stroke();

    // subtle synthetic under-skin traces
    ctx.strokeStyle = rgba(m.accent, .05 * m.bright); ctx.lineWidth = 1;
    for (let i = 0; i < 3; i++) { ctx.beginPath(); ctx.moveTo(-s * .5, -s * .2 + i * s * .28);
      ctx.quadraticCurveTo(0, -s * .05 + i * s * .28, s * .5, -s * .2 + i * s * .28); ctx.stroke(); }

    // brows + eyes on the face midline (smaller, calmer, human spacing)
    const er = s * .14, ey = -s * .04, ex = s * .32;
    drawBrow(-ex, ey - s * .22, er, -1); drawBrow(ex, ey - s * .22, er, 1);
    drawEye(-ex, ey, er, -1); drawEye(ex, ey, er, 1);

    // environmental rim light on the active side
    if (m.env.on > .01) {
      ctx.save(); ctx.beginPath();
      ctx.moveTo(0, -s * 1.02);
      ctx.bezierCurveTo(s * .8, -s * .98, s * .74, s * .05, s * .46, s * .5);
      ctx.bezierCurveTo(s * .3, s * .82, -s * .3, s * .82, -s * .46, s * .5);
      ctx.bezierCurveTo(-s * .74, s * .05, -s * .8, -s * .98, 0, -s * 1.02);
      ctx.closePath(); ctx.clip();
      const rl = ctx.createLinearGradient(-s * m.env.side, 0, s * m.env.side, 0);
      rl.addColorStop(0, rgba(m.env.c, 0)); rl.addColorStop(1, rgba(m.env.c, .3 * m.env.on));
      ctx.fillStyle = rl; ctx.fillRect(-s, -s * 1.1, s * 2, s * 2); ctx.restore();
    }
    ctx.restore();

    // chest dissolve particles (figure → OS)
    ctx.save(); ctx.translate(cx, cy);
    for (const p of chest) {
      const px = p.a * shW * .5 * (1 - p.t * .3), py = s * (1.6 + p.t * .8);
      ctx.beginPath(); ctx.arc(px, py, p.r * (1 - p.t) * DPR * .8, 0, TAU);
      ctx.fillStyle = rgba(mix(skin, m.accent, .5), (1 - p.t) * .5 * m.bright); ctx.fill();
    }
    ctx.restore();
  }

  // ---- Intelligence Halo (labeled, event-driven) --------------------------
  function drawHalo(cx, cy, R) {
    ctx.save(); ctx.translate(cx, cy);
    ctx.beginPath(); ctx.arc(0, 0, R, 0, TAU); ctx.strokeStyle = rgba(m.accent, .08); ctx.lineWidth = 1; ctx.stroke();
    ctx.font = `${Math.max(7, R * .028)}px var(--mono, monospace)`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    for (let i = 0; i < 8; i++) {
      const a0 = (i / 8) * TAU - Math.PI / 2 + m.haloSpin, a1 = a0 + TAU / 8 * .8;
      const lit = m.haloLit[i];
      ctx.beginPath(); ctx.arc(0, 0, R, a0, a1);
      ctx.strokeStyle = rgba(m.accent, .1 + lit * .8); ctx.lineWidth = 1.5 + lit * 4; ctx.stroke();
      const mid = (a0 + a1) / 2, nx = Math.cos(mid) * R, ny = Math.sin(mid) * R;
      ctx.beginPath(); ctx.arc(nx, ny, 1.8 + lit * 3.5, 0, TAU);
      ctx.fillStyle = rgba(mix(m.accent, ENERGY, lit), .4 + lit * .6); ctx.fill();
      // label just outside, dim unless lit
      ctx.fillStyle = rgba(mix(m.accent, ENERGY, lit), .12 + lit * .7);
      ctx.fillText(SECTORS[i], Math.cos(mid) * (R + R * .09), Math.sin(mid) * (R + R * .09));
    }
    // particle flows outward from lit sectors
    for (const f of flows) {
      const a = (f.s / 8) * TAU - Math.PI / 2 + m.haloSpin + TAU / 16 * .8;
      const rr = R * f.t, px = Math.cos(a) * rr, py = Math.sin(a) * rr;
      ctx.beginPath(); ctx.arc(px, py, f.r * (1 - f.t * .5), 0, TAU);
      ctx.fillStyle = rgba(ENERGY, (1 - f.t) * .7); ctx.fill();
    }
    ctx.restore();
  }

  // ---- particle wings (barely visible) ------------------------------------
  function drawWings(cx, cy, s) {
    if (m.wings < .01) return;
    ctx.save(); ctx.translate(cx, cy + s * .3);
    const N = lowQ() ? 26 : 52;
    for (const dir of [-1, 1]) for (let i = 0; i < N; i++) {
      const t = i / N, x = t * s * 2.1 * dir, y = -Math.sin(t * Math.PI) * s * .95 + Math.sin(t * 12 + m.haloSpin * 4) * 3;
      ctx.beginPath(); ctx.arc(x, y, 1.5 * (1 - t * .5), 0, TAU);
      ctx.fillStyle = rgba(mix(m.accent, ENERGY, .4), m.wings * (.5 - t * .4)); ctx.fill();
    }
    ctx.restore();
  }

  // ---- spatial gaze: resolve a screen point into head-space vector ---------
  function resolveGaze(dt, still) {
    let tx, ty;
    if (gazeMode === 'point' && gazePoint) {
      const hx = rect.left + rect.width / 2, hy = rect.top + rect.height * .44;
      tx = clamp((gazePoint.x - hx) / (innerWidth * .5), -1, 1);
      ty = clamp((gazePoint.y - hy) / (innerHeight * .5), -1, 1);
    } else { const g = GAZE[gazeMode] || GAZE.camera; tx = g[0]; ty = g[1]; }
    m.gaze.x = lerp(m.gaze.x, tx, still ? 1 : dt * 3.5);
    m.gaze.y = lerp(m.gaze.y, ty, still ? 1 : dt * 3.5);
    m.turn = lerp(m.turn, tx * .09, still ? 1 : dt * 2.5);   // head follows gaze a touch
  }

  // ---- frame ---------------------------------------------------------------
  let raf = 0, last = performance.now(), blinkT = 0, saccT = 0, microT = 0;
  function frame(now) {
    const dt = Math.min(.05, (now - last) / 1000); last = now;
    const still = lowMotion();

    m.illum = lerp(m.illum, m.illumT, dt * 3);
    m.eyeShift = lerp(m.eyeShift, m.eyeShiftT, dt * 2.5);
    m.bright = lerp(m.bright, m.brightT, dt * 2);
    m.tilt = lerp(m.tilt, m.tiltT + m.turn, still ? 1 : dt * 2);
    m.pupil = lerp(m.pupil, m.pupilT, dt * 3);
    m.brow = lerp(m.brow, m.browT, dt * 4);
    m.exec = lerp(m.exec, m.execT, dt * 3);
    m.wings = lerp(m.wings, m.wingsT, dt * 4);
    m.micro = lerp(m.micro, m.microT, dt * 5);
    m.env.on = lerp(m.env.on, m.env.on > 0 ? Math.max(0, m.env.on - dt * .12) : 0, 1);  // env light slowly fades
    m.haloSpin += still ? 0 : dt * .06;

    // jaw driven by real viseme events during speech; gentle fallback if no stream
    const speaking = KAI.state === 'speaking';
    const vFresh = (now - m.visemeAt) < 380;
    const mouth = speaking && !still ? (vFresh ? m.mouthT : Math.sin(now * .02) * .25 + .28) : 0;
    m.jaw = lerp(m.jaw, mouth, dt * 14);

    if (!still) {
      m.breath += dt * (KAI.state === 'sleep' ? .7 : 1.3);
      m.shoulder = Math.sin(m.breath * .5) * 1;
      blinkT += dt * 1000;
      const closeSpeed = KAI.state === 'sleep' ? 6 : 15;
      if (blinkT > m.nextBlink) { m.blink = Math.min(1, m.blink + dt * closeSpeed);
        if (m.blink >= 1) { blinkT = 0; m.nextBlink = KAI.state === 'sleep' ? rand(600, 1400) : rand(3000, 8000); if (Math.random() < .14) m.nextBlink = 170; } }
      else if (m.blink > 0) m.blink = Math.max(KAI.state === 'sleep' ? .5 : 0, m.blink - dt * (closeSpeed + 2));
      saccT += dt; if (saccT > rand(.7, 2.4)) { saccT = 0; m.sacc = rand(-2.2, 2.2); }
      m.sacc = lerp(m.sacc, 0, dt * 3);
      microT += dt; if (microT > rand(3, 7)) { microT = 0; m.microT = rand(-1, 1); setTimeout(() => (m.microT = 0), 500); }
      // idle head drift + presence wandering
      m.presenceAt += dt;
      if (KAI.state === 'idle') {
        m.tiltT = Math.sin(m.breath * .2) * .02;
        if (m.presenceAt > 7) { m.presenceAt = 0; bus.emit('gaze', ['up', 'camera', 'camera'][Math.floor(rand(0, 3))]);
          setTimeout(() => KAI.state === 'idle' && bus.emit('gaze', 'camera'), 1700); }
      }
    } else { m.blink = 0; m.jaw = 0; }

    resolveGaze(dt, still);

    // advance particles
    for (const p of chest) { if (!still) { p.t += dt * p.sp; if (p.t > 1) { p.t = 0; p.a = rand(-1, 1); } } }
    for (let i = flows.length - 1; i >= 0; i--) { flows[i].t += dt * flows[i].sp; if (flows[i].t >= 1) flows.splice(i, 1); }
    for (let i = 0; i < 8; i++) m.haloLit[i] = Math.max(0, m.haloLit[i] - dt * .55);

    // ---- render ----
    ctx.clearRect(0, 0, W, H);
    ctx.save(); ctx.scale(DPR, DPR);
    const cw = W / DPR, ch = H / DPR, cx = cw / 2;
    const bob = still ? 0 : Math.sin(m.breath) * ch * .004 + m.shoulder * .3;
    const cy = ch * .4 + bob;
    const s = cw * .19;
    // presence glow
    const pg = ctx.createRadialGradient(cx, cy, s * .2, cx, cy, s * 2.2);
    pg.addColorStop(0, rgba(m.accent, .1 * (.5 + m.illum) * m.bright)); pg.addColorStop(1, rgba(m.accent, 0));
    ctx.fillStyle = pg; ctx.fillRect(0, 0, cw, ch);
    drawHalo(cx, cy - s * .1, s * 1.75);
    drawWings(cx, cy, s);
    drawFigure(cx, cy, s);
    ctx.restore();

    raf = requestAnimationFrame(frame);
  }
  raf = requestAnimationFrame(frame);

  return {
    litHalo: sec => bus.emit('halo', sec),
    lookAt: (x, y) => bus.emit('gaze:point', { x, y }),
    destroy: () => cancelAnimationFrame(raf),
  };
}
