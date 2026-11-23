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
  let r;
  try {
    r = await fetch(API + path, {
      ...opts,
      signal: _signal,
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token,
        ...(opts.headers || {})
      }
    });
  } catch (e) {
    // No answer at all (network error): mark it, so a caller can tell it from
    // an answer (init() keeps the session and tries again).
    if (e && typeof e === 'object' && !_aborted(e)) { try { e.transient = true; } catch {} }
    throw e;
  }
  if (r.status === 204) return null;
  // 401 = access token expired. Try silently refreshing via the refresh token
  // (valid 30 days) before giving up and bouncing the user to login. This
  // keeps long-running tabs alive past the access token's lifetime (15 minutes
  // by default at the backend, ACCESS_TOKEN_EXPIRE_MINUTES).
  // A request re-sent with another tab's newer access token ('adopted') may still
  // get a 401 (e.g. this device's clock is behind); it then gets one real refresh.
  if (r.status === 401 && (!opts._retry || opts._retry === 'adopted')) {
    // This page signed out (it may be back from the back/forward cache): never
    // refresh from here; let the sign-out finish.
    if (_logoutPromise) { await _logoutPromise; throw new Error('Signed out'); }
    const refreshed = await _tryRefresh();
    if (refreshed) {
      return api(path, { ...opts, _retry: (_refreshAdopted && !opts._retry) ? 'adopted' : true });
    }
    // Signing out (core/router.js logout()): let it finish revoking and redirect.
    // Navigating away here first would cancel its revoke request. (During a
    // sign-out _tryRefresh() always returns false.)
    if (_logoutPromise) { await _logoutPromise; throw new Error('Signed out'); }
    // The refresh could not be done right now (429, 5xx, network, or another
    // tab's refresh still holds the lock): the session may still be valid, so
    // keep it and fail only this request.
    if (_refreshOutcome === 'transient') {
      const err = new Error('Could not renew your session right now. Please try again.');
      err.transient = true;
      throw err;
    }
    // A different session is stored now (another user's, or one stored after a
    // sign-out): this page belongs to the old one, so reload it. The request is
    // not re-sent under that session. Otherwise this tab's session is over.
    const stale = _refreshOutcome === 'stale';
    _leaveAfterRefresh(stale);
    throw new Error(stale ? 'Session changed in another tab' : 'Session expired');
  }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = new Error(formatApiError(d, r.statusText));
    err.status = r.status;
    err.detail = d ? d.detail : undefined;   // the raw detail (an object for some refusals, e.g. 409 reasons)
    throw err;
  }
  return d;
}

// Get a usable access token after a 401. Returns true when this tab may re-send
// its request with `token`; never throws. When it returns false, _refreshOutcome
// says why: 'signed-out' (this tab's session is over), 'stale' (a different
// session is stored now: another user's, or one stored after a sign-out) or
// 'transient' (the refresh could not be done now; the session is kept), and
// api() leaves, reloads or just fails the request. See the comment above
// _authEpoch in core/router.js for what this guards against.
let _refreshPromise = null;
let _refreshOutcome = null;
let _refreshAdopted = false;   // the last successful call used another tab's newer token
const REFRESH_LOCK_WAIT_MS = 10000;
// This tab stops waiting for a refresh that has not answered by then: the
// request fails ('transient') and the lock is released, so one hung request
// does not hold every tab's refresh. The answer is still kept (_lateRefresh):
// if the server received the request it has rotated the refresh token, and
// dropping the answer would end the session. When it comes it is handled as if
// it had come in time. Until then (it is noted in localStorage, core/session.js)
// tabs use a newer session another tab stored if there is one; this tab's next
// 401 waits up to REFRESH_LATE_JOIN_MS for that answer; and the token is sent
// again at most once, as a probe: if the earlier request never reached the
// server, the probe renews the session; if it did, the probe gets a 401, which
// then ends nothing. Other requests fail as 'transient' meanwhile. The request
// itself is given up after REFRESH_ANSWER_MAX_MS.
const REFRESH_FETCH_TIMEOUT_MS = 20000;
const REFRESH_ANSWER_MAX_MS = 120000;
const REFRESH_LATE_JOIN_MS = 3000;
let _lateRefresh = null;
let _lateProbeSent = false;   // used when the note could not be written

