// SOL member app — pages/kyc.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ═══ Verify ID / KYC — high-trust identity-verification center ════════════════
// Canonical KYC-state model. The backend KYCStatus enum is exactly
// PENDING | SUBMITTED | VERIFIED | REJECTED (app/models/user.py); the ONLY field
// /kyc/submit accepts that affects verification is date_of_birth (address is
// declared but never sent to the provider, and legal name comes from the account
// — so we collect ONLY date of birth and never simulate document/selfie/SSN steps
// the backend doesn't support). SUBMITTED is NEVER shown as VERIFIED, and a
// successful POST is never treated as final verification — status is read from
// the backend response only. Unrecognized/missing → UNKNOWN ("Status unavailable"),
// never defaulted to PENDING.
const KYC_STATE = {
  PENDING:   { key:'PENDING',   title:'Verification required', chip:'pending',  chipLabel:'Verification required', lead:'Confirm your date of birth to verify your identity.' },
  SUBMITTED: { key:'SUBMITTED', title:'Under review',          chip:'active',   chipLabel:'Under review',          lead:'Your information was submitted and is being reviewed.' },
  VERIFIED:  { key:'VERIFIED',  title:'Identity verified',     chip:'verified', chipLabel:'Verified',              lead:'Your identity has been verified.' },
  REJECTED:  { key:'REJECTED',  title:'Action required',       chip:'warning',  chipLabel:'Action required',       lead:"We couldn't verify your identity with the details provided." },
  UNKNOWN:   { key:'UNKNOWN',   title:'Status unavailable',    chip:'pending',  chipLabel:'Status unavailable',    lead:"We can't load your verification status right now." },
};
function normalizeKycState(raw) {
  const k = String(raw || '').toUpperCase();
  if (k === 'VERIFIED' || k === 'APPROVED') return KYC_STATE.VERIFIED;
  if (k === 'SUBMITTED') return KYC_STATE.SUBMITTED;
  if (k === 'REJECTED' || k === 'DECLINED') return KYC_STATE.REJECTED;
  if (k === 'PENDING') return KYC_STATE.PENDING;
  return KYC_STATE.UNKNOWN;   // missing/unrecognized — never assume PENDING
}
function kycAnnounce(msg) { const el = document.getElementById('kycLiveStatus'); if (el) { el.textContent = ''; el.textContent = msg; } }

// Focus a stable landmark after an innerHTML swap so keyboard/SR users aren't dumped to <body>.
function kycLandFocus() { const h = document.getElementById('kycHeroTitle') || document.getElementById('kycFbTitle'); if (h && h.focus) { try { h.focus(); } catch (e) {} } }

async function loadKYC(userInitiated) {
  const el = document.getElementById('kycContent');
  if (!el) return;
  el.innerHTML = kycSkeleton();
  let raw = null, ok = false;
  try { const m = await api('/auth/me'); if (m && typeof m === 'object') { me = m; raw = m.kyc_status; ok = true; } }
  catch (e) { if (_aborted(e)) return; ok = false; }
  const st = ok ? normalizeKycState(raw) : KYC_STATE.UNKNOWN;
  el.innerHTML = renderKyc(st);
  if (userInitiated) {   // a Refresh/Retry — announce the resulting state and land focus (the clicked button is gone)
    kycAnnounce(st.key === 'VERIFIED' ? 'Identity verified.' : st.title);
    kycLandFocus();
  }
}

function renderKyc(st) {
  return `<div class="kyc-grid">
    <div class="kyc-main">
      ${kycHero(st)}
      ${kycStatePanel(st)}
    </div>
    <aside class="kyc-side">
      ${kycWhyPanel()}
      ${kycPrivacyPanel()}
      ${kycHelpPanel()}
    </aside>
  </div>`;
}

