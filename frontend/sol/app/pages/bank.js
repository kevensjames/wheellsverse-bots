// SOL member app — pages/bank.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── Bank ──────────────────────────────────────────────────────────────────────
// ═══ Bank & payment methods — high-trust linked-account center ════════════════
// Canonical bank-state model. The backend BankAccount exposes ONLY: status
// (ACTIVE | REMOVED) + a `verified` bool + is_primary. There is NO reconnect /
// failed / blocked enum, so we never fabricate those controls — we map the REAL
// states and fall to an honest "Status unavailable" for anything unrecognized.
// A record existing is NEVER payment-ready: only ACTIVE + verified===true is READY.
const BANK_STATE = {
  VERIFIED:     { key:'VERIFIED',     label:'Verified',             cls:'verified',  ready:true,  desc:'Ready for contributions and payouts.' },
  PENDING:      { key:'PENDING',      label:'Verification pending', cls:'pending',   ready:false, desc:'Confirm the two micro-deposits below to finish linking this account.' },
  DISCONNECTED: { key:'DISCONNECTED', label:'Removed',              cls:'cancelled', ready:false, desc:'This account is no longer linked.' },
  UNKNOWN:      { key:'UNKNOWN',      label:'Status unavailable',   cls:'pending',   ready:false, desc:"We can't confirm this account's status right now." },
};
function normalizeBank(a) {
  if (!a || typeof a !== 'object') return BANK_STATE.UNKNOWN;
  if (a.status === 'REMOVED') return BANK_STATE.DISCONNECTED;
  if (a.status !== 'ACTIVE') return BANK_STATE.UNKNOWN;   // unrecognized status → honest unavailable
  return a.verified === true ? BANK_STATE.VERIFIED : BANK_STATE.PENDING;
}
function bankDate(s) { return fmtDate(s) || null; }   // canonical "Jul 19, 2026" via the shared formatter
function bankMask(a) { const l4 = (a && typeof a.account_last4 === 'string' && /^\d{2,4}$/.test(a.account_last4)) ? a.account_last4 : null; return l4 ? ('•••• ' + l4) : 'Account ending unavailable'; }
// Announce into a persistent page-level live region that survives loadBank()'s re-render.
function bankAnnounce(msg) { const el = document.getElementById('bankLiveStatus'); if (el) { el.textContent = ''; el.textContent = msg; } }

let bankState = { accounts: [], ok: false, me: null, meOk: false };

async function loadBank() {
  const list = document.getElementById('bankList');
  if (!list) return;
  list.innerHTML = '<div class="spinner"></div>';
  const [accRes, meRes] = await Promise.allSettled([ api('/bank/list'), api('/auth/me') ]);
  bankState.ok = accRes.status === 'fulfilled' && Array.isArray(accRes.value);
  bankState.accounts = bankState.ok ? accRes.value : [];
  bankState.meOk = meRes.status === 'fulfilled' && meRes.value && typeof meRes.value === 'object';
  bankState.me = bankState.meOk ? meRes.value : null;

  if (!bankState.ok) {
    list.innerHTML = `<div class="bank-empty bank-empty--err">
      <div class="bank-empty__title">We couldn't load your accounts</div>
      <p class="hint-muted">Your linked accounts are safe. Please try again in a moment.</p>
      <button type="button" class="btn btn-ghost btn--sm" onclick="loadBank()">Retry</button></div>`;
  } else if (!bankState.accounts.length) {
    list.innerHTML = `<div class="bank-empty">
      <div class="bank-empty__icon" aria-hidden="true"><svg class="ic"><use href="#ic-bank"/></svg></div>
      <div class="bank-empty__title">No account linked yet</div>
      <p class="hint-muted">Link a US checking or savings account to make contributions and receive payouts.</p>
      <button type="button" class="btn btn-primary btn--sm" onclick="openBankAdd()">Connect a bank account</button></div>`;
  } else {
    list.innerHTML = bankState.accounts.map(bankCard).join('');
  }
  renderBankSummary();
  renderBankReadiness();
  renderBankHeadAction();
}

function bankCard(a) {
  const st = normalizeBank(a);
  const masked = bankMask(a);
  const inst = esc((a && a.institution_name) || 'Bank account');
  const type = (a && a.account_type) ? esc(String(a.account_type)) : 'Account';
  const primary = !!(a && a.is_primary === true);
  const id = esc(String((a && a.id) || ''));
  const linked = bankDate(a && a.created_at);
  return `<div class="bank-acct${primary ? ' bank-acct--primary' : ''}">
    <div class="bank-acct__head">
      <div class="bank-acct__id">
        <div class="bank-acct__inst">${inst}${primary ? ' <span class="bank-acct__pri">Primary</span>' : ''}</div>
        <div class="bank-acct__meta"><span class="bank-acct__type">${type}</span><span class="bank-acct__mask">${masked}</span></div>
      </div>
      <span class="status status--${st.cls}">${st.label}</span>
    </div>
    <p class="bank-acct__desc">${esc(st.desc)}</p>
    ${linked ? `<div class="bank-acct__linked hint-muted">Linked ${linked}</div>` : ''}
    <div class="bank-acct__actions">
      <div class="bank-acct__actions-l">${primary
        ? '<span class="bank-acct__contrib">Contribution account</span>'
        : (st.key === 'VERIFIED' ? `<button type="button" class="btn btn-ghost btn--sm" onclick="setPrimary('${id}')">Use as primary</button>` : '')}</div>
      <button type="button" class="btn btn-ghost btn--sm bank-acct__remove" aria-label="Remove ${inst}, ${masked}" onclick="openRemoveDialog('${id}')">Remove</button>
    </div>
    ${st.key === 'PENDING' ? microDepositForm(id) : ''}
  </div>`;
}

