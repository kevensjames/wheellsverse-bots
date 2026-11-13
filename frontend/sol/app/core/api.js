// SOL member app — core/api.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── API helpers ───────────────────────────────────────────────────────────────
// True when an error is an aborted request (navigation cancelled a stale load) —
// callers can use this to bail silently instead of showing an error.
function _aborted(e) { return !!(e && (e.name === 'AbortError' || e.aborted)); }

async function api(path, opts = {}) {
  // P3 — GET route-loads carry the current route's AbortSignal so navigating away
  // cancels them. Mutations (any non-GET method) never get it and always run to
  // completion; a caller can opt a GET out with { noAbort: true } (e.g. the
  // background unread-badge refresh). An explicit opts.signal always wins.
  const _method = (opts.method || 'GET').toUpperCase();
  const _signal = opts.signal
    || (_method === 'GET' && !opts.noAbort && _routeAbort ? _routeAbort.signal : undefined);
  const r = await fetch(API + path, {
    ...opts,
    signal: _signal,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + token,
      ...(opts.headers || {})
    }
  });
  if (r.status === 204) return null;
  // 401 = access token expired. Try silently refreshing via the refresh token
  // (valid 30 days) before giving up and bouncing the user to login. This
  // keeps long-running tabs alive past the 60-min access-token TTL.
  if (r.status === 401 && !opts._retry) {
    // This page signed out (it may be back from the back/forward cache): never
    // refresh from here; let the sign-out finish.
    if (_logoutPromise) { await _logoutPromise; throw new Error('Signed out'); }
    const refreshed = await _tryRefresh();
    if (refreshed) {
      return api(path, { ...opts, _retry: true });
    }
    // Signing out (core/router.js logout()): let it finish revoking and redirect.
    // Navigating away here first would cancel its revoke request. (During a
    // sign-out _tryRefresh() always returns false.)
    if (_logoutPromise) { await _logoutPromise; throw new Error('Signed out'); }
    // A different session is stored now (another user's, or one stored after a
    // sign-out): this page belongs to the old one, so reload it. The request is
    // not re-sent under that session.
    if (_refreshOutcome === 'stale') { _leave(true); throw new Error('Session changed in another tab'); }
    _leave(false);
    throw new Error('Session expired');
  }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(formatApiError(d, r.statusText));
  return d;
}

// Get a usable access token after a 401. Returns true when this tab may re-send
// its request with `token`; never throws. When it returns false, _refreshOutcome
// says why: 'signed-out' (this tab's session is over) or 'stale' (a different
// session is stored now: another user's, or one stored after a sign-out), and
// api() leaves or reloads the tab. See the comment above _authEpoch in
// core/router.js for what this guards against.
let _refreshPromise = null;
let _refreshOutcome = null;
const REFRESH_LOCK_WAIT_MS = 10000;
async function _tryRefresh() {
  if (!localStorage.getItem('sol_refresh')) { _refreshOutcome = 'signed-out'; return false; }
  // One refresh per tab at a time; concurrent 401s share it.
  if (_refreshPromise) return _refreshPromise;
  const epoch = _authEpoch;
  const sentWith = token;
  const p = _withRefreshLock(() => _refreshSession(epoch, sentWith));
  _refreshPromise = p;
  p.then(() => { if (_refreshPromise === p) _refreshPromise = null; });
  return p;
}

