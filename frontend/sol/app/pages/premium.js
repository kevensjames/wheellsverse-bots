// SOL member app — pages/premium.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── Premium ─────────────────────────────────────────────────────────────────────
// ═══ SOL Premium — subscription & billing-management center ═══════════════════
// Canonical subscription-state model from the REAL backend /subscriptions/me:
//   is_premium (authoritative), status (INCOMPLETE|ACTIVE|PAST_DUE|CANCELED|
//   TRIALING|null), cancel_at_period_end, current_period_end, price_cents.
// Premium state is ALWAYS backend truth — checkout creation, the Stripe redirect,
// the browser return, and any local flag are NEVER treated as activation. The
// responses also carry provider_customer_id / provider_subscription_id / invoice
// provider ids: those are NEVER rendered. There is no resume endpoint, so no
// resume/keep control is fabricated. price comes from backend price_cents only.
const SUB_STATE = {
  ACTIVE:           { key:'ACTIVE',           chip:'active',    label:'Active' },
  CANCEL_SCHEDULED: { key:'CANCEL_SCHEDULED', chip:'warning',   label:'Cancellation scheduled' },
  PAST_DUE:         { key:'PAST_DUE',         chip:'overdue',   label:'Billing action required' },
  INACTIVE:         { key:'INACTIVE',         chip:'pending',   label:'Not subscribed' },
  CANCELLED:        { key:'CANCELLED',        chip:'cancelled', label:'Ended' },
  UNKNOWN:          { key:'UNKNOWN',          chip:'pending',   label:'Status unavailable' },
};
function normalizeSubscriptionState(s) {
  if (!s || typeof s !== 'object') return SUB_STATE.UNKNOWN;
  const status = String(s.status || '').toUpperCase();
  const premium = s.is_premium === true;
  if (status === 'PAST_DUE') return SUB_STATE.PAST_DUE;                 // billing attention first
  if (premium) return s.cancel_at_period_end === true ? SUB_STATE.CANCEL_SCHEDULED : SUB_STATE.ACTIVE;
  if (status === 'CANCELED') return SUB_STATE.CANCELLED;
  return SUB_STATE.INACTIVE;                                            // null/free/INCOMPLETE → inactive (never premium)
}
// Stripe invoice status — deliberately SEPARATE from circle-contribution settlement.
const INV_STATUS = { PAID: { label:'Paid', chip:'verified' }, OPEN: { label:'Pending', chip:'pending' }, FAILED: { label:'Failed', chip:'failed' } };
function normalizeInvoiceStatus(raw) { return INV_STATUS[String(raw || '').toUpperCase()] || { label:'Status unavailable', chip:'pending' }; }

function premiumAnnounce(msg) { const el = document.getElementById('premiumLiveStatus'); if (el) { el.textContent = ''; el.textContent = msg; } }
function premDate(s) { return fmtDate(s) || null; }   // canonical "Jul 19, 2026" via the shared formatter
function premPrice(cents) { return (typeof cents === 'number' && isFinite(cents)) ? fmt$(cents) : null; }
function premShowInlineError(msg) { const e = document.getElementById('premActionErr'); if (e) { e.textContent = msg; e.style.display = 'block'; } }

let premiumState = { sub: null, subOk: false, invoices: [], invOk: false };