function microDepositForm(id) {
  return `<details class="bank-micro" open>
    <summary>Verify micro-deposits</summary>
    <p class="hint-muted">Within 1–3 business days, SOLCIRCLE sends two small deposits (each under $1) to this account. Enter the amounts in cents to verify.</p>
    <form onsubmit="handleVerifyMicro(event, '${id}')" class="bank-micro__form">
      <div class="field"><label for="a1-${id}">Amount 1 (cents)</label><input id="a1-${id}" name="a1" class="input" type="number" min="1" max="99" required placeholder="e.g. 3"></div>
      <div class="field"><label for="a2-${id}">Amount 2 (cents)</label><input id="a2-${id}" name="a2" class="input" type="number" min="1" max="99" required placeholder="e.g. 9"></div>
      <button class="btn btn-primary btn--sm" type="submit">Verify</button>
    </form>
    <p class="err" id="vErr-${id}" style="display:none" role="alert"></p>
    <p class="ok-msg" id="vOk-${id}" style="display:none" aria-live="polite"></p>
  </details>`;
}

function bankSumCard(label, val, cls) {
  return `<div class="sum-card"><div class="sum-label">${esc(label)}</div><div class="sum-val"><span class="status status--${cls}">${esc(val)}</span></div></div>`;
}
function renderBankSummary() {
  const el = document.getElementById('bankSummary'); if (!el) return;
  if (!bankState.ok) {
    el.innerHTML = bankSumCard('Connection status','Unavailable','pending')
      + bankSumCard('Verification','Unavailable','pending')
      + bankSumCard('Payment readiness','Unavailable','pending')
      + bankSumCard('Connected accounts','—','pending');
    return;
  }
  const active = bankState.accounts.filter(a => a && a.status === 'ACTIVE');
  const verified = active.filter(a => a.verified === true);
  const conn = active.length ? ['Connected','active'] : ['Not connected','pending'];
  const ver = verified.length ? ['Verified','verified'] : (active.length ? ['Pending','pending'] : ['None','pending']);
  let ready;
  if (!bankState.meOk) ready = ['Status unavailable','pending'];
  else {
    const idOk = String((bankState.me && bankState.me.kyc_status) || '').toUpperCase() === 'VERIFIED';
    ready = (verified.length && idOk) ? ['Ready','verified'] : ['Action needed','pending'];
  }
  el.innerHTML = bankSumCard('Connection status', conn[0], conn[1])
    + bankSumCard('Verification', ver[0], ver[1])
    + bankSumCard('Payment readiness', ready[0], ready[1])
    + bankSumCard('Connected accounts', String(active.length), active.length ? 'verified' : 'pending');
}

function renderBankReadiness() {
  const el = document.getElementById('bankReadiness'); if (!el) return;
  const active = bankState.ok ? bankState.accounts.filter(a => a && a.status === 'ACTIVE') : [];
  const verified = active.filter(a => a.verified === true);
  const idState = !bankState.meOk ? 'unknown' : (String((bankState.me.kyc_status) || '').toUpperCase() === 'VERIFIED' ? 'done' : 'todo');
  const connState = !bankState.ok ? 'unknown' : (active.length ? 'done' : 'todo');
  const verState = !bankState.ok ? 'unknown' : (verified.length ? 'done' : 'todo');
  const anyUnknown = [idState, connState, verState].includes('unknown');
  const allDone = idState === 'done' && connState === 'done' && verState === 'done';
  const item = (state, text) => {
    const mark = state === 'done' ? '✓' : (state === 'unknown' ? '?' : '○');
    return `<li class="bank-check bank-check--${state}"><span class="bank-check__mark" aria-hidden="true">${mark}</span><span>${esc(text)}</span></li>`;
  };
  const payLabel = anyUnknown ? 'Status unavailable' : (allDone ? 'Payments enabled' : 'Finish the steps above to enable payments');
  const payCls = anyUnknown ? 'pending' : (allDone ? 'verified' : 'pending');
  el.innerHTML = `<h3>Payment readiness</h3>
    <ul class="bank-checklist">
      ${item(idState, idState === 'done' ? 'Identity verified' : (idState === 'unknown' ? 'Identity status unavailable' : 'Verify your identity'))}
      ${item(connState, connState === 'done' ? 'Bank account connected' : (connState === 'unknown' ? 'Connection status unavailable' : 'Connect a bank account'))}
      ${item(verState, verState === 'done' ? 'Bank account verified' : (verState === 'unknown' ? 'Verification status unavailable' : 'Verify your bank account'))}
    </ul>
    <div class="bank-ready-note status status--${payCls}">${esc(payLabel)}</div>
    ${idState === 'todo' ? `<button type="button" class="btn btn-ghost btn--sm" style="margin-top:.7rem" onclick="nav('kyc')">Verify identity</button>` : ''}`;
}