// Runs fn holding a lock shared by every tab of this origin (Web Locks API), so
// two tabs never rotate the same refresh token at once. Without the API, or if
// the lock is not granted within REFRESH_LOCK_WAIT_MS, fn runs without it.
async function _withRefreshLock(fn) {
  const locks = (typeof navigator !== 'undefined' && navigator && navigator.locks) || null;
  if (!locks || typeof locks.request !== 'function') return fn();
  let started = false;
  try {
    const opts = (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function')
      ? { signal: AbortSignal.timeout(REFRESH_LOCK_WAIT_MS) } : {};
    return await locks.request('sol-auth-refresh', opts, () => { started = true; return fn(); });
  } catch {
    return started ? false : fn();
  }
}

async function _refreshSession(epoch, sentWith) {
  const ended = () => epoch !== _authEpoch || _signedOutSinceLoad();
  // 'none': no session stored; 'stale': a session that is not this tab's;
  // 'mine': this tab's user, and no sign-out since this tab loaded.
  const stored = () => {
    if (!localStorage.getItem('sol_refresh')) return 'none';
    const t = localStorage.getItem('sol_token');
    return (ended() || (t && _isOtherUser(t))) ? 'stale' : 'mine';
  };
  const fail = outcome => { _refreshOutcome = outcome; return false; };
  const refresh = localStorage.getItem('sol_refresh');
  // Clear the stored session only if it is still the one this refresh used.
  const clearMine = () => { if (localStorage.getItem('sol_refresh') === refresh) { localStorage.removeItem('sol_token'); localStorage.removeItem('sol_refresh'); } };
  // The refresh was rejected or did not complete. If another tab stored a newer
  // session of this user meanwhile (it rotated this token first, without the
  // lock), use it; otherwise this tab's session is over.
  const afterFailure = () => {
    const now = stored();
    if (now === 'mine' && localStorage.getItem('sol_refresh') !== refresh && localStorage.getItem('sol_token')) {
      token = localStorage.getItem('sol_token');
      return true;
    }
    if (now === 'stale') return fail('stale');
    clearMine();
    return fail('signed-out');
  };
  try {
    const before = stored();
    if (before !== 'mine') return fail(before === 'none' ? 'signed-out' : 'stale');
    // Another tab already refreshed this session: use its access token rather
    // than rotating the refresh token again.
    const storedToken = localStorage.getItem('sol_token');
    if (storedToken && storedToken !== sentWith && !_expiresSoon(storedToken)) { token = storedToken; return true; }
    const r = await fetch(API + '/auth/refresh', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ refresh_token: refresh }),
    });
    if (!r.ok) return afterFailure();
    const d = await r.json();
    const late = d && d.refresh_token;
    if (ended()) {
      // Signed out (here or in another tab) while this refresh was in flight:
      // store nothing (that would sign the browser back in) and revoke what
      // the server just created, before this tab navigates (bounded).
      await _withTimeout(_revokeRefresh(late), REVOKE_TIMEOUT_MS);
      return fail(stored() === 'none' ? 'signed-out' : 'stale');
    }
    if (d && _isOtherUser(d.access_token)) {
      // The stored refresh token was another user's: keep that user's rotated
      // session for them if it is still the one stored, but do not use it here.
      if (localStorage.getItem('sol_refresh') === refresh) {
        localStorage.setItem('sol_token', d.access_token);
        localStorage.setItem('sol_refresh', late);
      } else {
        _revokeRefresh(late);
      }
      return fail('stale');
    }
    const storedRefresh = localStorage.getItem('sol_refresh');
    if (storedRefresh && storedRefresh !== refresh) {
      // Another tab stored a newer session meanwhile. Ours is redundant: revoke
      // it without waiting (keepalive; nothing depends on the answer) and use
      // the stored one if it is this tab's user's.
      _revokeRefresh(late);
      if (stored() !== 'mine') return fail('stale');
      token = localStorage.getItem('sol_token') || d.access_token;
      return true;
    }
    // Storage holds the token we sent, or is empty without any sign-out (another
    // tab's failed refresh cleared it): keep the new pair.
    localStorage.setItem('sol_token', d.access_token);
    localStorage.setItem('sol_refresh', late);
    token = d.access_token;
    return true;
  } catch {
    return afterFailure();
  }
}

// FastAPI returns validation errors as detail=[{loc, msg, type}, ...] on 422.
// Without this helper, `new Error(d.detail)` coerces the array to a string,
// producing "[object Object],[object Object]".
function formatApiError(d, fallback) {
  if (!d || !d.detail) return fallback || 'Request failed';
  if (typeof d.detail === 'string') return d.detail;
  if (Array.isArray(d.detail)) {
    return d.detail.map(e => {
      if (typeof e === 'string') return e;
      const field = Array.isArray(e.loc) ? e.loc.filter(x => x !== 'body').join('.') : '';
      const msg = e.msg || e.message || JSON.stringify(e);
      return field ? `${field}: ${msg}` : msg;
    }).join('; ');
  }
  return d.detail.msg || JSON.stringify(d.detail);
}

