// ============================================================================
// Panel: tools (workspace) — KAI CAPABILITIES grid.
// A responsive grid of capability cards. Each card lights ON when its matching
// agent (data:agents) is active/watching, else STANDBY. Live, no polling.
// Security: all data-derived values go through textContent only.
// ============================================================================

// Static catalog — name, the agent id it maps to, and a one-line description.
// (These strings are literals, never snapshot data.)
const CAPS = [
  { name: 'Research',       id: 'research', desc: 'Scans sources and synthesizes findings' },
  { name: 'Code',           id: 'code',     desc: 'Writes, refactors and reviews code' },
  { name: 'Browser',        id: 'browser',  desc: 'Navigates and extracts from the live web' },
  { name: 'Memory',         id: 'memory',   desc: 'Recalls episodic and semantic knowledge' },
  { name: 'Security',       id: 'security', desc: 'Audits posture and triages threats' },
  { name: 'Market',         id: 'market',   desc: 'Tracks equities, crypto and sentiment' },
  { name: 'Infrastructure', id: 'infra',    desc: 'Monitors services, nodes and health' },
  { name: 'Deploy',         id: 'deploy',   desc: 'Ships releases through the pipeline' },
];

const isLive = a => a && (a.status === 'active' || a.status === 'watching');

export function create(ctx) {
  const { bus, data, el } = ctx;
  const off = [];

  el.replaceChildren();

  const grid = document.createElement('div');
  grid.style.display = 'grid';
  grid.style.gridTemplateColumns = 'repeat(auto-fill,minmax(150px,1fr))';
  grid.style.gap = 'var(--s3)';
  el.appendChild(grid);

  function render(snapshot) {
    const list = Array.isArray(snapshot) ? snapshot : [];
    const byId = {};
    for (const a of list) if (a && a.id != null) byId[a.id] = a;

    grid.replaceChildren();
    for (const cap of CAPS) {
      const on = isLive(byId[cap.id]);

      const card = document.createElement('div');
      card.className = on ? 'panel live' : 'panel';

      const head = document.createElement('div');
      head.style.display = 'flex';
      head.style.alignItems = 'center';
      head.style.gap = 'var(--s2)';
      head.style.marginBottom = 'var(--s2)';

      const title = document.createElement('span');
      title.className = 'lbl';
      title.textContent = cap.name;

      const chip = document.createElement('span');
      chip.className = on ? 'chip on' : 'chip';
      chip.style.marginLeft = 'auto';
      const dot = document.createElement('span');
      dot.className = 'd';
      const clabel = document.createElement('span');
      clabel.textContent = on ? 'active' : 'standby';
      chip.append(dot, clabel);

      head.append(title, chip);

      const desc = document.createElement('div');
      desc.className = 'dim';
      desc.style.fontSize = 'var(--fs-sm)';
      desc.textContent = cap.desc;

      card.append(head, desc);
      grid.appendChild(card);
    }
  }

  render(data.get('agents'));                       // paint immediately
  off.push(bus.on('data:agents', render));          // stay live

  return { destroy() { off.forEach(f => f && f()); } };
}
