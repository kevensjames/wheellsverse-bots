// SOL member app — pages/goals.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── Goals ───────────────────────────────────────────────────────────────────────
// ═══ Savings goals center ═════════════════════════════════════════════════════
// Backend truth (app/models/goal.py): a Goal is PURELY A PLANNING AID — "it moves
// no money and has no bearing on circle membership or payouts". saved_cents is a
// user-entered tracked value (advanced manually via PATCH), NOT a ledger balance —
// so every amount is labelled "tracked"/"target", never "balance"/"funds held".
// GoalOut: id, type, name, target_cents(>=1), saved_cents(>=0), target_date|null,
// status(ACTIVE|ACHIEVED|ARCHIVED), progress_percent(server, 0-100), created/updated_at.
// Supported: create(POST), edit(PATCH name/target/date), update tracked progress
// (PATCH saved_cents), archive/restore(PATCH status), delete(DELETE). There is NO
// pause status and NO recommendations feed — neither is fabricated. Achievement
// auto-syncs on the backend (saved>=target), so there is no client-side complete.
const GOAL_TYPES = {
  EMERGENCY_FUND: { label:'Emergency fund', icon:'ic-score' },
  VACATION:       { label:'Vacation',       icon:'ic-goals' },
  WEDDING:        { label:'Wedding',        icon:'ic-goals' },
  BUSINESS:       { label:'Business',       icon:'ic-goals' },
  EDUCATION:      { label:'Education',      icon:'ic-goals' },
  VEHICLE:        { label:'Vehicle',        icon:'ic-goals' },
  HOME:           { label:'Home',           icon:'ic-goals' },
};
const GOAL_STATE = {
  ACTIVE:   { key:'ACTIVE',   label:'Active',             chip:'active' },
  ACHIEVED: { key:'ACHIEVED', label:'Achieved',           chip:'verified' },
  ARCHIVED: { key:'ARCHIVED', label:'Archived',           chip:'cancelled' },
  OVERDUE:  { key:'OVERDUE',  label:'Past target date',   chip:'overdue' },
  UNKNOWN:  { key:'UNKNOWN',  label:'Status unavailable', chip:'pending' },
};
const GOAL_TABS = [{ key:'active', label:'Active' }, { key:'achieved', label:'Achieved' }, { key:'archived', label:'Archived' }, { key:'all', label:'All' }];
const _goalUuid = (s) => typeof s === 'string' && /^[0-9a-f-]{8,}$/i.test(s);
function goalsAnnounce(msg) { const el = document.getElementById('goalsLiveStatus'); if (el) { el.textContent = ''; el.textContent = msg; } }
function dollarsToCents(v) { const n = parseFloat(String(v == null ? '' : v).replace(/[^0-9.]/g, '')); if (!Number.isFinite(n) || n < 0) return null; return Math.round(n * 100); }
function goalDate(d) { if (!d) return null; const x = new Date(String(d).length <= 10 ? d + 'T00:00:00' : d); return isNaN(x.getTime()) ? null : x; }
function _goalDateInput(d) { const m = String(d.getMonth() + 1).padStart(2, '0'), day = String(d.getDate()).padStart(2, '0'); return `${d.getFullYear()}-${m}-${day}`; }