function kycHero(st) {
  let actions = '';
  if (st.key === 'PENDING')       actions = `<button type="button" class="btn btn-primary" onclick="kycFocusForm()">Start verification</button>`;
  else if (st.key === 'REJECTED') actions = `<button type="button" class="btn btn-primary" onclick="kycFocusForm()">Try again</button><button type="button" class="btn btn-ghost" onclick="nav('notifications')">Get help</button>`;
  else if (st.key === 'SUBMITTED')actions = `<button type="button" class="btn btn-ghost" onclick="loadKYC(true)">Refresh status</button><button type="button" class="btn btn-ghost" onclick="nav('notifications')">Get help</button>`;
  else if (st.key === 'UNKNOWN')  actions = `<button type="button" class="btn btn-primary" onclick="loadKYC(true)">Retry</button>`;
  return `<section class="kyc-hero kyc-hero--${st.chip}" aria-labelledby="kycHeroTitle">
    <div class="kyc-hero__icon" aria-hidden="true"><svg class="ic"><use href="#ic-verify"/></svg></div>
    <div class="kyc-hero__body">
      <span class="status status--${st.chip}">${esc(st.chipLabel)}</span>
      <h2 id="kycHeroTitle" class="kyc-hero__title" tabindex="-1">${esc(st.title)}</h2>
      <p class="kyc-hero__lead">${esc(st.lead)}</p>
      ${actions ? `<div class="kyc-hero__actions">${actions}</div>` : ''}
    </div>
  </section>`;
}

function kycStatePanel(st) {
  if (st.key === 'VERIFIED')  return kycVerifiedPanel();
  if (st.key === 'SUBMITTED') return kycReviewPanel();
  if (st.key === 'REJECTED')  return kycFormPanel(true);
  if (st.key === 'PENDING')   return kycFormPanel(false);
  return kycUnknownPanel();
}

function kycFormPanel(rejected) {
  const maxDate = new Date().toISOString().slice(0, 10);
  return `<section class="kyc-panel" aria-labelledby="kycFormTitle">
    ${rejected ? `<div class="kyc-reject"><strong>We could not verify your identity.</strong><p>We could not verify the submitted information. Review your details and try again, or contact support.</p></div>` : ''}
    <h3 id="kycFormTitle">${rejected ? 'Try verification again' : 'Confirm your details'}</h3>
    <p class="hint-muted">We use your date of birth and the legal name on your account to confirm your identity. We never display these back to you in full.</p>
    <form id="kycForm" onsubmit="submitKyc(event)" novalidate>
      <div class="field">
        <label for="kDob">Date of birth</label>
        <input id="kDob" type="date" class="input" autocomplete="bday" max="${maxDate}" aria-describedby="kDobHelp kDobErr" required>
        <p id="kDobHelp" class="field-help">You must be at least 18 to verify.</p>
        <p id="kDobErr" class="err" style="display:none" role="alert"></p>
      </div>
      <p class="kyc-errsum err" id="kycErr" tabindex="-1" role="alert" style="display:none"></p>
      <button type="submit" class="btn btn-primary" id="kBtn">${rejected ? 'Resubmit for verification' : 'Submit for verification'}</button>
    </form>
    ${kycWhatNextPanel()}
  </section>`;
}

function kycReviewPanel() {
  return `<section class="kyc-panel" aria-labelledby="kycReviewTitle">
    <h3 id="kycReviewTitle">Your verification is under review</h3>
    <p>We've received your information and it's being reviewed. Your status will update here automatically when the review is complete.</p>
    <ul class="kyc-meanwhile">
      <li>You don't need to resubmit — one submission is enough.</li>
      <li>You can keep exploring circles while you wait.</li>
    </ul>
    <div class="kyc-panel__actions">
      <button type="button" class="btn btn-ghost" onclick="loadKYC(true)">Refresh status</button>
      <button type="button" class="btn btn-ghost" onclick="nav('notifications')">Get help</button>
    </div>
  </section>`;
}

