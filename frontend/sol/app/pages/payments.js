// SOL member app — pages/payments.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── Payments page ─────────────────────────────────────────────────────────────
// ═══ Payments — settlement-truthful contribution center ══════════════════════
// Canonical state model: maps the backend PaymentStatus enum
// (PENDING/INITIATED/PROCESSING/SUCCESS/FAILED/RETURNED) to user-facing states.
// SUCCESS is the ONLY settled state — INITIATED/PROCESSING are NEVER shown as
// paid/complete. Any unrecognized raw status falls to a safe neutral state (never
// classified as successful). Failure reasons are generic + safe: we never render
// the raw ach_error_code / ach_transfer_id / cycle_id.
const PAY_STATE = {
  PENDING:    { key: 'DUE',        label: 'Due',        cls: 'pending',  tab: 'upcoming',   desc: 'This contribution is ready to pay.' },
  INITIATED:  { key: 'INITIATED',  label: 'Submitted',  cls: 'active',   tab: 'processing', desc: 'Payment submitted — awaiting your bank.' },
  PROCESSING: { key: 'PROCESSING', label: 'Processing', cls: 'active',   tab: 'processing', desc: 'Bank transfer processing — not yet settled.' },
  SUCCESS:    { key: 'SETTLED',    label: 'Settled',    cls: 'verified', tab: 'completed',  desc: 'Contribution settled.' },
  FAILED:     { key: 'FAILED',     label: 'Failed',     cls: 'failed',   tab: 'failed',     desc: "We couldn't complete this payment." },
  RETURNED:   { key: 'RETURNED',   label: 'Returned',   cls: 'failed',   tab: 'failed',     desc: 'This payment was returned by your bank after it processed.' },
};
function normalizePayment(raw) { return PAY_STATE[raw] || { key: 'UNKNOWN', label: 'Pending review', cls: 'pending', tab: 'processing', desc: "This payment is in an unrecognized state — we're checking on it." }; }
const PAY_TABS = ['upcoming', 'processing', 'completed', 'failed'];

let payments = { all: [], gmap: {}, tab: 'upcoming', ok: true };
const _payInFlight = {};

async function loadMyPayments() {
  const el = document.getElementById('paymentsList'); if (!el) return;
  el.innerHTML = paySkeletons(); renderPaySummarySkeleton();
  const [pr, gr] = await Promise.allSettled([api('/payments/my'), api('/groups')]);
  payments.ok = pr.status === 'fulfilled';
  let all = pr.status === 'fulfilled' ? (pr.value || []) : [];
  payments.gmap = {};
  if (gr.status === 'fulfilled') {
    const raw = gr.value || [];
    raw.forEach(g => { payments.gmap[g.id] = { name: g.name, day: g.payout_day_of_month }; });
    // Never surface payments that belong to internal test circles.
    const testIds = new Set(raw.filter(isTestCircle).map(g => g.id));
    all = all.filter(p => !testIds.has(p.group_id));
  }
  payments.all = all;
  syncPayFromURL();
  renderPayments();
}

function payCircleName(p) { const g = payments.gmap[p.group_id]; return g && g.name ? g.name : 'Circle'; }

function renderPaySummary() {
  const el = document.getElementById('paySummary'); if (!el) return;
  const card = (label, val, meta) => `<div class="sum-card"><div class="sum-label">${label}</div><div class="sum-val tnum">${val}</div>${meta ? `<div class="sum-hint">${meta}</div>` : ''}</div>`;
  // Never report a definitive zero when the query failed — show unavailable.
  if (!payments.ok) { el.innerHTML = card('Due now', '—', 'unavailable') + card('Processing', '—', 'unavailable') + card('Settled', '—', 'unavailable') + card('Failed or returned', '—', 'unavailable'); return; }
  const key = p => normalizePayment(p.status).key;
  const due = payments.all.filter(p => key(p) === 'DUE');
  const proc = payments.all.filter(p => normalizePayment(p.status).tab === 'processing'); // incl. unknown (shown in Processing tab)
  const settled = payments.all.filter(p => key(p) === 'SETTLED');
  const bad = payments.all.filter(p => ['FAILED', 'RETURNED'].includes(key(p)));
  const sum = arr => arr.reduce((s, p) => s + (p.amount_cents || 0), 0);
  el.innerHTML =
    card('Due now', due.length ? fmt$(sum(due)) : '$0.00', due.length ? `${due.length} contribution${due.length === 1 ? '' : 's'}` : 'nothing due') +
    card('Processing', String(proc.length), proc.length ? 'awaiting settlement' : 'none') +
    card('Settled', String(settled.length), settled.length ? fmt$(sum(settled)) + ' total' : 'none yet') +
    card('Failed or returned', String(bad.length), bad.length ? 'needs attention' : 'none');
}

