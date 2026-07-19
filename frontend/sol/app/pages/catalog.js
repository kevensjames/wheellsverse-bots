// SOL member app — pages/catalog.js
// Phase 3 Increments 1–2 — Circle Catalog (mock-backed, flag-gated SOL_FEATURES
// .catalog). Inc 1: BROWSE admin-defined offerings + disclose the $9.99/mo SOL
// Circle participation subscription that gates JOINING (browsing is open to all).
// Inc 2: circle DETAIL + eligibility-driven, guarded JOIN. See docs/sol/PHASE3_API_CONTRACT.md.
//
// MONEY-SAFETY (this file renders money-adjacent info; it must not overstep):
//   • Backend-authoritative: joining access comes from /participation/me and
//     /catalog/{id}/eligibility (can_join); NEVER computed/optimistically granted.
//   • Joining never treats HTTP 200 alone as joined — membership is confirmed from
//     the response; no catalog/membership state is optimistically promoted.
//   • Browsing / opening a card RESERVES NOTHING; the entry fee + refund rule are
//     disclosed BEFORE any join action.
//   • NO guaranteed payout date or payout position is shown or implied.
//   • The $9.99 participation subscription is DISTINCT from circle contributions,
//     from the entry fee, and from the $14.99 Premium plan — never conflated.
//   • Still no checkout / refund / admin action here (later increments).

const CATALOG_STATUS = {
  OPEN:    { label: 'Open',    cls: 'active' },
  FORMING: { label: 'Forming', cls: 'forming' },
  FULL:    { label: 'Full',    cls: 'pending' },
  CLOSED:  { label: 'Closed',  cls: 'cancelled' },
};
function catalogStatus(s) {
  return CATALOG_STATUS[String(s || '').toUpperCase()] || { label: 'Unavailable', cls: 'completed' };
}

// Member-facing CONTRIBUTION frequency only — never a payout date. We deliberately
// do NOT surface payout_day_of_month here: it's a disbursement-timing field, and
// showing it pre-join would read as a payout-date signal (see invariant #3).
function catalogCadence(o) {
  const c = o.cadence;
  if (c === 'WEEKLY') return 'Weekly';
  if (c === 'BIWEEKLY') return 'Every 2 weeks';
  if (c === 'MONTHLY') return 'Monthly';
  if (c && typeof c === 'object' && c.kind === 'CUSTOM' && Number.isFinite(c.days)) return `Every ${esc(c.days)} days`;
  return 'Schedule set by the circle';
}

// Map one raw offering → a safe view model; returns null for malformed data so
// the page skips it rather than failing. No user_ids/PII are read or rendered.
function normalizeOffering(o) {
  if (!o || typeof o !== 'object' || Array.isArray(o)) return null;
  const id = (typeof o.id === 'string' && /^[0-9a-f-]{8,}$/i.test(o.id)) ? o.id : null;
  if (!id) return null;
  return {
    id,
    name: typeof o.name === 'string' && o.name.trim() ? o.name : 'Circle',
    description: typeof o.description === 'string' ? o.description : '',
    status: catalogStatus(o.status),
    // Money fields: require a finite, NON-NEGATIVE amount; anything else is unknown.
    contribution: Number.isFinite(o.contribution_cents) && o.contribution_cents >= 0 ? o.contribution_cents : null,
    // null = UNKNOWN (render "unavailable"); 0 = genuinely no fee. Never assert
    // "No entry fee" from absent/malformed data — that's a favorable money claim.
    entryFee: Number.isFinite(o.entry_fee_cents) && o.entry_fee_cents >= 0 ? o.entry_fee_cents : null,
    cadence: o.cadence,
    count: Number.isFinite(o.member_count) ? o.member_count : null,
    cap: Number.isFinite(o.max_members) ? o.max_members : null,
    isPrivate: o.is_private === true,
  };
}

// Participation subscription state — REFLECTED from the backend, never derived.
// can_join is THE gate decision; the client only renders it (default false).
function normalizeParticipation(p) {
  if (!p || typeof p !== 'object') return { ok: false };
  return {
    ok: true,
    canJoin: p.can_join === true,
    status: String(p.status || 'NONE').toUpperCase(),
    trialEnd: p.trial_end || null,
    priceCents: Number.isFinite(p.price_cents) ? p.price_cents : 999,
  };
}

