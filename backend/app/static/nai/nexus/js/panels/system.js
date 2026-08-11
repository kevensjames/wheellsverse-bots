// ============================================================================
// Panel: system  (left rail "SYSTEM")
// Five stacked glass cards — Health · Security · Agents · Memory · Costs —
// all live off their own data channels. Pure createElement/textContent DOM:
// no snapshot value ever touches innerHTML.
// ============================================================================
import { dataFreshness } from '../shared/dataFreshness.js';

export function create(ctx) {
  const { bus, data, el } = ctx;
  const off = [];

  // ---- tiny DOM helpers -----------------------------------------------------
  const mk = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };
  const fmt = n => (Number.isFinite(Number(n)) ? Number(n).toLocaleString() : '—');
  const clampPct = v => Math.max(0, Math.min(100, Number(v) || 0));

  function panel(title, domain) {
    const p = mk('div', 'panel');
    const h = mk('div', 'panel-h');
    h.append(mk('span', 'lbl', title));
    const spark = mk('span', 'spark', '');
    h.append(spark);
    h.append(dataFreshness.badge(domain));
    p.append(h);
    return { p, spark };
  }
  function kpi(label) {
    const k = mk('div', 'kpi');
    k.append(mk('div', 'lbl', label));
    const b = mk('div', 'big', '—');
    k.append(b);
    return { k, b };
  }
  function meter() {
    const wrap = mk('div', 'meter');
    wrap.style.margin = '10px 0 4px';
    const i = mk('i');
    wrap.append(i);
    return { wrap, i };
  }
  function setMeter(m, pct, cls) {
    m.i.style.width = clampPct(pct) + '%';
    m.wrap.classList.remove('warn', 'crit');
    if (cls) m.wrap.classList.add(cls);
  }
  function row(label) {
    const r = mk('div', 'row');
    r.append(mk('span', 'k', label));
    const v = mk('span', 'v', '—');
    r.append(v);
    return { r, v };
  }

  // ---- (1) HEALTH -----------------------------------------------------------
  const H = panel('System · Health', 'system');
  const hKpi = kpi('Health');
  const hMeter = meter();
  const hCpu = row('CPU');
  const hMem = row('Memory');
  const hReq = row('Requests');
  H.p.append(hKpi.k, hMeter.wrap, hCpu.r, hMem.r, hReq.r);

  function renderSystem(s) {
    if (!s) return;
    const health = clampPct(s.health);
    hKpi.b.textContent = health + '%';
    setMeter(hMeter, health, health < 60 ? 'crit' : health < 80 ? 'warn' : '');
    hCpu.v.textContent = (s.cpu != null ? s.cpu : '—') + '%';
    hMem.v.textContent = (s.memPct != null ? s.memPct : '—') + '%';
    hReq.v.textContent = (s.reqs != null ? s.reqs : '—');
    H.spark.textContent = s.uptime != null ? String(s.uptime) : '';
  }

  // ---- (2) SECURITY ---------------------------------------------------------
  const S = panel('Security', 'security');
  const sKpi = kpi('Score');
  const sMeter = meter();
  const sSub = mk('div', 'dim');
  sSub.style.fontSize = 'var(--fs-tiny)';
  sSub.style.marginTop = '4px';
  S.p.append(sKpi.k, sMeter.wrap, sSub);

  function renderSecurity(s) {
    if (!s) return;
    const score = clampPct(s.score);
    sKpi.b.textContent = Number(s.score) || 0;
    const cls = (Number(s.critical) || 0) > 0 ? 'crit' : score < 75 ? 'warn' : '';
    setMeter(sMeter, score, cls);
    sSub.textContent = (s.high != null ? s.high : 0) + ' high · ' + (s.medium != null ? s.medium : 0) + ' medium';
    const crit = Number(s.critical) || 0;
    S.spark.textContent = crit > 0 ? crit + ' crit' : 'ok';
  }

  // ---- (3) AGENTS -----------------------------------------------------------
  const A = panel('Agents', 'agents');
  const aKpi = kpi('Active');
  const aList = mk('div');
  aList.style.marginTop = '6px';
  A.p.append(aKpi.k, aList);

  function renderAgents(list) {
    const arr = Array.isArray(list) ? list : [];
    const active = arr.filter(a => a && a.status && a.status !== 'idle').length;
    aKpi.b.textContent = active;
    A.spark.textContent = arr.length + ' total';
    aList.replaceChildren();
    for (const a of arr) {
      const r = mk('div', 'row');
      r.append(mk('span', 'k', a && a.name != null ? String(a.name) : '—'));
      const on = !!(a && a.status && a.status !== 'idle');
      const chip = mk('span', on ? 'chip on' : 'chip');
      chip.style.marginLeft = 'auto';
      chip.append(mk('span', 'd'));
      chip.append(mk('span', null, a && a.status ? String(a.status) : 'idle'));
      r.append(chip);
      aList.append(r);
    }
  }

  // ---- (4) MEMORY -----------------------------------------------------------
  const M = panel('Memory', 'memory');
  const mEp = row('Episodic');
  const mSe = row('Semantic');
  const mPr = row('Project');
  const mUs = row('User');
  M.p.append(mEp.r, mSe.r, mPr.r, mUs.r);

  function renderMemory(m) {
    if (!m) return;
    mEp.v.textContent = fmt(m.episodic);
    mSe.v.textContent = fmt(m.semantic);
    mPr.v.textContent = fmt(m.project);
    mUs.v.textContent = fmt(m.user);
    M.spark.textContent = fmt((Number(m.episodic) || 0) + (Number(m.semantic) || 0));
  }

  // ---- (5) COSTS ------------------------------------------------------------
  const C = panel('Costs', 'costs');
  const cKpi = kpi('Today');
  const cMeter = meter();
  const cMonth = row('Month');
  C.p.append(cKpi.k, cMeter.wrap, cMonth.r);

  function renderCosts(c) {
    if (!c) return;
    const today = Number(c.today) || 0;
    const cap = Number(c.cap) || 0;
    cKpi.b.textContent = '$' + today.toFixed(2);
    const util = cap > 0 ? (today / cap) * 100 : 0;
    setMeter(cMeter, util, util > 90 ? 'crit' : util > 75 ? 'warn' : '');
    cMonth.v.textContent = '$' + (Number(c.month) || 0).toFixed(2);
    C.spark.textContent = cap > 0 ? 'cap $' + cap : '';
  }

  // ---- mount + subscribe ----------------------------------------------------
  el.replaceChildren(H.p, S.p, A.p, M.p, C.p);

  off.push(bus.on('data:system', renderSystem));
  off.push(bus.on('data:security', renderSecurity));
  off.push(bus.on('data:agents', renderAgents));
  off.push(bus.on('data:memory', renderMemory));
  off.push(bus.on('data:costs', renderCosts));

  // paint immediately from the current snapshots
  renderSystem(data.get('system'));
  renderSecurity(data.get('security'));
  renderAgents(data.get('agents'));
  renderMemory(data.get('memory'));
  renderCosts(data.get('costs'));

  return { destroy() { off.forEach(f => f && f()); } };
}
