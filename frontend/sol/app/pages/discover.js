// SOL member app — pages/discover.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── Discover / SOL Match ────────────────────────────────────────────────────────
const FREQ_LABEL = { WEEKLY:'Weekly', BIWEEKLY:'Bi-weekly', MONTHLY:'Monthly' };
// ═══ Discover circles — trustworthy discovery + SOL Match ═════════════════════
// Backend truth: GET /groups returns PUBLIC circles + the caller's private ones
// (member_count computed). Join (POST /groups/{id}/join) is IMMEDIATE membership,
// and the backend ENFORCES: KYC VERIFIED + account ACTIVE + >=1 ACTIVE bank + group
// FORMING + not full + not already a member + not private. Nothing is joinable
// merely because it is visible; the backend re-checks eligibility + capacity on
// join. GroupDetailOut carries members whose user_ids are PRIVATE — never rendered
// (only used to detect the caller's own membership via me.id). SOL Match: POST
// /circles/reserve matches you into a circle (MATCHED) or waitlists you
// (WAITLISTED); GET /circles/waitlist/me lists live entries. No guaranteed-payout
// language: a circle is a savings arrangement, not an investment.
const DISC_AVAIL = {
  OPEN:          { label:'Open to join', chip:'active',    joinable:true },
  LIMITED:       { label:'',             chip:'warning',   joinable:true },
  FULL:          { label:'Full',         chip:'cancelled', joinable:false },
  LOCKED:        { label:'Invite-only',  chip:'pending',   joinable:false },
  ACTIVE_CLOSED: { label:'Active — closed to new members', chip:'pending', joinable:false },
  PAUSED:        { label:'Paused',       chip:'pending',   joinable:false },
  COMPLETED:     { label:'Completed',    chip:'verified',  joinable:false },
  CANCELLED:     { label:'Unavailable',  chip:'cancelled', joinable:false },
  UNKNOWN:       { label:'Status unavailable', chip:'pending', joinable:false },
};
function normalizeAvailability(g) {
  const s = String(g && g.status || '').toUpperCase();
  const cap = Number.isFinite(g && g.max_members) ? g.max_members : null;
  const cnt = Number.isFinite(g && g.member_count) ? g.member_count : null;
  const spots = (cap != null && cnt != null) ? Math.max(0, cap - cnt) : null;
  let key;
  if (s === 'FORMING') { key = g.is_private ? 'LOCKED' : (spots === 0 ? 'FULL' : (spots != null && spots <= 3 ? 'LIMITED' : 'OPEN')); }
  else if (s === 'ACTIVE') key = 'ACTIVE_CLOSED';
  else if (s === 'PAUSED') key = 'PAUSED';
  else if (s === 'COMPLETED') key = 'COMPLETED';
  else if (s === 'FAILED' || s === 'CANCELLED') key = 'CANCELLED';
  else key = 'UNKNOWN';
  const base = DISC_AVAIL[key];
  const label = key === 'LIMITED' ? `${spots} spot${spots === 1 ? '' : 's'} left` : base.label;
  return { key, label, chip: base.chip, joinable: base.joinable, spots, cap, cnt };
}
function normalizeEligibility(m, meOk, banks, banksOk) {
  const acct = meOk ? String(m && m.account_status || 'ACTIVE').toUpperCase() : null;
  const kyc = !meOk ? 'unknown' : (String(m && m.kyc_status || '').toUpperCase() === 'VERIFIED' ? 'ok' : 'todo');
  const activeBanks = (banksOk && Array.isArray(banks)) ? banks.filter(b => b && b.status === 'ACTIVE') : [];
  const bank = !banksOk ? 'unknown' : (activeBanks.length ? 'ok' : 'todo');
  const acctBlocked = meOk && acct !== 'ACTIVE';   // backend also enforces account_status === ACTIVE on join
  return { kyc, bank, acctBlocked, eligible: kyc === 'ok' && bank === 'ok' && !acctBlocked, unknown: kyc === 'unknown' || bank === 'unknown' };
}
// The backend deducts a platform fee (fee_bps) from the payout — the recipient
// receives the NET, never the gross pool. Never show gross as "what you receive".
function discFeePct(g) { return Number.isFinite(g && g.fee_bps) ? (g.fee_bps / 100) : null; }
function discNetPayout(g, cap) {
  if (!Number.isFinite(g && g.contribution_cents) || cap == null) return null;
  const fee = Number.isFinite(g.fee_bps) ? g.fee_bps : 0;
  return Math.round(g.contribution_cents * cap * (1 - fee / 10000));
}
function discEligItem(state, okText, todoText) {
  const s = state || 'unknown';
  const mark = s === 'ok' ? '✓' : (s === 'unknown' ? '?' : '○');
  const txt = s === 'ok' ? okText : (s === 'unknown' ? (okText + ' — status unavailable') : todoText);
  return `<li class="disc-elig__item"><span class="disc-elig__mark disc-elig__mark--${s}" aria-hidden="true">${mark}</span><span>${esc(txt)}</span></li>`;
}
function discAnnounce(msg) { const el = document.getElementById('discLiveStatus'); if (el) { el.textContent = ''; el.textContent = msg; } }

