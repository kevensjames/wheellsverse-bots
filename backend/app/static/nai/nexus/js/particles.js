// ============================================================================
// Ambient environment (Increment 23) — slow floating data particles + grid.
// "Expensive, not busy": movement is slow, density adapts to quality, and the
// field tints toward --accent so it breathes with KAI's state.
// ============================================================================
import { bus } from './state.js';

export function mountParticles(canvas) {
  const ctx = canvas.getContext('2d');
  let W, H, DPR, accent = [63, 140, 255], parts = [];
  const off = () => document.documentElement.dataset.motion === 'off'
    || matchMedia('(prefers-reduced-motion: reduce)').matches;
  const low = () => document.documentElement.dataset.q === 'low';

  function accentColor() {
    const s = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();
    const m = s[0] === '#'
      ? [1, 3, 5].map(i => parseInt(s.length === 4 ? s[(i + 1) / 2] + s[(i + 1) / 2] : s.slice(i, i + 2), 16))
      : (s.match(/[\d.]+/g) || [63, 140, 255]).slice(0, 3).map(Number);
    accent = m;
  }
  bus.on('state', accentColor); accentColor();

  function seed() {
    const n = low() ? 34 : 90;
    parts = Array.from({ length: n }, () => ({
      x: Math.random(), y: Math.random(), z: Math.random() * .8 + .2,
      vx: (Math.random() - .5) * .00016, vy: (Math.random() - .5) * .00016, r: Math.random() * 1.6 + .4,
    }));
  }
  function resize() {
    DPR = Math.min(devicePixelRatio || 1, low() ? 1 : 2);
    W = canvas.width = innerWidth * DPR; H = canvas.height = innerHeight * DPR;
    seed();
  }
  addEventListener('resize', resize); resize();

  let raf;
  function frame() {
    ctx.clearRect(0, 0, W, H);
    const still = off();
    // depth-of-field vignette
    const g = ctx.createRadialGradient(W / 2, H * .42, 0, W / 2, H * .42, Math.max(W, H) * .7);
    g.addColorStop(0, `rgba(${accent[0]},${accent[1]},${accent[2]},0.05)`); g.addColorStop(1, 'rgba(4,6,13,0)');
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

    for (const p of parts) {
      if (!still) { p.x += p.vx; p.y += p.vy; if (p.x < 0 || p.x > 1) p.vx *= -1; if (p.y < 0 || p.y > 1) p.vy *= -1; }
      const x = p.x * W, y = p.y * H;
      ctx.beginPath(); ctx.arc(x, y, p.r * p.z * DPR, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(${accent[0]},${accent[1]},${accent[2]},${0.06 + p.z * 0.16})`; ctx.fill();
    }
    raf = requestAnimationFrame(frame);
  }
  frame();
  return { destroy: () => cancelAnimationFrame(raf) };
}
