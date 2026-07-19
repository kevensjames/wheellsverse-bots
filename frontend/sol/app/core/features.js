// SOL member app — core/features.js
// Classic script (shared global scope); loaded FIRST by app.html. Centralized
// feature flags. Every flag is OFF by default; a flagged surface (a nav entry,
// a route) appears only when its flag is true. Phase 3 Circle Catalog ships dark
// behind SOL_FEATURES.catalog until the real Phase 3 backend contract is live —
// see docs/sol/PHASE3_API_CONTRACT.md.
window.SOL_FEATURES = {
  catalog: false,   // Phase 3 — Circle Catalog browse (mock-backed; backend is a separate repo)
};

// Reveal flag-gated UI: any element with data-feature="X" is shown iff
// SOL_FEATURES.X is true. Elements ALSO carrying data-admin are shown only when
// the current member is an admin (backend-authoritative — this is UX-only; the
// backend enforces authz on every /admin call). Called at boot AND after `me`
// loads (init), since admin status isn't known until then.
function applyFeatureFlags() {
  document.querySelectorAll('[data-feature]').forEach((el) => {
    let on = !!(window.SOL_FEATURES && window.SOL_FEATURES[el.dataset.feature]);
    if (on && el.hasAttribute('data-admin')) on = isAdmin();
    if (on) el.removeAttribute('hidden');
    else el.setAttribute('hidden', '');
  });
}

// Guard for a flagged route/loader — true when the feature is enabled.
function featureOn(name) {
  return !!(window.SOL_FEATURES && window.SOL_FEATURES[name]);
}

// Admin gate (UX only — backend enforces authz). True when /auth/me marks the
// member an admin. Guarded so it's safe before `me` loads.
function isAdmin() {
  try { return !!(me && me.is_admin === true); } catch (e) { return false; }
}
