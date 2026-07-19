// SOL member app — pages/notifications.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── Notifications ───────────────────────────────────────────────────────────────
// ═══ Notifications & support hub — cross-app inbox ════════════════════════════
// Canonical model from the REAL backend: GET /notifications → {notifications:[
//   {id,type,title,body,channel,read_at,related_group_id,related_payment_id,created_at}
// ], unread_count}. There is NO priority/category/action-route field — priority
// and category are derived ONLY from the explicit NotificationType enum (narrow,
// documented, default NORMAL; never promoted to CRITICAL by client keyword match).
// title/body are server text rendered as TEXT (esc) — never HTML. id and
// related_* are internal uuids used ONLY for actions/deep-links, never displayed.
// Read/unread is backend-authoritative (POST /{id}/read, /read-all); there is no
// unread or dismiss endpoint, so neither is offered.
const NOTIF_TYPES = {
  UPCOMING_CONTRIBUTION: { cat:'PAYMENTS', pri:'NORMAL', nav:'payments',  act:'View payments' },
  PAYMENT_SUCCESS:       { cat:'PAYMENTS', pri:'NORMAL', nav:'payments',  act:'View payments' },
  PAYMENT_FAILURE:       { cat:'PAYMENTS', pri:'HIGH',   nav:'payments',  act:'Resolve payment' },
  PAYOUT_COMPLETED:      { cat:'PAYMENTS', pri:'NORMAL', nav:'payments',  act:'View payments' },
  CIRCLE_FULL:           { cat:'CIRCLES',  pri:'NORMAL', nav:'groups',    act:'View circle' },
  WAITLIST_PROMOTED:     { cat:'CIRCLES',  pri:'HIGH',   nav:'groups',    act:'View circle' },
  SUBSCRIPTION_RENEWAL:  { cat:'PREMIUM',  pri:'NORMAL', nav:'premium',   act:'View membership' },
  BADGE_AWARDED:         { cat:'GENERAL',  pri:'LOW',    nav:'dashboard', act:'View dashboard' },
  ANNOUNCEMENT_POSTED:   { cat:'GENERAL',  pri:'LOW',    nav:null,        act:null },
};
const NOTIF_CAT = {
  PAYMENTS: { label:'Payment',    icon:'ic-payments' },
  CIRCLES:  { label:'Circle',     icon:'ic-circles' },
  PREMIUM:  { label:'Membership', icon:'ic-premium' },
  GENERAL:  { label:'Update',     icon:'ic-alerts' },
};
const NOTIF_PRI = {
  HIGH:   { label:'Action needed', chip:'warning', rank:0 },
  NORMAL: { label:'Update',        chip:'active',  rank:2 },
  LOW:    { label:'Info',          chip:'pending', rank:3 },
};
// Only these internal app destinations may be navigated to — the payload never
// supplies a route string, so navigation targets come solely from this allowlist.
const NOTIF_NAV_ALLOW = ['dashboard', 'groups', 'payments', 'bank', 'kyc', 'premium', 'goals', 'timeline', 'notifications'];
const NOTIF_TABS = [
  { key:'all', label:'All' }, { key:'attention', label:'Needs attention' }, { key:'payments', label:'Payments' },
  { key:'circles', label:'Circles' }, { key:'account', label:'Account' }, { key:'read', label:'Read' },
];
const _isUuid = (s) => typeof s === 'string' && /^[0-9a-f-]{8,}$/i.test(s);