function renderPayPrimaryAction() {
  const el = document.getElementById('payHeadActions'); if (!el) return;
  const due = payments.ok ? payments.all.filter(p => normalizePayment(p.status).key === 'DUE') : [];
  const pay = due.length ? `<button type="button" class="btn btn-primary" aria-label="Pay next contribution: ${fmt$(due[0].amount_cents)} to ${esc(payCircleName(due[0]))}" onclick="payContribution('${esc(due[0].group_id)}',this)">Pay next contribution</button>` : '';
  el.innerHTML = pay + `<button type="button" class="btn btn-ghost" onclick="nav('bank')">Payment methods</button>`;
}

function payTimelineRows(st) {
  if (st.key === 'FAILED') return [{ l: 'Scheduled', done: 1 }, { l: 'Submitted', done: 1 }, { l: 'Failed', done: 1, fail: 1 }];
  if (st.key === 'RETURNED') return [{ l: 'Scheduled', done: 1 }, { l: 'Submitted', done: 1 }, { l: 'Processing', done: 1 }, { l: 'Settled', done: 1 }, { l: 'Returned', done: 1, fail: 1 }];
  if (st.key === 'UNKNOWN') return [{ l: 'Scheduled', done: 1 }, { l: 'Under review', done: 0, cur: 1 }]; // don't claim 'Submitted' for an unverifiable state
  const order = ['DUE', 'INITIATED', 'PROCESSING', 'SETTLED'], labels = ['Scheduled', 'Submitted', 'Processing', 'Settled'], idx = order.indexOf(st.key);
  return labels.map((l, i) => ({ l, done: i <= idx ? 1 : 0, cur: i === idx ? 1 : 0 }));
}
function payDetail(p, st, gname, dateLabel, dateStr) {
  const meta = `<dl class="pay-detail__meta"><div><dt>Circle</dt><dd>${esc(gname)}</dd></div><div><dt>Amount</dt><dd class="tnum">${fmt$(p.amount_cents)}</dd></div><div><dt>${dateLabel}</dt><dd>${dateStr}</dd></div><div><dt>Status</dt><dd>${st.label}</dd></div>${p.attempt_count > 1 ? `<div><dt>Attempts</dt><dd class="tnum">${esc(p.attempt_count)}</dd></div>` : ''}</dl>`;
  const tl = `<ol class="pay-tl">${payTimelineRows(st).map(r => `<li class="pay-tl__step${r.done ? ' is-done' : ''}${r.fail ? ' is-fail' : ''}${r.cur ? ' is-current' : ''}"><span class="pay-tl__dot" aria-hidden="true"></span><span>${r.l}${r.cur && !r.fail ? ' (current)' : ''}</span></li>`).join('')}</ol>`;
  return meta + tl + `<p class="hint-muted" style="margin:.5rem 0 0">${st.desc}</p>`;
}
function payCard(p) {
  const st = normalizePayment(p.status), gname = payCircleName(p);
  const dateStr = p.created_at ? fmtDate(p.created_at) : '—';
  const dateLabel = st.key === 'DUE' ? 'Created' : 'Submitted';
  const detailId = 'paydet-' + esc(p.id);
  const action = st.key === 'DUE' ? `<button type="button" class="btn btn-primary btn--sm" aria-label="Pay ${fmt$(p.amount_cents)} to ${esc(gname)}" onclick="payContribution('${esc(p.group_id)}',this)">Pay now</button>` : '';
  return `<article class="pay-card">
    <div class="pay-card__row">
      <div class="pay-card__lead"><div class="pay-card__amt tnum">${fmt$(p.amount_cents)}</div><div class="pay-card__meta"><span class="pay-card__circle">${esc(gname)}</span><span class="pay-card__date">${dateLabel} ${dateStr}</span></div></div>
      <div class="pay-card__end"><span class="status status--${st.cls}">${st.label}</span><div class="pay-card__acts">${action}<button type="button" class="btn btn-ghost btn--sm" aria-label="Details for ${esc(gname)}, ${fmt$(p.amount_cents)}" aria-expanded="false" aria-controls="${detailId}" onclick="payToggle(this,'${detailId}')">Details</button></div></div>
    </div>
    <div class="pay-card__desc">${st.desc}</div>
    <div id="${detailId}" class="pay-detail" hidden>${payDetail(p, st, gname, dateLabel, dateStr)}</div>
  </article>`;
}
function payToggle(btn, id) {
  const open = btn.getAttribute('aria-expanded') === 'true';
  btn.setAttribute('aria-expanded', open ? 'false' : 'true'); btn.textContent = open ? 'Details' : 'Hide';
  const d = document.getElementById(id); if (d) d.hidden = open;
}