let catalogState = { items: [], ok: false, part: { ok: false } };

async function loadCatalog(userInitiated) {
  if (!featureOn('catalog')) return;   // hard gate — dark unless SOL_FEATURES.catalog
  const list = document.getElementById('catalogList');
  if (!list) return;
  list.innerHTML = catalogSkeleton();
  // allSettled: browsing must survive a participation-state hiccup; a nav-abort
  // (P3) leaves this resilient (partial failure, not an error render).
  const [cRes, pRes] = await Promise.allSettled([api('/catalog'), api('/participation/me')]);
  if (_aborted(cRes.reason) || _aborted(pRes.reason)) return;   // navigation cancelled this load
  catalogState.ok = cRes.status === 'fulfilled' && Array.isArray(cRes.value);
  catalogState.items = catalogState.ok ? cRes.value.map(normalizeOffering).filter(Boolean) : [];
  catalogState.part = pRes.status === 'fulfilled' ? normalizeParticipation(pRes.value) : { ok: false };
  renderCatalog();
  if (userInitiated) catalogAnnounce(catalogState.ok ? 'Catalog refreshed.' : 'Catalog unavailable.');
}

function catalogAnnounce(msg) { const el = document.getElementById('catalogLiveStatus'); if (el) { el.textContent = ''; el.textContent = msg; } }
function catalogSkeleton() { return `<div class="catalog-grid">${Array.from({ length: 3 }).map(() => '<div class="catalog-card"><div class="spinner"></div></div>').join('')}</div>`; }

// Discloses the $9.99 participation subscription and REFLECTS the member's current
// joining access from /participation/me. Never grants or computes access here.
function catalogGateBanner() {
  const p = catalogState.part;
  const price = p && p.ok ? fmt$(p.priceCents) : '$9.99';
  const trialWhen = (p && p.ok && p.trialEnd) ? fmtDate(p.trialEnd) : '';   // '' if missing/invalid
  let state;
  if (!p || !p.ok) {
    state = '<p class="catalog-gate__state hint-muted">Your participation status is unavailable right now.</p>';
  } else if (p.canJoin && p.status === 'TRIALING') {
    state = `<p class="catalog-gate__state catalog-gate__state--ok">✓ You're on a free trial — full joining access${trialWhen ? ` until ${esc(trialWhen)}` : ''}.</p>`;
  } else if (p.canJoin) {
    state = '<p class="catalog-gate__state catalog-gate__state--ok">✓ Your participation subscription is active — you can join circles.</p>';
  } else if (p.status === 'PAST_DUE') {
    state = "<p class=\"catalog-gate__state\">Your participation subscription needs attention — joining is paused until it's resolved.</p>";
  } else if (p.status === 'NONE' || p.status === 'CANCELED' || p.status === 'CANCELLED') {
    state = "<p class=\"catalog-gate__state\">You don't have a participation subscription yet — you can still browse everything below.</p>";
  } else {
    // Any other non-join state (incl. a backend status/can_join disagreement, e.g.
    // TRIALING/ACTIVE with can_join:false): deny join with a NEUTRAL message —
    // never claim access, and never contradict the reported subscription status.
    state = "<p class=\"catalog-gate__state\">Joining isn't available on your current participation status — you can still browse everything below.</p>";
  }
  return `<section class="catalog-gate" aria-label="SOL Circle participation">
    <div class="catalog-gate__head">
      <h2 class="catalog-gate__title">Browsing is open — joining needs participation</h2>
      <span class="catalog-gate__price">${esc(price)}<span class="catalog-gate__per">/month</span></span>
    </div>
    <p class="catalog-gate__body">Anyone can browse the SOL Circle catalog. To <strong>join</strong> a circle you need an active <strong>SOL Circle participation</strong> subscription (or a free trial). Participation is separate from your circle contributions, from any entry fee, and from the SOL Premium plan.</p>
    ${state}
  </section>`;
}