// Canonical status chip — the ONE way to render a backend lifecycle enum as a
// member-facing chip. Replaces the legacy badge()/.badge-* system: maps the raw
// enum to a canonical label + a semantic .status--* variant (tinted pill + dot +
// text, never colour-only — see DESIGN_SYSTEM.md). Payment states mirror
// PAY_STATE severity (RETURNED reads as a failure). Generic across
// circle/cycle/member/payment, so PENDING stays neutral "Pending" (the Payments
// page's richer PAY_STATE uses the payment-specific "Due").
function statusChip(status) {
  const variant = {
    ACTIVE:'active', VERIFIED:'verified', SUCCESS:'active',
    FORMING:'forming', PENDING:'pending', SUBMITTED:'pending', INITIATED:'pending',
    COLLECTING:'active', SETTLING:'active', PROCESSING:'pending', COMPLETED:'completed',
    FAILED:'failed', DELINQUENT:'failed', SUSPENDED:'blocked', CLOSED:'cancelled', RETURNED:'failed',
    CANCELLED:'cancelled', PAUSED:'warning',
  };
  const label = {
    ACTIVE:'Active', VERIFIED:'Verified', SUCCESS:'Settled',
    FORMING:'Forming', PENDING:'Pending', SUBMITTED:'Under review', INITIATED:'Submitted',
    COLLECTING:'Active', SETTLING:'Active', PROCESSING:'Processing', COMPLETED:'Completed',
    FAILED:'Failed', DELINQUENT:'Action required', SUSPENDED:'Suspended', CLOSED:'Closed', RETURNED:'Returned',
  };
  const key = String(status || '').toUpperCase();
  const text = label[key] || (key ? key.charAt(0) + key.slice(1).toLowerCase() : '—');
  const v = variant[key] || 'completed';   // unknown enum → neutral grey (matches the old badge-gray default), never amber "in-progress"
  return `<span class="status status--${v}" aria-label="Status: ${esc(text)}">${esc(text)}</span>`;
}
function fmt$(c) { return '$' + (c/100).toLocaleString('en-US',{minimumFractionDigits:2}); }
// Canonical member-facing date — "Mon D, YYYY" in the user's locale. One helper
// so every surface formats a date identically (see docs/sol DATE-01). Returns ''
// for a null/invalid date so callers can guard.
function fmtDate(d, opts) {
  if (!d) return '';
  const x = new Date(d);
  if (isNaN(x.getTime())) return '';
  return x.toLocaleDateString(undefined, opts || { year: 'numeric', month: 'short', day: 'numeric' });
}
// Escape untrusted strings before interpolating into innerHTML — user-controlled
// data (circle names, notification bodies, template names) must never be able to
// inject markup/script that could read the session token from localStorage.
function esc(s){ return String(s??'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
// Only allow http(s) links; anything else (javascript:, data:) → empty.
function safeUrl(u){ return /^https?:\/\//i.test(u||'') ? u : ''; }

async function copyInvite(groupId) {
  const input = document.getElementById('inviteUrl-' + groupId);
  if (!input) return;
  try {
    await navigator.clipboard.writeText(input.value);
    const btn = event.target;
    const orig = btn.textContent;
    btn.textContent = '✓ Copied';
    setTimeout(() => { btn.textContent = orig; }, 1500);
  } catch {
    // Fallback for older browsers / insecure contexts: select the text so
    // the user can Cmd/Ctrl+C manually.
    input.select();
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  try {
    me = await api('/auth/me');
    document.getElementById('userEmail').textContent = me.email;
    applyFeatureFlags();   // re-reveal role-gated UI (e.g. /admin) now that me.is_admin is known
    loadDashboard();  // one consolidated, partial-failure-safe load feeds every card
    consumePendingInvite();  // if user arrived via ?invite=..., auto-join now
    // Returning from Stripe Checkout (?premium=success|cancel) — open the Premium
    // page so loadPremium() can show the return note and poll for activation.
    if (new URLSearchParams(location.search).get('premium')) nav('premium');
    // Return from participation checkout (?participation=success) — flag-gated; loadCatalog polls backend truth.
    if (featureOn('catalog') && new URLSearchParams(location.search).get('participation')) nav('catalog');
  } catch {
    // A sign-out in progress (core/router.js logout()) revokes the session and
    // redirects by itself; navigating here first would cancel its revoke.
    if (_logoutPromise) { await _logoutPromise; return; }
    // api() is already leaving or reloading this tab (another session is stored,
    // or none): do not remove a token that may be another session's.
    if (_leaving) return;
    localStorage.removeItem('sol_token');
    window.location.href = '/sol/';
  }
}

// Build the "Your money" panel: per-circle next-contribution date, next-payout
// estimate, and the running total this user has contributed across all active
// circles.
