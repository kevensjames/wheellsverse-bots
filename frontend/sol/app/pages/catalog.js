// SOL member app — pages/catalog.js
// Phase 3 Increment 1 — Circle Catalog BROWSE (read-only, mock-backed, flag-gated
// SOL_FEATURES.catalog). Lists admin-defined circle offerings and discloses the
// $9.99/mo SOL Circle participation subscription that gates JOINING (browsing is
// open to everyone). See docs/sol/PHASE3_API_CONTRACT.md.
//
// MONEY-SAFETY (this file renders money-adjacent info; it must not overstep):
//   • Backend-authoritative: joining access comes from /participation/me
//     (can_join); NEVER computed client-side, NEVER optimistically granted.
//   • Browsing / selecting / opening a card RESERVES NOTHING — stated in copy.
//   • NO guaranteed payout date or payout position is shown or implied.
//   • The $9.99 participation subscription is DISTINCT from circle contributions,
//     from the entry fee, and from the $14.99 Premium plan — never conflated.
//   • Entry fee disclosed as "refundable until the circle starts".
//   • READ-ONLY increment: no join, checkout, refund, or admin action here.

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
    <p class="catalog-note hint-muted">Browsing is read-only — opening or selecting a circle doesn't reserve a place or a payout position. Payout order and timing depend on each circle's rules and completing your contributions; no date or position is guaranteed. Joining opens in a later update.</p>`;
}
