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
// _authEpoch counts sign-outs in this tab. A refresh records it when it starts;
// if a sign-out happens before the refresh answers, the refresh must not store
// the new tokens (that would sign the tab back in) and revokes them instead
// (see _tryRefresh in core/api.js).
let _authEpoch = 0;
const REVOKE_TIMEOUT_MS = 3000;

// Settles when `p` settles or after `ms`, whichever is first; never rejects.
function _withTimeout(p, ms) {
  let timer;
  const limit = new Promise(resolve => { timer = setTimeout(resolve, ms); });
  return Promise.race([Promise.resolve(p).catch(() => {}), limit]).finally(() => clearTimeout(timer));
}

// Best-effort revoke of one refresh token (POST /auth/logout, body exactly
// {refresh_token}: the backend rejects extra fields). Resolves true only when the
// server answers 2xx; never throws. A 2xx is not proof of revocation (the
// backend also answers 204 for an unknown token), and it does not end an access
// token already issued.
async function _revokeRefresh(refreshToken) {
  if (!refreshToken) return false;
  try {
    const r = await fetch(API + '/auth/logout', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    return !!(r && r.ok);
  } catch {
    return false;
  }
}

// Sign out. Clears BOTH stored tokens first, so nothing in this tab can reuse
// them, then asks the backend to revoke this device's refresh session
// (POST /auth/logout), then leaves. Bumping _authEpoch stops a refresh that is
// already in flight from storing new tokens afterwards; logout also waits for
// that refresh, so if it answers within the bound the session it created is
// revoked before the page goes away. api() calls that get a 401 meanwhile wait
// for this sign-out instead of navigating first (a navigation would cancel the
// revoke request). The whole wait is bounded (REVOKE_TIMEOUT_MS): a failed,
// slow or unreachable revoke never keeps the user signed in here. Repeated
// clicks share one sign-out.
// Limits: revocation ends the refresh session only; an access token already
// issued stays valid at the API until it expires. Navigation started by
// anything else during the wait can still cancel the revoke.
let _logoutPromise = null;
function logout() {
  if (_logoutPromise) return _logoutPromise;
  _authEpoch++;
  const refresh = localStorage.getItem('sol_refresh');
  // core/api.js may not have run yet; then no refresh can be in flight.
  const inflightRefresh = (typeof _refreshPromise !== 'undefined') ? _refreshPromise : null;
  localStorage.removeItem('sol_token');
  localStorage.removeItem('sol_refresh');
  token = null;
  _logoutPromise = _withTimeout(Promise.all([_revokeRefresh(refresh), inflightRefresh]), REVOKE_TIMEOUT_MS)
    .then(() => { window.location.href = '/sol/'; });
  return _logoutPromise;
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