function kycVerifiedPanel() {
  return `<section class="kyc-panel" aria-labelledby="kycVerifiedTitle">
    <h3 id="kycVerifiedTitle">You're verified</h3>
    <p>Your identity has been verified. Identity verification is one step — connecting and verifying a bank account is separate and may still be needed before you can contribute.</p>
    <div class="kyc-links">
      <button type="button" class="btn btn-ghost" onclick="nav('bank')">Bank &amp; payment methods</button>
      <button type="button" class="btn btn-ghost" onclick="nav('payments')">Payments</button>
      <button type="button" class="btn btn-ghost" onclick="nav('groups')">Circles</button>
    </div>
  </section>`;
}

function kycUnknownPanel() {
  return `<section class="kyc-panel" aria-labelledby="kycUnknownTitle">
    <h3 id="kycUnknownTitle">Status unavailable</h3>
    <p class="hint-muted">We couldn't load your verification status right now — please try again in a moment.</p>
    <button type="button" class="btn btn-primary" onclick="loadKYC(true)">Retry</button>
  </section>`;
}

function kycWhatNextPanel() {
  return `<div class="kyc-next">
    <h4>What happens next</h4>
    <ol class="kyc-steps">
      <li>Enter your date of birth.</li>
      <li>We review your details to confirm your identity.</li>
      <li>Your status updates here — no need to check your email.</li>
    </ol>
  </div>`;
}

function kycWhyPanel() {
  return `<div class="side-card">
    <h3>Why we verify</h3>
    <ul class="kyc-why">
      <li>Confirm you own this account.</li>
      <li>Help reduce fraud across circles.</li>
      <li>Meet requirements for eligible payment features.</li>
    </ul>
  </div>`;
}

function kycPrivacyPanel() {
  return `<div class="side-card">
    <h3>Your privacy</h3>
    <ul class="kyc-why">
      <li>We ask for your date of birth; your legal name comes from your account.</li>
      <li>We never display sensitive details back to you in full.</li>
      <li>Identity checks may be handled by a verification provider.</li>
    </ul>
    <p class="hint-muted" style="margin-top:.6rem">Questions about your data? <button type="button" class="link-btn" onclick="nav('notifications')">Contact support</button>.</p>
  </div>`;
}

function kycHelpPanel() {
  return `<div class="side-card">
    <h3>Need help?</h3>
    <p class="hint-muted">Having trouble verifying? We can help you get unblocked.</p>
    <button type="button" class="btn btn-ghost btn--sm" onclick="nav('notifications')">Get support</button>
  </div>`;
}

function kycSkeleton() {
  return `<div class="kyc-grid"><div class="kyc-main">
    <section class="kyc-hero"><div class="kyc-hero__icon"></div><div class="kyc-hero__body" style="flex:1"><span class="sk sk-line" style="width:30%"></span><span class="sk sk-line" style="width:55%;height:1.6rem;margin-top:.4rem"></span><span class="sk sk-line" style="width:80%;margin-top:.4rem"></span></div></section>
    <section class="kyc-panel"><span class="sk sk-line" style="width:40%"></span><span class="sk sk-block" style="margin-top:.6rem"></span></section>
  </div><aside class="kyc-side"><div class="side-card"><span class="sk sk-line" style="width:50%"></span><span class="sk sk-block" style="margin-top:.6rem"></span></div></aside></div>`;
}

function kycFocusForm() {
  const inp = document.getElementById('kDob');
  if (!inp) return;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  inp.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'center' });
  setTimeout(() => inp.focus(), reduce ? 0 : 180);
}

function validateDob(dob) {
  if (!dob) return 'Enter your date of birth.';
  const d = new Date(dob);
  if (isNaN(d.getTime())) return 'Enter a valid date.';
  const today = new Date(); today.setHours(0, 0, 0, 0);
  if (d > today) return 'Date of birth cannot be in the future.';
  const age = (today - d) / (365.25 * 24 * 3600 * 1000);
  if (age < 18) return 'You must be at least 18 to verify your identity.';
  if (age > 120) return 'Enter a valid date of birth.';
  return null;
}

