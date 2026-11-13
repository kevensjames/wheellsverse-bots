// SOL member app — core/state.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

const API = 'https://sol-api-production.up.railway.app';
// The stored session only if it counts (core/session.js): not a pair another
// tab wrote late after a sign-out, nor one whose refresh token is dead. An
// app.html cached from before core/session.js existed loads these scripts
// without it: then take no session (the sign-in page; a fresh load of the app
// gets matching files) rather than fail to load.
const _sessionAtStart = (typeof _solLiveSession === 'function') ? _solLiveSession() : null;
let token = _sessionAtStart ? _sessionAtStart.token : null;
// Read with the token, in the same script: a sign-out in another tab while the
// rest of the app is still loading must not be mistaken for an older one
// (core/router.js compares against it).
const _signoutAtStart = localStorage.getItem('sol_signout');
let me = null;

if (!token) { window.location.href = '/sol/'; }
