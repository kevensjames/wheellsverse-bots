// SOL member app — core/router.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── Nav ───────────────────────────────────────────────────────────────────────
// P3 — request cancellation: each navigation owns an AbortController. Switching
// routes aborts the previous route's in-flight GET loads so a slow response can't
// render into (or clobber) a page the user already left. api() attaches this
// signal to GETs only, so in-flight mutations (payments, cancels, joins) are
// NEVER cancelled by navigation. See core/api.js.
let _routeAbort = null;
function nav(page) {
  if (page === 'catalog' && !featureOn('catalog')) return;   // route gated behind SOL_FEATURES.catalog (defense-in-depth; nav entries are also hidden)
  if (page === 'admin' && (!featureOn('catalog') || !isAdmin())) return;   // role-gated /admin route (UX; backend enforces authz)
  try { if (_routeAbort) _routeAbort.abort(); } catch (e) {}
  _routeAbort = (typeof AbortController !== 'undefined') ? new AbortController() : null;
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => { n.classList.remove('active'); n.removeAttribute('aria-current'); });
  document.querySelectorAll('.mn').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + page)?.classList.add('active');
  const _side = document.querySelector(`[data-page="${page}"]`);
  if (_side) { _side.classList.add('active'); _side.setAttribute('aria-current', 'page'); }
  document.querySelector(`[data-mpage="${page}"]`)?.classList.add('active');
  if (page === 'groups') loadGroups();
  if (page === 'kyc') loadKYC();
  if (page === 'bank') loadBank();
  if (page === 'payments') loadMyPayments();
  if (page === 'discover') loadDiscover();
  if (page === 'catalog') loadCatalog();   // Phase 3 — flag-gated inside loadCatalog()
  if (page === 'admin') loadAdmin();       // Phase 3 — flag + role gated inside loadAdmin()
  if (page === 'timeline') loadTimeline();
  if (page === 'trust') loadTrust();
  if (page === 'premium') loadPremium();
  if (page === 'notifications') loadNotifications();
  if (page === 'community') loadCommunity();
  if (page === 'goals') loadGoals();
  if (page === 'dashboard') loadDashboard();   // revalidate summary cards on return (they change after money/goal mutations elsewhere)
  try { if (typeof SolOrb !== 'undefined') { page === 'dashboard' ? SolOrb.resume() : SolOrb.stop(); } } catch (e) {}
}

// ── Sign-out and session revocation ──────────────────────────────────────────
// These live here, not in core/api.js: app.html loads router.js before api.js,
// and the Sign out button can be clicked before api.js has run, so logout()
// must not depend on api.js having loaded.
//
// The session is shared by every tab of this origin (localStorage; see
// core/session.js for how a stored pair counts), so a tab guards against three
// things (see _tryRefresh in core/api.js):
// - A sign-out, in this tab (_authEpoch) or in another (the sign-out record,
//   which logout() and the landing page's sign-in change when they end a
//   session, and a 'signed-out' message on the sol-auth channel). Once a tab has
//   seen it, a request from before it is not refreshed or re-sent, even if
//   someone has signed in again since, and a refresh that answers after it
//   stores nothing and revokes what it was given. Each tab has its own copy of
//   localStorage that other tabs' writes reach a little later, so a tab that
//   has not seen the sign-out yet can still store a late pair (and re-send the
//   request it refreshed for, under that pair); the pair carries the earlier
//   record in its tag, so no page uses it, and the tab revokes it when the
//   sign-out reaches it (_endMySession). No tab deletes anything for this; the
//   late pair stays stored, unused, until the next sign-in replaces it, and its
//   access token stays valid at the API until it expires.
// - Another user's session. A tab only continues with sessions of the user it
//   was opened for (the `sub` of its access token); otherwise it reloads.
// - Two tabs refreshing at once. Refreshes take a lock shared by the tabs (Web
//   Locks API) where available; a tab whose refresh is rejected because another
//   tab rotated the token first uses the session that tab stored, and only a
//   rejected refresh (401/403) ends the session: a 429, 5xx, network error or a
//   refresh that does not answer in time keeps it.
let _authEpoch = 0;
const REVOKE_TIMEOUT_MS = 3000;
const SIGNOUT_KEY = 'sol_signout';   // SOL_SIGNOUT_KEY in core/session.js (named here so this file loads without it)
const _signoutAtLoad = (typeof _signoutAtStart !== 'undefined') ? _signoutAtStart : localStorage.getItem(SIGNOUT_KEY);
let _signoutSeen = false;   // a 'signed-out' message, or the record changing, reached this tab
let _leaving = false;       // this tab is already navigating away or reloading

