// ============================================================================
// Panel: agents — AGENT CONSTELLATION (Increment 9, workspace kind)
// Inline SVG star-map: KAI at the center, each agent on a ring by its `ang`.
// Faint edges KAI<->agent + a ring of agent<->agent links. Click a node to
// inspect it; 'agents:link' briefly flashes the line between two agents.
// Live via data:agents. All snapshot values reach the DOM through textContent
// only — never innerHTML — so agent tasks/names can't inject markup.
// ============================================================================
import { dataFreshness } from '../shared/dataFreshness.js';

export function create(ctx) {
  const { bus, data, sound, el } = ctx;
  const off = [];

  const NS = 'http://www.w3.org/2000/svg';
  const W = 600, H = 460, CX = 300, CY = 205, R = 150, AR = 19, KR = 30;

  const svgEl = (t, attrs) => {
    const e = document.createElementNS(NS, t);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  };
  const mmss = sec => {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    const m = Math.floor(sec / 60), s = sec % 60;
    return String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
  };
  const isOn = st => st === 'active' || st === 'watching';

  // ---- layout: two responsive columns (svg + detail), reflow when narrow ----
  const wrap = document.createElement('div');
  wrap.style.cssText = 'display:flex;flex-wrap:wrap;gap:var(--s5);align-items:flex-start';

  const graph = document.createElement('div');
  graph.style.cssText = 'flex:1 1 340px;min-width:0';

  const svg = svgEl('svg', { viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': 'Agent constellation' });
  svg.style.cssText = 'width:100%;height:auto;display:block;overflow:visible';
  graph.appendChild(svg);

  const side = document.createElement('div');
  side.style.cssText = 'flex:1 1 260px;min-width:0';
  const card = document.createElement('div');
  card.className = 'panel';
  const head = document.createElement('div');
  head.className = 'panel-h';
  const lbl = document.createElement('span');
  lbl.className = 'lbl';
  lbl.textContent = 'AGENT';
  const spark = document.createElement('span');
  spark.className = 'spark';
  head.append(lbl, spark, dataFreshness.badge('agents'));
  const cardBody = document.createElement('div');
  card.append(head, cardBody);
  side.append(card);

  wrap.append(graph, side);
  el.replaceChildren(wrap);

  // ---- constellation state ---------------------------------------------------
  const pos = new Map();      // id -> {x,y}
  const nodeEls = new Map();  // id -> {g, circle, label}
  let linkLine = null;
  let layoutKey = '';
  let current = [];
  let selectedId = null;
  let flashT = 0;

  const place = agents => {
    pos.clear();
    agents.forEach(a => {
      const ang = Number(a.ang) || 0;
      pos.set(a.id, { x: CX + R * Math.cos(ang), y: CY + R * Math.sin(ang) });
    });
  };

  function buildGraph(agents) {
    place(agents);
    svg.replaceChildren();
    nodeEls.clear();

    // faint KAI <-> agent spokes
    agents.forEach(a => {
      const p = pos.get(a.id);
      const ln = svgEl('line', { x1: CX, y1: CY, x2: p.x, y2: p.y, 'stroke-width': 1 });
      ln.style.stroke = 'var(--glass-stroke)';
      svg.appendChild(ln);
    });

    // a few agent <-> agent edges (ring neighbours)
    const n = agents.length;
    for (let i = 0; i < n && n > 2; i++) {
      const pa = pos.get(agents[i].id), pb = pos.get(agents[(i + 1) % n].id);
      const ln = svgEl('line', { x1: pa.x, y1: pa.y, x2: pb.x, y2: pb.y, 'stroke-width': 1 });
      ln.style.stroke = 'var(--stroke-soft)';
      svg.appendChild(ln);
    }

    // reusable flash line for agents:link (sits under the nodes)
    linkLine = svgEl('line', { x1: CX, y1: CY, x2: CX, y2: CY, 'stroke-width': 2.5 });
    linkLine.style.stroke = 'var(--accent)';
    linkLine.style.opacity = '0';
    linkLine.style.filter = 'drop-shadow(0 0 6px var(--accent-glow))';
    svg.appendChild(linkLine);

    // agent nodes
    agents.forEach(a => {
      const p = pos.get(a.id);
      const g = svgEl('g', { tabindex: '0', role: 'button', 'aria-label': `${a.name || a.id}, ${a.status || ''}` });
      g.style.cursor = 'pointer';
      const circle = svgEl('circle', { cx: p.x, cy: p.y, r: AR });
      circle.style.transition = 'stroke var(--t-med) var(--ease), fill var(--t-med) var(--ease)';
      const label = svgEl('text', { x: p.x, y: p.y + AR + 15, 'text-anchor': 'middle', 'font-size': '11.5' });
      label.style.fontFamily = 'var(--font)';
      label.textContent = a.name || a.id;
      g.append(circle, label);
      const sel = () => select(a.id);
      g.addEventListener('click', sel);
      g.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sel(); } });
      svg.appendChild(g);
      nodeEls.set(a.id, { g, circle, label });
    });

    // KAI core (drawn last → on top of the spokes)
    const core = svgEl('circle', { cx: CX, cy: CY, r: KR });
    core.style.fill = 'var(--accent-soft)';
    core.style.stroke = 'var(--accent)';
    core.style.strokeWidth = '2';
    core.style.filter = 'drop-shadow(0 0 16px var(--accent-glow))';
    const coreT = svgEl('text', { x: CX, y: CY + 5, 'text-anchor': 'middle', 'font-size': '14' });
    coreT.style.fontFamily = 'var(--mono)';
    coreT.style.fill = 'var(--accent-ink)';
    coreT.style.fontWeight = '700';
    coreT.style.letterSpacing = '.12em';
    coreT.textContent = 'KAI';
    svg.append(core, coreT);
  }

  function styleNodes(agents) {
    agents.forEach(a => {
      const refs = nodeEls.get(a.id);
      if (!refs) return;
      const on = isOn(a.status);
      const selected = a.id === selectedId;
      refs.circle.style.fill = on ? 'var(--accent-soft)' : 'var(--bg-raised)';
      refs.circle.style.stroke = selected ? 'var(--accent-ink)' : (on ? 'var(--accent)' : 'var(--ink-mute)');
      refs.circle.style.strokeWidth = selected ? '3' : '1.5';
      refs.circle.style.filter = selected ? 'drop-shadow(0 0 10px var(--accent-glow))' : 'none';
      refs.label.style.fill = selected ? 'var(--ink)' : (on ? 'var(--accent-ink)' : 'var(--ink-dim)');
    });
  }

  // ---- detail card -----------------------------------------------------------
  function mkRow(label, value, cls, wrapV) {
    const r = document.createElement('div');
    r.className = 'row';
    const k = document.createElement('span');
    k.className = 'k';
    k.textContent = label;
    const v = document.createElement('span');
    v.className = 'v' + (cls ? ' ' + cls : '');
    if (wrapV) { v.style.whiteSpace = 'normal'; v.style.textAlign = 'left'; v.style.maxWidth = '62%'; }
    v.textContent = value;
    r.append(k, v);
    return r;
  }

  function renderDetail() {
    const a = current.find(x => x.id === selectedId);
    cardBody.replaceChildren();
    if (!a) {
      lbl.textContent = 'AGENT';
      const hint = document.createElement('div');
      hint.className = 'dim';
      hint.style.fontSize = 'var(--fs-sm)';
      hint.textContent = 'Select a node to inspect an agent.';
      cardBody.append(hint);
      return;
    }
    lbl.textContent = 'AGENT · ' + (a.name || a.id);
    const on = isOn(a.status);
    cardBody.append(
      mkRow('Status', String(a.status || '—').toUpperCase(), on ? 'acc' : 'dim'),
      mkRow('Current task', a.task || '—', null, true),
      mkRow('Runtime', mmss(a.runtime), 'mono'),
      mkRow('Tools', String(a.tools ?? 0), 'mono'),
      mkRow('Findings', String(a.findings ?? 0), a.findings > 0 ? 'acc' : 'mono'),
      mkRow('Confidence', (Number(a.confidence) || 0) + '%', 'acc'),
    );
    const meter = document.createElement('div');
    meter.className = 'meter';
    meter.style.marginTop = 'var(--s2)';
    const i = document.createElement('i');
    i.style.width = Math.max(0, Math.min(100, Number(a.confidence) || 0)) + '%';
    meter.append(i);
    cardBody.append(meter);
  }

  function select(id) {
    selectedId = id;
    if (sound && sound.cue) sound.cue('tick');
    styleNodes(current);
    renderDetail();
  }

  // ---- link flash ------------------------------------------------------------
  function flash(pair) {
    if (!linkLine || !Array.isArray(pair)) return;
    const pa = pos.get(pair[0]), pb = pos.get(pair[1]);
    if (!pa || !pb) return;
    linkLine.setAttribute('x1', pa.x); linkLine.setAttribute('y1', pa.y);
    linkLine.setAttribute('x2', pb.x); linkLine.setAttribute('y2', pb.y);
    linkLine.style.transition = 'none';
    linkLine.style.opacity = '0.95';
    requestAnimationFrame(() => {
      if (!linkLine) return;
      linkLine.style.transition = 'opacity 700ms var(--ease-out)';
      linkLine.style.opacity = '0';
    });
  }

  // ---- live render -----------------------------------------------------------
  function render(agents) {
    current = Array.isArray(agents) ? agents : [];
    const key = current.map(a => a.id + ':' + a.ang).join('|');
    if (key !== layoutKey) { layoutKey = key; buildGraph(current); }
    if (selectedId && !current.some(a => a.id === selectedId)) selectedId = null;
    styleNodes(current);
    spark.textContent = current.filter(a => isOn(a.status)).length + ' active';
    renderDetail();
  }

  render(data.get('agents'));
  off.push(bus.on('data:agents', render));
  off.push(bus.on('agents:link', flash));

  return {
    destroy() {
      clearTimeout(flashT);
      off.forEach(f => f && f());
    },
  };
}
