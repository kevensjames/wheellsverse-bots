// SOL member app — main.js
// Classic script (shared global scope); loaded LAST by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.
// Boot: init() authenticates + loads the dashboard; refreshUnread() populates
// the Alerts badge. Both depend on functions defined in the files loaded above.

init();
refreshUnread();
applyFeatureFlags();   // reveal any flag-gated nav/UI (Phase 3 catalog is OFF by default)