function normalizeGoal(g) {
  if (!g || typeof g !== 'object' || Array.isArray(g)) return null;   // skip malformed — never fail the page
  const raw = String(g.status || '').toUpperCase();
  const backend = (raw === 'ACTIVE' || raw === 'ACHIEVED' || raw === 'ARCHIVED') ? raw : 'UNKNOWN';
  const target = Number.isFinite(g.target_cents) ? g.target_cents : null;
  const saved = Number.isFinite(g.saved_cents) ? g.saved_cents : null;
  const targetValid = target != null && target > 0;
  let pct = null;   // only meaningful with a valid target — never show a % while the body says "progress unavailable"
  if (targetValid && Number.isFinite(g.progress_percent)) pct = Math.max(0, Math.min(100, Math.round(g.progress_percent)));
  else if (targetValid && saved != null) pct = Math.max(0, Math.min(100, Math.round(saved * 100 / target)));   // guarded: target>0
  const td = goalDate(g.target_date);
  let display = GOAL_STATE[backend] || GOAL_STATE.UNKNOWN, overdue = false;
  if (backend === 'ACTIVE' && td) { const t = new Date(); t.setHours(0, 0, 0, 0); if (td < t) { display = GOAL_STATE.OVERDUE; overdue = true; } }
  return {
    id: _goalUuid(g.id) ? g.id : null,
    typeLabel: (g.type && GOAL_TYPES[g.type]) ? GOAL_TYPES[g.type].label : 'Goal',
    icon: (g.type && GOAL_TYPES[g.type]) ? GOAL_TYPES[g.type].icon : 'ic-goals',
    name: g.name || 'Goal', target, saved, pct, targetValid,
    overTarget: targetValid && saved != null && saved > target,
    targetDate: td, backend, display, overdue,
  };
}

let goalsState = { items: [], ok: false, tab: 'active' };

async function loadGoals(userInitiated) {
  const list = document.getElementById('goalList'); if (!list) return;
  list.innerHTML = goalsSkeleton();
  let ok = false, items = [];
  try { const r = await api('/goals'); if (Array.isArray(r)) { items = r.map(normalizeGoal).filter(Boolean); ok = true; } }
  catch (e) { ok = false; }
  goalsState.items = items; goalsState.ok = ok;
  renderGoalsSummary(); renderGoalsTabs(); renderGoalsHeadActions(); renderGoalsFeed();
  if (userInitiated) goalsAnnounce(ok ? 'Goals refreshed.' : 'Goals unavailable.');
}

function goalSumCard(label, val, planning) {
  return `<div class="sum-card"><div class="sum-label">${esc(label)}</div><div class="sum-val tnum">${esc(val)}</div>${planning ? '<div class="sum-hint">tracked planning value</div>' : ''}</div>`;
}
function renderGoalsSummary() {
  const el = document.getElementById('goalsSummary'); if (!el) return;
  if (!goalsState.ok) { el.innerHTML = ['Active goals', 'Total tracked', 'Total target', 'Achieved'].map(l => goalSumCard(l, 'Unavailable', false)).join(''); return; }
  const its = goalsState.items;
  const active = its.filter(g => g.backend === 'ACTIVE');
  const achieved = its.filter(g => g.backend === 'ACHIEVED').length;
  // All amounts share ONE semantic (a planning/tracked value), so summing is honest — labelled tracked, never a balance/portfolio.
  const totTracked = active.reduce((s, g) => s + (g.saved || 0), 0);
  const totTarget = active.reduce((s, g) => s + (g.target || 0), 0);
  el.innerHTML =
    goalSumCard('Active goals', String(active.length), false) +
    goalSumCard('Total tracked', fmt$(totTracked), true) +
    goalSumCard('Total target', fmt$(totTarget), true) +
    goalSumCard('Achieved', String(achieved), false);
}

function goalsFilter(g, tab) {
  if (tab === 'active') return g.backend === 'ACTIVE';
  if (tab === 'achieved') return g.backend === 'ACHIEVED';
  if (tab === 'archived') return g.backend === 'ARCHIVED';
  return true;
}
function renderGoalsTabs() {
  const el = document.getElementById('goalsTabs'); if (!el) return;
  el.innerHTML = GOAL_TABS.map(t => {
    const sel = t.key === goalsState.tab;
    const c = goalsState.ok ? goalsState.items.filter(g => goalsFilter(g, t.key)).length : 0;
    return `<button type="button" class="ctab${sel ? ' active' : ''}" role="tab" id="gtab-${t.key}" aria-controls="goalList" aria-selected="${sel}" tabindex="${sel ? '0' : '-1'}" data-gtab="${t.key}" onclick="goalsSetTab('${t.key}')">${esc(t.label)}${goalsState.ok ? ` <span class="notif-tabcount">${c}</span>` : ''}</button>`;
  }).join('');
  const p = document.getElementById('goalList'); if (p) p.setAttribute('aria-labelledby', `gtab-${goalsState.tab}`);
}
function goalsSetTab(tab) { goalsState.tab = tab; renderGoalsTabs(); renderGoalsFeed(); }
function goalsTabKey(e) {
  const keys = GOAL_TABS.map(t => t.key); let i = keys.indexOf(goalsState.tab);
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') i = (i + 1) % keys.length;
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') i = (i - 1 + keys.length) % keys.length;
  else if (e.key === 'Home') i = 0; else if (e.key === 'End') i = keys.length - 1; else return;
  e.preventDefault(); goalsSetTab(keys[i]); const t = document.getElementById(`gtab-${keys[i]}`); if (t) t.focus();
}

