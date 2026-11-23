// SOL member session in localStorage — core/session.js
// Classic script, shared by the member app (app.html loads it before
// core/state.js) and the landing page (index.html loads it before finishAuth()).
//
// The session (sol_token, sol_refresh) is shared by every tab of this origin.
// Each tab reads its own copy of localStorage, which other tabs' writes reach a
// little later (Chromium), and no API lets a tab write only if a value is still
// what it read. So a tab never deletes a stored session because of what it read:
// its copy may be behind, and the delete would remove a newer session (another
// user's sign-in). Instead:
// - Whoever stores a session writes the two tokens and then a commit tag
//   (sol_session) naming the sign-out record (sol_signout) it saw, the user of
//   the pair and the pair itself. A stored pair counts only while the tag was
//   written under the current record for the same user (_solTagCovers). A tab
//   whose late write lands after a sign-out elsewhere tagged its pair with the
//   earlier record, and a late pair of one user written over another user's
//   sign-in names the wrong user, so no page uses either. A pair of the same
//   user under the same record still counts even when the tag does not name
//   it: a tab still running an earlier version refreshed it (no tag), or the
//   tag has not reached this tab's copy of localStorage yet (another tab's
//   writes arrive one at a time).
// - A refresh token the server rejected, or that a tab ends because of a
//   sign-out or another user's sign-in elsewhere, is marked dead (one key per
//   token, sol_dead.<fingerprint>, so tabs marking at once do not overwrite
//   each other) instead of being deleted.
// - A refresh that a tab stopped waiting for, whose answer may still come, is
//   noted (sol_refresh_pending): until the answer comes or the request is given
//   up, tabs send that refresh token again at most once (a probe) and do not
//   end the session over a 401 on it.
// - Only the user's own sign-out removes the tokens, and a sign-in replaces them.
// A pair stored before this file existed has no tag at all and counts as before.
// Limit: when two sign-ins or a sign-in and a sign-out race in different tabs,
// the later one's pair may not count; the user then signs in again. A sign-in
// written by a landing page of an earlier version (no tag) over a tagged pair
// of another user does not count either.
const SOL_SIGNOUT_KEY = 'sol_signout';
const SOL_SESSION_KEY = 'sol_session';
const SOL_DEAD_PREFIX = 'sol_dead.';
const SOL_DEAD_KEEP_MS = 24 * 3600 * 1000;   // dead marks older than this are pruned (their access tokens expired long ago)
const SOL_PENDING_KEY = 'sol_refresh_pending';
// One channel per page: a sign-out is also announced here, so open tabs leave
// even when its record cannot be written (storage full). A message never
// reaches the channel that posted it.
const _solChannel = (typeof BroadcastChannel === 'function') ? new BroadcastChannel('sol-auth') : null;

function _solFingerprint(t) { return t ? String(t).length + '.' + String(t).slice(-16) : '-'; }
// The user an access token (a JWT) names (its `sub`), or null when it cannot be
// read. Only used to tell sessions of different users apart, never to authorize
// anything (the API verifies the token).
function _solUser(jwt) {
  try {
    const part = String(jwt).split('.')[1];
    if (!part) return null;
    const b64 = part.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - part.length % 4) % 4);
    const claims = JSON.parse(atob(b64));
    return claims && typeof claims.sub === 'string' && claims.sub ? claims.sub : null;
  } catch {
    return null;
  }
}
function _solTag(token, refresh, signout) {
  const user = token ? _solUser(token) : null;
  return [signout || '-', user ? encodeURIComponent(user) : '-', _solFingerprint(token), _solFingerprint(refresh)].join('|');
}
// True when `tag` covers the stored pair: it names that pair under the current
// sign-out record, or it was written under the current record for the same
// (readable) user. A tag for no session (a sign-out's) covers nothing.
function _solTagCovers(tag, token, refresh, signout) {
  if (tag === _solTag(token, refresh, signout)) return true;
  const parts = String(tag).split('|');
  const user = _solUser(token);
  return parts[0] === (signout || '-') && !!user && parts[1] === encodeURIComponent(user);
}
function _solIsDead(refresh) {
  return !!refresh && localStorage.getItem(SOL_DEAD_PREFIX + _solFingerprint(refresh)) !== null;
}

