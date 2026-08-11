// ============================================================================
// KAI NEXUS — Panel: infrastructure (workspace, Increment 16)
// The INFRASTRUCTURE brain: a live node graph. Nodes placed by x,y fractions on
// a 640x520 viewBox, colored by status (ok/warn/crit). Edges from data.edges.
// Small "packets" periodically travel a random edge to suggest live traffic.
// Live via data:infra. Security: every data-derived value goes through
// textContent / SVG textContent — never innerHTML.
// ============================================================================

import { dataFreshness } from '../shared/dataFreshness.js';

const NS = 'http://www.w3.org/2000/svg';
const W = 640, H = 520;

// status -> state token (no invented colors)
function statusColor(s) {
  return s === 'crit' ? 'var(--crit)' : s === 'warn' ? 'var(--warn)' : 'var(--ok)';
}
const clamp01 = n => (typeof n === 'number' && isFinite(n)) ? Math.max(0, Math.min(1, n)) : 0;
const svgEl = t => document.createElementNS(NS, t);

export function create(ctx) {
  const { bus, data, el } = ctx;
  const off = [];
  el.replaceChildren();

  // ---- header + legend (static strings only) ----
  const head = document.createElement('div');
  head.style.display = 'flex';
  head.style.alignItems = 'center';
  head.style.gap = 'var(--s3)';
  head.style.marginBottom = 'var(--s4)';

  const title = document.createElement('span');
  title.className = 'lbl';
  title.textContent = 'Infrastructure Graph';

  const legend = document.createElement('div');
  legend.style.marginLeft = 'auto';
  legend.style.display = 'flex';
  legend.style.gap = 'var(--s3)';
  [['var(--ok)', 'Healthy'], ['var(--warn)', 'Degraded'], ['var(--crit)', 'Down']]
    .forEach(([c, label]) => {
      const item = document.createElement('span');
      item.style.display = 'inline-flex';
      item.style.alignItems = 'center';
      item.style.gap = 'var(--s1)';
      item.style.fontSize = 'var(--fs-micro)';
      item.style.textTransform = 'uppercase';
      item.style.letterSpacing = 'var(--tracking-wide)';
      item.style.color = 'var(--ink-mute)';
      const dot = document.createElement('span');
      dot.style.width = '8px';
      dot.style.height = '8px';
      dot.style.borderRadius = '50%';
      dot.style.background = c;
      const txt = document.createElement('span');
      txt.textContent = label;
      item.append(dot, txt);
      legend.appendChild(item);
    });

  head.append(title, dataFreshness.badge('infra'), legend);
  el.appendChild(head);

  // ---- svg canvas ----
  const svg = svgEl('svg');
  svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
  svg.setAttribute('preserveAspectRatio', 'xMidYMid meet');
  svg.style.width = '100%';
  svg.style.height = 'auto';
  svg.style.display = 'block';
  const gEdges = svgEl('g');
  const gPackets = svgEl('g');
  const gNodes = svgEl('g');
  svg.append(gEdges, gPackets, gNodes);  // nodes paint on top of edges/packets
  el.appendChild(svg);

  // empty-state hint
  const empty = document.createElement('div');
  empty.className = 'dim';
  empty.style.textAlign = 'center';
  empty.style.padding = 'var(--s4)';
  empty.style.fontSize = 'var(--fs-sm)';
  empty.textContent = 'Awaiting infrastructure telemetry…';
  el.appendChild(empty);

  // shared state
  let pos = {};        // id -> {x, y}
  let edgeList = [];   // [[aId, bId], ...] with both endpoints present

  function render(snap) {
    const nodes = (snap && Array.isArray(snap.nodes)) ? snap.nodes : [];
    const edges = (snap && Array.isArray(snap.edges)) ? snap.edges : [];

    pos = {};
    gEdges.replaceChildren();
    gNodes.replaceChildren();

    empty.style.display = nodes.length ? 'none' : 'block';

    // record positions first (edges/nodes both need them)
    for (const n of nodes) {
      if (!n || n.id == null) continue;
      pos[String(n.id)] = { x: clamp01(n.x) * W, y: clamp01(n.y) * H };
    }

    // edges
    edgeList = [];
    for (const e of edges) {
      if (!Array.isArray(e) || e.length < 2) continue;
      const a = pos[String(e[0])], b = pos[String(e[1])];
      if (!a || !b) continue;
      edgeList.push([String(e[0]), String(e[1])]);
      const line = svgEl('line');
      line.setAttribute('x1', a.x); line.setAttribute('y1', a.y);
      line.setAttribute('x2', b.x); line.setAttribute('y2', b.y);
      line.style.stroke = 'var(--stroke)';
      line.style.strokeWidth = '1.5';
      line.style.strokeOpacity = '0.85';
      gEdges.appendChild(line);
    }

    // nodes (glow ring + core + label)
    for (const n of nodes) {
      if (!n || n.id == null) continue;
      const p = pos[String(n.id)];
      const col = statusColor(n.status);

      const glow = svgEl('circle');
      glow.setAttribute('cx', p.x); glow.setAttribute('cy', p.y);
      glow.setAttribute('r', '16');
      glow.style.fill = col;
      glow.style.opacity = '0.16';

      const core = svgEl('circle');
      core.setAttribute('cx', p.x); core.setAttribute('cy', p.y);
      core.setAttribute('r', '8');
      core.style.fill = col;
      core.style.stroke = 'var(--bg-void)';
      core.style.strokeWidth = '2';

      const label = svgEl('text');
      label.setAttribute('x', p.x);
      label.setAttribute('y', p.y + 26);
      label.setAttribute('text-anchor', 'middle');
      label.style.fill = 'var(--ink-dim)';
      label.style.fontFamily = 'var(--mono)';
      label.style.fontSize = '12px';
      label.textContent = String(n.id);   // data -> textContent (safe)

      gNodes.append(glow, core, label);
    }
  }

  // ---- live packets along random edges ----
  const packets = [];
  let raf = 0, last = 0, sinceSpawn = 0;

  function spawn() {
    if (!edgeList.length) return;
    if (packets.length > 6) return;
    const [aId, bId] = edgeList[(Math.random() * edgeList.length) | 0];
    const a = pos[aId], b = pos[bId];
    if (!a || !b) return;
    const dist = Math.hypot(b.x - a.x, b.y - a.y);
    const dot = svgEl('circle');
    dot.setAttribute('r', '4');
    dot.style.fill = 'var(--accent)';        // state-themed
    dot.style.opacity = '0';
    gPackets.appendChild(dot);
    packets.push({
      x1: a.x, y1: a.y, x2: b.x, y2: b.y,
      t: 0, dur: Math.max(650, dist / 0.13), el: dot,
    });
  }

  function frame(now) {
    const dt = Math.min(now - last, 60); last = now;
    sinceSpawn += dt;
    if (sinceSpawn > 1100) { sinceSpawn = 0; spawn(); }
    for (let i = packets.length - 1; i >= 0; i--) {
      const p = packets[i];
      p.t += dt;
      const f = p.t / p.dur;
      if (f >= 1) { p.el.remove(); packets.splice(i, 1); continue; }
      p.el.setAttribute('cx', p.x1 + (p.x2 - p.x1) * f);
      p.el.setAttribute('cy', p.y1 + (p.y2 - p.y1) * f);
      p.el.style.opacity = String(Math.sin(f * Math.PI));  // fade in then out
    }
    raf = requestAnimationFrame(frame);
  }

  render(data.get('infra'));                 // paint immediately
  off.push(bus.on('data:infra', render));    // stay live

  // Respect reduced-motion: static graph, no traffic animation.
  const still = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!still) {
    last = performance.now();
    raf = requestAnimationFrame(frame);
    off.push(() => cancelAnimationFrame(raf));
  }

  return { destroy() { off.forEach(f => f && f()); } };
}
