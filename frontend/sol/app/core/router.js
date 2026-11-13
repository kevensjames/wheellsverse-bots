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
// The session is shared by every tab of this origin (localStorage), so a tab
// guards against three things (see _tryRefresh in core/api.js):
// - A sign-out, in this tab (_authEpoch) or in any tab (SIGNOUT_KEY, which
//   logout() changes on every sign-out). A request from before it is never
//   refreshed or re-sent, even if someone has signed in again since, and a
//   refresh that answers after it stores nothing and revokes what it was given.
// - Another user's session. A tab only continues with sessions of the user it
//   was opened for (the `sub` of its access token); otherwise it reloads.
// - Two tabs refreshing at once. Refreshes take a lock shared by the tabs (Web
//   Locks API) where available, and a tab whose refresh is rejected because
//   another tab rotated the token first uses the session that tab stored.
let _authEpoch = 0;
const REVOKE_TIMEOUT_MS = 3000;
const SIGNOUT_KEY = 'sol_signout';
const _signoutAtLoad = localStorage.getItem(SIGNOUT_KEY);
let _leaving = false;   // this tab is already navigating away or reloading

// True when a sign-out happened, in this tab or another, since this tab loaded.
function _signedOutSinceLoad() { return localStorage.getItem(SIGNOUT_KEY) !== _signoutAtLoad; }

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
// The user this tab was opened for (state.js read its token). Null if the token
// cannot be read; the user check is then skipped.
const _tabUser = _tokenUser(typeof token !== 'undefined' ? token : null);
// True when `jwt` belongs to a different user than this tab's (both known).
function _isOtherUser(jwt) { const u = _tokenUser(jwt); return !!(_tabUser && u && u !== _tabUser); }
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

// Sign out. Records the sign-out for the other tabs (SIGNOUT_KEY), clears BOTH
// stored tokens, so nothing can reuse them, then asks the backend to revoke this
// device's refresh session (POST /auth/logout), then leaves. Bumping _authEpoch
// stops a refresh already in flight in this tab from storing new tokens
// afterwards; logout also waits for that refresh, so if it answers within the
// bound the session it created is revoked before the page goes away. api()
// calls that get a 401 meanwhile wait for this sign-out instead of navigating
// first. The whole wait is bounded (REVOKE_TIMEOUT_MS): a failed, slow or
// unreachable revoke never keeps the user signed in here. Repeated clicks share
// one sign-out.
// Limits: revocation ends the refresh session only; an access token already
// issued stays valid at the API until it expires.
let _logoutPromise = null;
function logout() {
  if (_logoutPromise) return _logoutPromise;
  _authEpoch++;
  const refresh = localStorage.getItem('sol_refresh');
  // core/api.js may not have run yet; then no refresh can be in flight.
  const inflightRefresh = (typeof _refreshPromise !== 'undefined') ? _refreshPromise : null;
  try { localStorage.setItem(SIGNOUT_KEY, Date.now() + '-' + Math.random().toString(36).slice(2)); } catch {}
  localStorage.removeItem('sol_token');
  localStorage.removeItem('sol_refresh');
  token = null;
  _logoutPromise = _withTimeout(Promise.all([_revokeRefresh(refresh), inflightRefresh]), REVOKE_TIMEOUT_MS)
    .then(() => { _leaving = true; window.location.href = '/sol/'; });
  return _logoutPromise;
}

// Leave once a refresh in flight in this tab has finished (bounded): it sees
// that the session changed, stores nothing and revokes the session it was
// given, and leaving first would cancel that. Several events while waiting
// share one wait; a reload wins over the sign-in page.
let _leaveWantReload = null;
function _leaveAfterRefresh(reload) {
  const first = _leaveWantReload === null;
  _leaveWantReload = !!reload || _leaveWantReload === true;
  if (!first) return;
  token = null;
  const inflight = (typeof _refreshPromise !== 'undefined') ? _refreshPromise : null;
  _withTimeout(inflight, REVOKE_TIMEOUT_MS).then(() => _leave(_leaveWantReload));
}

// Follow the other tabs at once instead of acting with this tab's in-memory
// access token until it expires: a sign-out elsewhere signs this tab out, and
// another user signing in reloads it. Other changes (a refresh by another tab,
// or another tab dropping only its access token after an error) change nothing.
if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
  window.addEventListener('storage', e => {
    if (_leaving || _logoutPromise) return;
    if (e.key === null || e.key === SIGNOUT_KEY) _leaveAfterRefresh(false);
    else if (e.key === 'sol_token' && e.newValue && _isOtherUser(e.newValue)) _leaveAfterRefresh(true);
  });
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
