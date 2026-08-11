// KAI NEXUS — "intelligence" panel (Increment 11)
// RIGHT-RAIL "LIVE INTELLIGENCE" — News Intelligence Center.
// One glass panel of clickable headlines; each reveals a KAI IMPACT ANALYSIS block.
// Live via the data:news channel. Column kind.
import { dataFreshness } from '../shared/dataFreshness.js';

// §6 provenance: item.verification → freshness badge level. A DEMO item must
// read clearly as sample data, so the badge lives on the always-visible
// provenance line, never inside the collapsible impact block.
const VERIF_BADGE = { 'DEMO': 'demo', 'VERIFIED': 'live', 'SINGLE SOURCE': 'cached', 'UNVERIFIED': 'stale' };

export function create(ctx) {
  const { bus, data, sound, avatar } = ctx;
  const el = ctx.el;
  const off = [];

  // — Panel shell ---------------------------------------------------------
  const panel = document.createElement('div');
  panel.className = 'panel';

  const head = document.createElement('div');
  head.className = 'panel-h';
  const lbl = document.createElement('span');
  lbl.className = 'lbl';
  lbl.textContent = 'LIVE INTELLIGENCE';
  const spark = document.createElement('span');
  spark.className = 'spark';
  head.appendChild(lbl);
  head.appendChild(spark);
  head.appendChild(dataFreshness.badge('news'));

  const list = document.createElement('div');

  panel.appendChild(head);
  panel.appendChild(list);
  el.appendChild(panel);

  // Expanded headlines survive re-render (keyed by title).
  const expanded = new Set();

  const clamp = n => Math.max(0, Math.min(100, Math.round(Number(n) || 0)));
  const impactClass = imp => {
    const u = String(imp || '').toUpperCase();
    if (u === 'HIGH') return 'crit';
    if (u === 'MED') return 'warn';
    return 'dim';
  };

  // Build one label/value row for the analysis block. Value goes in via
  // textContent only — never innerHTML — because it is snapshot data.
  function analysisRow(key, value, valueClass) {
    const row = document.createElement('div');
    row.className = 'row';
    const k = document.createElement('span');
    k.className = 'k';
    k.textContent = key;
    const v = document.createElement('span');
    v.className = valueClass ? 'v ' + valueClass : 'v';
    v.textContent = (value === undefined || value === null || value === '') ? '—' : String(value);
    row.appendChild(k);
    row.appendChild(v);
    return row;
  }

  // §6 provenance line: source · published · verification badge · N corroborations.
  // Always visible so a DEMO item never masquerades as a live feed.
  function provenanceLine(item) {
    const line = document.createElement('div');
    line.className = 'dim mono';
    line.style.display = 'flex';
    line.style.alignItems = 'center';
    line.style.flexWrap = 'wrap';
    line.style.gap = 'var(--s2)';
    line.style.fontSize = 'var(--fs-tiny)';
    line.style.padding = '0 0 var(--s3) var(--s5)';

    const addText = t => {
      const s = document.createElement('span');
      s.textContent = t;
      line.appendChild(s);
    };
    const addSep = () => {
      const s = document.createElement('span');
      s.textContent = '·';
      s.style.flex = 'none';
      line.appendChild(s);
    };

    addText(item && item.source ? String(item.source) : '—');
    addSep();
    addText(item && item.published ? String(item.published) : '—');
    addSep();
    const verif = String((item && item.verification) || '').toUpperCase();
    line.appendChild(dataFreshness.badge(VERIF_BADGE[verif] || 'demo'));

    const corr = Number(item && item.corroborations) || 0;
    if (corr > 0) {
      addSep();
      addText(corr + ' corroborating sources');
    }
    return line;
  }

  function render(items) {
    const news = Array.isArray(items) ? items : [];
    list.textContent = '';
    spark.textContent = news.length ? news.length + ' SIGNALS' : '';

    if (!news.length) {
      const empty = document.createElement('div');
      empty.className = 'dim';
      empty.style.fontSize = 'var(--fs-sm)';
      empty.style.padding = 'var(--s2) 0';
      empty.textContent = 'No intelligence signals';
      list.appendChild(empty);
      return;
    }

    news.forEach((item, i) => {
      const title = item && item.title ? String(item.title) : 'Untitled signal';
      const key = title + '#' + i;
      const rel = clamp(item && item.relevance);

      const wrap = document.createElement('div');
      wrap.style.borderBottom = '1px solid var(--stroke-soft)';

      // — Clickable headline row (button = free focus + a11y) --------------
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.setAttribute('aria-expanded', 'false');
      btn.style.display = 'flex';
      btn.style.alignItems = 'center';
      btn.style.gap = 'var(--s2)';
      btn.style.width = '100%';
      btn.style.textAlign = 'left';
      btn.style.padding = 'var(--s3) 0';

      const caret = document.createElement('span');
      caret.className = 'dim mono';
      caret.textContent = '▸';
      caret.style.flex = 'none';
      caret.style.fontSize = 'var(--fs-tiny)';
      caret.style.transition = 'transform var(--t-fast) var(--ease)';

      const chip = document.createElement('span');
      chip.className = 'chip';
      chip.textContent = item && item.category ? String(item.category) : 'GENERAL';
      chip.style.flex = 'none';

      const text = document.createElement('span');
      text.textContent = title;
      text.style.flex = '1';
      text.style.fontSize = 'var(--fs-sm)';
      text.style.color = 'var(--ink)';
      text.style.lineHeight = '1.35';

      const pct = document.createElement('span');
      pct.className = 'mono acc';
      pct.textContent = rel + '%';
      pct.style.flex = 'none';
      pct.style.fontSize = 'var(--fs-tiny)';

      btn.appendChild(caret);
      btn.appendChild(chip);
      btn.appendChild(text);
      btn.appendChild(pct);

      // — Collapsible KAI IMPACT ANALYSIS ---------------------------------
      const reveal = document.createElement('div');
      reveal.style.overflow = 'hidden';
      reveal.style.maxHeight = '0px';
      reveal.style.transition = 'max-height var(--t-med) var(--ease)';

      const inner = document.createElement('div');
      inner.style.padding = '0 0 var(--s3) var(--s5)';

      const cap = document.createElement('div');
      cap.className = 'acc';
      cap.textContent = 'KAI IMPACT ANALYSIS';
      cap.style.fontSize = 'var(--fs-micro)';
      cap.style.letterSpacing = 'var(--tracking-wide)';
      cap.style.textTransform = 'uppercase';
      cap.style.margin = 'var(--s1) 0 var(--s2)';

      inner.appendChild(cap);
      inner.appendChild(analysisRow('Relevance', rel + '%'));
      inner.appendChild(analysisRow('KAI impact', item && item.impact, impactClass(item && item.impact)));
      inner.appendChild(analysisRow('Infrastructure', item && item.infra));
      inner.appendChild(analysisRow('Action', item && item.action));
      reveal.appendChild(inner);

      const open = () => {
        reveal.style.maxHeight = reveal.scrollHeight + 'px';
        caret.style.transform = 'rotate(90deg)';
        btn.setAttribute('aria-expanded', 'true');
      };
      const close = () => {
        reveal.style.maxHeight = '0px';
        caret.style.transform = 'none';
        btn.setAttribute('aria-expanded', 'false');
      };

      btn.addEventListener('click', () => {
        if (expanded.has(key)) {
          expanded.delete(key);
          close();
        } else {
          expanded.add(key);
          open();
          sound && sound.cue && sound.cue('tick');
          avatar && avatar.litHalo && avatar.litHalo('research');
        }
      });

      // Restore prior expanded state across live re-renders.
      if (expanded.has(key)) {
        open();
        // maxHeight measured before layout can read 0; nudge to auto-fit.
        requestAnimationFrame(() => { if (expanded.has(key)) reveal.style.maxHeight = reveal.scrollHeight + 'px'; });
      }

      wrap.appendChild(btn);
      wrap.appendChild(provenanceLine(item));
      wrap.appendChild(reveal);
      list.appendChild(wrap);
    });
  }

  // Paint immediately from the current snapshot, then track live updates.
  render(data && data.get ? data.get('news') : null);
  off.push(bus.on('data:news', render));

  return { destroy() { off.forEach(f => f && f()); } };
}
