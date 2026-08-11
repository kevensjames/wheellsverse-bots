// ============================================================================
// Panel: mission (workspace) — MISSION CONTROL (Increment 17)
// Big mission name · large progress meter with % · "KAI currently → …" ·
// agent status list · warn-colored Blocker callout. Live via data:mission.
//
// SECURITY: all snapshot values reach the DOM through textContent only.
// innerHTML is never used. Rebuilds wholesale on each snapshot — data:mission
// fires rarely (once on start + on mission change), so a full repaint is cheap.
// ============================================================================
export function create(ctx) {
  const { bus, data, el } = ctx;
  const off = [];

  const clampPct = v => Math.max(0, Math.min(100, Number(v) || 0));

  // status → chip. COMPLETE=ok / ACTIVE=accent / WAITING=dim (per spec).
  function chipFor(status) {
    const c = document.createElement('span');
    c.className = 'chip';
    c.append(Object.assign(document.createElement('span'), { className: 'd' }));
    c.append(Object.assign(document.createElement('span'), { textContent: String(status ?? '—') }));
    const s = String(status ?? '').toUpperCase();
    if (s === 'ACTIVE') c.classList.add('on');                                 // accent-themed
    else if (s === 'COMPLETE') { c.style.color = 'var(--ok)'; c.style.borderColor = 'var(--ok)'; }
    else c.classList.add('dim');                                               // WAITING / unknown
    return c;
  }

  function render(m) {
    m = m || {};
    const wrap = document.createElement('div');
    wrap.style.display = 'flex';
    wrap.style.flexDirection = 'column';
    wrap.style.gap = 'var(--s5)';

    // — header: kicker + big mission name —
    const head = document.createElement('div');
    head.append(Object.assign(document.createElement('div'), {
      className: 'dim', textContent: 'ACTIVE MISSION',
      style: 'font-size:var(--fs-micro);letter-spacing:var(--tracking-wide);text-transform:uppercase',
    }));
    const name = document.createElement('div');
    name.className = 'big';
    name.style.marginTop = 'var(--s1)';
    name.textContent = m.name || 'Untitled mission';
    head.append(name);
    wrap.append(head);

    // — progress: label + big % over a large meter —
    const prog = document.createElement('div');
    const pct = clampPct(m.progress);
    const phead = document.createElement('div');
    phead.style.display = 'flex';
    phead.style.alignItems = 'baseline';
    phead.style.marginBottom = 'var(--s2)';
    phead.append(Object.assign(document.createElement('span'), {
      className: 'dim', textContent: 'PROGRESS',
      style: 'font-size:var(--fs-micro);letter-spacing:var(--tracking-wide);text-transform:uppercase',
    }));
    const pval = document.createElement('span');
    pval.className = 'big acc mono';
    pval.style.marginLeft = 'auto';
    pval.textContent = pct + '%';
    phead.append(pval);
    prog.append(phead);

    const meter = document.createElement('div');
    meter.className = 'meter';
    meter.style.height = '12px';                          // larger than the column default
    const fill = document.createElement('i');
    fill.style.width = pct + '%';
    meter.append(fill);
    prog.append(meter);
    wrap.append(prog);

    // — "KAI currently → {current}" —
    const cur = document.createElement('div');
    cur.style.fontSize = 'var(--fs-lg)';
    cur.append(Object.assign(document.createElement('span'), { className: 'dim', textContent: 'KAI currently → ' }));
    cur.append(Object.assign(document.createElement('span'), { className: 'acc', textContent: m.current || 'standing by' }));
    wrap.append(cur);

    // — agent status list —
    const agentsWrap = document.createElement('div');
    agentsWrap.append(Object.assign(document.createElement('div'), {
      className: 'dim', textContent: 'AGENTS',
      style: 'font-size:var(--fs-micro);letter-spacing:var(--tracking-wide);text-transform:uppercase;margin-bottom:var(--s2)',
    }));
    const agents = Array.isArray(m.agents) ? m.agents : [];
    if (agents.length) {
      for (const a of agents) {
        const row = document.createElement('div');
        row.className = 'row';
        row.append(Object.assign(document.createElement('span'), { className: 'k', textContent: (a && a.name) || 'Agent' }));
        const val = document.createElement('span');
        val.className = 'v';
        val.append(chipFor(a && a.status));
        row.append(val);
        agentsWrap.append(row);
      }
    } else {
      agentsWrap.append(Object.assign(document.createElement('div'), { className: 'dim', textContent: 'No agents assigned' }));
    }
    wrap.append(agentsWrap);

    // — blocker callout (warn) —
    if (m.blocker) {
      const cal = document.createElement('div');
      cal.className = 'warn';
      cal.style.borderLeft = '3px solid var(--warn)';
      cal.style.borderRadius = 'var(--r-md)';
      cal.style.padding = 'var(--s3) var(--s4)';
      cal.style.background = 'var(--bg-raised)';
      cal.append(Object.assign(document.createElement('span'), {
        textContent: 'Blocker: ',
        style: 'font-weight:700;letter-spacing:.04em',
      }));
      cal.append(document.createTextNode(String(m.blocker)));
      wrap.append(cal);
    }

    el.replaceChildren(wrap);
  }

  render(data.get('mission'));                 // paint immediately
  off.push(bus.on('data:mission', render));    // stay live

  return { destroy() { off.forEach(f => f && f()); } };
}