function renderGoalsHeadActions() {
  const el = document.getElementById('goalsHeadActions'); if (!el) return;
  el.innerHTML = `<button type="button" class="btn btn-primary" onclick="openGoalForm('create')">Create goal</button><button type="button" class="btn btn-ghost" onclick="nav('groups')">View circles</button>`;
}

// Planning-only pace estimate — clearly labelled, guarded against NaN/Infinity/div0.
function goalPace(g) {
  if (g.backend !== 'ACTIVE' || !g.targetDate || !g.targetValid || g.saved == null) return null;
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const days = Math.round((g.targetDate - today) / 86400000);
  if (!Number.isFinite(days) || days <= 0) return null;
  const remaining = g.target - g.saved;
  if (remaining <= 0) return null;
  const months = Math.max(1, Math.round(days / 30));
  const perMonth = Math.ceil(remaining / months / 100) * 100;   // cents, rounded up to the dollar
  if (!Number.isFinite(perMonth) || perMonth <= 0) return null;
  return { perMonth, dateStr: fmtDate(g.targetDate, { month: 'short', year: 'numeric' }) };
}

function goalCard(g) {
  const st = g.display;
  const id = g.id ? esc(g.id) : '';
  const pctKnown = g.pct != null;
  const barPct = pctKnown ? g.pct : 0;
  const savedStr = g.saved != null ? fmt$(g.saved) : '—';
  const targetStr = g.targetValid ? fmt$(g.target) : '—';
  const dateStr = g.targetDate ? fmtDate(g.targetDate) : null;
  const pace = goalPace(g);
  const pctLabel = pctKnown ? `${g.pct}%` : 'Progress unavailable';
  const nm = esc(g.name);
  let actions;
  if (g.backend === 'ARCHIVED') actions = (id ? `<button type="button" class="btn btn-ghost btn--sm" aria-label="Restore ${nm}" onclick="restoreGoal('${id}',event)">Restore</button><button type="button" class="btn btn-ghost btn--sm goal-del" aria-label="Delete ${nm}" onclick="openGoalConfirm('delete','${id}')">Delete</button>` : '');
  else if (g.backend === 'ACHIEVED') actions = (id ? `<button type="button" class="btn btn-ghost btn--sm" aria-label="Edit ${nm}" onclick="openGoalForm('edit','${id}')">Edit</button><button type="button" class="btn btn-ghost btn--sm" aria-label="Archive ${nm}" onclick="openGoalConfirm('archive','${id}')">Archive</button>` : '');
  else actions = (id ? `<button type="button" class="btn btn-ghost btn--sm" aria-label="Update progress for ${nm}" onclick="openGoalProgress('${id}')">Update progress</button><button type="button" class="btn btn-ghost btn--sm" aria-label="Edit ${nm}" onclick="openGoalForm('edit','${id}')">Edit</button><button type="button" class="btn btn-ghost btn--sm" aria-label="Archive ${nm}" onclick="openGoalConfirm('archive','${id}')">Archive</button>` : '');
  return `<li class="goal-card">
    <div class="goal-card__head">
      <span class="goal-card__ic" aria-hidden="true"><svg class="ic"><use href="#${g.icon}"/></svg></span>
      <div class="goal-card__id"><div class="goal-card__name">${esc(g.name)}</div><div class="goal-card__type">${esc(g.typeLabel)}</div></div>
      <span class="status status--${st.chip}">${esc(st.label)}</span>
    </div>
    <div class="goal-card__amounts"><span>${savedStr} <span class="goal-card__of">tracked of</span> ${targetStr} target</span><span class="goal-card__pct">${pctKnown ? esc(pctLabel) : ''}</span></div>
    ${g.targetValid ? `<div class="pbar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${barPct}" aria-label="${esc(g.name)} progress: ${esc(pctLabel)}, ${esc(savedStr)} tracked of ${esc(targetStr)} target"><div class="pbar__fill${g.backend === 'ACHIEVED' ? ' pbar__fill--done' : ''}" style="width:${barPct}%"></div></div>` : `<p class="hint-muted">Progress unavailable — no valid target set.</p>`}
    <div class="goal-card__meta">
      ${g.overTarget ? '<span class="goal-card__over">Reached target</span>' : ''}
      ${dateStr ? `<span class="${g.overdue ? 'goal-card__overdue' : 'goal-card__date'}">${g.overdue ? 'Was due' : 'Target'} ${esc(dateStr)}</span>` : ''}
    </div>
    ${pace ? `<details class="goal-pace"><summary><span class="goal-pace__lead">Estimate — about ${fmt$(pace.perMonth)}/month to reach ${esc(targetStr)} by ${esc(pace.dateStr)}</span></summary><p class="hint-muted">A rough estimate from your remaining amount and target date. It's a planning guide, not financial advice, and it doesn't move or collect any money.</p></details>` : ''}
    ${actions ? `<div class="goal-card__acts">${actions}</div>` : ''}
  </li>`;
}