function normalizeNotification(n) {
  if (!n || typeof n !== 'object') return null;   // skip an unusable item — never fail the whole page
  const rawType = String(n.type || '').toUpperCase();
  const t = NOTIF_TYPES[rawType] || { cat:'GENERAL', pri:'NORMAL', nav:null, act:null };
  const cat = NOTIF_CAT[t.cat] || NOTIF_CAT.GENERAL;
  const pri = NOTIF_PRI[t.pri] || NOTIF_PRI.NORMAL;
  const read = !!n.read_at;
  let action = null;
  if (t.nav && NOTIF_NAV_ALLOW.indexOf(t.nav) !== -1) {
    const gid = (t.cat === 'CIRCLES' && _isUuid(n.related_group_id)) ? n.related_group_id : null;
    action = { label: t.act, nav: t.nav, gid };
  }
  return {
    id: _isUuid(n.id) ? n.id : null,
    catKey: t.cat, catLabel: cat.label, icon: cat.icon,
    priKey: t.pri, priLabel: pri.label, priChip: pri.chip, rank: pri.rank,
    title: n.title || cat.label, body: n.body || '',
    read, created: n.created_at || null, action,
    needsAttention: t.pri === 'HIGH' && !read,   // HIGH + unread = unresolved/actionable
  };
}
function notifFilter(n, tab) {
  if (tab === 'attention') return n.needsAttention;
  if (tab === 'payments') return n.catKey === 'PAYMENTS';
  if (tab === 'circles') return n.catKey === 'CIRCLES';
  if (tab === 'account') return n.catKey === 'PREMIUM' || n.catKey === 'GENERAL';
  if (tab === 'read') return n.read;
  return true;   // all
}
function sortNotifs(list) {
  return list.map((n, i) => ({ n, i })).sort((a, b) => {
    if (a.n.needsAttention !== b.n.needsAttention) return a.n.needsAttention ? -1 : 1;
    if (a.n.read !== b.n.read) return a.n.read ? 1 : -1;                    // unread before read
    const ta = a.n.created ? Date.parse(a.n.created) : 0, tb = b.n.created ? Date.parse(b.n.created) : 0;
    if ((tb || 0) !== (ta || 0)) return (tb || 0) - (ta || 0);              // newest first
    return a.i - b.i;                                                       // stable
  }).map(x => x.n);
}
function notifRelTime(iso) {
  if (!iso) return { rel: '', exact: '' };
  const d = new Date(iso); if (isNaN(d.getTime())) return { rel: '', exact: '' };
  const exact = d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
  const diff = (Date.now() - d.getTime()) / 1000;
  let rel;
  if (diff < 60) rel = 'just now';
  else if (diff < 3600) rel = `${Math.floor(diff / 60)}m ago`;
  else if (diff < 86400) rel = `${Math.floor(diff / 3600)}h ago`;
  else if (diff < 604800) rel = `${Math.floor(diff / 86400)}d ago`;
  else rel = fmtDate(d, { month: 'short', day: 'numeric' });
  return { rel, exact };
}
function notifAnnounce(msg) { const el = document.getElementById('notifLiveStatus'); if (el) { el.textContent = ''; el.textContent = msg; } }

let notifState = { items: [], unread: 0, ok: false, tab: 'all', busy: {} };

async function loadNotifications(userInitiated) {
  const list = document.getElementById('notifList');
  if (!list) return;
  list.innerHTML = notifSkeleton();
  let ok = false, items = [], unread = 0;
  try {
    const r = await api('/notifications');   // exact shape: { notifications:[...], unread_count }
    if (r && typeof r === 'object') {
      items = Array.isArray(r.notifications) ? r.notifications.map(normalizeNotification).filter(Boolean) : [];
      unread = (typeof r.unread_count === 'number') ? r.unread_count : items.filter(n => !n.read).length;
      ok = true;
    }
  } catch (e) { ok = false; }
  notifState.items = items; notifState.ok = ok;
  if (ok) notifState.unread = unread;   // preserve the last-known count on failure — never silently zero
  updateUnreadBadge(ok ? unread : (notifState.unread || 0));
  renderNotifSummary();
  renderNotifTabs();
  renderNotifHeadActions();
  renderNotifFeed();
  if (userInitiated) { notifAnnounce(ok ? 'Notifications refreshed.' : 'Notifications unavailable.'); }
}

function renderNotifSummary() {
  const el = document.getElementById('notifSummary'); if (!el) return;
  if (!notifState.ok) {
    el.innerHTML = ['Unread', 'Needs attention', 'Payment updates', 'Circle updates'].map(l =>
      notifSumCard(l, 'Unavailable', null)).join('');
    return;
  }
  const its = notifState.items;
  const unread = (typeof notifState.unread === 'number') ? notifState.unread : its.filter(n => !n.read).length;   // backend-authoritative count
  const attn = its.filter(n => n.needsAttention).length;
  const pay = its.filter(n => n.catKey === 'PAYMENTS').length;
  const cir = its.filter(n => n.catKey === 'CIRCLES').length;
  // Counts are neutral tallies — never dressed in settlement vocabulary (no green
  // "verified" all-clear for a zero, no "pending/due" tint on informational counts).
  el.innerHTML =
    notifSumCard('Unread', String(unread), null) +
    notifSumCard('Needs attention', String(attn), attn ? 'warning' : null) +
    notifSumCard('Payment updates', String(pay), null) +
    notifSumCard('Circle updates', String(cir), null);
}
function notifSumCard(label, val, chip) {
  const inner = chip ? `<span class="status status--${chip}">${esc(val)}</span>` : `<span class="tnum">${esc(val)}</span>`;
  return `<div class="sum-card"><div class="sum-label">${esc(label)}</div><div class="sum-val">${inner}</div></div>`;
}