async function _tryRefresh() {
  // One refresh per tab at a time; concurrent 401s share it (also while another
  // tab's sign-out is emptying the storage, so it can revoke its late session).
  if (_refreshPromise) return _refreshPromise;
  const s = _liveSession();
  if (!_lateRefresh && (!s || !s.refresh)) { _refreshOutcome = 'signed-out'; return false; }
  const epoch = _authEpoch;
  const sentWith = token;
  // This tab's own earlier refresh may answer any moment: give it a short while
  // (not when another tab already stored a usable newer session: use that).
  const late = _lateRefresh;
  const newerUsable = !!(s && s.token !== sentWith && !_expiresSoon(s.token) && !_isOtherUser(s.token));
  const p = (late && !newerUsable ? _withTimeout(late, REFRESH_LATE_JOIN_MS) : Promise.resolve())
    .then(() => _withRefreshLock(() => _refreshSession(epoch, sentWith)));
  _refreshPromise = p;
  p.then(() => { if (_refreshPromise === p) _refreshPromise = null; });
  return p;
}

// Runs fn holding a lock shared by every tab of this origin (Web Locks API), so
// two tabs do not rotate the same refresh token at once. Without the API, fn
// runs without it. If the lock is not granted within REFRESH_LOCK_WAIT_MS
// (another tab's refresh is hung or frozen), fn does NOT run: refreshing then
// could rotate the token under that tab, so the request fails ('transient') and
// the session is kept. The wait has its own timer (no AbortSignal.timeout).
async function _withRefreshLock(fn) {
  const locks = (typeof navigator !== 'undefined' && navigator && navigator.locks) || null;
  if (!locks || typeof locks.request !== 'function') return fn();
  const ctrl = (typeof AbortController === 'function') ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), REFRESH_LOCK_WAIT_MS) : null;
  let started = false;
  try {
    return await locks.request('sol-auth-refresh', ctrl ? { signal: ctrl.signal } : {}, () => {
      started = true;
      if (timer) clearTimeout(timer);
      return fn();
    });
  } catch {
    if (started) return false;
    _refreshOutcome = 'transient';
    return false;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

// POST /auth/refresh, given up after REFRESH_ANSWER_MAX_MS (also while its body
// is being read). Returns { status } or { status, body }; throws when there is
// no answer or the body cannot be read.
async function _postRefresh(refreshToken) {
  const ctrl = (typeof AbortController === 'function') ? new AbortController() : null;
  const timer = ctrl ? setTimeout(() => ctrl.abort(), REFRESH_ANSWER_MAX_MS) : null;
  try {
    const r = await fetch(API + '/auth/refresh', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: ctrl ? ctrl.signal : undefined,
    });
    if (!r.ok) return { status: r.status };
    return { status: r.status, body: await r.json() };
  } finally {
    if (timer) clearTimeout(timer);
  }
}

