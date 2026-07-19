// SOL member app — core/state.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

const API = 'https://sol-api-production.up.railway.app';
let token = localStorage.getItem('sol_token');
let me = null;

if (!token) { window.location.href = '/sol/'; }