async function loadPremium(userInitiated) {
  const el = document.getElementById('premiumContent');
  if (!el) return;
  // Return from Stripe Checkout (?premium=success|cancel) — NEVER treated as activation; poll backend truth.
  const ret = new URLSearchParams(location.search).get('premium');
  // During the poll show a NEUTRAL pending note — never assert "Payment received" before backend truth.
  let note = '';
  if (ret === 'success') note = `<div class="prem-note" role="status">Confirming your payment — this can take a moment…</div>`;
  else if (ret === 'cancel') note = `<div class="prem-note" role="status">Checkout canceled — no charge was made.</div>`;
  el.innerHTML = note + premiumSkeleton();
  if (ret === 'success') {
    for (let i = 0; i < 3; i++) { try { const s = await api('/subscriptions/me'); if (s && s.is_premium) break; } catch (_) {} await new Promise(r => setTimeout(r, 1500)); }
  }
  if (ret) history.replaceState(null, '', location.pathname);   // don't re-trigger on refresh

  const [subRes, invRes] = await Promise.allSettled([ api('/subscriptions/me'), api('/subscriptions/invoices') ]);
  premiumState.subOk = subRes.status === 'fulfilled' && subRes.value && typeof subRes.value === 'object';
  premiumState.sub = premiumState.subOk ? subRes.value : null;
  premiumState.invOk = invRes.status === 'fulfilled' && Array.isArray(invRes.value);
  premiumState.invoices = premiumState.invOk ? invRes.value : [];

  const st = premiumState.subOk ? normalizeSubscriptionState(premiumState.sub) : SUB_STATE.UNKNOWN;
  // Recompute the return note from BACKEND TRUTH — only claim "Payment received" when the backend confirms premium.
  const premiumNow = st.key === 'ACTIVE' || st.key === 'CANCEL_SCHEDULED' || st.key === 'PAST_DUE';
  let finalNote = '';
  if (ret === 'success') finalNote = premiumNow
    ? `<div class="prem-note prem-note--ok" role="status">Payment received — your membership is active.</div>`
    : `<div class="prem-note" role="status">We're still confirming your payment. This can take a moment — refresh in a bit.</div>`;
  else if (ret === 'cancel') finalNote = `<div class="prem-note" role="status">Checkout canceled — no charge was made.</div>`;
  el.innerHTML = finalNote + renderPremium(st, premiumState.sub);
  if (userInitiated) { premiumAnnounce(st.label); const h = document.getElementById('premHeroTitle'); if (h) h.focus(); }
}

function renderPremium(st, s) {
  const showManage = st.key === 'ACTIVE' || st.key === 'CANCEL_SCHEDULED' || st.key === 'PAST_DUE';
  return `<div class="prem-grid">
    <div class="prem-main">
      ${premiumHero(st, s)}
      ${billingSummary(st, s)}
      ${showManage ? manageSection(st, s) : ''}
      ${billingHistorySection()}
    </div>
    <aside class="prem-side">
      ${benefitsCard()}
      ${planComparison()}
      ${disclosuresCard(s)}
    </aside>
  </div>`;
}

function premiumHero(st, s) {
  const price = premPrice(s && s.price_cents);
  const priceStr = price ? `${price}/month` : 'Price unavailable';
  const end = premDate(s && s.current_period_end);
  let title, lead, actions = '';
  if (st.key === 'ACTIVE') {
    title = 'SOL Premium'; lead = `${priceStr}${end ? ` · renews on ${end}` : ''}`;
    actions = `<button type="button" class="btn btn-ghost" onclick="premScrollManage()">Manage membership</button>`;
  } else if (st.key === 'CANCEL_SCHEDULED') {
    title = 'SOL Premium'; lead = end ? `Active through ${end} — automatic renewal is off.` : 'Cancellation scheduled — automatic renewal is off.';
    actions = `<button type="button" class="btn btn-ghost" onclick="premScrollManage()">Manage membership</button>`;
  } else if (st.key === 'PAST_DUE') {
    title = 'Billing action required'; lead = `We couldn't process your latest payment.${end ? ` Premium access continues through ${end}.` : ''}`;
    actions = `<button type="button" class="btn btn-ghost" onclick="nav('notifications')">Get billing help</button>`;
  } else if (st.key === 'CANCELLED') {
    title = 'Your Premium has ended'; lead = `Resubscribe anytime to get Premium benefits again.`;
    actions = `<button type="button" class="btn btn-primary" id="subBtn" onclick="startCheckout()">Upgrade to Premium — ${priceStr}</button>`;
  } else if (st.key === 'UNKNOWN') {
    title = 'Status unavailable'; lead = `We couldn't load your membership status right now.`;
    actions = `<button type="button" class="btn btn-primary" onclick="loadPremium(true)">Refresh status</button>`;
  } else {
    title = 'Upgrade to SOL Premium'; lead = `${priceStr} · cancel anytime`;
    actions = `<button type="button" class="btn btn-primary" id="subBtn" onclick="startCheckout()">Upgrade to Premium</button>`;
  }
  return `<section class="prem-hero prem-hero--${st.chip}" aria-labelledby="premHeroTitle">
    <div class="prem-hero__icon" aria-hidden="true"><svg class="ic"><use href="#ic-premium"/></svg></div>
    <div class="prem-hero__body">
      <span class="status status--${st.chip}">${esc(st.label)}</span>
      <h2 id="premHeroTitle" class="prem-hero__title" tabindex="-1">${esc(title)}</h2>
      <p class="prem-hero__lead">${esc(lead)}</p>
      <div class="prem-hero__actions">${actions}</div>
      <p class="err" id="premActionErr" role="alert" style="display:none"></p>
    </div>
  </section>`;
}

