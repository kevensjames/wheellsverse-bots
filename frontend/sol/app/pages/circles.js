// SOL member app — pages/circles.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── Circles (savings groups) ──────────────────────────────────────────────────
// TEMPORARY test-data display filter. The /groups API has no is_test/environment
// field yet, so we hide internal load/smoke-test circles from the MEMBER view by
// name prefix. Records are NEVER deleted or mutated; admins still see everything
// in the admin app, and the count is logged for diagnostics.
// TODO(backend): add an explicit is_test (or environment) field to the group
// model and filter server-side, then delete this heuristic.
// Conservative: matches the internal camelCase generators ("LoadTest …",
// "Smoketest …") but NOT space-separated user text like "Load Test Fund", to
// avoid hiding a legitimate circle a member happened to name that way.
const CIRCLE_TEST_RE = /^\s*(loadtest|smoketest)\b/i;
function isTestCircle(g) { return CIRCLE_TEST_RE.test((g && g.name) || ''); }

const CIRCLES_MINE = ['FORMING', 'ACTIVE', 'COLLECTING', 'SETTLING', 'FAILED'];
const CIRCLES_ARCHIVED = ['COMPLETED', 'CANCELLED'];
const CIRCLE_PAGE = 12;
const CIRCLE_PRIO = { FORMING: 0, ACTIVE: 1, COLLECTING: 1, SETTLING: 1, FAILED: 2, COMPLETED: 3, CANCELLED: 4 };
let circles = { all: [], tab: 'mine', q: '', status: 'all', role: 'all', sort: 'action', limit: CIRCLE_PAGE, testHidden: 0 };

function circleRole(g) { return (me && g.created_by === me.id) ? 'owner' : 'member'; }
function statusGroup(s) { return ['ACTIVE', 'COLLECTING', 'SETTLING'].includes(s) ? 'active' : (s || '').toLowerCase(); }
function circleStatusMeta(s) {
  switch (s) {
    case 'ACTIVE': case 'COLLECTING': case 'SETTLING': return { cls: 'active', label: 'Active' };
    case 'FORMING': return { cls: 'forming', label: 'Forming' };
    case 'COMPLETED': return { cls: 'completed', label: 'Completed' };
    case 'FAILED': return { cls: 'failed', label: 'Failed' };
    case 'CANCELLED': return { cls: 'cancelled', label: 'Cancelled' };
    default: return { cls: 'pending', label: s ? esc(s) : 'Pending' };
  }
}
function circleProgress(g) { const f = g.member_count || 0, m = g.max_members || 0; return m ? Math.min(100, Math.round(f / m * 100)) : 0; }
function circleNextDateStr(g) {
  if (!['ACTIVE', 'COLLECTING', 'SETTLING'].includes(g.status)) return null;
  if (g.payout_day_of_month == null) return null;  // no date rather than "Invalid Date"
  try {
    const d = _nextDayOfMonth(new Date(), g.payout_day_of_month);
    if (isNaN(d.getTime())) return null;
    return fmtDate(d, { month: 'short', day: 'numeric' });
  } catch { return null; }
}
function circleAvatars(g) {
  const total = g.member_count || 0, n = Math.min(total, 4);
  let dots = ''; for (let i = 0; i < n; i++) dots += '<span class="ava" aria-hidden="true"></span>';
  const extra = total - n;
  return `<span class="ava-stack">${dots}${extra > 0 ? `<span class="ava ava--more" aria-hidden="true">+${extra}</span>` : ''}<span class="sr-only">${total} members</span></span>`;
}