// What a stored session means to this tab, read through core/session.js: a
// pair counts only if its commit tag matches and its refresh token is not dead.
// Nothing here deletes a stored session (see core/session.js for why).
async function _refreshSession(epoch, sentWith) {
  // True while handling an answer that came after this tab stopped waiting: it
  // then stores, uses or revokes the session as usual, but the outcome of the
  // request that gave up was already reported, and another may be in progress.
  let late = false;
  const ended = () => epoch !== _authEpoch || _signedOutSinceLoad();
  // Another user's access token is stored, whether or not its pair counts yet
  // (a sign-in elsewhere may be half written).
  const otherUserStored = () => { const t = localStorage.getItem('sol_token'); return !!t && _isOtherUser(t); };
  // 'none': no session counts (none stored, a sign-out's leftovers, or a dead
  // refresh token); 'stale': a session that is not this tab's (another user's,
  // or one stored after a sign-out); 'mine': this tab's user's, and no sign-out
  // since this tab loaded.
  const stored = () => {
    const s = _solLiveSession();
    if (!s || !s.refresh) return otherUserStored() ? 'stale' : 'none';
    return (ended() || _isOtherUser(s.token)) ? 'stale' : 'mine';
  };
  const fail = outcome => { if (!late) _refreshOutcome = outcome; return false; };
  const adopt = t => { token = t; if (!late) _refreshAdopted = true; return true; };
  const start = _solLiveSession();
  const refresh = start && start.refresh;
  _refreshAdopted = false;
  // A newer, still usable access token of this tab's user that another tab
  // stored (it refreshed first), or null.
  const newerStored = () => {
    const s = _solLiveSession();
    return (stored() === 'mine' && s.refresh !== refresh && !_expiresSoon(s.token)) ? s.token : null;
  };
  // 401/403: this refresh token is not valid any more.
  const afterRejected = () => {
    const t = newerStored(); if (t) return adopt(t);
    const now = stored();
    if (now === 'stale') return fail('stale');
    if (now === 'mine' && _solLiveSession().refresh !== refresh) return fail('transient');   // newer session, access token not usable yet
    // A refresh of this token that a tab stopped waiting for may still answer
    // (it rotated it): that answer decides, not this 401.
    if (!late && (_solRefreshPending(refresh) || _lateRefresh)) return fail('transient');
    // This tab's session is over. List its refresh token as dead, so the other
    // tabs stop using it too (a concurrent refresh of the same token that
    // succeeded may still store its pair over it).
    _solMarkDead(refresh);
    return fail('signed-out');
  };
  // 429, 5xx, network, no answer in time: the session may well still be valid; keep it.
  const afterTransient = () => {
    const t = newerStored(); if (t) return adopt(t);
    const now = stored();
    return fail(now === 'stale' ? 'stale' : now === 'none' ? 'signed-out' : 'transient');
  };
  try {
    const before = stored();
    if (before !== 'mine') {
      // This tab's own earlier refresh may still answer: that decides.
      if (before === 'none' && _lateRefresh) return fail('transient');
      return fail(before === 'none' ? 'signed-out' : 'stale');
    }
    // Another tab already refreshed this session: use its access token rather
    // than rotating the refresh token again.
    if (start.token !== sentWith && !_expiresSoon(start.token)) return adopt(start.token);
    // A refresh of this token that a tab (this one or another) stopped waiting
    // for may still answer, and may already have rotated it: send it again only
    // as the one probe (see REFRESH_FETCH_TIMEOUT_MS); otherwise this request
    // fails and that answer decides.
    if (_solRefreshPending(refresh)) {
      if (!_solClaimProbe(refresh)) return fail('transient');
    } else if (_lateRefresh) {
      if (_lateProbeSent) return fail('transient');
      _lateProbeSent = true;
    }
    const startedAt = Date.now();
    const answer = _postRefresh(refresh);
    const TIMED_OUT = {};
    let timer = null;
    let a;
    try {
      a = await Promise.race([answer, new Promise(resolve => { timer = setTimeout(() => resolve(TIMED_OUT), REFRESH_FETCH_TIMEOUT_MS); })]);
    } catch {
      return afterTransient();
    } finally {
      clearTimeout(timer);
    }
    if (a === TIMED_OUT) {
      _solNotePending(refresh, startedAt + REFRESH_ANSWER_MAX_MS);
      _lateProbeSent = false;
      const kept = answer
        .then(x => { late = true; return handle(x); }, () => false)
        .catch(() => false)
        .finally(() => { _solClearPending(refresh); if (_lateRefresh === kept) _lateRefresh = null; });
      _lateRefresh = kept;
      return fail('transient');
    }
    return await handle(a);
  } catch {
    return afterTransient();
  }

  // What to do with the answer to this refresh.
  async function handle(a) {
    if (a.status === 401 || a.status === 403) return afterRejected();
    const d = a.body;
    if (!d || typeof d.access_token !== 'string' || !d.refresh_token) return afterTransient();
    const issued = d.refresh_token;
    if (ended()) {
      // Signed out (here or in another tab) while this refresh was in flight:
      // store nothing (that would sign the browser back in) and revoke what
      // the server just created, before this tab navigates (bounded).
      await _withTimeout(_revokeRefresh(issued), REVOKE_TIMEOUT_MS);
      return fail(stored() === 'none' ? 'signed-out' : 'stale');
    }
    if (_isOtherUser(d.access_token)) {
      // The stored refresh token was another user's: keep that user's rotated
      // session for them if it is still the one stored, but do not use it here.
      const s = _solStoredSession();
      if (s && s.refresh === refresh) _solWriteSession(d.access_token, issued);
      else _revokeRefresh(issued);
      return fail('stale');
    }
    const now = _solStoredSession();
    if (now && now.refresh === refresh && !_isOtherUser(now.token)) {
      // Storage still holds the session this refresh used (also when another
      // tab's refresh of the same token was rejected meanwhile and listed it as
      // dead: ours rotated it first): keep the pair.
      _solWriteSession(d.access_token, issued);
      _myToken = d.access_token;
      _myRefresh = issued;
      token = d.access_token;
      return true;
    }
    const live = _solLiveSession();
    if (live && live.refresh && !_isOtherUser(live.token)) {
      // Another tab stored a newer session of this user meanwhile. Ours is
      // redundant: revoke it without waiting (keepalive; nothing depends on the
      // answer). Use the stored session if its access token is usable;
      // otherwise keep using our own fresh access token, in memory only.
      _revokeRefresh(issued);
      if (!_expiresSoon(live.token)) return adopt(live.token);
      token = d.access_token;
      return true;
    }
    // No session of this tab's user counts now: a sign-out this tab has not
    // seen yet (or whose record could not be written), or another user's
    // sign-in, perhaps half written. Store nothing and revoke what we were given.
    await _withTimeout(_revokeRefresh(issued), REVOKE_TIMEOUT_MS);
    return fail(stored() === 'stale' ? 'stale' : 'signed-out');
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
// A passing failure (5xx, 429, no answer, a refresh that could not be done right
// now) never signs the user out: init() keeps the session and tries again,
// waiting INIT_RETRY_FIRST_MS, then twice as long each time, at most
// INIT_RETRY_MAX_MS.
const INIT_RETRY_FIRST_MS = 2000;
const INIT_RETRY_MAX_MS = 30000;
let _initRetryMs = INIT_RETRY_FIRST_MS;
async function init() {
  // This tab is already leaving (a sign-out, or another user's sign-in, in
  // another tab while it loaded), or state.js took no session and sent it to
  // the sign-in page: load nothing.
  if (_logoutPromise || _leavePending() || !token) return;
  try {
    me = await api('/auth/me');
    _initRetryMs = INIT_RETRY_FIRST_MS;
    document.getElementById('userEmail').textContent = me.email;
    applyFeatureFlags();   // re-reveal role-gated UI (e.g. /admin) now that me.is_admin is known
    loadDashboard();  // one consolidated, partial-failure-safe load feeds every card
    consumePendingInvite();  // if user arrived via ?invite=..., auto-join now
    // Returning from Stripe Checkout (?premium=success|cancel) — open the Premium
    // page so loadPremium() can show the return note and poll for activation.
    if (new URLSearchParams(location.search).get('premium')) nav('premium');
    // Return from participation checkout (?participation=success) — flag-gated; loadCatalog polls backend truth.
    if (featureOn('catalog') && new URLSearchParams(location.search).get('participation')) nav('catalog');
  } catch (e) {
    // A sign-out in progress (core/router.js logout()) revokes the session and
    // redirects by itself; navigating here first would cancel its revoke.
    if (_logoutPromise) { await _logoutPromise; return; }
    // api() is already leaving or reloading this tab (another session is stored,
    // or none).
    if (_leavePending()) return;
    if (e && (e.transient || e.status === 429 || e.status >= 500 || _aborted(e))) {
      // Say so, rather than sit on the loading state (a rate limit can last
      // minutes); the Sign out button stays usable.
      try { const el = document.getElementById('userEmail'); if (el) el.textContent = 'Reconnecting…'; } catch {}
      const wait = _initRetryMs;
      _initRetryMs = Math.min(_initRetryMs * 2, INIT_RETRY_MAX_MS);
      setTimeout(init, wait);
      return;
    }
    // Anything else: go to the sign-in page. Nothing is deleted: this tab's copy
    // of localStorage may be behind the others', and another tab may have stored
    // a newer session meanwhile (core/session.js).
    window.location.href = '/sol/';
  }
}

// Build the "Your money" panel: per-circle next-contribution date, next-payout
// estimate, and the running total this user has contributed across all active
// circles.