let discState = { groups: [], ok: false, elig: null, waitlist: [], waitOk: false, search: '', hideFull: false };

async function loadDiscover() {
  const list = document.getElementById('discList'); if (!list) return;
  const d = document.getElementById('mDate'); if (d && !d.value) d.value = new Date(Date.now() + 30 * 864e5).toISOString().slice(0, 10);
  list.innerHTML = discSkeleton();
  const [gRes, meRes, bRes, wRes] = await Promise.allSettled([ api('/groups?status=FORMING'), api('/auth/me'), api('/bank/list'), api('/circles/waitlist/me') ]);
  discState.ok = gRes.status === 'fulfilled' && Array.isArray(gRes.value);
  const rawGroups = discState.ok ? gRes.value : [];
  const meOk = meRes.status === 'fulfilled' && meRes.value && typeof meRes.value === 'object';
  if (meOk) me = meRes.value;
  const banksOk = bRes.status === 'fulfilled' && Array.isArray(bRes.value);
  discState.elig = normalizeEligibility(meOk ? me : null, meOk, banksOk ? bRes.value : [], banksOk);
  discState.waitOk = wRes.status === 'fulfilled' && Array.isArray(wRes.value);
  discState.waitlist = discState.waitOk ? wRes.value : [];
  // Discovery universe: PUBLIC FORMING circles, test-filtered, excluding ones I created.
  const myId = me && me.id;
  discState.groups = rawGroups.filter(g => g && !isTestCircle(g) && String(g.status || '').toUpperCase() === 'FORMING' && !g.is_private && g.created_by !== myId);
  renderDiscElig(); renderDiscWaitlist(); renderDiscList();
}

function renderDiscElig() {
  const el = document.getElementById('discElig'); if (!el) return;
  const e = discState.elig; if (!e) { el.innerHTML = ''; return; }
  const chip = e.eligible ? 'verified' : (e.unknown ? 'pending' : 'warning');
  const label = e.eligible ? 'Eligible to join' : (e.unknown ? 'Eligibility unavailable' : 'Action needed to join');
  const lead = e.eligible ? 'You can join open circles below.' : (e.unknown ? "We can't confirm your eligibility right now — you can still open a circle to see details." : 'Complete these steps to join a circle. The backend confirms eligibility when you join.');
  el.innerHTML = `<div class="disc-elig__head"><span class="status status--${chip}">${esc(label)}</span><span class="disc-elig__lead">${esc(lead)}</span></div>
    <ul class="disc-elig__list">
      ${discEligItem(e.kyc, 'Identity verified', 'Verify your identity')}${e.kyc === 'todo' ? '<li class="disc-elig__cta"><button type="button" class="link-btn" onclick="nav(\'kyc\')">Verify ID</button></li>' : ''}
      ${discEligItem(e.bank, 'Bank account connected', 'Connect a bank account')}${e.bank === 'todo' ? '<li class="disc-elig__cta"><button type="button" class="link-btn" onclick="nav(\'bank\')">Connect bank</button></li>' : ''}
      ${e.acctBlocked ? '<li class="disc-elig__item"><span class="disc-elig__mark disc-elig__mark--todo" aria-hidden="true">!</span><span>Your account isn\'t active</span></li><li class="disc-elig__cta"><button type="button" class="link-btn" onclick="nav(\'notifications\')">Get help</button></li>' : ''}
    </ul>`;
}

