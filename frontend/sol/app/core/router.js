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
  if (page === 'timeline') loadTimeline();
  if (page === 'trust') loadTrust();
  if (page === 'premium') loadPremium();
  if (page === 'notifications') loadNotifications();
  if (page === 'community') loadCommunity();
  if (page === 'goals') loadGoals();
  if (page === 'dashboard') loadDashboard();   // revalidate summary cards on return (they change after money/goal mutations elsewhere)
  try { if (typeof SolOrb !== 'undefined') { page === 'dashboard' ? SolOrb.resume() : SolOrb.stop(); } } catch (e) {}
}

function logout() {
  localStorage.removeItem('sol_token');
  window.location.href = '/sol/';
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