function circleCardV2(g) {
  const sm = circleStatusMeta(g.status), role = circleRole(g), nextDate = circleNextDateStr(g), pct = circleProgress(g);
  const priv = g.is_private ? ' <span title="Private" aria-label="Private">🔒</span>' : '';
  let action = '';
  if (g.status === 'FORMING' && role === 'owner' && g.invite_code) action = `<button type="button" class="btn btn-ghost btn--sm" onclick="showGroup('${g.id}')">Invite</button>`;
  else if (['ACTIVE', 'COLLECTING', 'SETTLING'].includes(g.status)) action = `<button type="button" class="btn btn-ghost btn--sm" onclick="showGroup('${g.id}')">Timeline</button>`;
  return `<article class="circle-card">
    <div class="circle-card__top">
      <h3 class="circle-card__name">${esc(g.name)}${priv}</h3>
      <span class="status status--${sm.cls}">${sm.label}</span>
    </div>
    <div class="circle-card__role">${role === 'owner' ? 'Owner' : 'Member'}</div>
    <div class="circle-card__figs">
      <div><span class="fig-label">Contribution</span><span class="fig-val tnum">${fmt$(g.contribution_cents)}</span></div>
      <div><span class="fig-label">Cadence</span><span class="fig-val">${g.payout_day_of_month ? 'Monthly · day ' + esc(g.payout_day_of_month) : 'Monthly'}</span></div>
      <div><span class="fig-label">Cycle</span><span class="fig-val tnum">${g.current_cycle_number != null ? esc(g.current_cycle_number) : '—'}</span></div>
    </div>
    <div class="circle-card__progress">
      <div class="pbar-row"><span>${esc(g.member_count || 0)} / ${esc(g.max_members || '—')} members</span><span class="tnum">${pct}%</span></div>
      <div class="pbar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100" aria-label="Slots filled"><div class="pbar__fill" style="width:${pct}%"></div></div>
    </div>
    <div class="circle-card__foot">
      <div class="circle-card__foot-l">${circleAvatars(g)}${nextDate ? `<span class="circle-card__next">Next ${nextDate}</span>` : (g.status === 'FORMING' ? '<span class="circle-card__next">Awaiting members</span>' : '')}</div>
      <div class="circle-card__acts">${action}<button type="button" class="btn btn-primary btn--sm" onclick="showGroup('${g.id}')">View</button></div>
    </div>
  </article>`;
}

function circleFailedRow(g) {
  return `<div class="attn-row">
    <div class="attn-row__info"><div class="attn-name">${esc(g.name)}</div><div class="attn-meta">Didn't complete · ${esc(g.member_count || 0)}/${esc(g.max_members || '—')} members · ${fmt$(g.contribution_cents)}</div></div>
    <div class="circle-card__acts"><span class="status status--failed">Failed</span><button type="button" class="btn btn-ghost btn--sm" onclick="showGroup('${g.id}')">View issue</button></div>
  </div>`;
}

function summaryCard(label, val, hint) { return `<div class="sum-card"><div class="sum-label">${label}</div><div class="sum-val tnum">${val}</div>${hint ? `<div class="sum-hint">${hint}</div>` : ''}</div>`; }
function renderCirclesSummary(all) {
  const el = document.getElementById('circlesSummary'); if (!el) return;
  const active = all.filter(g => ['ACTIVE', 'COLLECTING', 'SETTLING'].includes(g.status)).length;
  const forming = all.filter(g => g.status === 'FORMING').length;
  let nextC = '—';
  const soonest = all.filter(g => ['ACTIVE', 'COLLECTING', 'SETTLING'].includes(g.status) && g.payout_day_of_month != null)
    .map(g => { try { const d = _nextDayOfMonth(new Date(), g.payout_day_of_month); return isNaN(d.getTime()) ? null : d; } catch { return null; } })
    .filter(Boolean).sort((a, b) => a - b)[0];
  if (soonest) nextC = fmtDate(soonest, { month: 'short', day: 'numeric' });
  el.innerHTML = summaryCard('Active circles', active) + summaryCard('Forming circles', forming)
    + summaryCard('Next contribution', nextC) + summaryCard('Next payout', 'See circle', 'per-circle');
}

function updateCount(n) { const el = document.getElementById('circlesCount'); if (!el) return; el.textContent = n < 0 ? '' : (n === 0 ? 'No circles match' : (n + ' circle' + (n === 1 ? '' : 's'))); }

