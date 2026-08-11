// ============================================================================
// Panel: world (workspace) — WORLD PULSE (Increment 12)
// Stylized inline-SVG globe (circle + graticule). Each data:world event is
// projected onto the disk (equirect-ish) and plotted as a colored dot by type.
// Clicking a dot shows KAI's one-line read (the event label) in the caption.
//
// SECURITY: every snapshot value (label, type) reaches the DOM through
// textContent / SVG <title>.textContent only — innerHTML is never fed data.
// The globe frame is built once; only the dots group is rebuilt per snapshot,
// so a click-selected caption survives until its dot leaves the feed.
//
// SEAM: projection is a stylized equirect placeholder — real geodata / basemap
// wiring is a future increment.
// ============================================================================

const NS = 'http://www.w3.org/2000/svg';

// viewBox geometry
const CX = 320, CY = 180, R = 150;

// type → dot color (design tokens only; --accent is state-themed)
const TYPE_COLOR = {
  news:   'var(--accent)',
  market: 'var(--ok)',
  cyber:  'var(--crit)',
  infra:  'var(--warn)',
};
// type → avatar halo channel (living-system feedback on select)
const TYPE_HALO = {
  news:   'research',
  market: 'market',
  cyber:  'security',
  infra:  'infra',
};

const num = v => (typeof v === 'number' && isFinite(v)) ? v : Number(v) || 0;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function svg(name, attrs) {
  const e = document.createElementNS(NS, name);
  if (attrs) for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}

// equirect-ish projection onto the disk (spec: x=cx+(lng/180)*R, y=cy-(lat/90)*R*0.9)
function project(lng, lat) {
  return {
    x: CX + (clamp(num(lng), -180, 180) / 180) * R,
    y: CY - (clamp(num(lat), -90, 90) / 90) * R * 0.9,
  };
}