// Map to a safe, generic message — never surface raw provider/vendor payloads.
function kycSafeError(ex) {
  const m = (ex && ex.message) ? String(ex.message) : '';
  if (/already verified/i.test(m)) return 'Your identity is already verified.';
  return "We couldn't submit your verification. Please check your details and try again, or contact support.";
}

async function submitKyc(e) {
  if (e && e.preventDefault) e.preventDefault();
  if (SolGuard.isLocked('kyc:submit')) return;
  const dobEl = document.getElementById('kDob');
  const dobErr = document.getElementById('kDobErr');
  const errSum = document.getElementById('kycErr');
  if (dobErr) dobErr.style.display = 'none';
  if (errSum) errSum.style.display = 'none';
  const dob = dobEl ? dobEl.value : '';
  const invalid = validateDob(dob);
  if (invalid) { if (dobErr) { dobErr.textContent = invalid; dobErr.style.display = 'block'; } if (dobEl) dobEl.focus(); return; }
  SolGuard.acquire('kyc:submit');   // sync validation above returned already if in-flight; acquire after it (no stuck lock on invalid DOB)
  const btn = document.getElementById('kBtn');
  const label = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'Submitting…'; }
  try {
    // Only date_of_birth is sent — the sole field the provider actually uses.
    // Not persisted to storage, not logged, not echoed back after submission.
    const resp = await api('/kyc/submit', { method: 'POST', body: JSON.stringify({ date_of_birth: dob }) });
    let status = (resp && typeof resp.kyc_status === 'string') ? resp.kyc_status : null;   // backend truth only
    if (status) { me = me || {}; me.kyc_status = status; }
    else {
      // POST accepted but status unreadable — try one refresh, else honest fallback.
      try { const m = await api('/auth/me'); if (m && m.kyc_status) { me = m; status = m.kyc_status; } } catch (_) {}
    }
    SolGuard.release('kyc:submit');
    if (status) {
      // Render the exact status the backend returned for THIS submission — not an
      // optimistic guess and not a second /auth/me fetch that could lag or fail.
      const st = normalizeKycState(status);
      kycAnnounce(st.key === 'VERIFIED' ? 'Identity verified.' : 'Verification submitted.');
      const cEl = document.getElementById('kycContent');
      if (cEl) { cEl.innerHTML = renderKyc(st); kycLandFocus(); }   // form + entered DOB removed — never echoed back
    } else {
      renderKycSubmittedFallback();             // POST ok but status unreadable — never PENDING, never VERIFIED
    }
  } catch (ex) {
    const msg = kycSafeError(ex);
    if (/already verified/i.test((ex && ex.message) || '')) { SolGuard.release('kyc:submit'); loadKYC(); return; }
    if (errSum) { errSum.textContent = msg; errSum.style.display = 'block'; if (errSum.focus) errSum.focus(); }
    if (btn) { btn.disabled = false; btn.textContent = label || 'Submit for verification'; }   // DOB preserved for retry
    SolGuard.release('kyc:submit');
  }
}

// POST succeeded but the status couldn't be read — honest interim state (not PENDING, not VERIFIED).
function renderKycSubmittedFallback() {
  const el = document.getElementById('kycContent');
  if (!el) return;
  el.innerHTML = `<div class="kyc-grid"><div class="kyc-main">
    <section class="kyc-panel" aria-labelledby="kycFbTitle">
      <span class="status status--active">Submitted</span>
      <h2 id="kycFbTitle" class="kyc-fb-title" tabindex="-1">Submission received</h2>
      <p>Your information was submitted. Your verification status is temporarily unavailable — refresh in a moment to see the latest.</p>
      <button type="button" class="btn btn-ghost" onclick="loadKYC(true)">Refresh status</button>
    </section></div>
    <aside class="kyc-side">${kycWhyPanel()}${kycPrivacyPanel()}${kycHelpPanel()}</aside></div>`;
  kycAnnounce('Submission received. Status temporarily unavailable.');
  kycLandFocus();
}