function premSum(label, val, chip) {
  const inner = chip ? `<span class="status status--${chip}">${esc(val)}</span>` : `<span class="tnum">${esc(val)}</span>`;
  return `<div class="sum-card"><div class="sum-label">${esc(label)}</div><div class="sum-val">${inner}</div></div>`;
}
function billingSummary(st, s) {
  const price = premPrice(s && s.price_cents);
  const end = premDate(s && s.current_period_end);
  let dateLabel = 'Next billing', dateVal = '—';
  if (st.key === 'ACTIVE') { dateLabel = 'Renews on'; dateVal = end || 'Status unavailable'; }
  else if (st.key === 'CANCEL_SCHEDULED') { dateLabel = 'Active through'; dateVal = end || 'Status unavailable'; }
  else if (st.key === 'PAST_DUE') { dateLabel = 'Access through'; dateVal = end || 'Status unavailable'; }
  else if (st.key === 'CANCELLED') { dateLabel = 'Ended on'; dateVal = end || '—'; }
  else if (st.key === 'UNKNOWN') { dateVal = 'Status unavailable'; }
  let histVal = '—';
  if (!premiumState.invOk) histVal = 'Unavailable';
  else if (!premiumState.invoices.length) histVal = 'None yet';
  else histVal = `${premiumState.invoices.length} invoice${premiumState.invoices.length === 1 ? '' : 's'}`;
  return `<div class="dash-summary prem-summary" aria-label="Billing summary">
    ${premSum('Membership', st.label, st.chip)}
    ${premSum('Plan price', price ? `${price}/mo` : 'Price unavailable', null)}
    ${premSum(dateLabel, dateVal, null)}
    ${premSum('Billing history', histVal, null)}
  </div>`;
}