function renderNotifTabs() {
  const el = document.getElementById('notifTabs'); if (!el) return;
  el.innerHTML = NOTIF_TABS.map((t, i) => {
    const sel = t.key === notifState.tab;
    let count = '';
    if (notifState.ok) {
      const c = notifState.items.filter(n => notifFilter(n, t.key)).length;
      if (t.key === 'attention' && c) count = ` <span class="notif-tabcount">${c}</span>`;
      else if (t.key === 'all') count = ` <span class="notif-tabcount">${notifState.items.length}</span>`;
    }
    return `<button type="button" class="ctab${sel ? ' active' : ''}" role="tab" id="ntab-${t.key}" aria-controls="notifList" aria-selected="${sel}" tabindex="${sel ? '0' : '-1'}" data-ntab="${t.key}" onclick="notifSetTab('${t.key}')">${esc(t.label)}${count}</button>`;
  }).join('');
  const panel = document.getElementById('notifList'); if (panel) panel.setAttribute('aria-labelledby', `ntab-${notifState.tab}`);
}
function notifSetTab(tab) { notifState.tab = tab; renderNotifTabs(); renderNotifFeed(); }
function notifTabKey(e) {
  const keys = NOTIF_TABS.map(t => t.key);
  let idx = keys.indexOf(notifState.tab);
  if (e.key === 'ArrowRight' || e.key === 'ArrowDown') idx = (idx + 1) % keys.length;
  else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') idx = (idx - 1 + keys.length) % keys.length;
  else if (e.key === 'Home') idx = 0;
  else if (e.key === 'End') idx = keys.length - 1;
  else return;
  e.preventDefault();
  notifSetTab(keys[idx]);
  const t = document.getElementById(`ntab-${keys[idx]}`); if (t) t.focus();
}

function renderNotifHeadActions() {
  const el = document.getElementById('notifHeadActions'); if (!el) return;
  const unread = notifState.ok ? notifState.items.filter(n => !n.read).length : 0;
  const markAll = unread > 0 ? `<button type="button" class="btn btn-ghost" id="notifMarkAll" onclick="markAllRead()">Mark all as read</button>` : '';
  el.innerHTML = `${markAll}<button type="button" class="btn btn-ghost" onclick="loadNotifications(true)">Refresh</button>`;
}

function renderNotifFeed() {
  const el = document.getElementById('notifList'); const cEl = document.getElementById('notifCount');
  if (!el) return;
  if (!notifState.ok) {
    if (cEl) cEl.textContent = '';
    el.innerHTML = `<div class="notif-empty"><div class="notif-empty__title">Notifications unavailable</div><p class="hint-muted">We couldn't load your notifications. Please try again.</p><button type="button" class="btn btn-ghost btn--sm" onclick="loadNotifications(true)">Retry</button></div>`;
    return;
  }
  const filtered = sortNotifs(notifState.items.filter(n => notifFilter(n, notifState.tab)));
  if (cEl) cEl.textContent = `${filtered.length} ${filtered.length === 1 ? 'notification' : 'notifications'}`;
  if (!filtered.length) { el.innerHTML = `<div class="notif-empty"><div class="notif-empty__title">${esc(notifEmptyMsg(notifState.tab))}</div></div>`; return; }
  el.innerHTML = `<ul class="notif-feed">${filtered.map(notifCard).join('')}</ul>`;
}
function notifEmptyMsg(tab) {
  if (tab === 'attention') return 'Nothing needs your attention right now.';
  if (tab === 'read') return 'No read notifications yet.';
  if (tab === 'all') return "You're all caught up.";
  return 'Nothing here right now.';
}
function notifCard(n) {
  const time = notifRelTime(n.created);
  const idAttr = n.id ? esc(n.id) : '';
  const act = n.action
    ? `<button type="button" class="btn btn-ghost btn--sm" aria-label="${esc(n.action.label)}: ${esc(n.title)}" onclick="notifGo('${esc(n.action.nav)}','${n.action.gid ? esc(n.action.gid) : ''}')">${esc(n.action.label)}</button>`
    : '';
  const markBtn = (!n.read && n.id)
    ? `<button type="button" class="btn btn-ghost btn--sm notif-markread" id="nmr-${idAttr}" aria-label="Mark &quot;${esc(n.title)}&quot; as read" onclick="markOneRead('${idAttr}')">Mark read</button>`
    : '';
  return `<li class="notif-item${n.read ? '' : ' notif-item--unread'}${n.needsAttention ? ' notif-item--attn' : ''}">
    <span class="notif-item__ic" aria-hidden="true"><svg class="ic"><use href="#${n.icon}"/></svg></span>
    <div class="notif-item__main">
      <div class="notif-item__top">
        <span class="notif-item__title">${esc(n.title)}</span>
        ${!n.read ? '<span class="notif-unread-dot" aria-hidden="true"></span><span class="sr-only">Unread. </span>' : ''}
        ${n.priKey === 'HIGH' ? `<span class="status status--${n.priChip}">${esc(n.priLabel)}</span>` : ''}
      </div>
      ${n.body ? `<p class="notif-item__body">${esc(n.body)}</p>` : ''}
      <div class="notif-item__meta">
        <span class="notif-item__cat">${esc(n.catLabel)}</span>
        ${time.rel ? `<span class="notif-item__time"><time datetime="${esc(n.created || '')}" title="${esc(time.exact)}">${esc(time.rel)}</time><span class="sr-only"> — ${esc(time.exact)}</span></span>` : ''}
      </div>
    </div>
    ${(act || markBtn) ? `<div class="notif-item__acts">${act}${markBtn}</div>` : ''}
  </li>`;
}

