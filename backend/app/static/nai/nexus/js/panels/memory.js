// ============================================================================
// KAI MEMORY — knowledge graph (Increment 14). Workspace panel.
// Radial SVG graph with KAI at the center and a static ring of memory nodes
// (SOL, Stripe, Dwolla, Money, Payments, User, Projects, Research). Clicking a
// node highlights it + its edges and shows a detail line. Four KPI blocks show
// live episodic/semantic/project/user counts from data.get('memory').
// Renders directly into `el` (already inside the workspace glass frame).
// ============================================================================
export function create(ctx) {
  const { data, bus, avatar, sound, el } = ctx;
  const off = [];
  const NS = 'http://www.w3.org/2000/svg';
  const svg = (t, attrs) => {
    const e = document.createElementNS(NS, t);
    if (attrs) for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  };
  const fmt = v => Number(v || 0).toLocaleString();

  // ---- static topology (viewBox 0 0 640 460) --------------------------------
  const NODES = [
    { id: 'KAI',      x: 320, y: 220, r: 42, type: 'Core',              detail: 'Central reasoning & memory core', center: true },
    { id: 'Research', x: 320, y: 60,  r: 30, type: 'Domain',            detail: 'Sources, findings & evidence' },
    { id: 'SOL',      x: 486, y: 106, r: 30, type: 'Project',           detail: 'SOLCIRCLE product & circles' },
    { id: 'Stripe',   x: 556, y: 220, r: 30, type: 'Payments Provider', detail: 'Card processing & subscriptions' },
    { id: 'Dwolla',   x: 486, y: 334, r: 30, type: 'Payments Provider', detail: 'ACH bank transfers' },
    { id: 'Payments', x: 320, y: 380, r: 30, type: 'Domain',            detail: 'Charges, payouts & ledgers' },
    { id: 'Money',    x: 154, y: 334, r: 30, type: 'Domain',            detail: 'Treasury, balances & flows' },
    { id: 'User',     x: 84,  y: 220, r: 30, type: 'Entity',            detail: 'People & accounts KAI serves' },
    { id: 'Projects', x: 154, y: 106, r: 30, type: 'Domain',            detail: 'Active initiatives & missions' },
  ];
  const byId = {};
  for (const n of NODES) byId[n.id] = n;
  const EDGES = [
    ['KAI', 'Research'], ['KAI', 'SOL'], ['KAI', 'Stripe'], ['KAI', 'Dwolla'],
    ['KAI', 'Payments'], ['KAI', 'Money'], ['KAI', 'User'], ['KAI', 'Projects'],
    ['SOL', 'Stripe'], ['SOL', 'Dwolla'], ['Money', 'Payments'],
    ['Payments', 'Stripe'], ['Payments', 'Dwolla'], ['User', 'Money'], ['Projects', 'SOL'],
  ];

  // ---- shell ----------------------------------------------------------------
  const root = document.createElement('div');
  root.style.display = 'flex';
  root.style.flexDirection = 'column';
  root.style.gap = 'var(--s5)';

  // KPI row (episodic / semantic / project / user)
  const kpis = document.createElement('div');
  kpis.style.display = 'grid';
  kpis.style.gridTemplateColumns = 'repeat(4, 1fr)';
  kpis.style.gap = 'var(--s4)';
  const kpiVals = {};
  for (const [key, label] of [['episodic', 'Episodic'], ['semantic', 'Semantic'], ['project', 'Project'], ['user', 'User']]) {
    const card = document.createElement('div');
    card.className = 'kpi';
    card.style.background = 'var(--bg-panel)';
    card.style.border = '1px solid var(--stroke)';
    card.style.borderRadius = 'var(--r-md)';
    card.style.padding = 'var(--s4)';
    const big = document.createElement('div');
    big.className = 'big acc';
    big.textContent = '—';
    const lbl = document.createElement('div');
    lbl.className = 'lbl';
    lbl.textContent = label;
    card.append(big, lbl);
    kpis.appendChild(card);
    kpiVals[key] = big;
  }

  // graph + detail
  const stage = document.createElement('div');
  stage.style.display = 'grid';
  stage.style.gridTemplateColumns = 'minmax(0, 1fr) 220px';
  stage.style.gap = 'var(--s5)';
  stage.style.alignItems = 'stretch';

  // --- graph card ---
  const gcard = document.createElement('div');
  gcard.style.background = 'var(--bg-panel)';
  gcard.style.border = '1px solid var(--stroke)';
  gcard.style.borderRadius = 'var(--r-lg)';
  gcard.style.padding = 'var(--s4)';
  gcard.style.minWidth = '0';

  const graph = svg('svg', { viewBox: '0 0 640 460', role: 'img', 'aria-label': 'KAI memory knowledge graph' });
  graph.style.width = '100%';
  graph.style.height = 'auto';
  graph.style.display = 'block';

  // center ambient glow + soft pulse (living system)
  const glow = svg('circle', { cx: 320, cy: 220, r: 78 });
  glow.style.fill = 'var(--accent-soft)';
  glow.style.opacity = '0.5';
  const pulse = svg('animate', { attributeName: 'r', values: '72;90;72', dur: '4.5s', repeatCount: 'indefinite' });
  glow.appendChild(pulse);
  graph.appendChild(glow);

  // edges (drawn under nodes)
  const edgeEls = EDGES.map(([a, b]) => {
    const A = byId[a], B = byId[b];
    const line = svg('line', { x1: A.x, y1: A.y, x2: B.x, y2: B.y });
    graph.appendChild(line);
    return { line, a, b };
  });

  // nodes
  const nodeEls = {};
  for (const n of NODES) {
    const g = svg('g');
    g.style.cursor = 'pointer';
    g.setAttribute('tabindex', '0');
    g.setAttribute('role', 'button');
    g.setAttribute('aria-label', n.id + ' — ' + n.type);
    const c = svg('circle', { cx: n.x, cy: n.y, r: n.r });
    const label = svg('text', { x: n.x, y: n.y + (n.center ? 5 : 4), 'text-anchor': 'middle' });
    label.style.fontFamily = 'var(--font)';
    label.style.fontSize = n.center ? '16px' : '12px';
    label.style.fontWeight = n.center ? '700' : '600';
    label.style.pointerEvents = 'none';
    label.textContent = n.id; // static topology labels; textContent keeps it safe
    g.append(c, label);
    graph.appendChild(g);
    const select = () => choose(n.id);
    g.addEventListener('click', select);
    g.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(); } });
    nodeEls[n.id] = { g, c, label };
  }
  gcard.appendChild(graph);

  // --- detail card ---
  const dcard = document.createElement('div');
  dcard.style.background = 'var(--bg-panel)';
  dcard.style.border = '1px solid var(--stroke)';
  dcard.style.borderRadius = 'var(--r-lg)';
  dcard.style.padding = 'var(--s4)';
  dcard.style.display = 'flex';
  dcard.style.flexDirection = 'column';
  dcard.style.gap = 'var(--s3)';

  const dHead = document.createElement('div');
  dHead.className = 'lbl';
  dHead.textContent = 'Selected Node';
  const dTitle = document.createElement('div');
  dTitle.className = 'big acc';
  dTitle.style.fontSize = 'var(--fs-xl)';
  dTitle.textContent = '—';
  const dType = document.createElement('span');
  dType.className = 'chip';
  dType.style.alignSelf = 'flex-start';
  dType.textContent = 'no selection';
  const dDetail = document.createElement('div');
  dDetail.className = 'dim';
  dDetail.style.fontSize = 'var(--fs-sm)';
  dDetail.style.lineHeight = '1.5';
  dDetail.textContent = 'Select a node in the graph to inspect what KAI remembers about it.';
  dcard.append(dHead, dTitle, dType, dDetail);

  stage.append(gcard, dcard);
  root.append(kpis, stage);
  el.replaceChildren(root);

  // ---- interaction ----------------------------------------------------------
  let selected = null;

  function paint() {
    for (const e of edgeEls) {
      const hot = selected && (e.a === selected || e.b === selected);
      e.line.style.stroke = hot ? 'var(--accent)' : 'var(--stroke)';
      e.line.style.strokeWidth = hot ? '2.4' : '1.4';
      e.line.style.opacity = selected ? (hot ? '0.95' : '0.28') : '0.6';
    }
    for (const n of NODES) {
      const { c, label } = nodeEls[n.id];
      const on = n.id === selected;
      const dimmed = selected && !on && !n.center;
      c.style.stroke = on ? 'var(--accent)' : (n.center ? 'var(--accent)' : 'var(--accent-soft)');
      c.style.strokeWidth = on || n.center ? '2.4' : '1.4';
      c.style.fill = on || n.center ? 'var(--accent-soft)' : 'var(--bg-raised)';
      c.style.filter = on || n.center ? 'drop-shadow(0 0 10px var(--accent-glow))' : 'none';
      c.style.opacity = dimmed ? '0.45' : '1';
      label.style.fill = on || n.center ? 'var(--accent-ink)' : 'var(--ink)';
      label.style.opacity = dimmed ? '0.5' : '1';
    }
  }

  function choose(id) {
    const n = byId[id];
    if (!n) return;
    selected = id;
    dTitle.textContent = n.id;
    dType.textContent = n.type;
    dType.classList.add('on');
    dDetail.textContent = n.detail;
    paint();
    if (sound) sound.cue('tick');
    if (avatar) avatar.litHalo('memory');
  }

  // ---- live KPIs ------------------------------------------------------------
  function renderKPIs(m) {
    m = m || {};
    kpiVals.episodic.textContent = fmt(m.episodic);
    kpiVals.semantic.textContent = fmt(m.semantic);
    kpiVals.project.textContent = fmt(m.project);
    kpiVals.user.textContent = fmt(m.user);
  }

  renderKPIs(data.get('memory'));
  paint();
  off.push(bus.on('data:memory', renderKPIs));

  return { destroy() { off.forEach(f => f && f()); } };
}