function manageSection(st, s) {
  const end = premDate(s && s.current_period_end);
  let body;
  if (st.key === 'ACTIVE') {
    body = `<p class="hint-muted">Your membership renews automatically${end ? ` on ${end}` : ''}. You can cancel anytime — you'll keep Premium through the end of the current billing period.</p>
      <button type="button" class="btn btn-danger prem-cancel-btn" onclick="openCancelDialog()">Cancel membership</button>`;
  } else if (st.key === 'CANCEL_SCHEDULED') {
    body = `<p class="hint-muted">Your membership is set to end${end ? ` on ${end}` : ' at the end of the current period'}. You'll keep Premium until then. To keep your membership, contact support before that date.</p>
      <button type="button" class="btn btn-ghost" onclick="nav('notifications')">Contact support</button>`;
  } else {
    body = `<p class="hint-muted">We couldn't process your most recent payment. To avoid losing Premium, contact support for help with your billing.</p>
      <button type="button" class="btn btn-ghost" onclick="nav('notifications')">Get billing help</button>`;
  }
  return `<section class="prem-panel prem-manage" id="premManage" aria-labelledby="premManageTitle"><h3 id="premManageTitle">Manage membership</h3>${body}</section>`;
}
function premScrollManage() { const m = document.getElementById('premManage'); if (m) { const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches; m.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' }); } }

function billingHistorySection() {
  if (!premiumState.invOk) {
    return `<section class="prem-panel" aria-labelledby="premHistTitle"><h3 id="premHistTitle">Billing history</h3>
      <p class="prem-hist-err">We couldn't load your billing history. <button type="button" class="link-btn" onclick="loadPremium(true)">Retry</button></p></section>`;
  }
  if (!premiumState.invoices.length) {
    return `<section class="prem-panel" aria-labelledby="premHistTitle"><h3 id="premHistTitle">Billing history</h3>
      <p class="hint-muted">No billing history yet. Your invoices and receipts will appear here after your first payment.</p></section>`;
  }
  const rows = premiumState.invoices.map(inv => {
    const iv = normalizeInvoiceStatus(inv && inv.status);
    const date = premDate(inv && inv.created_at) || '—';
    const amt = (inv && typeof inv.amount_cents === 'number') ? fmt$(inv.amount_cents) : '—';
    const receipt = safeUrl(inv && inv.hosted_url);   // http(s) only; never render provider ids
    return `<tr>
      <td data-label="Date">${esc(date)}</td>
      <td data-label="Amount" class="tnum">${esc(amt)}</td>
      <td data-label="Plan">SOL Premium</td>
      <td data-label="Status"><span class="status status--${iv.chip}">${esc(iv.label)}</span></td>
      <td data-label="Receipt" class="prem-receipt">${receipt ? `<a class="link-btn" href="${esc(receipt)}" target="_blank" rel="noopener noreferrer">Receipt</a>` : ''}</td>
    </tr>`;
  }).join('');
  return `<section class="prem-panel" aria-labelledby="premHistTitle"><h3 id="premHistTitle">Billing history</h3>
    <div class="table-wrap"><table class="prem-table"><thead><tr><th>Date</th><th>Amount</th><th>Plan</th><th>Status</th><th><span class="sr-only">Receipt</span></th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

function benefitsCard() {
  const b = [
    { ic:'ic-discover',  t:'Enhanced circle recommendations', d:'Smarter SOL Match™ suggestions to help you find or start the right circle.' },
    { ic:'ic-score',     t:'Advanced savings insights', d:'A clearer view of your progress and trust score over time.' },
    { ic:'ic-goals',     t:'Enhanced planning tools',   d:'More detail as you plan toward your savings goals.' },
    { ic:'ic-community', t:'Priority member support',   d:'Get help faster when you need a hand.' },
  ];
  return `<div class="side-card">
    <h3>What's included</h3>
    <ul class="prem-benefits">
      ${b.map(x => `<li><span class="prem-benefit__ic" aria-hidden="true"><svg class="ic"><use href="#${x.ic}"/></svg></span><span class="prem-benefit__txt"><strong>${esc(x.t)}</strong><span class="prem-benefit__d">${esc(x.d)}</span></span></li>`).join('')}
    </ul>
  </div>`;
}

function planComparison() {
  return `<div class="side-card">
    <h3>Free vs Premium</h3>
    <div class="prem-compare">
      <div class="prem-compare__col"><div class="prem-compare__h">Free</div><ul><li>Create &amp; join circles</li><li>Track contributions &amp; payouts</li><li>Savings goals</li><li>Identity verification</li></ul></div>
      <div class="prem-compare__col prem-compare__col--pro"><div class="prem-compare__h">Premium</div><ul><li>Everything in Free</li><li>Enhanced recommendations</li><li>Advanced insights &amp; planning</li><li>Priority support</li></ul></div>
    </div>
    <p class="hint-muted">Cancel anytime — you keep Premium through the current billing period.</p>
  </div>`;
}

function disclosuresCard(s) {
  const price = premPrice(s && s.price_cents);
  return `<div class="side-card">
    <h3>Billing details</h3>
    <ul class="kyc-why">
      <li>${price ? `${price} per month` : 'A monthly price'}, billed automatically until you cancel.</li>
      <li>Cancel anytime — Premium stays active through the current billing period, then renewal stops.</li>
      <li>Your billing history and receipts stay available here.</li>
    </ul>
  </div>`;
}

function premiumSkeleton() {
  return `<div class="prem-grid"><div class="prem-main">
    <section class="prem-hero"><div class="prem-hero__icon"></div><div class="prem-hero__body" style="flex:1"><span class="sk sk-line" style="width:25%"></span><span class="sk sk-line" style="width:50%;height:1.6rem;margin-top:.4rem"></span><span class="sk sk-line" style="width:70%;margin-top:.4rem"></span></div></section>
    <div class="dash-summary">${Array.from({ length: 4 }).map(() => `<div class="sum-card"><span class="sk sk-line" style="width:55%"></span><span class="sk sk-line" style="width:40%;height:1.3rem;margin-top:.3rem"></span></div>`).join('')}</div>
    </div><aside class="prem-side"><div class="side-card"><span class="sk sk-line" style="width:50%"></span><span class="sk sk-block" style="margin-top:.6rem"></span></div></aside></div>`;
}

// ── Checkout — one centralized starter. Backend-authoritative; NEVER activates Premium. ──
async function startCheckout() {
  if (!SolGuard.acquire('checkout')) return;
  const errEl = document.getElementById('premActionErr'); if (errEl) errEl.style.display = 'none';
  const btn = document.getElementById('subBtn');
  const label = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'Starting checkout…'; }
  try {
    const resp = await api('/subscriptions/checkout', { method: 'POST' });
    const url = safeUrl(resp && resp.checkout_url);   // http(s) only — never javascript:/data:; never a client-supplied URL
    if (!url) throw new Error('unsafe_or_missing_url');
    window.location.href = url;   // hand off to Stripe-hosted Checkout (this is NOT premium activation)
    // Intentionally leave the lock HELD — the page is navigating away.
  } catch (e) {
    premiumAnnounce('Checkout could not be started.');
    premShowInlineError("We couldn't start checkout. Please try again in a moment, or contact support.");
    if (btn) { btn.disabled = false; btn.textContent = label || 'Upgrade to Premium'; }
    SolGuard.release('checkout');
  }
}
// Legacy alias — any old caller routes through the centralized starter.
function subscribePremium() { startCheckout(); }

// ── Cancel membership — accessible dialog, backend-authoritative, no optimistic change ──
let _premCancel = { trigger: null };
function openCancelDialog() {
  _premCancel = { trigger: document.activeElement };
  const s = premiumState.sub || {};
  const end = premDate(s.current_period_end);
  const body = document.getElementById('premCancelBody');
  body.innerHTML = `<p>You're about to turn off automatic renewal for <strong>SOL Premium</strong>.</p>
    <ul class="bank-remove-list">
      <li>Your renewal stops — you won't be charged again.</li>
      <li>${end ? `You'll keep Premium through <strong>${esc(end)}</strong>.` : "You'll keep Premium through the end of the current billing period."}</li>
      <li>After that date, Premium access ends.</li>
      <li>Your billing history and receipts stay available.</li>
      <li>To undo this, contact support before it takes effect.</li>
    </ul>`;
  document.getElementById('premCancelErr').style.display = 'none';
  const btn = document.getElementById('premCancelConfirm'); btn.disabled = false; btn.textContent = 'Cancel membership';
  // canClose blocks Escape while the cancel request is in flight (preserved).
  SolDialog.open('premCancelDialog', { opener: _premCancel.trigger, initialFocus: '.btn-ghost', canClose: () => !SolGuard.isLocked('subscription:cancel'), onClose: () => { _premCancel = { trigger: null }; } });
}
function closeCancelDialog(skipRestore) {
  SolDialog.close('premCancelDialog', { restoreFocus: !skipRestore });
  _premCancel = { trigger: null };
}
async function confirmCancelPremium() {
  if (!SolGuard.acquire('subscription:cancel')) return;
  const btn = document.getElementById('premCancelConfirm'); btn.disabled = true; btn.textContent = 'Cancelling…';
  const keep = document.querySelector('#premCancelDialog .btn-ghost'); if (keep) keep.disabled = true;   // commit-until-resolved: no dismiss mid-flight
  try {
    await api('/subscriptions/cancel', { method: 'POST' });   // backend-authoritative; at-period-end default
    closeCancelDialog(true);
    premiumAnnounce('Renewal turned off. You keep Premium through the end of the current period.');
    await loadPremium();   // re-fetch backend truth — no optimistic cancellation
    const h = document.getElementById('premHeroTitle'); if (h) h.focus();
  } catch (e) {
    const err = document.getElementById('premCancelErr');
    err.textContent = "We couldn't cancel your membership. Please try again, or contact support.";
    err.style.display = 'block';
    btn.disabled = false; btn.textContent = 'Cancel membership';
    if (keep) keep.disabled = false;   // restore the dismiss path only after a failed attempt
  } finally { SolGuard.release('subscription:cancel'); }
}
// Legacy alias → accessible dialog.
function cancelPremium() { openCancelDialog(); }