function renderDiscWaitlist() {
  const el = document.getElementById('discWaitlist'); if (!el) return;
  if (!discState.waitOk || !discState.waitlist.length) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="side-card disc-waitlist"><h3>Your waitlist</h3><ul class="disc-waitlist__list">${discState.waitlist.map(w => `<li><span>${esc(FREQ_LABEL[w.frequency] || w.frequency)} · ${Number.isFinite(w.contribution_cents) ? fmt$(w.contribution_cents) : '—'}/cycle</span>${Number.isFinite(w.position) ? `<span class="hint-muted">Queue position ${w.position}</span>` : ''}</li>`).join('')}</ul><p class="hint-muted">We'll place you when a compatible circle forms. A waitlist spot isn't a membership, and the timing isn't guaranteed.</p></div>`;
}

function discCard(g) {
  const av = normalizeAvailability(g);
  const id = _goalUuid(g && g.id) ? g.id : null;
  const nm = esc(g.name || 'Circle');
  const contrib = Number.isFinite(g.contribution_cents) ? fmt$(g.contribution_cents) : '—';
  const net = discNetPayout(g, av.cap);
  const payoutStr = net != null ? fmt$(net) : '—';
  const day = Number.isFinite(g.payout_day_of_month) ? g.payout_day_of_month : null;
  const membersStr = (av.cnt != null && av.cap != null) ? `${av.cnt} / ${av.cap}` : '—';
  const capPct = (av.cap && av.cnt != null) ? Math.min(100, Math.round(av.cnt / av.cap * 100)) : 0;
  let action;
  if (!id) action = '<span class="hint-muted">Details unavailable</span>';
  else if (!av.joinable) action = `<button type="button" class="btn btn-ghost btn--sm" ${av.key === 'FULL' ? 'disabled' : `aria-label="View details for ${nm}" onclick="openCircleDetail('${esc(id)}')"`}>${av.key === 'FULL' ? 'Full' : 'View details'}</button>`;
  else if (discState.elig && discState.elig.acctBlocked) action = `<button type="button" class="btn btn-ghost btn--sm" onclick="nav('notifications')">Account inactive</button>`;
  else if (discState.elig && discState.elig.kyc === 'todo') action = `<button type="button" class="btn btn-ghost btn--sm" onclick="nav('kyc')">Verify ID to join</button>`;
  else if (discState.elig && discState.elig.bank === 'todo') action = `<button type="button" class="btn btn-ghost btn--sm" onclick="nav('bank')">Connect bank to join</button>`;
  else action = `<button type="button" class="btn btn-primary btn--sm" aria-label="View details for ${nm}" onclick="openCircleDetail('${esc(id)}')">View details</button>`;
  return `<li class="disc-card">
    <div class="disc-card__head">
      <div class="disc-card__id"><div class="disc-card__name">${nm}</div>${g.description ? `<div class="disc-card__desc">${esc(g.description)}</div>` : ''}</div>
      <span class="status status--${av.chip}">${esc(av.label)}</span>
    </div>
    <div class="disc-card__facts">
      <div><span class="disc-card__k">Contribution</span><span class="disc-card__v tnum">${contrib}<span class="disc-card__per">/cycle</span></span></div>
      <div><span class="disc-card__k">Members</span><span class="disc-card__v tnum">${membersStr}</span></div>
      <div><span class="disc-card__k">Cadence</span><span class="disc-card__v">${day ? `Monthly · day ${day}` : 'Monthly'}</span></div>
      <div><span class="disc-card__k">Payout to recipient</span><span class="disc-card__v tnum">${payoutStr}</span></div>
    </div>
    ${(av.key === 'LIMITED' || av.key === 'FULL') && av.cap ? `<div class="pbar disc-card__cap" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${capPct}" aria-label="${av.cnt} of ${av.cap} spots filled"><div class="pbar__fill" style="width:${capPct}%"></div></div>` : ''}
    <div class="disc-card__acts">${action}</div>
  </li>`;
}

function renderDiscList() {
  const el = document.getElementById('discList'); const cEl = document.getElementById('discCount'); if (!el) return;
  if (!discState.ok) {
    if (cEl) cEl.textContent = '';
    el.innerHTML = `<div class="notif-empty"><div class="notif-empty__title">Circles are temporarily unavailable</div><p class="hint-muted">We couldn't load available circles. Please try again.</p><button type="button" class="btn btn-ghost btn--sm" onclick="loadDiscover()">Retry</button></div>`;
    return;
  }
  let items = discState.groups.slice();
  const q = discState.search.trim().toLowerCase();
  if (q) items = items.filter(g => String(g.name || '').toLowerCase().includes(q));
  if (discState.hideFull) items = items.filter(g => normalizeAvailability(g).key !== 'FULL');
  items.sort((a, b) => { const aa = normalizeAvailability(a), bb = normalizeAvailability(b); if (aa.joinable !== bb.joinable) return aa.joinable ? -1 : 1; const sa = aa.spots == null ? -1 : aa.spots, sb = bb.spots == null ? -1 : bb.spots; if (sb !== sa) return sb - sa; return String(a.name || '').localeCompare(String(b.name || '')); });
  if (cEl) cEl.textContent = `${items.length} ${items.length === 1 ? 'circle' : 'circles'}`;
  if (!items.length) { el.innerHTML = `<div class="notif-empty"><div class="notif-empty__title">No circles currently match these filters.</div><div class="goal-empty-acts"><button type="button" class="btn btn-ghost btn--sm" onclick="discResetFilters()">Reset filters</button><button type="button" class="btn btn-ghost btn--sm" onclick="nav('groups')">View my circles</button></div></div>`; return; }
  el.innerHTML = `<ul class="disc-grid">${items.map(discCard).join('')}</ul>`;
}
function discSetSearch(v) { discState.search = v || ''; renderDiscList(); }
function discSetHideFull(v) { discState.hideFull = !!v; renderDiscList(); }
function discResetFilters() { discState.search = ''; discState.hideFull = false; const s = document.getElementById('discSearch'); if (s) s.value = ''; const h = document.getElementById('discHideFull'); if (h) h.checked = false; renderDiscList(); }
function discSkeleton() { return `<ul class="disc-grid">${Array.from({ length: 3 }).map(() => `<li class="disc-card"><span class="sk sk-line" style="width:50%"></span><span class="sk sk-line" style="width:75%;margin-top:.4rem"></span><span class="sk sk-block" style="margin-top:.6rem"></span></li>`).join('')}</ul>`; }

