/* ============================================================================
   KAI NEXUS — Panel: activity (Increment 10)
   "LIVE ACTIVITY" global stream. Each bus 'data:activity:new' {time,text,sector}
   prepends a .feed .item (slide-in comes free from the .feed .item CSS rule),
   capped at 14 rows. No snapshot — starts empty.
   ========================================================================== */

const CAP = 14;

/* Per-sector dot color — all reference existing design tokens, no invented hex.
   Unknown sectors fall through to the CSS default (var(--accent)). */
const SECTOR = {
  reasoning: 'var(--st-think)',
  memory:    'var(--info)',
  tools:     'var(--accent)',
  agents:    'var(--st-exec)',
  research:  'var(--st-research)',
  security:  'var(--warn)',
  market:    'var(--cyan-400)',
  infra:     'var(--ok)',
};

export function create(ctx) {
  const { bus, data, el } = ctx;
  const off = [];

  const panel = document.createElement('div');
  panel.className = 'panel';
  panel.innerHTML =
    '<div class="panel-h"><span class="lbl">Live Activity</span>' +
    '<span class="spark mono">LIVE</span></div>';

  const feed = document.createElement('div');
  feed.className = 'feed';
  panel.appendChild(feed);
  el.appendChild(panel);

  function prepend(ev) {
    if (!ev) return;

    const item = document.createElement('div');
    item.className = 'item';

    const t = document.createElement('time');
    t.textContent = ev.time || '';

    const dot = document.createElement('span');
    dot.className = 'dotc';
    const c = SECTOR[ev.sector];
    if (c) dot.style.background = c;

    const text = document.createElement('span');
    text.textContent = ev.text || '';

    item.append(t, dot, text);
    feed.insertBefore(item, feed.firstChild);

    while (feed.children.length > CAP) feed.removeChild(feed.lastChild);
  }

  // first paint: render any seeded recent activity (oldest-first so newest ends on top)
  const seed = (data.get('activity') || []).slice().reverse();
  seed.forEach(prepend);

  off.push(bus.on('data:activity:new', prepend));

  return { destroy() { off.forEach(f => f && f()); } };
}
