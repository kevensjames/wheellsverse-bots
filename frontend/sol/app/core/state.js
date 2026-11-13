// SOL member app — core/state.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

const API = 'https://sol-api-production.up.railway.app';
let token = localStorage.getItem('sol_token');
// Read with the token, in the same script: a sign-out in another tab while the
// rest of the app is still loading must not be mistaken for an older one
// (core/router.js compares against it).
const _signoutAtStart = localStorage.getItem('sol_signout');
let me = null;

if (!token) { window.location.href = '/sol/'; }