function sortCircles(list) {
  const byDate = g => { if (g.payout_day_of_month == null) return Infinity; try { const t = _nextDayOfMonth(new Date(), g.payout_day_of_month).getTime(); return isNaN(t) ? Infinity : t; } catch { return Infinity; } };
  const prio = g => (CIRCLE_PRIO[g.status] != null ? CIRCLE_PRIO[g.status] : 5);
  const s = list.slice();
  switch (circles.sort) {
    case 'newest': s.sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0)); break;
    case 'payout': s.sort((a, b) => byDate(a) - byDate(b)); break;
    case 'amount': s.sort((a, b) => (b.contribution_cents || 0) - (a.contribution_cents || 0)); break;
    case 'progress': s.sort((a, b) => circleProgress(b) - circleProgress(a)); break;
    default: s.sort((a, b) => prio(a) - prio(b) || byDate(a) - byDate(b));
  }
  return s;
}

function circleSkeletons() {
  return `<div class="circle-grid">${Array.from({ length: 6 }).map(() => `<div class="circle-card is-skeleton"><span class="sk sk-line" style="width:55%"></span><span class="sk sk-line" style="width:35%"></span><span class="sk sk-block"></span><span class="sk sk-line" style="width:70%"></span></div>`).join('')}</div>`;
}
function circlesEmpty() {
  if (circles.q || circles.status !== 'all' || circles.role !== 'all')
    return `<div class="empty"><p>No circles match your filters.</p><button type="button" class="btn btn-ghost btn--sm" onclick="circlesClearFilters()">Clear filters</button></div>`;
  if (circles.tab === 'archived') return `<div class="empty"><p>No archived circles yet.</p><div class="hint-muted">Completed and cancelled circles will appear here.</div></div>`;
  return `<div class="empty"><p>You're not in any circles yet.</p><div class="cluster" style="justify-content:center;margin-top:1rem"><button type="button" class="btn btn-primary" onclick="toggleCreateForm()">Create a circle</button><button type="button" class="btn btn-ghost" onclick="nav('discover')">Discover circles</button></div></div>`;
}
function circlesPanelCTA(title, body, btnLabel, btnAction) {
  return `<div class="panel-cta"><h3>${title}</h3><p class="sub">${body}</p><button type="button" class="btn btn-primary" onclick="${btnAction}">${btnLabel}</button></div>`;
}
function circlesToggleAttn(btn) { const open = btn.getAttribute('aria-expanded') === 'true'; btn.setAttribute('aria-expanded', open ? 'false' : 'true'); const b = document.getElementById('attn-body'); if (b) b.hidden = open; }
function circlesAttentionSection(failed) {
  return `<section class="attn"><button type="button" class="attn-head" aria-expanded="true" aria-controls="attn-body" onclick="circlesToggleAttn(this)">Needs attention (${failed.length})</button><div id="attn-body">${failed.map(circleFailedRow).join('')}</div></section>`;
}

function renderCircles() {
  const el = document.getElementById('groupList'); if (!el) return;
  renderCirclesSummary(circles.all);
  if (circles.tab === 'discover') { el.innerHTML = circlesPanelCTA('Discover circles', 'Browse public circles you can join.', 'Open Discover', "nav('discover')"); updateCount(-1); return; }
  if (circles.tab === 'invitations') { el.innerHTML = circlesPanelCTA('Have an invite code?', "Join a friend's private circle with the code they shared.", 'Join with invite code', 'toggleJoinByCode()'); updateCount(-1); return; }
  const wanted = circles.tab === 'archived' ? CIRCLES_ARCHIVED : CIRCLES_MINE;
  let list = circles.all.filter(g => wanted.includes(g.status));
  if (circles.status !== 'all') list = list.filter(g => statusGroup(g.status) === circles.status);
  if (circles.role !== 'all') list = list.filter(g => circleRole(g) === circles.role);
  if (circles.q) { const q = circles.q.toLowerCase(); list = list.filter(g => (g.name || '').toLowerCase().includes(q) || (g.invite_code || '').toLowerCase().includes(q)); }
  let failed = [];
  if (circles.tab === 'mine' && circles.status === 'all') { failed = list.filter(g => g.status === 'FAILED'); list = list.filter(g => g.status !== 'FAILED'); }
  list = sortCircles(list);
  const total = list.length + failed.length;
  updateCount(total);
  if (total === 0) { el.innerHTML = circlesEmpty(); return; }
  const shown = list.slice(0, circles.limit);
  let html = failed.length ? circlesAttentionSection(failed) : '';
  html += `<div class="circle-grid">${shown.map(circleCardV2).join('')}</div>`;
  if (list.length > circles.limit) html += `<div class="load-more"><button type="button" class="btn btn-ghost" onclick="circlesLoadMore()">Load more (${list.length - circles.limit})</button></div>`;
  el.innerHTML = html;
}