function payEmpty(tab) {
  const m = { upcoming: 'No contributions are currently due.', processing: 'No payments are processing.', completed: 'Completed payments appear here after they settle.', failed: 'No failed or returned payments.' };
  return `<div class="empty"><p>${m[tab] || 'Nothing here yet.'}</p></div>`;
}
function updatePayCount(n) { const el = document.getElementById('payCount'); if (!el) return; el.textContent = n < 0 ? '' : (n === 0 ? 'No payments in this view' : (n + ' payment' + (n === 1 ? '' : 's'))); }
function paySkeletons() { return `<div class="pay-list">${Array.from({ length: 3 }).map(() => `<div class="pay-card is-skeleton"><span class="sk sk-line" style="width:28%;height:1.4rem"></span><span class="sk sk-line" style="width:55%"></span></div>`).join('')}</div>`; }
function renderPaySummarySkeleton() { const el = document.getElementById('paySummary'); if (el) el.innerHTML = Array.from({ length: 4 }).map(() => `<div class="sum-card"><span class="sk sk-line" style="width:55%"></span><span class="sk sk-line" style="width:40%;height:1.3rem"></span></div>`).join(''); }

function renderPayments() {
  const el = document.getElementById('paymentsList'); if (!el) return;
  renderPaySummary(); renderPayPrimaryAction();
  if (!payments.ok) { el.innerHTML = `<div class="empty"><p>Couldn't load your payments.</p><button type="button" class="btn btn-primary btn--sm" onclick="loadMyPayments()">Retry</button></div>`; const c = document.getElementById('payCount'); if (c) c.textContent = "Couldn't load your payments."; return; }
  const list = payments.all.filter(p => normalizePayment(p.status).tab === payments.tab).sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0));
  updatePayCount(list.length);
  el.innerHTML = list.length ? `<div class="pay-list">${list.map(payCard).join('')}</div>` : payEmpty(payments.tab);
}

// Duplicate-safe contribution submit. The backend is idempotent on (cycle,user),
// but the UI also blocks re-entry, disables the button, shows a loading label,
// and — critically — NEVER optimistically marks the payment paid; it re-fetches
// the backend truth so the record shows its real (submitted/processing) state.
async function payContribution(groupId, btn) {
  if (_payInFlight[groupId]) return;
  _payInFlight[groupId] = true;
  if (btn) { btn.disabled = true; btn.classList.add('btn--loading'); btn.dataset.orig = btn.textContent; btn.textContent = 'Submitting…'; }
  try {
    await api('/payments/initiate', { method: 'POST', body: JSON.stringify({ group_id: groupId }) });
    // Re-fetch the backend truth and let the record render in its ACTUAL state —
    // never force a "now processing" tab/announcement the backend may not confirm yet.
    await loadMyPayments();
    const live = document.getElementById('payCount'); if (live) live.textContent = 'Payment submitted.';
  } catch (e) {
    if (btn) { btn.disabled = false; btn.classList.remove('btn--loading'); btn.textContent = btn.dataset.orig || 'Pay now'; }
    alert(safeError(e));   // safe generic — never surface a raw backend/provider message on a money flow
  } finally { delete _payInFlight[groupId]; }
}