// ── Circle detail / pre-join review dialog ───────────────────────────────────
let _discDetailId = null, _discJoinBusy = false, _discDlgTrigger = null;
async function openCircleDetail(id) {
  if (!_goalUuid(id)) return;
  _discDetailId = id; _discDlgTrigger = document.activeElement;
  const dlg = document.getElementById('circleDetailDialog'); const content = document.getElementById('circleDetailContent');
  dlg.dataset.busy = '0'; content.innerHTML = '<div class="spinner"></div>'; dlg.classList.add('is-open');
  document.addEventListener('keydown', _discTrapKey, true);
  const modal = dlg.querySelector('.modal'); if (modal) { modal.setAttribute('tabindex', '-1'); modal.focus(); }   // move focus into the dialog during the async load
  try { const g = await api(`/groups/${id}`); renderCircleDetail(g); }
  catch (e) {
    content.innerHTML = `<h3 id="cdTitle">Circle unavailable</h3><p id="cdBody" class="hint-muted">We couldn't load this circle right now. Please try again.</p><div class="modal-actions"><button type="button" class="btn btn-ghost" onclick="closeCircleDetail()">Close</button></div>`;
    setTimeout(() => { const f = content.querySelector('button'); if (f) f.focus(); }, 0);
  }
}
function renderCircleDetail(g) {
  const content = document.getElementById('circleDetailContent');
  const av = normalizeAvailability(g);
  const members = Array.isArray(g.members) ? g.members : [];
  const myId = me && me.id;
  const isMember = !!myId && members.some(m => m && m.user_id === myId);   // membership from backend truth; user_ids never rendered
  const contrib = Number.isFinite(g.contribution_cents) ? fmt$(g.contribution_cents) : '—';
  const cap = Number.isFinite(g.max_members) ? g.max_members : null;
  const cnt = Number.isFinite(g.member_count) ? g.member_count : members.filter(m => m && m.status === 'ACTIVE').length;
  const net = discNetPayout(g, cap); const payoutStr = net != null ? fmt$(net) : '—'; const feePct = discFeePct(g);
  const day = Number.isFinite(g.payout_day_of_month) ? g.payout_day_of_month : null;
  const yourPos = (cnt != null && cap != null) ? Math.min(cnt + 1, cap) : null;
  const e = discState.elig;
  const gid = _goalUuid(g && g.id) ? g.id : null;   // validate before it reaches an inline handler
  let action;
  if (isMember) action = `<button type="button" class="btn btn-primary" onclick="closeCircleDetail();nav('groups')">You're a member — view in My circles</button>`;
  else if (!av.joinable) action = `<button type="button" class="btn btn-ghost" disabled>${av.key === 'FULL' ? 'Full' : (av.key === 'LOCKED' ? 'Invite-only' : 'Not joinable')}</button>`;
  else if (e && e.acctBlocked) action = `<button type="button" class="btn btn-ghost" onclick="closeCircleDetail();nav('notifications')">Account inactive — get help</button>`;
  else if (e && e.kyc === 'todo') action = `<button type="button" class="btn btn-primary" onclick="closeCircleDetail();nav('kyc')">Verify your identity to join</button>`;
  else if (e && e.bank === 'todo') action = `<button type="button" class="btn btn-primary" onclick="closeCircleDetail();nav('bank')">Connect a bank to join</button>`;
  else if (gid) action = `<button type="button" class="btn btn-primary" id="cdJoinBtn" onclick="confirmJoinCircle('${esc(gid)}',this)">Confirm &amp; join this circle</button>`;
  else action = `<button type="button" class="btn btn-ghost" disabled>Join unavailable</button>`;
  content.innerHTML = `
    <div class="disc-detail__head"><h3 id="cdTitle">${esc(g.name || 'Circle')}</h3><span class="status status--${av.chip}">${esc(av.label)}</span></div>
    ${g.description ? `<p class="disc-detail__desc">${esc(g.description)}</p>` : ''}
    <div id="cdBody">
      <dl class="disc-detail__facts">
        <div><dt>Contribution</dt><dd class="tnum">${contrib} <span class="hint-muted">per cycle</span></dd></div>
        <div><dt>Cadence</dt><dd>${day ? `Monthly, on day ${day}` : 'Monthly'}</dd></div>
        <div><dt>Members</dt><dd class="tnum">${cnt != null && cap != null ? `${cnt} / ${cap}` : '—'}</dd></div>
        <div><dt>Payout to recipient</dt><dd class="tnum">${payoutStr}${feePct != null ? ` <span class="hint-muted">after ${feePct}% platform fee</span>` : ''}</dd></div>
      </dl>
      ${av.joinable && !isMember && yourPos != null ? `<p class="disc-detail__pos">If you join now you'd take payout position <strong>${yourPos}</strong> of ${cap}. Your exact position is confirmed when you join.</p>` : ''}
      <div class="disc-detail__rules"><h4>Key rules</h4><ul>
        <li>You contribute ${contrib} each cycle until the circle completes${cap != null ? ` (${cap} cycles)` : ''}.</li>
        <li>Each cycle one member receives the pooled payout${feePct != null ? `, less a ${feePct}% platform fee` : ''}, in rotation by position.</li>
        <li>Payout timing depends on the circle's rules and completing your contributions — no specific date is guaranteed.</li>
        <li>Joining creates a recurring contribution obligation.</li>
        <li>A circle is a savings arrangement, not an investment — no profit or guaranteed return, and SOLCIRCLE is not a bank.</li>
      </ul></div>
      <div class="disc-detail__elig"><h4>Your eligibility</h4><ul class="disc-elig__list">
        ${discEligItem(e && e.kyc, 'Identity verified', 'Verify your identity')}
        ${discEligItem(e && e.bank, 'Bank account connected', 'Connect a bank account')}
      </ul></div>
    </div>
    <p class="err" id="cdErr" role="alert" style="display:none"></p>
    <div class="modal-actions"><button type="button" class="btn btn-ghost" onclick="closeCircleDetail()">Close</button>${action}</div>`;
  setTimeout(() => { const f = document.querySelector('#circleDetailDialog .btn-ghost'); if (f) f.focus(); }, 0);
}
function closeCircleDetail() {
  const dlg = document.getElementById('circleDetailDialog'); if (dlg) dlg.classList.remove('is-open');
  document.removeEventListener('keydown', _discTrapKey, true);
  const t = _discDlgTrigger; _discDlgTrigger = null; _discDetailId = null;
  if (t && typeof t.focus === 'function') { try { t.focus(); } catch (e) {} }
}
function _discTrapKey(e) {
  const d = document.getElementById('circleDetailDialog'); if (!d) return;
  if (e.key === 'Escape') { e.preventDefault(); if (d.dataset.busy === '1') return; closeCircleDetail(); return; }
  if (e.key === 'Tab') {
    const f = [...d.querySelectorAll('input,select,button,textarea,a[href]')].filter(x => !x.disabled && x.offsetParent !== null);
    if (!f.length) { e.preventDefault(); return; }
    const first = f[0], last = f[f.length - 1];
    if (!d.contains(document.activeElement)) { e.preventDefault(); first.focus(); return; }
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
}
async function confirmJoinCircle(id, btn) {
  if (_discJoinBusy || !_goalUuid(id)) return;
  _discJoinBusy = true;
  const dlg = document.getElementById('circleDetailDialog'); dlg.dataset.busy = '1';
  const err = document.getElementById('cdErr'); if (err) err.style.display = 'none';
  if (btn) { btn.disabled = true; btn.textContent = 'Joining…'; }
  try {
    const g = await api(`/groups/${id}/join`, { method: 'POST' });   // backend-authoritative; re-checks eligibility + capacity
    // Never treat HTTP success alone as joined — confirm membership from the returned detail.
    const joined = g && Array.isArray(g.members) && !!(me && me.id) && g.members.some(m => m && m.user_id === me.id);
    discAnnounce(joined ? 'You joined the circle.' : 'Your join request was received.');
    dlg.dataset.busy = '0';
    closeCircleDetail();
    await loadDiscover();   // re-fetch discovery + eligibility (no optimistic membership)
    const lp = document.getElementById('discList'); if (lp) lp.focus();
  } catch (ex) {
    if (err) { err.textContent = discJoinError(ex); err.style.display = 'block'; }
    if (btn) { btn.disabled = false; btn.textContent = 'Confirm & join this circle'; }
    dlg.dataset.busy = '0';
  } finally { _discJoinBusy = false; }
}
function discJoinError(ex) {
  const m = (ex && ex.message) ? String(ex.message) : '';
  if (/full|capacity/i.test(m)) return 'This circle just filled up. Try another open circle.';   // check before "already" ("already full")
  if (/already a member|already an? active/i.test(m)) return "You're already a member of this circle.";
  if (/not forming|no longer|forming/i.test(m)) return 'This circle is no longer accepting new members.';
  if (/kyc|identity|verif/i.test(m)) return 'Verify your identity before joining.';
  if (/bank/i.test(m)) return 'Connect a bank account before joining.';
  if (/account status|not active|suspend|delinquent|closed/i.test(m)) return "Your account isn't active right now — please contact support.";
  if (/invite|private/i.test(m)) return 'This circle is invite-only — you need an invite link to join.';
  return "We couldn't complete your join. Please try again in a moment.";
}

// ── SOL Match — reserve a payout spot (matched into a circle or waitlisted) ───
let _reserveBusy = false;
async function reservePayout() {
  if (_reserveBusy) return;
  const btn = document.getElementById('mBtn'), err = document.getElementById('mErr'), res = document.getElementById('mResult');
  err.style.display = 'none';
  const dateV = document.getElementById('mDate').value;
  const amt = dollarsToCents(document.getElementById('mAmt').value);
  const freq = document.getElementById('mFreq').value;
  if (!dateV || !goalDate(dateV)) { err.textContent = 'Pick a valid payout date.'; err.style.display = 'block'; return; }
  if (amt == null || amt < 100) { err.textContent = 'Enter a contribution of at least $1.'; err.style.display = 'block'; return; }
  _reserveBusy = true; btn.disabled = true; btn.textContent = 'Matching…';
  try {
    const r = await api('/circles/reserve', { method: 'POST', body: JSON.stringify({ preferred_payout_date: dateV, contribution_cents: amt, frequency: freq }) });
    const st = String(r && r.status || '').toUpperCase();
    if (st === 'MATCHED') res.innerHTML = `<div class="disc-match__ok"><strong>Matched.</strong> You've been placed into a circle — your membership and payout terms are confirmed there. <button type="button" class="link-btn" onclick="nav('groups')">View your circles</button></div>`;
    else if (st === 'WAITLISTED') res.innerHTML = `<div class="disc-match__wait"><strong>You're on the waitlist${Number.isFinite(r.waitlist_position) ? ` — position ${r.waitlist_position}` : ''}.</strong> We'll place you when a compatible circle forms. A waitlist spot isn't a membership, and timing isn't guaranteed.</div>`;
    else res.innerHTML = `<div class="disc-match__wait">Your request was received${st ? ` (${esc(st.toLowerCase())})` : ''}.</div>`;
    discAnnounce(st === 'MATCHED' ? 'Matched into a circle.' : (st === 'WAITLISTED' ? 'Added to the waitlist.' : 'Reservation received.'));
    await loadDiscover();
  } catch (e) { err.textContent = discReserveError(e); err.style.display = 'block'; }
  finally { _reserveBusy = false; btn.disabled = false; btn.textContent = 'Find my circle'; }
}
function discReserveError(ex) {
  const m = (ex && ex.message) ? String(ex.message) : '';
  if (/kyc|identity|verif/i.test(m)) return 'Verify your identity before reserving a spot.';
  if (/bank/i.test(m)) return 'Connect a bank account before reserving a spot.';
  return "We couldn't complete your reservation. Please try again.";
}