// Safe deep-link: destination comes from the type-derived allowlist; a circle id
// (validated uuid) opens that circle. No payload route string ever reaches nav().
function notifGo(dest, gid) {
  if (gid && _isUuid(gid) && typeof showGroup === 'function') { showGroup(gid); return; }
  if (NOTIF_NAV_ALLOW.indexOf(dest) !== -1 && typeof nav === 'function') nav(dest);
}

async function markOneRead(id) {
  if (!id || !SolGuard.acquire('notification:read:' + id)) return;   // per-notification: reading A never blocks B
  const btn = document.getElementById('nmr-' + id);
  if (btn) { btn.disabled = true; btn.textContent = 'Marking…'; }
  try {
    const updated = await api(`/notifications/${id}/read`, { method: 'POST' });   // backend-authoritative
    const item = notifState.items.find(x => x.id === id);
    // A 2xx from mark-read means the backend committed it as read (response carries read_at).
    if (item) { item.read = true; item.needsAttention = false; }
    notifAnnounce('Marked as read.');
    renderNotifSummary(); renderNotifTabs(); renderNotifHeadActions(); renderNotifFeed();
    const lp = document.getElementById('notifList'); if (lp) lp.focus();   // keep focus in the panel, not on <body>
    refreshUnread();   // reconcile the nav badge count from the backend
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = 'Mark read'; }   // keep it unread — no silent change
    notifAnnounce("Couldn't mark as read. Please try again.");
  } finally { SolGuard.release('notification:read:' + id); }
}
async function markAllRead() {
  if (!SolGuard.acquire('notification:read-all')) return;
  const btn = document.getElementById('notifMarkAll');
  if (btn) { btn.disabled = true; btn.textContent = 'Marking…'; }
  try {
    await api('/notifications/read-all', { method: 'POST' });
    notifAnnounce('All notifications marked as read.');
    await loadNotifications();   // re-fetch backend truth (read states + count)
    const lp = document.getElementById('notifList'); if (lp) lp.focus();   // keep focus in the panel
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = 'Mark all as read'; }
    notifAnnounce("Couldn't mark all as read. Please try again.");
  } finally { SolGuard.release('notification:read-all'); }
}
function notifSkeleton() {
  return `<ul class="notif-feed">${Array.from({ length: 4 }).map(() => `<li class="notif-item"><span class="notif-item__ic"></span><div class="notif-item__main" style="flex:1"><span class="sk sk-line" style="width:45%"></span><span class="sk sk-line" style="width:75%;margin-top:.4rem"></span></div></li>`).join('')}</ul>`;
}
function updateUnreadBadge(n) {
  const b = document.getElementById('navUnread');
  if (!b) return;
  if (n>0){ b.textContent=n; b.style.display='inline-block'; } else { b.style.display='none'; }
}
async function refreshUnread() {
  try { const r = await api('/notifications'); const c = (r && typeof r.unread_count === 'number') ? r.unread_count : 0; notifState.unread = c; updateUnreadBadge(c); } catch(_) {}
}