function goalEmptyMsg(tab) {
  if (tab === 'active') return 'No active goals right now.';
  if (tab === 'achieved') return 'No achieved goals yet.';
  if (tab === 'archived') return 'No archived goals.';
  return 'No goals yet.';
}
function renderGoalsFeed() {
  const el = document.getElementById('goalList'); const cEl = document.getElementById('goalsCount'); if (!el) return;
  if (!goalsState.ok) {
    if (cEl) cEl.textContent = '';
    el.innerHTML = `<div class="notif-empty"><div class="notif-empty__title">Goals are temporarily unavailable</div><p class="hint-muted">We couldn't load your goals. Please try again.</p><button type="button" class="btn btn-ghost btn--sm" onclick="loadGoals(true)">Retry</button></div>`;
    return;
  }
  if (!goalsState.items.length) {
    if (cEl) cEl.textContent = '';
    el.innerHTML = `<div class="notif-empty"><div class="notif-empty__title">Create a goal to track progress toward a planned expense or milestone.</div><div class="goal-empty-acts"><button type="button" class="btn btn-primary btn--sm" onclick="openGoalForm('create')">Create goal</button><button type="button" class="btn btn-ghost btn--sm" onclick="nav('groups')">View circles</button></div></div>`;
    return;
  }
  const filtered = goalsState.items.filter(g => goalsFilter(g, goalsState.tab));
  if (cEl) cEl.textContent = `${filtered.length} ${filtered.length === 1 ? 'goal' : 'goals'}`;
  if (!filtered.length) { el.innerHTML = `<div class="notif-empty"><div class="notif-empty__title">${esc(goalEmptyMsg(goalsState.tab))}</div></div>`; return; }
  el.innerHTML = `<ul class="goal-grid">${filtered.map(goalCard).join('')}</ul>`;
}
function goalsSkeleton() { return `<ul class="goal-grid">${Array.from({ length: 3 }).map(() => `<li class="goal-card"><span class="sk sk-line" style="width:45%"></span><span class="sk sk-line" style="width:70%;margin-top:.5rem"></span><span class="sk sk-block" style="margin-top:.6rem;height:8px"></span></li>`).join('')}</ul>`; }

