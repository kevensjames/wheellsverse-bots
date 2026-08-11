// ============================================================================
// Panel: market (workspace) — MARKET INTELLIGENCE (Increment 13)
// Top row: S&P 500 · NASDAQ · BTC · ETH as KPIs, % colored green(>=0)/red(<0).
// Middle band: AI sentiment · Volatility · Risk regime as chips.
// "KAI WATCHING": data.watch symbols with live value (green/red) + tiny bar.
// Live via data:market.
//
// SECURITY: every snapshot value reaches the DOM through textContent only —
// innerHTML is never used. Rebuilds wholesale per snapshot; data:market fires
// rarely (once on start + on tick), so a full repaint is cheap.
// ============================================================================
export function create(ctx) {
  const { bus, data, avatar } = ctx;
  const el = ctx.el;
  const off = [];

  const num = v => { const n = Number(v); return Number.isFinite(n) ? n : null; };
  // Signed percent, e.g. +1.24% / -0.80%. Null → em dash.
  const fmtPct = v => { const n = num(v); return n === null ? '—' : (n >= 0 ? '+' : '') + n.toFixed(2) + '%'; };
  // Green >= 0, red < 0, dim when unknown.
  const colorFor = v => { const n = num(v); return n === null ? 'var(--ink-dim)' : n >= 0 ? 'var(--ok)' : 'var(--crit)'; };

  function caption(text) {
    return Object.assign(document.createElement('div'), {
      className: 'dim',
      textContent: text,
      style: 'font-size:var(--fs-micro);letter-spacing:var(--tracking-wide);text-transform:uppercase;margin-bottom:var(--s2)',
    });
  }

  // One KPI block: label over a large signed % coloured by sign.
  function kpi(label, value) {
    const k = document.createElement('div');
    k.className = 'kpi';
    k.append(Object.assign(document.createElement('span'), { className: 'lbl', textContent: label }));
    const big = document.createElement('span');
    big.className = 'big mono';
    big.style.color = colorFor(value);
    big.textContent = fmtPct(value);
    k.append(big);
    return k;
  }

  // A labelled chip: small caption above a pill carrying the value.
  function chipStat(label, value) {
    const wrap = document.createElement('div');
    wrap.style.display = 'flex';
    wrap.style.flexDirection = 'column';
    wrap.style.gap = 'var(--s1)';
    wrap.append(Object.assign(document.createElement('span'), {
      className: 'dim',
      textContent: label,
      style: 'font-size:var(--fs-micro);letter-spacing:var(--tracking-wide);text-transform:uppercase',
    }));
    const chip = document.createElement('span');
    chip.className = 'chip on';
    chip.style.alignSelf = 'flex-start';
    chip.append(Object.assign(document.createElement('span'), { className: 'd' }));
    chip.append(Object.assign(document.createElement('span'), {
      textContent: (value === undefined || value === null || value === '') ? '—' : String(value),
    }));
    wrap.append(chip);
    return wrap;
  }

  function render(m) {
    m = m || {};
    const root = document.createElement('div');
    root.style.display = 'flex';
    root.style.flexDirection = 'column';
    root.style.gap = 'var(--s5)';

    // — Top row: index / crypto KPIs —
    const kpis = document.createElement('div');
    kpis.style.display = 'grid';
    kpis.style.gridTemplateColumns = 'repeat(4, minmax(0, 1fr))';
    kpis.style.gap = 'var(--s4)';
    kpis.append(kpi('S&P 500', m.sp));
    kpis.append(kpi('NASDAQ', m.nasdaq));
    kpis.append(kpi('BTC', m.btc));
    kpis.append(kpi('ETH', m.eth));
    root.append(kpis);

    // — Middle band: sentiment · volatility · regime —
    const band = document.createElement('div');
    band.style.display = 'flex';
    band.style.flexWrap = 'wrap';
    band.style.gap = 'var(--s6)';
    band.append(chipStat('AI Sentiment', m.sentiment));
    band.append(chipStat('Volatility', m.volatility));
    band.append(chipStat('Risk Regime', m.regime));
    root.append(band);

    // — KAI WATCHING list —
    const watchWrap = document.createElement('div');
    watchWrap.append(caption('KAI Watching'));
    const watch = Array.isArray(m.watch) ? m.watch : [];
    if (watch.length) {
      // Normalise bar widths against the largest move so bars are comparable.
      const maxAbs = watch.reduce((mx, w) => Math.max(mx, Math.abs(num(w && w.v) || 0)), 0);
      for (const w of watch) {
        const v = w && w.v;
        const n = num(v);

        const row = document.createElement('div');
        row.className = 'row';

        const sym = document.createElement('span');
        sym.className = 'k mono';
        sym.style.minWidth = '64px';
        sym.textContent = (w && w.s) ? String(w.s) : '—';
        row.append(sym);

        // tiny inline bar (reuses .meter track)
        const track = document.createElement('div');
        track.className = 'meter';
        track.style.flex = '1';
        track.style.margin = '0 var(--s3)';
        const fill = document.createElement('i');
        const pct = (n === null || maxAbs === 0) ? 0 : Math.max(6, (Math.abs(n) / maxAbs) * 100);
        fill.style.width = pct + '%';
        fill.style.background = colorFor(v);
        track.append(fill);
        row.append(track);

        const val = document.createElement('span');
        val.className = 'v';
        val.style.color = colorFor(v);
        val.style.minWidth = '68px';
        val.textContent = fmtPct(v);
        row.append(val);

        watchWrap.append(row);
      }
    } else {
      watchWrap.append(Object.assign(document.createElement('div'), {
        className: 'dim', textContent: 'No symbols on watch',
      }));
    }
    root.append(watchWrap);

    el.replaceChildren(root);
  }

  render(data && data.get ? data.get('market') : null);   // paint immediately
  off.push(bus.on('data:market', m => {                    // stay live
    avatar && avatar.litHalo && avatar.litHalo('market');
    render(m);
  }));

  return { destroy() { off.forEach(f => f && f()); } };
}