export function create(ctx) {
  const { bus, data, el } = ctx;
  const avatar = ctx.avatar, sound = ctx.sound;
  const off = [];

  const wrap = document.createElement('div');
  wrap.style.display = 'flex';
  wrap.style.flexDirection = 'column';
  wrap.style.gap = 'var(--s4)';

  // — header: kicker + live count —
  const head = document.createElement('div');
  head.style.display = 'flex';
  head.style.alignItems = 'baseline';
  head.append(Object.assign(document.createElement('div'), {
    className: 'dim',
    textContent: 'WORLD PULSE',
    style: 'font-size:var(--fs-micro);letter-spacing:var(--tracking-wide);text-transform:uppercase',
  }));
  const count = document.createElement('span');
  count.className = 'spark mono dim';
  count.style.marginLeft = 'auto';
  count.textContent = '0 PULSES';
  head.append(count);
  wrap.append(head);

  // — globe SVG —
  const board = svg('svg', {
    viewBox: '0 0 640 360',
    width: '100%',
    role: 'img',
    'aria-label': 'World pulse globe',
  });
  board.style.display = 'block';
  board.style.height = 'auto';
  board.style.maxWidth = '100%';

  // disk fill
  board.append(svg('circle', { cx: CX, cy: CY, r: R, fill: 'var(--bg-raised)' }));

  // graticule: meridian + parallel ellipses (subtle, state-themed)
  const grat = svg('g', { fill: 'none', stroke: 'var(--accent)', 'stroke-width': '1' });
  for (const f of [0.42, 0.78]) {
    grat.append(svg('ellipse', { cx: CX, cy: CY, rx: R * f, ry: R, 'stroke-opacity': '0.18' })); // meridians
    grat.append(svg('ellipse', { cx: CX, cy: CY, rx: R, ry: R * f, 'stroke-opacity': '0.18' })); // parallels
  }
  // equator + central meridian (a touch stronger)
  grat.append(svg('line', { x1: CX - R, y1: CY, x2: CX + R, y2: CY, 'stroke-opacity': '0.3' }));
  grat.append(svg('line', { x1: CX, y1: CY - R, x2: CX, y2: CY + R, 'stroke-opacity': '0.3' }));
  board.append(grat);

  // outer rim
  board.append(svg('circle', {
    cx: CX, cy: CY, r: R, fill: 'none',
    stroke: 'var(--accent)', 'stroke-opacity': '0.55', 'stroke-width': '1.5',
  }));

  // dots live in their own group, rebuilt per snapshot
  const dots = svg('g', {});
  board.append(dots);
  wrap.append(board);

  // — legend (static labels; safe) —
  const legend = document.createElement('div');
  legend.style.display = 'flex';
  legend.style.flexWrap = 'wrap';
  legend.style.gap = 'var(--s3)';
  for (const [type, color] of Object.entries(TYPE_COLOR)) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    const d = document.createElement('span');
    d.className = 'd';
    d.style.background = color;
    chip.append(d, Object.assign(document.createElement('span'), { textContent: type }));
    legend.append(chip);
  }
  wrap.append(legend);

  // — caption: KAI's read on the selected pulse —
  const cap = document.createElement('div');
  cap.style.minHeight = '2.4em';
  cap.style.padding = 'var(--s3) var(--s4)';
  cap.style.borderRadius = 'var(--r-md)';
  cap.style.background = 'var(--bg-raised)';
  cap.style.borderLeft = '3px solid var(--stroke)';
  const capKick = document.createElement('div');
  capKick.className = 'dim';
  capKick.style.cssText = 'font-size:var(--fs-micro);letter-spacing:var(--tracking-wide);text-transform:uppercase;margin-bottom:var(--s1)';
  capKick.textContent = 'KAI reads';
  const capText = document.createElement('div');
  capText.className = 'dim';
  capText.textContent = 'Select a pulse to read KAI’s take on it.';
  cap.append(capKick, capText);
  wrap.append(cap);

  // — seam note —
  wrap.append(Object.assign(document.createElement('div'), {
    className: 'dim mono',
    textContent: 'SEAM: real geodata basemap pending',
    style: 'font-size:var(--fs-tiny);opacity:.7',
  }));

  el.replaceChildren(wrap);

  // selection state
  let selected = null;

  function select(node, ev) {
    if (selected && selected !== node) {
      selected.querySelector('.pulse-core').setAttribute('r', '4.5');
      selected.querySelector('.pulse-glow').setAttribute('r', '9');
      selected.querySelector('.pulse-glow').setAttribute('fill-opacity', '0.18');
    }
    selected = node;
    const color = TYPE_COLOR[ev.type] || 'var(--ink-dim)';
    node.querySelector('.pulse-core').setAttribute('r', '6');
    node.querySelector('.pulse-glow').setAttribute('r', '12');
    node.querySelector('.pulse-glow').setAttribute('fill-opacity', '0.32');

    cap.style.borderLeftColor = color;
    capText.classList.remove('dim');
    capText.textContent = ev.label || '(no read available)';

    if (sound && sound.cue) sound.cue('tick');
    if (avatar && avatar.litHalo && TYPE_HALO[ev.type]) avatar.litHalo(TYPE_HALO[ev.type]);
  }

  function render(list) {
    const events = Array.isArray(list) ? list : [];
    selected = null;
    while (dots.firstChild) dots.removeChild(dots.firstChild);

    for (const ev of events) {
      if (!ev) continue;
      const p = project(ev.lng, ev.lat);
      const color = TYPE_COLOR[ev.type] || 'var(--ink-dim)';

      const g = svg('g', {});
      g.style.cursor = 'pointer';

      const glow = svg('circle', {
        class: 'pulse-glow', cx: p.x, cy: p.y, r: 9,
        fill: color, 'fill-opacity': '0.18',
      });
      const core = svg('circle', {
        class: 'pulse-core', cx: p.x, cy: p.y, r: 4.5,
        fill: color, stroke: 'var(--bg-void)', 'stroke-width': '1',
      });

      // native hover tooltip — textContent keeps data out of markup
      const title = svg('title');
      title.textContent = ev.label || '';
      g.append(title, glow, core);

      const onClick = () => select(g, ev);
      g.addEventListener('click', onClick);
      off.push(() => g.removeEventListener('click', onClick));

      dots.append(g);
    }

    count.textContent = events.length + (events.length === 1 ? ' PULSE' : ' PULSES');
  }

  render(data.get('world'));                 // paint immediately
  off.push(bus.on('data:world', render));    // stay live

  return { destroy() { off.forEach(f => f && f()); } };
}