// ── Shared accessible dialog (focus trap, Escape, restore) ────────────────────
let _goalDlg = { id: null, trigger: null };
function openGoalDialog(dialogId, focusSel) {
  _goalDlg = { id: dialogId, trigger: document.activeElement };
  const d = document.getElementById(dialogId); if (!d) return;
  d.dataset.busy = '0'; d.classList.add('is-open');
  document.addEventListener('keydown', _goalTrapKey, true);
  setTimeout(() => { const f = (focusSel && d.querySelector(focusSel)) || d.querySelector('input,select,button'); if (f) f.focus(); }, 0);
}
function closeGoalDialog(dialogId, skipRestore) {
  const which = dialogId || _goalDlg.id;
  const d = document.getElementById(which); if (d) d.classList.remove('is-open');
  document.removeEventListener('keydown', _goalTrapKey, true);
  const t = _goalDlg.trigger; _goalDlg = { id: null, trigger: null };
  // On success we skip restore (loadGoals re-renders the trigger away); caller lands focus on #goalList.
  if (!skipRestore && t && typeof t.focus === 'function') { try { t.focus(); } catch (e) {} }
}
function goalLandFocus() { const lp = document.getElementById('goalList'); if (lp && lp.focus) { try { lp.focus(); } catch (e) {} } }
function _goalTrapKey(e) {
  const d = document.getElementById(_goalDlg.id); if (!d) return;
  if (e.key === 'Escape') { e.preventDefault(); if (d.dataset.busy === '1') return; closeGoalDialog(_goalDlg.id); return; }
  if (e.key === 'Tab') {
    const f = [...d.querySelectorAll('input,select,button,textarea')].filter(x => !x.disabled && x.offsetParent !== null);   // visible only (hidden gfType excluded in edit mode)
    if (!f.length) { e.preventDefault(); return; }
    const first = f[0], last = f[f.length - 1];
    if (!d.contains(document.activeElement)) { e.preventDefault(); first.focus(); return; }
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
}
function _goalSafeErr(ex, fallback) { const m = (ex && ex.message) ? String(ex.message) : ''; if (/already|exists/i.test(m)) return 'A goal like this already exists.'; return fallback; }

// ── Create / edit ─────────────────────────────────────────────────────────────
let _goalFormMode = 'create', _goalFormId = null, _goalFormBusy = false;
function openGoalForm(mode, id) {
  _goalFormMode = mode; _goalFormId = (mode === 'edit' && _goalUuid(id)) ? id : null;
  const title = document.getElementById('goalFormTitle'), submit = document.getElementById('goalFormSubmit');
  const typeF = document.getElementById('gfType'), nameF = document.getElementById('gfName'), targetF = document.getElementById('gfTarget'), dateF = document.getElementById('gfDate');
  const note = document.getElementById('gfTargetNote'), err = document.getElementById('goalFormErr');
  err.style.display = 'none'; note.style.display = 'none';
  const typeRow = typeF.closest('.field');
  if (mode === 'edit') {
    const g = goalsState.items.find(x => x.id === _goalFormId);
    title.textContent = 'Edit goal'; submit.textContent = 'Save changes';
    if (typeRow) typeRow.style.display = 'none';   // goal type isn't editable via PATCH
    if (g) {
      nameF.value = g.name; targetF.value = g.targetValid ? (g.target / 100) : ''; dateF.value = g.targetDate ? _goalDateInput(g.targetDate) : '';
      if (g.saved != null) { note.textContent = `Your tracked progress is ${fmt$(g.saved)}. If you set the target below that, the goal will show as reached.`; note.style.display = 'block'; }
    }
  } else {
    title.textContent = 'Create goal'; submit.textContent = 'Create goal';
    if (typeRow) typeRow.style.display = '';
    typeF.value = 'EMERGENCY_FUND'; nameF.value = ''; targetF.value = ''; dateF.value = '';
  }
  submit.disabled = false;
  openGoalDialog('goalFormDialog', '#gfName');
}
async function submitGoalForm(e) {
  if (e && e.preventDefault) e.preventDefault();
  if (_goalFormBusy) return;
  const nameF = document.getElementById('gfName'), targetF = document.getElementById('gfTarget'), dateF = document.getElementById('gfDate');
  const typeF = document.getElementById('gfType'), err = document.getElementById('goalFormErr'), submit = document.getElementById('goalFormSubmit'), dlg = document.getElementById('goalFormDialog');
  err.style.display = 'none';
  const name = (nameF.value || '').trim();
  const targetCents = dollarsToCents(targetF.value);
  if (!name) { err.textContent = 'Enter a name for this goal.'; err.style.display = 'block'; nameF.focus(); return; }
  if (targetCents == null || targetCents < 100) { err.textContent = 'Enter a target amount of at least $1.'; err.style.display = 'block'; targetF.focus(); return; }
  const dateV = dateF.value || null;
  if (dateV && !goalDate(dateV)) { err.textContent = 'Enter a valid target date.'; err.style.display = 'block'; dateF.focus(); return; }
  _goalFormBusy = true; dlg.dataset.busy = '1';
  submit.disabled = true; submit.textContent = _goalFormMode === 'edit' ? 'Saving…' : 'Creating…';
  try {
    if (_goalFormMode === 'edit') {
      await api(`/goals/${_goalFormId}`, { method: 'PATCH', body: JSON.stringify({ name, target_cents: targetCents, target_date: dateV }) });
      goalsAnnounce('Goal updated.');
    } else {
      const body = { type: typeF.value, name, target_cents: targetCents };
      if (dateV) body.target_date = dateV;
      await api('/goals', { method: 'POST', body: JSON.stringify(body) });
      goalsAnnounce('Goal created.');
    }
    dlg.dataset.busy = '0'; closeGoalDialog('goalFormDialog', true);
    await loadGoals();   // re-fetch backend truth — no optimistic create/update
    goalLandFocus();
  } catch (ex) {
    err.textContent = _goalSafeErr(ex, _goalFormMode === 'edit' ? "We couldn't save your changes. Please try again." : "We couldn't create your goal. Please try again.");
    err.style.display = 'block';
    submit.disabled = false; submit.textContent = _goalFormMode === 'edit' ? 'Save changes' : 'Create goal';
    dlg.dataset.busy = '0';
  } finally { _goalFormBusy = false; }
}

// ── Update tracked progress (a planning value — never moves money) ────────────
let _goalProgId = null, _goalProgBusy = false;
function openGoalProgress(id) {
  if (!_goalUuid(id)) return;
  _goalProgId = id;
  const g = goalsState.items.find(x => x.id === id);
  const amt = document.getElementById('gpAmount'), err = document.getElementById('goalProgErr'), submit = document.getElementById('goalProgSubmit');
  err.style.display = 'none'; submit.disabled = false; submit.textContent = 'Save progress';
  amt.value = (g && g.saved != null) ? (g.saved / 100) : '';
  openGoalDialog('goalProgressDialog', '#gpAmount');
}
async function submitGoalProgress(e) {
  if (e && e.preventDefault) e.preventDefault();
  if (_goalProgBusy || !_goalProgId) return;
  const amt = document.getElementById('gpAmount'), err = document.getElementById('goalProgErr'), submit = document.getElementById('goalProgSubmit'), dlg = document.getElementById('goalProgressDialog');
  err.style.display = 'none';
  const cents = dollarsToCents(amt.value);
  if (cents == null) { err.textContent = 'Enter a tracked amount of $0 or more.'; err.style.display = 'block'; amt.focus(); return; }
  _goalProgBusy = true; dlg.dataset.busy = '1';
  submit.disabled = true; submit.textContent = 'Saving…';
  try {
    await api(`/goals/${_goalProgId}`, { method: 'PATCH', body: JSON.stringify({ saved_cents: cents }) });
    goalsAnnounce('Tracked progress updated.');
    dlg.dataset.busy = '0'; closeGoalDialog('goalProgressDialog', true);
    await loadGoals();
    goalLandFocus();
  } catch (ex) {
    err.textContent = _goalSafeErr(ex, "We couldn't update your progress. Please try again.");
    err.style.display = 'block'; submit.disabled = false; submit.textContent = 'Save progress'; dlg.dataset.busy = '0';
  } finally { _goalProgBusy = false; }
}

// ── Archive / delete / restore ───────────────────────────────────────────────
let _goalConfirm = { action: null, id: null }, _goalConfirmBusy = false;
function openGoalConfirm(action, id) {
  if (!_goalUuid(id)) return;
  _goalConfirm = { action, id };
  const g = goalsState.items.find(x => x.id === id);
  const nameStr = g ? esc(g.name) : 'this goal';
  const title = document.getElementById('goalConfirmTitle'), body = document.getElementById('goalConfirmBody'), ok = document.getElementById('goalConfirmOk'), err = document.getElementById('goalConfirmErr');
  err.style.display = 'none'; ok.disabled = false;
  if (action === 'delete') {
    title.textContent = 'Delete goal?'; ok.textContent = 'Delete goal';
    body.innerHTML = `<p>Delete <strong>${nameStr}</strong>?</p><ul class="bank-remove-list"><li>This permanently removes the goal and its tracked progress.</li><li>It's different from archiving — this can't be undone.</li><li>No money is affected — goals move no money.</li></ul>`;
  } else {
    title.textContent = 'Archive goal?'; ok.textContent = 'Archive goal';
    body.innerHTML = `<p>Archive <strong>${nameStr}</strong>?</p><ul class="bank-remove-list"><li>It moves to Archived and stays visible in your history.</li><li>You won't track progress while it's archived — you can restore it anytime.</li><li>No money is affected — goals move no money.</li></ul>`;
  }
  openGoalDialog('goalConfirmDialog', '.btn-ghost');
}
async function confirmGoalAction() {
  if (_goalConfirmBusy || !_goalConfirm.id) return;
  _goalConfirmBusy = true; const dlg = document.getElementById('goalConfirmDialog'); dlg.dataset.busy = '1';
  const ok = document.getElementById('goalConfirmOk'); ok.disabled = true; ok.textContent = _goalConfirm.action === 'delete' ? 'Deleting…' : 'Archiving…';
  const { action, id } = _goalConfirm;
  try {
    if (action === 'delete') await api(`/goals/${id}`, { method: 'DELETE' });
    else await api(`/goals/${id}`, { method: 'PATCH', body: JSON.stringify({ status: 'ARCHIVED' }) });
    goalsAnnounce(action === 'delete' ? 'Goal deleted.' : 'Goal archived.');
    dlg.dataset.busy = '0'; closeGoalDialog('goalConfirmDialog', true);
    await loadGoals();
    goalLandFocus();
  } catch (ex) {
    const err = document.getElementById('goalConfirmErr'); err.textContent = _goalSafeErr(ex, "We couldn't complete that. Please try again."); err.style.display = 'block';
    ok.disabled = false; ok.textContent = action === 'delete' ? 'Delete goal' : 'Archive goal'; dlg.dataset.busy = '0';
  } finally { _goalConfirmBusy = false; }
}
let _goalRestoreBusy = false;
async function restoreGoal(id, ev) {
  if (!_goalUuid(id) || _goalRestoreBusy) return;
  _goalRestoreBusy = true;
  const btn = (ev && ev.currentTarget) ? ev.currentTarget : null;
  if (btn) { btn.disabled = true; btn.textContent = 'Restoring…'; }
  try { await api(`/goals/${id}`, { method: 'PATCH', body: JSON.stringify({ status: 'ACTIVE' }) }); goalsAnnounce('Goal restored.'); await loadGoals(); goalLandFocus(); }
  catch (e) { if (btn) { btn.disabled = false; btn.textContent = 'Restore'; } goalsAnnounce("Couldn't restore the goal."); }
  finally { _goalRestoreBusy = false; }
}