function offeringCard(o) {
  const contribution = o.contribution != null ? fmt$(o.contribution) : '—';
  const members = (o.count != null && o.cap != null) ? `${esc(o.count)} / ${esc(o.cap)}` : '—';
  const fee = o.entryFee == null
    ? '<span class="hint-muted">Entry fee: unavailable</span>'
    : o.entryFee > 0
      ? `${fmt$(o.entryFee)} entry fee <span class="hint-muted">· refundable until the circle starts</span>`
      : 'No entry fee';
  const priv = o.isPrivate ? ' <span title="Private" aria-label="Private">🔒</span>' : '';
  return `<article class="catalog-card">
    <div class="catalog-card__top">
      <h3 class="catalog-card__name">${esc(o.name)}${priv}</h3>
      <span class="status status--${o.status.cls}">${esc(o.status.label)}</span>
    </div>
    ${o.description ? `<p class="catalog-card__desc">${esc(o.description)}</p>` : ''}
    <div class="catalog-card__figs">
      <div><span class="fig-label">Contribution</span><span class="fig-val tnum">${contribution}</span></div>
      <div><span class="fig-label">Cadence</span><span class="fig-val">${catalogCadence(o)}</span></div>
      <div><span class="fig-label">Members</span><span class="fig-val tnum">${members}</span></div>
    </div>
    <div class="catalog-card__fee">${fee}</div>
    <div class="catalog-card__act"><button type="button" class="btn btn-ghost btn--sm" aria-label="View details for ${esc(o.name)}" onclick="openCatalogDetail('${esc(o.id)}')">View details</button></div>
  </article>`;
}

function renderCatalog() {
  const el = document.getElementById('catalogList');
  if (!el) return;
  if (!catalogState.ok) {
    el.innerHTML = `${catalogGateBanner()}<div class="empty"><p>The catalog is unavailable right now.</p><button type="button" class="btn btn-ghost btn--sm" onclick="loadCatalog(true)">Retry</button></div>`;
    return;
  }
  const cards = catalogState.items.length
    ? `<div class="catalog-grid">${catalogState.items.map(offeringCard).join('')}</div>`
    : '<div class="empty"><p>No circles are open to browse right now. Check back soon.</p></div>';
  el.innerHTML = `${catalogGateBanner()}${cards}
    <p class="catalog-note hint-muted">Opening a circle shows its full details and, if you're eligible, lets you join. Browsing itself reserves nothing. Payout order and timing depend on each circle's rules and completing your contributions; no date or position is guaranteed.</p>`;
}

// ── Circle detail + join (Increment 2) ────────────────────────────────────────
// Read eligibility → guarded join, all backend-authoritative. Eligibility
// (/catalog/{id}/eligibility: can_join + checks) drives the CTA; the client only
// REFLECTS it. The entry fee + refund rule are disclosed in the body BEFORE the
// join. Joining never treats HTTP 200 alone as joined — membership is confirmed
// from the response — and no catalog/membership state is optimistically promoted.
const _catId = (s) => typeof s === 'string' && /^[0-9a-f-]{8,}$/i.test(s);
let catalogDetail = { id: null, offering: null, elig: null, trigger: null };

function normalizeCatalogEligibility(e) {
  if (!e || typeof e !== 'object') return null;
  const c = (e.checks && typeof e.checks === 'object') ? e.checks : {};
  return {
    canJoin: e.can_join === true,   // backend-authoritative; default false
    subscription: c.subscription === 'ok' ? 'ok' : 'todo',
    kyc: c.kyc === 'ok' ? 'ok' : 'todo',
    bank: c.bank === 'ok' ? 'ok' : 'todo',
    account: c.account === 'blocked' ? 'blocked' : 'ok',
    entryFee: Number.isFinite(e.entry_fee_cents) && e.entry_fee_cents >= 0 ? e.entry_fee_cents : null,
  };
}