// The pair this tab itself last stored (see _refreshSession in core/api.js).
// When a sign-out or another user's sign-in elsewhere reaches this tab, that
// pair's session is over: list it as dead (so no page uses it, even if this
// tab's late write landed last) and revoke it. Nothing is deleted: this tab's
// copy of localStorage may be behind, and a delete could remove a newer session.
let _myToken = null, _myRefresh = null;
function _endMySession() {
  const mine = _myRefresh;
  _myToken = _myRefresh = null;
  if (typeof _solMarkDead === 'function') _solMarkDead(mine);
  return _revokeRefresh(mine);
}

// The stored session that counts (core/session.js), or null. Also null when
// core/session.js did not load (an app.html from before it): such a page takes
// no session (see core/state.js) and must still be able to sign out and leave.
function _liveSession() { return (typeof _solLiveSession === 'function') ? _solLiveSession() : null; }

// This tab's refresh still in flight, and one it stopped waiting for whose
// answer may still come (core/api.js). Leaving first would cancel either.
function _refreshesInFlight() {
  return Promise.all([
    (typeof _refreshPromise !== 'undefined') ? _refreshPromise : null,
    (typeof _lateRefresh !== 'undefined') ? _lateRefresh : null,
  ]);
}

// True when a sign-out happened, in this tab or another, since this tab loaded.
function _signedOutSinceLoad() { return _signoutSeen || localStorage.getItem(SIGNOUT_KEY) !== _signoutAtLoad; }

// The claims of an access token (a JWT), or null when they cannot be read. Used
// only to tell apart sessions of different users in this browser, never to
// authorize anything (the API verifies the token itself).
function _tokenClaims(jwt) {
  try {
    const part = String(jwt).split('.')[1];
    if (!part) return null;
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - part.length % 4) % 4);
    const claims = JSON.parse(atob(b64));
    return claims && typeof claims === 'object' ? claims : null;
  } catch {
    return null;
  }
}
function _tokenUser(jwt) { const c = _tokenClaims(jwt); return c && typeof c.sub === 'string' ? c.sub : null; }
// The user this tab was opened for (state.js read its token). Null if that token
// cannot be read; the user check is then skipped for this tab.
const _tabUser = _tokenUser(typeof token !== 'undefined' ? token : null);
// True when `jwt` is not this tab's user's. Once this tab's user is known, a
// token whose user cannot be read counts as another user's.
function _isOtherUser(jwt) { return !!_tabUser && _tokenUser(jwt) !== _tabUser; }
// True when `jwt` cannot be used for at least another 30 s (or its expiry is unknown).
function _expiresSoon(jwt) { const c = _tokenClaims(jwt); return !(c && typeof c.exp === 'number' && c.exp * 1000 > Date.now() + 30000); }

// Settles when `p` settles or after `ms`, whichever is first; never rejects.
function _withTimeout(p, ms) {
  let timer;
  const limit = new Promise(resolve => { timer = setTimeout(resolve, ms); });
  return Promise.race([Promise.resolve(p).catch(() => {}), limit]).finally(() => clearTimeout(timer));
}