function circlesSetTab(tab) {
  circles.tab = tab; circles.limit = CIRCLE_PAGE;
  document.querySelectorAll('.circles-tabs .ctab').forEach(t => { const on = t.dataset.tab === tab; t.classList.toggle('active', on); t.setAttribute('aria-selected', on ? 'true' : 'false'); t.tabIndex = on ? 0 : -1; });
  const panel = document.getElementById('groupList'); if (panel) panel.setAttribute('aria-labelledby', 'ctab-' + tab);
  syncCirclesToURL(); renderCircles();
}
// Roving tabindex + arrow-key traversal for the WAI-ARIA tab pattern.
function circlesTabKey(e) {
  const tabs = Array.from(document.querySelectorAll('.circles-tabs .ctab'));
  const cur = tabs.findIndex(t => t.dataset.tab === circles.tab);
  let j = null;
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') j = (cur + 1) % tabs.length;
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') j = (cur - 1 + tabs.length) % tabs.length;
  else if (e.key === 'Home') j = 0;
  else if (e.key === 'End') j = tabs.length - 1;
  if (j == null) return;
  e.preventDefault(); circlesSetTab(tabs[j].dataset.tab); tabs[j].focus();
}
function circlesSetSearch(v) { circles.q = v; circles.limit = CIRCLE_PAGE; syncCirclesToURL(); renderCircles(); }
function circlesSetFilter() {
  circles.status = document.getElementById('circlesStatus').value;
  circles.role = document.getElementById('circlesRole').value;
  circles.sort = document.getElementById('circlesSort').value;
  circles.limit = CIRCLE_PAGE; syncCirclesToURL(); renderCircles();
}
function circlesClearFilters() {
  circles.q = ''; circles.status = 'all'; circles.role = 'all';
  const s = document.getElementById('circlesSearch'); if (s) s.value = '';
  const st = document.getElementById('circlesStatus'); if (st) st.value = 'all';
  const r = document.getElementById('circlesRole'); if (r) r.value = 'all';
  circles.limit = CIRCLE_PAGE; syncCirclesToURL(); renderCircles();
}
function circlesLoadMore() { circles.limit += CIRCLE_PAGE; renderCircles(); }

function syncCirclesToURL() {
  const p = new URLSearchParams();
  if (circles.tab !== 'mine') p.set('tab', circles.tab);
  if (circles.q) p.set('q', circles.q);
  if (circles.status !== 'all') p.set('status', circles.status);
  if (circles.role !== 'all') p.set('role', circles.role);
  if (circles.sort !== 'action') p.set('sort', circles.sort);
  const qs = p.toString();
  try { history.replaceState(null, '', location.pathname + (qs ? '?' + qs : '') + location.hash); } catch (e) {}
}
function syncCirclesFromURL() {
  const p = new URLSearchParams(location.search);
  circles.tab = p.get('tab') || 'mine'; circles.q = p.get('q') || ''; circles.status = p.get('status') || 'all';
  circles.role = p.get('role') || 'all'; circles.sort = p.get('sort') || 'action';
  const set = (id, v) => { const e = document.getElementById(id); if (e) e.value = v; };
  set('circlesSearch', circles.q); set('circlesStatus', circles.status); set('circlesRole', circles.role); set('circlesSort', circles.sort);
  document.querySelectorAll('.circles-tabs .ctab').forEach(t => { const on = t.dataset.tab === circles.tab; t.classList.toggle('active', on); t.setAttribute('aria-selected', on ? 'true' : 'false'); t.tabIndex = on ? 0 : -1; });
  const panel = document.getElementById('groupList'); if (panel) panel.setAttribute('aria-labelledby', 'ctab-' + circles.tab);
}