async function openCatalogDetail(id) {
  if (!featureOn('catalog') || !_catId(id)) return;
  catalogDetail = { id, offering: null, elig: null, trigger: document.activeElement };
  document.getElementById('catalogDetailContent').innerHTML = '<div class="spinner"></div>';
  SolDialog.open('catalogDetailDialog', { opener: catalogDetail.trigger, initialFocus: false, onClose: () => { catalogDetail = { id: null, offering: null, elig: null, trigger: null }; } });
  // Move focus into the dialog during the async load so the trap engages and focus
  // isn't stranded on the background trigger while the spinner shows (mirror discover).
  const _m = document.querySelector('#catalogDetailDialog .modal');
  if (_m) { _m.setAttribute('tabindex', '-1'); try { _m.focus(); } catch (e) {} }
  const [oRes, eRes] = await Promise.allSettled([api(`/catalog/${id}`), api(`/catalog/${id}/eligibility`)]);
  if (catalogDetail.id !== id) return;   // dialog closed/replaced while loading — drop stale result
  catalogDetail.offering = oRes.status === 'fulfilled' ? normalizeOffering(oRes.value) : null;
  catalogDetail.elig = eRes.status === 'fulfilled' ? normalizeCatalogEligibility(eRes.value) : null;
  renderCatalogDetail();
}

function closeCatalogDetail() { SolDialog.close('catalogDetailDialog'); }

// Eligibility-driven CTA — REFLECTS the backend decision; never computes access.
// `fee` is the disclosable entry fee (eligibility-authoritative, else listing; null = unknown).
function catalogDetailCTA(o, el, id, fee) {
  if (!el) return '<button type="button" class="btn btn-ghost" disabled>Eligibility unavailable — try again shortly</button>';
  if (el.account === 'blocked') return `<button type="button" class="btn btn-ghost" onclick="closeCatalogDetail();nav('notifications')">Account inactive — get help</button>`;
  if (el.canJoin) {
    // NEVER offer a charge-triggering join action when the entry fee can't be
    // disclosed (invariant #3: fee disclosed BEFORE the join).
    if (fee == null) return '<button type="button" class="btn btn-ghost" disabled>Entry fee unavailable — try again shortly</button>';
    return `<button type="button" class="btn btn-primary" id="catJoinBtn" onclick="doCatalogJoin('${esc(id)}',this)">Confirm &amp; join this circle</button>`;
  }
  if (el.subscription === 'todo') return '<p class="catalog-cta-note">SOL Circle participation ($9.99/mo, or a free trial) is required to join. You can browse now — subscribing opens in a later update.</p>';
  if (el.kyc === 'todo') return `<button type="button" class="btn btn-primary" onclick="closeCatalogDetail();nav('kyc')">Verify your identity to join</button>`;
  if (el.bank === 'todo') return `<button type="button" class="btn btn-primary" onclick="closeCatalogDetail();nav('bank')">Connect a bank to join</button>`;
  return '<button type="button" class="btn btn-ghost" disabled>Joining unavailable</button>';
}

