// SOL member app — core/router.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── Nav ───────────────────────────────────────────────────────────────────────
function nav(page) {
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
let _moreTrigger = null;
function openMore() {
  const s = document.getElementById('moreSheet');
  if (!s) return;
  _moreTrigger = document.activeElement;
  s.classList.add('open'); s.setAttribute('aria-hidden', 'false');
  document.addEventListener('keydown', _moreTrapKey, true);   // aria-modal now backed by a real trap
  // Focus after the sheet's slide-in transition settles (unlike the display-toggle
  // .bank-modal dialogs, this sheet animates in, so a 0ms focus lands too early).
  // The trap also pulls focus in on the first Tab, so this is best-effort.
  const first = s.querySelector('.more-item');
  requestAnimationFrame(() => requestAnimationFrame(() => { if (first && s.classList.contains('open')) first.focus(); }));
}
function closeMore() {
  const s = document.getElementById('moreSheet');
  if (!s) return;
  const wasOpen = s.classList.contains('open');
  s.classList.remove('open'); s.setAttribute('aria-hidden', 'true');
  document.removeEventListener('keydown', _moreTrapKey, true);
  if (wasOpen) { const t = _moreTrigger; _moreTrigger = null; if (t && typeof t.focus === 'function') { try { t.focus(); } catch (e) {} } }
}
function _moreTrapKey(e) {
  const d = document.getElementById('moreSheet'); if (!d || !d.classList.contains('open')) return;
  if (e.key === 'Escape') { e.preventDefault(); closeMore(); return; }
  if (e.key === 'Tab') {
    const f = [...d.querySelectorAll('button:not([disabled])')].filter(x => x.offsetParent !== null);
    if (!f.length) { e.preventDefault(); return; }
    const first = f[0], last = f[f.length - 1];
    if (!d.contains(document.activeElement)) { e.preventDefault(); first.focus(); return; }
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
}
function navMore(page) { closeMore(); nav(page); }
