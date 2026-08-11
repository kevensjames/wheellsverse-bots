// ============================================================================
// Panel: thinking — "LIVE THINKING" (Increment 8)
// Operational status of the current request, NOT hidden chain-of-thought.
// Renders data.get('thinking').steps as .steps; idle shows a calm line.
// Live channel: data:thinking. Reused full-size in the workspace.
// ============================================================================
export function create(ctx) {
  const { bus, data, el } = ctx;
  const off = [];

  const panel = document.createElement('div');
  panel.className = 'panel';

  const head = document.createElement('div');
  head.className = 'panel-h';
  const lbl = document.createElement('span');
  lbl.className = 'lbl';
  lbl.textContent = 'KAI · THINKING';
  const spark = document.createElement('span');
  spark.className = 'spark';
  head.append(lbl, spark);

  // request title (working) / calm status line (idle)
  const line = document.createElement('div');
  line.style.marginBottom = 'var(--s3)';

  const stepsEl = document.createElement('div');
  stepsEl.className = 'steps';

  panel.append(head, line, stepsEl);
  el.replaceChildren(panel);

  function render(s) {
    s = s || {};
    const steps = Array.isArray(s.steps) ? s.steps : [];
    const working = s.mode === 'working';

    // spark: IDLE at rest, else done/total progress
    if (working) {
      const done = steps.filter(x => x && x.state === 'done').length;
      spark.textContent = done + '/' + steps.length;
    } else {
      spark.textContent = 'IDLE';
    }

    // status / request line — data goes through textContent only (no innerHTML)
    if (working && s.title) {
      line.className = 'acc';
      line.textContent = s.title;
    } else if (working) {
      line.className = 'acc';
      line.textContent = 'Working…';
    } else {
      line.className = 'dim';
      line.textContent = 'Ready — no active operation';
    }

    // steps
    stepsEl.replaceChildren();
    for (const st of steps) {
      if (!st) continue;
      const row = document.createElement('div');
      row.className = 'step' + (st.state === 'done' ? ' done'
        : st.state === 'active' ? ' active' : '');
      const b = document.createElement('span');
      b.className = 'b';
      const t = document.createElement('span');
      t.textContent = st.label || '';
      row.append(b, t);
      stepsEl.append(row);
    }

    panel.classList.toggle('live', working);   // accent glow while active
  }

  render(data.get('thinking'));                // paint immediately from snapshot
  off.push(bus.on('data:thinking', render));   // then stay live

  return { destroy() { off.forEach(f => f && f()); } };
}