// Best-effort revoke of one refresh token (POST /auth/logout, body exactly
// {refresh_token}: the backend rejects extra fields). keepalive lets the request
// outlive a navigation or a closed tab, which would otherwise cancel it.
// Resolves true only when the server answers 2xx; never throws. A 2xx is not
// proof of revocation (the backend also answers 204 for an unknown token), and
// it does not end an access token already issued.
async function _revokeRefresh(refreshToken) {
  if (!refreshToken) return false;
  try {
    const r = await fetch(API + '/auth/logout', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ refresh_token: refreshToken }),
      keepalive: true,
    });
    return !!(r && r.ok);
  } catch {
    return false;
  }
}

// Leave this tab once: to the sign-in page, or reload it when a different
// session is stored now (its page belongs to the old one).
function _leave(reload) {
  if (_leaving) return;
  _leaving = true;
  token = null;
  if (reload) window.location.reload();
  else window.location.href = '/sol/';
}

// Sign out. Records the sign-out for the other tabs (a new sign-out record and,
// with it, a tag for no session, so a pair another tab writes late does not
// count), clears BOTH stored tokens, so nothing can reuse them, announces it on
// the sol-auth channel, then asks the backend to revoke this device's refresh
// session (POST /auth/logout), then leaves. Bumping _authEpoch stops a refresh
// already in flight in this tab from storing new tokens afterwards; logout also
// waits for that refresh, so if it answers within the bound the session it
// created is revoked before the page goes away. api() calls that get a 401
// meanwhile wait for this sign-out instead of navigating first. The whole wait
// is bounded (REVOKE_TIMEOUT_MS): a failed, slow or unreachable revoke never
// keeps the user signed in here. Repeated clicks share one sign-out.
// Limits: revocation ends the refresh session only; an access token already
// issued stays valid at the API until it expires.
let _logoutPromise = null;
function logout() {
  if (_logoutPromise) return _logoutPromise;
  _authEpoch++;
  const refresh = localStorage.getItem('sol_refresh');
  // core/api.js may not have run yet; then no refresh can be in flight.
  const inflightRefresh = _refreshesInFlight();
  // The record and the empty tag go first, so the other tabs see the sign-out
  // before the tokens go. If storage is full, the record is retried once
  // removing the tokens has freed space; even if it never lands, the
  // announcement reaches the open tabs, and a refresh elsewhere will not store
  // a pair into the emptied storage (see _refreshSession).
  // (Written here rather than through core/session.js, so that sign-out works
  // on a page where that file did not load.)
  const writeRecord = () => { try { localStorage.setItem(SIGNOUT_KEY, Date.now() + '-' + Math.random().toString(36).slice(2)); return true; } catch { return false; } };
  const tagNoSession = () => { try { if (typeof _solTag === 'function') localStorage.setItem(SOL_SESSION_KEY, _solTag(null, null, localStorage.getItem(SIGNOUT_KEY))); } catch {} };
  const recorded = writeRecord();
  tagNoSession();
  localStorage.removeItem('sol_token');
  localStorage.removeItem('sol_refresh');
  if (!recorded && writeRecord()) tagNoSession();
  if (typeof _solAnnounceSignout === 'function') _solAnnounceSignout();
  _myToken = _myRefresh = null;
  token = null;
  _logoutPromise = _withTimeout(Promise.all([_revokeRefresh(refresh), inflightRefresh]), REVOKE_TIMEOUT_MS)
    .then(() => { _leaving = true; window.location.href = '/sol/'; });
  return _logoutPromise;
}