function paySetTab(tab) {
  payments.tab = tab;
  document.querySelectorAll('.pay-tabs .ptab').forEach(t => { const on = t.dataset.ptab === tab; t.classList.toggle('active', on); t.setAttribute('aria-selected', on ? 'true' : 'false'); t.tabIndex = on ? 0 : -1; });
  const panel = document.getElementById('paymentsList'); if (panel) panel.setAttribute('aria-labelledby', 'ptab-' + tab);
  syncPayToURL(); renderPayments();
}
function payTabKey(e) {
  const tabs = Array.from(document.querySelectorAll('.pay-tabs .ptab')), cur = tabs.findIndex(t => t.dataset.ptab === payments.tab);
  let j = null;
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') j = (cur + 1) % tabs.length;
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') j = (cur - 1 + tabs.length) % tabs.length;
  else if (e.key === 'Home') j = 0; else if (e.key === 'End') j = tabs.length - 1;
  if (j == null) return; e.preventDefault(); paySetTab(tabs[j].dataset.ptab); tabs[j].focus();
}
function syncPayToURL() { syncPayFromURL_write(payments.tab); }
function syncPayFromURL_write(tab) { try { const p = new URLSearchParams(location.search); tab !== 'upcoming' ? p.set('ptab', tab) : p.delete('ptab'); history.replaceState(null, '', location.pathname + (p.toString() ? '?' + p.toString() : '') + location.hash); } catch (e) {} }
function syncPayFromURL() {
  const tab = new URLSearchParams(location.search).get('ptab');
  if (PAY_TABS.includes(tab)) payments.tab = tab;
  document.querySelectorAll('.pay-tabs .ptab').forEach(t => { const on = t.dataset.ptab === payments.tab; t.classList.toggle('active', on); t.setAttribute('aria-selected', on ? 'true' : 'false'); t.tabIndex = on ? 0 : -1; });
  const panel = document.getElementById('paymentsList'); if (panel) panel.setAttribute('aria-labelledby', 'ptab-' + payments.tab);
}

async function setPrimary(id) {
  try {
    await api(`/bank/${id}/primary`, { method:'PATCH' });
    loadBank();
  } catch(e) { alert(safeError(e)); }
}

// Legacy alias → routes any old caller through the accessible confirmation dialog.
function removeBank(id) { openRemoveDialog(id); }

async function handleVerifyMicro(e, accountId) {
  e.preventDefault();
  const form = e.target;
  const a1 = parseInt(form.a1.value, 10);
  const a2 = parseInt(form.a2.value, 10);
  const errEl = document.getElementById('vErr-' + accountId);
  const okEl = document.getElementById('vOk-' + accountId);
  errEl.style.display = 'none'; okEl.style.display = 'none';
  try {
    await api(`/bank/${accountId}/verify-micro-deposits`, {
      method: 'POST',
      body: JSON.stringify({ amount1_cents: a1, amount2_cents: a2 }),
    });
    okEl.textContent = '✓ Verified — you can now contribute to circles.';
    okEl.style.display = 'block';
    bankAnnounce('Account verified. You can now contribute to circles.');  // persists past the loadBank re-render
    form.reset();
    loadBank();       // refresh badges on the bank page
    loadOnboarding(); // refresh dashboard checklist
  } catch (ex) {
    errEl.textContent = ex.message || 'Verification failed';
    errEl.style.display = 'block';
  }
}

async function handleAddBank(e) {
  e.preventDefault();
  const btn = document.getElementById('bankBtn');
  const err = document.getElementById('bankErr');
  err.style.display = 'none';
  btn.textContent = 'Connecting…'; btn.disabled = true;
  try {
    await api('/bank/manual', {
      method: 'POST',
      body: JSON.stringify({
        institution_name: document.getElementById('bankName').value.trim(),
        routing_number:   document.getElementById('routingNumber').value.trim(),
        account_number:   document.getElementById('accountNumber').value.trim(),
        account_type:     document.getElementById('accountType').value,
      }),
    });
    document.getElementById('bankForm').reset();
    loadBank();
    loadOnboarding();
  } catch(ex) {
    err.textContent = ex.message; err.style.display = 'block';
  } finally { btn.textContent = 'Connect account'; btn.disabled = false; }
}