function renderBankHeadAction() {
  const el = document.getElementById('bankHeadActions'); if (!el) return;
  const active = bankState.ok ? bankState.accounts.filter(a => a && a.status === 'ACTIVE') : [];
  let primary = '';
  if (bankState.ok && !active.length) primary = `<button type="button" class="btn btn-primary" onclick="openBankAdd()">Connect a bank account</button>`;
  else if (bankState.ok) primary = `<button type="button" class="btn btn-ghost" onclick="openBankAdd()">Add another account</button>`;
  el.innerHTML = `${primary}<button type="button" class="btn btn-ghost" onclick="nav('payments')">View payment activity</button>`;
}

function openBankAdd() {
  const d = document.getElementById('bankAddSection');
  if (!d) return;
  d.open = true;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  d.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
  const inp = document.getElementById('bankName');
  if (inp) setTimeout(() => inp.focus(), reduce ? 0 : 200);
}

// ── Remove-account confirmation dialog (accessible: focus-trap, Escape, restore) ─
let _bankRemove = { id: null, trigger: null };
function openRemoveDialog(id) {
  const a = (bankState.accounts || []).find(x => x && String(x.id) === String(id));
  if (!a) return;
  _bankRemove = { id: String(id), trigger: document.activeElement };
  const masked = bankMask(a);
  const inst = esc(a.institution_name || 'Bank account');
  const primary = a.is_primary === true;
  const others = (bankState.accounts || []).filter(x => x && x.status === 'ACTIVE' && String(x.id) !== String(id)).length;
  const body = document.getElementById('bankRemoveBody');
  body.innerHTML = `<p>You're about to remove <strong>${inst} ${esc(masked)}</strong>.</p>
    <ul class="bank-remove-list">
      <li>Future contributions and payouts will need a connected, verified account.</li>
      ${primary && others ? '<li>Another linked account will automatically become your contribution account — check which one is primary afterward.</li>' : ''}
      ${primary && !others ? "<li>This is your only linked account — you'll need to connect a new one before you can contribute.</li>" : ''}
      <li>Your past payment history is kept — removing an account doesn't erase records.</li>
      <li>This can't be undone from here.</li>
    </ul>
    <p class="hint-muted">If a payment is in progress, removal may be declined to protect it.</p>`;
  document.getElementById('bankRemoveErr').style.display = 'none';
  const btn = document.getElementById('bankRemoveConfirm'); btn.disabled = false; btn.textContent = 'Remove account';
  // canClose blocks Escape mid-delete; closeRemoveDialog() blocks the cancel button too.
  SolDialog.open('bankRemoveDialog', { opener: _bankRemove.trigger, initialFocus: '.btn-ghost', canClose: () => !SolGuard.isLocked('bank:remove:' + (_bankRemove.id || '')), onClose: () => { _bankRemove = { id: null, trigger: null }; } });
}
function closeRemoveDialog(skipRestore) {
  // Block user-initiated close (Escape key OR the "Keep account" button) while a
  // removal is in flight; the success path passes skipRestore=true so it still closes.
  if (SolGuard.isLocked('bank:remove:' + (_bankRemove.id || '')) && !skipRestore) return;
  // On success we skip restore because loadBank() destroys the trigger; caller lands focus itself.
  SolDialog.close('bankRemoveDialog', { restoreFocus: !skipRestore });
  _bankRemove = { id: null, trigger: null };
}
async function confirmRemove() {
  const id = _bankRemove.id;
  if (!id || !SolGuard.acquire('bank:remove:' + id)) return;
  const btn = document.getElementById('bankRemoveConfirm'); btn.disabled = true; btn.textContent = 'Removing…';
  try {
    await api(`/bank/${id}`, { method: 'DELETE' });
    closeRemoveDialog(true);            // skip focus-restore: loadBank() destroys the trigger
    await loadBank();                   // re-fetch backend truth — never optimistically hide
    bankAnnounce('Account removed.');
    const h = document.getElementById('bankListHeading'); if (h) h.focus();   // land focus on a stable element
  } catch (e) {
    const err = document.getElementById('bankRemoveErr');
    err.textContent = (e && e.message) ? e.message : "We couldn't remove this account. Please try again.";
    err.style.display = 'block';
    btn.disabled = false; btn.textContent = 'Remove account';
    loadBank();                         // reconcile list with server truth (e.g. 404/409 already-removed)
  } finally { SolGuard.release('bank:remove:' + id); }
}
