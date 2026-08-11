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
const SKIN      = [172, 176, 196];   // synthetic skin midtone (cool, a touch of life)

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

  // ---- face + figure — adult synthetic human (§2) --------------------------
  // Head silhouette path (adult oval: cheekbones + tapered jaw + defined chin).
  function headPath(s) {
    ctx.beginPath();
    ctx.moveTo(0, -s * 1.0);
    ctx.bezierCurveTo(s * .6, -s * .98, s * .74, -s * .15, s * .7, s * .15);   // R forehead → cheekbone (widest)
    ctx.bezierCurveTo(s * .66, s * .5, s * .4, s * .82, s * .18, s * .98);      // R cheek → jaw
    ctx.quadraticCurveTo(0, s * 1.08, -s * .18, s * .98);                       // chin
    ctx.bezierCurveTo(-s * .4, s * .82, -s * .66, s * .5, -s * .7, s * .15);    // L jaw → cheek
    ctx.bezierCurveTo(-s * .74, -s * .15, -s * .6, -s * .98, 0, -s * 1.0);      // L cheekbone → forehead
    ctx.closePath();
  }

  function drawFigure(cx, cy, s) {
    const skin = mix(SKIN, m.accent, .05);
    const suit = [10, 14, 26];
    ctx.save(); ctx.translate(cx, cy); ctx.rotate(m.tilt);

    // — neural suit + broad shoulders (behind, dissolving below) ---------------
    const shW = s * 2.15;
    const shg = ctx.createLinearGradient(0, s * .8, 0, s * 2.3);
    shg.addColorStop(0, rgba(mix(suit, m.accent, .06), .95 * m.bright));
    shg.addColorStop(.7, rgba(suit, .8 * m.bright)); shg.addColorStop(1, rgba([6, 9, 20], 0));
    ctx.beginPath();
    ctx.moveTo(-s * .3, s * .78); ctx.quadraticCurveTo(-s * .9, s * .92, -shW * .5, s * 1.5);
    ctx.lineTo(-shW * .5, s * 2.3); ctx.lineTo(shW * .5, s * 2.3);
    ctx.lineTo(shW * .5, s * 1.5); ctx.quadraticCurveTo(s * .9, s * .92, s * .3, s * .78);
    ctx.closePath(); ctx.fillStyle = shg; ctx.fill();
    // circuit lines on the suit
    ctx.strokeStyle = rgba(m.accent, .16 * m.bright); ctx.lineWidth = 1;
    for (const d of [-1, 1]) { ctx.beginPath();
      ctx.moveTo(d * s * .3, s * 1.05); ctx.lineTo(d * s * .55, s * 1.3); ctx.lineTo(d * s * .55, s * 1.7);
      ctx.moveTo(d * s * .9, s * 1.2); ctx.lineTo(d * s * 1.2, s * 1.5); ctx.stroke(); }
    // high collar
    ctx.beginPath(); ctx.moveTo(-s * .32, s * .82); ctx.quadraticCurveTo(0, s * 1.02, s * .32, s * .82);
    ctx.lineTo(s * .4, s * 1.02); ctx.quadraticCurveTo(0, s * 1.2, -s * .4, s * 1.02); ctx.closePath();
    ctx.fillStyle = rgba(mix(suit, m.accent, .12), .9 * m.bright); ctx.fill();
    // illuminated chest core (pulses with breath + state)
    const corePulse = .6 + .4 * Math.sin(m.breath * 1.2) * (lowMotion() ? 0 : 1) + m.illum * .3;
    const coreY = s * 1.62, coreR = s * .12;
    const cg = ctx.createRadialGradient(0, coreY, 0, 0, coreY, coreR * 3.2);
    cg.addColorStop(0, rgba(mix(m.accent, ENERGY, .4), .8 * corePulse * m.bright)); cg.addColorStop(1, rgba(m.accent, 0));
    ctx.fillStyle = cg; ctx.beginPath(); ctx.arc(0, coreY, coreR * 3.2, 0, TAU); ctx.fill();
    ctx.save(); ctx.translate(0, coreY); ctx.rotate(Math.PI / 4);   // hex/diamond emblem
    ctx.beginPath(); ctx.rect(-coreR * .6, -coreR * .6, coreR * 1.2, coreR * 1.2);
    ctx.strokeStyle = rgba(ENERGY, .9 * corePulse); ctx.lineWidth = 2; ctx.stroke();
    ctx.fillStyle = rgba(mix(m.accent, ENERGY, .5), .5 * corePulse); ctx.fill(); ctx.restore();

    // — neck (with sterno hint) -----------------------------------------------
    const ng = ctx.createLinearGradient(0, s * .5, 0, s * 1);
    ng.addColorStop(0, rgba(mix(skin, [0, 0, 0], .42), m.bright)); ng.addColorStop(1, rgba(mix(skin, [0, 0, 0], .2), .9 * m.bright));
    ctx.beginPath(); ctx.moveTo(-s * .24, s * .6); ctx.lineTo(-s * .28, s * .92); ctx.lineTo(s * .28, s * .92); ctx.lineTo(s * .24, s * .6); ctx.closePath();
    ctx.fillStyle = ng; ctx.fill();
    ctx.beginPath(); ctx.ellipse(0, s * .62, s * .3, s * .1, 0, 0, TAU); ctx.fillStyle = 'rgba(6,10,22,.55)'; ctx.fill(); // jaw shadow

    // — head: shaded adult form ------------------------------------------------
    const hg = ctx.createRadialGradient(-s * .28, -s * .45, s * .1, s * .1, s * .1, s * 1.15);
    hg.addColorStop(0, rgba(mix(skin, [255, 255, 255], .14), m.bright));
    hg.addColorStop(.55, rgba(skin, m.bright));
    hg.addColorStop(1, rgba(mix(skin, [5, 9, 20], .6), m.bright));
    headPath(s); ctx.fillStyle = hg; ctx.fill();

    // sleek synthetic scalp/crown (so KAI reads adult, not a bald doll)
    const scg = ctx.createLinearGradient(0, -s * 1.3, 0, -s * .2);
    scg.addColorStop(0, rgba(mix(suit, m.accent, .1), .96 * m.bright)); scg.addColorStop(1, rgba([8, 12, 24], .9 * m.bright));
    ctx.beginPath();
    ctx.moveTo(-s * .7, -s * .1);
    ctx.bezierCurveTo(-s * .78, -s * .8, -s * .5, -s * 1.28, 0, -s * 1.26);
    ctx.bezierCurveTo(s * .5, -s * 1.28, s * .78, -s * .8, s * .7, -s * .1);
    ctx.bezierCurveTo(s * .5, -s * .62, s * .3, -s * .74, 0, -s * .74);        // hairline dip (forehead V)
    ctx.bezierCurveTo(-s * .3, -s * .74, -s * .5, -s * .62, -s * .7, -s * .1);
    ctx.closePath(); ctx.fillStyle = scg; ctx.fill();
    ctx.strokeStyle = rgba(m.accent, .14 * m.bright); ctx.lineWidth = 1;   // crown neural lines
    for (let i = -2; i <= 2; i++) { ctx.beginPath(); ctx.moveTo(i * s * .16, -s * .78);
      ctx.quadraticCurveTo(i * s * .22, -s * 1.05, i * s * .12, -s * 1.24); ctx.stroke(); }

    // volume: cheekbones, brow ridge, temples, jaw definition
    const hi = (x, y, rx, ry, a) => { const g = ctx.createRadialGradient(x, y, 0, x, y, rx);
      g.addColorStop(0, rgba(mix(skin, [255, 255, 255], .55), a * m.bright)); g.addColorStop(1, rgba(skin, 0));
      ctx.save(); ctx.beginPath(); ctx.ellipse(x, y, rx, ry, 0, 0, TAU); ctx.fillStyle = g; ctx.fill(); ctx.restore(); };
    hi(-s * .46, s * .08, s * .26, s * .2, .55); hi(s * .46, s * .08, s * .26, s * .2, .55);   // cheekbones (high)
    hi(0, -s * .4, s * .3, s * .16, .4);                                                        // brow ridge sheen
    const sh = (x, y, rx, ry, a) => { const g = ctx.createRadialGradient(x, y, 0, x, y, rx);
      g.addColorStop(0, rgba([5, 9, 20], a)); g.addColorStop(1, rgba([5, 9, 20], 0));
      ctx.save(); ctx.beginPath(); ctx.ellipse(x, y, rx, ry, 0, 0, TAU); ctx.fillStyle = g; ctx.fill(); ctx.restore(); };
    sh(-s * .62, s * .46, s * .12, s * .22, .2); sh(s * .62, s * .46, s * .12, s * .22, .2);     // jaw edge (subtle, lateral)
    sh(-s * .09, s * .16, s * .045, s * .16, .12); sh(s * .09, s * .16, s * .045, s * .16, .12); // nose sides (soft, close to bridge)
    sh(-s * .085, s * .3, s * .045, s * .05, .18); sh(s * .085, s * .3, s * .045, s * .05, .18); // nostrils (tiny)
    sh(0, s * .74, s * .11, s * .06, .16);                                                        // under-lip crease (light)

    // nose ridge highlight + tip
    ctx.strokeStyle = rgba(mix(skin, [255, 255, 255], .45), .4 * m.bright); ctx.lineWidth = s * .035; ctx.lineCap = 'round';
    ctx.beginPath(); ctx.moveTo(0, -s * .34); ctx.lineTo(-s * .015, s * .22); ctx.stroke();
    ctx.beginPath(); ctx.arc(0, s * .26, s * .05, 0, TAU); ctx.fillStyle = rgba(mix(skin, [255, 255, 255], .3), .3 * m.bright); ctx.fill();

    // lips (defined upper/lower + philtrum; jaw opens on speaking)
    const mo = m.jaw * s * .16;
    ctx.strokeStyle = rgba(mix(skin, [110, 66, 84], .4), .55 * m.bright); ctx.lineWidth = s * .02;
    ctx.beginPath(); ctx.moveTo(-s * .04, s * .4); ctx.lineTo(-s * .02, s * .5); ctx.stroke();   // philtrum
    ctx.strokeStyle = rgba(mix(skin, [120, 70, 90], .4), .6 * m.bright); ctx.lineWidth = s * .03;
    ctx.beginPath(); ctx.moveTo(-s * .17, s * .55); ctx.quadraticCurveTo(-s * .06, s * .5, 0, s * .53);
    ctx.quadraticCurveTo(s * .06, s * .5, s * .17, s * .55); ctx.stroke();                        // upper lip
    if (mo > .25) { ctx.fillStyle = 'rgba(16,8,14,.6)'; ctx.beginPath(); ctx.ellipse(0, s * .58 + mo * .4, s * .13, mo, 0, 0, TAU); ctx.fill(); }
    ctx.beginPath(); ctx.moveTo(-s * .15, s * .58 + mo); ctx.quadraticCurveTo(0, s * .66 + mo * 1.3, s * .15, s * .58 + mo); ctx.stroke(); // lower lip

    // brows + eyes on the adult vertical midline
    const er = s * .135, ey = -s * .02, ex = s * .3;
    drawBrow(-ex, ey - s * .21, er, -1); drawBrow(ex, ey - s * .21, er, 1);
    drawEye(-ex, ey, er, -1); drawEye(ex, ey, er, 1);

    // — cinematic key rim (cool light, upper-left) + env rim (active side) -----
    ctx.save(); headPath(s); ctx.clip();
    const keyRim = ctx.createLinearGradient(-s * .8, -s, -s * .2, 0);
    keyRim.addColorStop(0, rgba(mix(m.accent, [255, 255, 255], .3), .22 * m.bright)); keyRim.addColorStop(1, rgba(m.accent, 0));
    ctx.fillStyle = keyRim; ctx.fillRect(-s, -s * 1.1, s * 2, s * 2.2);
    if (m.env.on > .01) {
      const rl = ctx.createLinearGradient(-s * m.env.side, 0, s * m.env.side, 0);
      rl.addColorStop(0, rgba(m.env.c, 0)); rl.addColorStop(1, rgba(m.env.c, .32 * m.env.on));
      ctx.fillStyle = rl; ctx.fillRect(-s, -s * 1.1, s * 2, s * 2.2);
    }
    ctx.restore();
    ctx.restore();

    // chest/shoulder dissolve into the OS
    ctx.save(); ctx.translate(cx, cy);
    for (const p of chest) {
      const px = p.a * shW * .5 * (1 - p.t * .25), py = s * (1.9 + p.t * .7);
      ctx.beginPath(); ctx.arc(px, py, p.r * (1 - p.t) * DPR * .8, 0, TAU);
      ctx.fillStyle = rgba(mix(suit, m.accent, .5), (1 - p.t) * .5 * m.bright); ctx.fill();
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