// Leave once a refresh in flight in this tab has finished (bounded): it sees
// that the session changed, stores nothing and revokes the session it was
// given, and leaving first would cancel that. Every caller shares one wait; a
// reload wins over the sign-in page, and the tab also reloads (rather than
// showing the sign-in page) when a session that counts is stored by the time it
// leaves.
// Limit: a refresh that answers after the bound is cancelled by the navigation;
// the session the server created for it then stays active, held by no browser.
// When the sign-out came from a sign-in elsewhere (the landing page replacing
// the session), the new pair follows the sign-out record, and this tab's copy of
// localStorage receives the writes one at a time: it waits up to
// SIGNIN_FOLLOWS_WAIT_MS for that pair before choosing the sign-in page, so it
// reloads into the new session instead.
const SIGNIN_FOLLOWS_WAIT_MS = 500;
let _leaveWantReload = null;
let _leaveSignInFollows = false;
function _leavePending() { return _leaving || _leaveWantReload !== null; }
function _leaveAfterRefresh(reload, signInFollows) {
  const first = _leaveWantReload === null;
  _leaveWantReload = !!reload || _leaveWantReload === true;
  _leaveSignInFollows = _leaveSignInFollows || !!signInFollows;
  if (!first) return;
  token = null;
  _withTimeout(_refreshesInFlight(), REVOKE_TIMEOUT_MS).then(() => {
    const until = Date.now() + (_leaveSignInFollows ? SIGNIN_FOLLOWS_WAIT_MS : 0);
    const decide = () => {
      if (_leaveWantReload || _liveSession()) return _leave(true);
      if (Date.now() < until && !_leaving) return void setTimeout(decide, 50);
      _leave(false);
    };
    decide();
  });
}

// Follow the other tabs at once instead of acting with this tab's in-memory
// access token until it expires: a sign-out elsewhere (its record, or its
// announcement on the sol-auth channel) signs this tab out, and another user
// signing in reloads it; in both cases this tab first ends a pair it stored
// itself. Other changes (a refresh by another tab, another tab listing a dead
// refresh token) change nothing.
function _onSignedOutElsewhere(signInFollows) {
  _signoutSeen = true;
  if (_leaving || _logoutPromise) return;
  _endMySession();
  _leaveAfterRefresh(false, signInFollows);
}
if (typeof _solChannel !== 'undefined' && _solChannel) {
  _solChannel.addEventListener('message', e => { if (e && e.data && e.data.type === 'signed-out') _onSignedOutElsewhere(e.data.next === true); });
}
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('storage', e => {
    if (e.key === null || e.key === SIGNOUT_KEY) { _onSignedOutElsewhere(e.key !== null && typeof _solRecordIsSignIn === 'function' && _solRecordIsSignIn(e.newValue)); return; }
    if (_leaving || _logoutPromise) return;
    if (e.key === 'sol_token' && e.newValue && _isOtherUser(e.newValue)) { _endMySession(); _leaveAfterRefresh(true); }
  });
  // Back/forward cache: a restored page keeps its old JS state and still shows
  // the old session's data. If this page signed out, or no session that counts
  // is stored or it is another user's, reload it so state.js starts again from
  // what is stored now (and sends the tab to the sign-in page when nothing
  // counts). Storage events the page missed while cached arrive after this;
  // _leaving makes them change nothing, so the reload is not replaced.
  window.addEventListener('pageshow', e => {
    if (!e || !e.persisted) return;
    const stored = _liveSession();
    if (_logoutPromise || _leaving || _signedOutSinceLoad() || !stored || _isOtherUser(stored.token)) {
      if (_signedOutSinceLoad()) _endMySession();
      _leaving = true;
      window.location.reload();
    }
  });
}

// A sign-out, or another user's sign-in, in another tab while this page was
// still loading (before the listener above existed): leave now.
if (typeof token !== 'undefined' && token) {
  const storedAtLoad = _liveSession();
  if (_signedOutSinceLoad()) _leaveAfterRefresh(false);
  else if (storedAtLoad && _isOtherUser(storedAtLoad.token)) _leaveAfterRefresh(true);
}

// Mobile "More" sheet
// Mobile "More" bottom sheet — a sliding sheet (openClass 'open', aria-hidden
// toggled), so SolDialog focuses the first item after the slide-in transition
// (mobileSheet). The backdrop's inline onclick still calls closeMore().
function openMore() {
  SolDialog.open('moreSheet', { openClass: 'open', ariaHidden: true, mobileSheet: true, initialFocus: '.more-item' });
}
function closeMore() { SolDialog.close('moreSheet'); }
function navMore(page) { closeMore(); nav(page); }