// The stored session { token, refresh, dead } if it counts (see above), else null.
function _solStoredSession() {
  const token = localStorage.getItem('sol_token');
  if (!token) return null;
  const refresh = localStorage.getItem('sol_refresh');
  const tag = localStorage.getItem(SOL_SESSION_KEY);
  if (tag !== null && !_solTagCovers(tag, token, refresh, localStorage.getItem(SOL_SIGNOUT_KEY))) return null;
  return { token, refresh, dead: _solIsDead(refresh) };
}
// The stored session a page may use: it counts and its refresh token is not dead.
function _solLiveSession() {
  const s = _solStoredSession();
  return s && !s.dead ? s : null;
}

// Store a session: both tokens, then the tag, so a pair half written never
// counts. Throws if storage refuses a write (as setItem does).
function _solWriteSession(token, refresh) {
  localStorage.setItem('sol_token', token);
  if (refresh) localStorage.setItem('sol_refresh', refresh);
  else localStorage.removeItem('sol_refresh');
  localStorage.setItem(SOL_SESSION_KEY, _solTag(token, refresh, localStorage.getItem(SOL_SIGNOUT_KEY)));
}

// Mark a refresh token as dead (its own key), and prune old marks. Best effort.
function _solMarkDead(refresh) {
  if (!refresh) return;
  try { localStorage.setItem(SOL_DEAD_PREFIX + _solFingerprint(refresh), String(Date.now())); } catch {}
  try {
    if (typeof localStorage.key !== 'function') return;
    const old = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.indexOf(SOL_DEAD_PREFIX) === 0 && Date.now() - Number(localStorage.getItem(k)) > SOL_DEAD_KEEP_MS) old.push(k);
    }
    old.forEach(k => localStorage.removeItem(k));
  } catch {}
}

// True while a refresh of `refresh` that a tab stopped waiting for may still
// answer (see _lateRefresh in core/api.js).
function _solRefreshPending(refresh) {
  try {
    const v = (localStorage.getItem(SOL_PENDING_KEY) || '').split('|');
    return !!refresh && v[0] === _solFingerprint(refresh) && Number(v[1]) > Date.now();
  } catch {
    return false;
  }
}
function _solNotePending(refresh, until) {
  try { localStorage.setItem(SOL_PENDING_KEY, _solFingerprint(refresh) + '|' + until); } catch {}
}
// Claim the one probe allowed while `refresh` is pending: true for the first
// tab that asks (it may send the token again), false afterwards.
function _solClaimProbe(refresh) {
  try {
    const v = (localStorage.getItem(SOL_PENDING_KEY) || '').split('|');
    if (v[0] !== _solFingerprint(refresh) || v[2] === 'probed') return false;
    localStorage.setItem(SOL_PENDING_KEY, v[0] + '|' + v[1] + '|probed');
    return true;
  } catch {
    return false;
  }
}
function _solClearPending(refresh) {
  try { if ((localStorage.getItem(SOL_PENDING_KEY) || '').split('|')[0] === _solFingerprint(refresh)) localStorage.removeItem(SOL_PENDING_KEY); } catch {}
}

// A new sign-out record. `signIn`: a sign-in follows at once (the landing
// page replacing a session), so open tabs give its new pair a moment to arrive
// and reload into it. Returns false if storage refused it.
function _solWriteSignoutRecord(signIn) {
  try {
    localStorage.setItem(SOL_SIGNOUT_KEY, Date.now() + '-' + Math.random().toString(36).slice(2) + (signIn ? '-in' : ''));
    return true;
  } catch {
    return false;
  }
}
// True when a sign-out record says a sign-in follows.
function _solRecordIsSignIn(record) { return typeof record === 'string' && /-in$/.test(record); }

// Tell the other open pages that the session they run on has ended (`signIn`:
// a new session is already stored).
function _solAnnounceSignout(signIn) {
  try { if (_solChannel) _solChannel.postMessage(signIn ? { type: 'signed-out', next: true } : { type: 'signed-out' }); } catch {}
}