function renderCatalogDetail() {
  const content = document.getElementById('catalogDetailContent');
  const o = catalogDetail.offering, el = catalogDetail.elig, id = catalogDetail.id;
  if (!o) {
    content.innerHTML = '<h3 id="catDetailTitle">Circle unavailable</h3><p id="catDetailBody" class="hint-muted">We couldn\'t load this circle right now. Please try again.</p><div class="modal-actions"><button type="button" class="btn btn-ghost" onclick="closeCatalogDetail()">Close</button></div>';
    setTimeout(() => { const f = content.querySelector('button'); if (f) f.focus(); }, 0);
    return;
  }
  const contribution = o.contribution != null ? fmt$(o.contribution) : '—';
  const cadence = catalogCadence(o).toLowerCase();
  // Entry fee: the eligibility value is authoritative for THIS join; fall back to the listing.
  const fee = (el && el.entryFee != null) ? el.entryFee : o.entryFee;
  const feeLine = fee == null ? '<span class="hint-muted">unavailable</span>'
    : fee > 0 ? `${fmt$(fee)} <span class="hint-muted">· refundable until the circle starts</span>` : 'None';
  const members = (o.count != null && o.cap != null) ? `${esc(o.count)} / ${esc(o.cap)}` : '—';
  const priv = o.isPrivate ? ' <span title="Private" aria-label="Private">🔒</span>' : '';
  content.innerHTML = `
    <div class="disc-detail__head"><h3 id="catDetailTitle">${esc(o.name)}${priv}</h3><span class="status status--${o.status.cls}">${esc(o.status.label)}</span></div>
    ${o.description ? `<p class="disc-detail__desc">${esc(o.description)}</p>` : ''}
    <div id="catDetailBody">
      <dl class="disc-detail__facts">
        <div><dt>Contribution</dt><dd class="tnum">${contribution} <span class="hint-muted">${esc(cadence)}</span></dd></div>
        <div><dt>Members</dt><dd class="tnum">${members}</dd></div>
        <div><dt>Entry fee</dt><dd>${feeLine}</dd></div>
      </dl>
      <div class="disc-detail__rules"><h4>Before you join</h4><ul>
        <li>Joining creates a recurring contribution obligation of ${contribution} ${esc(cadence)} until the circle completes.</li>
        <li>SOL Circle participation ($9.99/mo, or a free trial) is required to join — separate from your contributions, the entry fee, and the SOL Premium plan.</li>
        ${fee != null && fee > 0 ? `<li>The ${fmt$(fee)} entry fee is refundable until the circle starts; once it activates it is non-refundable.</li>` : ''}
        <li>A circle is a savings arrangement, not an investment — no profit or guaranteed return. Payout order and timing depend on the circle's rules and completing your contributions; no date or position is guaranteed.</li>
      </ul></div>
      <div class="disc-detail__elig"><h4>Your eligibility</h4><ul class="disc-elig__list">
        ${discEligItem(el && el.subscription, 'SOL Circle participation', 'Participation required to join')}
        ${discEligItem(el && el.kyc, 'Identity verified', 'Verify your identity')}
        ${discEligItem(el && el.bank, 'Bank account connected', 'Connect a bank account')}
      </ul></div>
    </div>
    <p class="err" id="catDetailErr" role="alert" style="display:none"></p>
    <div class="modal-actions"><button type="button" class="btn btn-ghost" onclick="closeCatalogDetail()">Close</button>${catalogDetailCTA(o, el, id, fee)}</div>`;
  setTimeout(() => { const f = content.querySelector('.btn-ghost'); if (f) f.focus(); }, 0);
}

// Guarded join — mirrors discover confirmJoinCircle. Backend charges the entry fee,
// creates membership, and re-checks eligibility/capacity; HTTP 200 alone is NOT
// treated as joined, and no catalog/membership state is optimistically promoted.
async function doCatalogJoin(id, btn) {
  if (!featureOn('catalog') || !_catId(id) || !SolGuard.acquire('catalog:join:' + id)) return;   // flag-gated + per-circle guard (joining A never blocks B)
  const dlg = document.getElementById('catalogDetailDialog'); if (dlg) dlg.dataset.busy = '1';
  const err = document.getElementById('catDetailErr'); if (err) err.style.display = 'none';
  if (btn) { btn.disabled = true; btn.textContent = 'Joining…'; }
  try {
    const r = await api(`/catalog/${id}/join`, { method: 'POST' });   // mutation — never cancelled by navigation
    const joined = r && Array.isArray(r.members) && !!(me && me.id) && r.members.some(m => m && m.user_id === me.id);
    catalogAnnounce(joined ? 'You joined the circle.' : 'Your join request was received.');
    if (dlg) dlg.dataset.busy = '0';
    closeCatalogDetail();
    nav('groups');   // show the member their circles from backend truth — no optimistic catalog mutation
  } catch (ex) {
    if (err) { err.textContent = catalogJoinError(ex); err.style.display = 'block'; }
    if (btn) { btn.disabled = false; btn.innerHTML = 'Confirm &amp; join this circle'; }
    if (dlg) dlg.dataset.busy = '0';
  } finally { SolGuard.release('catalog:join:' + id); }
}

// Map a join failure to safe, actionable guidance — never surface raw provider detail.
function catalogJoinError(ex) {
  const m = (ex && ex.message) ? String(ex.message) : '';
  if (/already a member|already joined/i.test(m)) return "You're already a member of this circle.";
  if (/full|capacity/i.test(m)) return 'This circle just filled up. Try another open circle.';
  if (/participation|subscription/i.test(m)) return 'SOL Circle participation is required to join.';
  if (/kyc|identity/i.test(m)) return 'Complete identity verification first.';
  if (/bank/i.test(m)) return 'You need a verified bank account before joining.';
  if (/account status|inactive|not active/i.test(m)) return 'Your account is not active. Please contact support.';
  return safeError(ex);
}