async function loadGroups() {
  const el = document.getElementById('groupList');
  el.innerHTML = circleSkeletons();
  try {
    const gs = await api('/groups');
    const clean = (gs || []).filter(g => !isTestCircle(g));
    circles.testHidden = (gs || []).length - clean.length;
    if (circles.testHidden) console.info('[circles] hid ' + circles.testHidden + ' internal test record(s) from the member view');
    circles.all = clean;
    syncCirclesFromURL();
    renderCircles();
  } catch (e) { if (_aborted(e)) return; 
    el.innerHTML = `<div class="empty"><p>Couldn't load your circles.</p><div class="hint-muted" style="margin-bottom:1rem">${esc(e.message || 'Network error')}</div><button type="button" class="btn btn-primary" onclick="loadGroups()">Retry</button></div>`;
  }
}

function toggleCreateForm() {
  const f = document.getElementById('createForm');
  f.style.display = f.style.display === 'none' ? '' : 'none';
  // Hide the other form if the user opens this one
  if (f.style.display === '') document.getElementById('joinByCodeForm').style.display = 'none';
}

function toggleJoinByCode() {
  const f = document.getElementById('joinByCodeForm');
  f.style.display = f.style.display === 'none' ? '' : 'none';
  if (f.style.display === '') document.getElementById('createForm').style.display = 'none';
}

async function createGroup() {
  const name = document.getElementById('cName').value.trim();
  if (!name) return;
  const maxMembers = parseInt(document.getElementById('cMax').value, 10) || 20;
  const payoutDay = parseInt(document.getElementById('cDay').value, 10) || 1;
  const isPrivate = document.getElementById('cPrivate').checked;
  const btn = document.getElementById('cBtn');
  const err = document.getElementById('cErr');
  err.style.display = 'none';
  btn.disabled = true; btn.textContent = 'Creating…';
  try {
    const g = await api('/groups', { method:'POST', body: JSON.stringify({
      name,
      max_members: maxMembers,
      payout_day_of_month: payoutDay,
      is_private: isPrivate,
    })});
    document.getElementById('cName').value = '';
    document.getElementById('cPrivate').checked = false;
    toggleCreateForm();
    loadGroups();
    // If the new circle is private (or any circle with an invite code), jump
    // the user straight to the detail page where the invite URL is shown
    // prominently so they can copy + share it with friends immediately.
    if (g && g.id) showGroup(g.id);
  } catch(e) { err.textContent = e.message; err.style.display = 'block'; }
  finally { btn.disabled = false; btn.textContent = 'Create'; }
}

async function joinByCode() {
  const code = document.getElementById('jbcCode').value.trim();
  if (!code) return;
  const btn = document.getElementById('jbcBtn');
  const err = document.getElementById('jbcErr');
  err.style.display = 'none';
  btn.disabled = true; btn.textContent = 'Joining…';
  try {
    const g = await api('/groups/join-by-code', { method:'POST', body: JSON.stringify({ invite_code: code }) });
    document.getElementById('jbcCode').value = '';
    toggleJoinByCode();
    if (g && g.id) showGroup(g.id);
  } catch(e) {
    let msg = e.message || 'Failed to join';
    if (/no active bank/i.test(msg)) {
      msg = 'You need a verified bank account first.';
    } else if (/kyc/i.test(msg)) {
      msg = 'Complete identity verification first.';
    } else if (/invite code|not found/i.test(msg)) {
      msg = 'Invite code is invalid or expired.';
    }
    err.textContent = msg; err.style.display = 'block';
  } finally { btn.disabled = false; btn.textContent = 'Join circle'; }
}
