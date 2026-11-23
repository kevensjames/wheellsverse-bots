// SOL member app — core/account.js
// Classic script (shared global scope). window.SolAccount: pure helpers for the member
// account pages, shared by the member app (Settings, the verify-email banner, the first-run
// guide) and the pages without a session (index.html, reset-password.html, verify.html).
// No DOM work and no side effects at load. Nothing here logs, and nothing stores a token.
window.SolAccount = (function () {
  const TOKEN_MAX = 2048;

  // An email link's ?token= (the backend builds APP_BASE_URL/verify?token= and
  // /reset-password?token=, services/email.py:129, :142). Read once: the parameter is
  // removed from the address bar at once with history.replaceState (other parameters and
  // the hash are kept), so it is not left in the history, a bookmark or a shared screen.
  // The caller keeps the value in memory only. Returns null when there is no usable token.
  function readTokenOnce(win) {
    let params;
    try { params = new URLSearchParams(win.location.search || ''); } catch (e) { return null; }
    if (!params.has('token')) return null;
    const raw = params.get('token');
    params.delete('token');
    const rest = params.toString();
    try {
      win.history.replaceState(win.history.state, '', (win.location.pathname || '') + (rest ? '?' + rest : '') + (win.location.hash || ''));
    } catch (e) { /* the token is still used; the address bar keeps it */ }
    const token = (raw || '').trim();
    return token && token.length <= TOKEN_MAX ? token : null;
  }

  // A route that exists only in a draft backend PR answers 404 (unknown path) or 405 (the
  // path exists with another method) on the deployed backend: "not available yet".
  function notAvailable(e) { return !!(e && (e.status === 404 || e.status === 405)); }
  function rateLimited(e) { return !!(e && e.status === 429); }

  // The backend's password rule: 8 to 128 characters (pydantic Field(min_length=8,
  // max_length=128), schemas/auth.py:81), counted as code points like Python does.
  function passwordProblem(pw, confirm) {
    const n = [...String(pw || '')].length;
    if (n < 8) return 'Use at least 8 characters.';
    if (n > 128) return 'Use 128 characters or fewer.';
    if (String(pw) !== String(confirm == null ? '' : confirm)) return 'The two passwords do not match.';
    return '';
  }

  // Forgot password: one neutral answer whatever the server says, so the page never shows
  // whether an account exists. A rate limit says to wait; no answer at all is a connection
  // problem (saying "we sent a link" then would be untrue).
  function forgotOutcome(status) {
    if (status === 429) return 'limited';
    if (!status) return 'offline';
    return 'sent';
  }
  // POST /auth/reset-password: 200, or 400 "Invalid or expired token" / "User not found".
  function resetOutcome(status) {
    if (status >= 200 && status < 300) return 'done';
    if (status === 400) return 'invalid';
    if (status === 429) return 'limited';
    if (!status) return 'offline';
    return 'retry';
  }
  // POST /auth/verify-email?token=: 200, 400 invalid or expired, 422 no token.
  function verifyOutcome(status) {
    if (status >= 200 && status < 300) return 'done';
    if (status === 400 || status === 422) return 'invalid';
    if (status === 404 || status === 405) return 'unavailable';
    if (status === 429) return 'limited';
    if (!status) return 'offline';
    return 'retry';
  }

  // GET /legal/documents (draft PR #34): [{kind, version, consent_kind, ...}]. The current
  // terms and privacy versions, or null when either is missing.
  function consentVersions(docs) {
    if (!Array.isArray(docs)) return null;
    const v = {};
    for (const d of docs) {
      if (d && (d.consent_kind === 'terms' || d.consent_kind === 'privacy') && typeof d.version === 'string' && d.version) v[d.consent_kind] = d.version;
    }
    return v.terms && v.privacy ? { terms: v.terms, privacy: v.privacy } : null;
  }
  // The three documents sign-up agrees to, by consent kind, with their exact title, text and
  // version: { terms, privacy, esign } (PR #34 legal/__init__.py:41-62, 94-102; the esign consent
  // accepts the esign_disclosure document). Null unless all three are complete: sign-up records
  // esign at the current version, so the page must have shown that text too.
  const CONSENT_KINDS = ['terms', 'privacy', 'esign'];
  function consentDocs(docs) {
    if (!Array.isArray(docs)) return null;
    const out = {};
    for (const kind of CONSENT_KINDS) {
      const d = docs.find(x => x && x.consent_kind === kind);
      if (!d || typeof d.version !== 'string' || !d.version || typeof d.title !== 'string' || !d.title.trim()
        || typeof d.text !== 'string' || !d.text.trim()) return null;
      out[kind] = { version: d.version, title: d.title.trim(), text: d.text };
    }
    return out;
  }
  // True when two consentDocs() results carry the same three versions.
  function sameConsentVersions(a, b) {
    if (!a || !b) return false;
    return CONSENT_KINDS.every(k => a[k] && b[k] && a[k].version === b[k].version);
  }
  // POST /auth/signup body. The deployed backend forbids extra keys, so the consent fields
  // are added only with versions from PR #34's /legal/documents.
  function signupPayload(f, versions) {
    const body = { email: f.email, password: f.password, full_name: f.fullName };
    if (versions && versions.terms && versions.privacy) {
      body.accepted_terms_version = versions.terms;
      body.accepted_privacy_version = versions.privacy;
      body.esign_consent = true;
    }
    return body;
  }

  // The first-run guide's "seen" mark, per member id. Storage can be blocked (a private
  // window, site data off): then nothing throws and the guide may show again next time.
  const guideKey = id => 'sol_guide_seen:' + id;
  function storageOf(win) { try { return win.localStorage || null; } catch (e) { return null; } }
  function guideSeen(storage, userId) {
    if (!userId) return true;
    if (!storage) return false;
    try { return storage.getItem(guideKey(userId)) !== null; } catch (e) { return false; }
  }
  function markGuideSeen(storage, userId) {
    if (!userId || !storage) return false;
    try { storage.setItem(guideKey(userId), '1'); return true; } catch (e) { return false; }
  }

  // PATCH /account/settings merges preferences at the top level only: a nested object
  // replaces the whole stored one (api/account.py:109-113). So send the full
  // notifications object, with the other channels as stored.
  function notificationsOf(prefs) {
    const n = prefs && prefs.notifications;
    return n && typeof n === 'object' && !Array.isArray(n) ? n : {};
  }
  function emailNotificationsOn(prefs) { return notificationsOf(prefs).email !== false; }
  function notificationsPatch(prefs, emailOn) {
    return { preferences: { notifications: Object.assign({}, notificationsOf(prefs), { email: !!emailOn }) } };
  }

  // POST /account/close body (draft PR #33 api/account.py:63-70): extra keys are forbidden,
  // totp_code is 6 characters or null, confirm must be exactly "DELETE".
  function closePayload(password, code, totpOn) {
    return { password: String(password || ''), totp_code: totpOn ? String(code || '').trim() : null, confirm: 'DELETE' };
  }
  // A 409 refusal's reasons, as plain sentences: the backend's own message, or one from the
  // code. Never an id (the backend lists the member's group, payment and payout ids).
  const REASON_TEXT = {
    admin_account: 'An admin account cannot be closed.',
    circle_not_finished: 'You still belong to a circle that has not finished.',
    payment_in_progress: 'A contribution is still pending or processing.',
    payout_in_progress: 'A payout to you is still pending or processing.',
    active_subscription: 'You have an active plan. Cancel your plan first.',
    checkout_in_progress: 'A plan checkout you started recently could still be paid.',
  };
  function closeRefusals(detail) {
    const reasons = detail && typeof detail === 'object' && Array.isArray(detail.reasons) ? detail.reasons : [];
    return reasons.map(r => {
      if (!r || typeof r !== 'object') return '';
      if (typeof r.message === 'string' && r.message.trim()) return r.message.trim();
      return REASON_TEXT[r.code] || 'Something on your account is still open.';
    }).filter(Boolean);
  }

  // What POST /account/close (PR #33, 200) says it removed and kept, and for how long
  // (services/account_lifecycle.py:491-555): the descriptions only (never an id), the
  // retention years (a setting, 5 by default) and the backend's note.
  function closeSummary(d) {
    const texts = list => (Array.isArray(list) ? list : [])
      .map(x => (x && typeof x.description === 'string' ? x.description.trim() : '')).filter(Boolean);
    const r = d && typeof d === 'object' && d.retention && typeof d.retention === 'object' ? d.retention : {};
    return {
      removed: texts(d && d.removed),
      kept: texts(d && d.kept),
      years: Number.isInteger(r.years) && r.years >= 0 ? r.years : null,
      note: typeof r.note === 'string' ? r.note.trim() : '',
    };
  }

  // A two-factor secret in groups of 4, easier to type into an authenticator app.
  function groupSecret(s) { return String(s || '').replace(/\s+/g, '').replace(/(.{4})(?=.)/g, '$1 '); }
  function exportFileName(d) {
    const x = d instanceof Date && !isNaN(d) ? d : new Date();
    const p = n => String(n).padStart(2, '0');
    return `mysol-data-${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}.json`;
  }

  // A call to a public auth route (no session). Never throws: an HTTP error is returned
  // with its status, no answer at all is status 0.
  async function callPublic(base, path, opts) {
    const o = opts || {};
    const init = { method: o.method || 'GET', headers: {} };
    if (o.body !== undefined) { init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(o.body); }
    let r;
    try { r = await fetch(base + path, init); } catch (e) { return { ok: false, status: 0, data: null }; }
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    return { ok: !!r.ok, status: r.status, data };
  }

  return {
    readTokenOnce, notAvailable, rateLimited, passwordProblem,
    forgotOutcome, resetOutcome, verifyOutcome,
    consentVersions, consentDocs, sameConsentVersions, signupPayload,
    storageOf, guideSeen, markGuideSeen,
    emailNotificationsOn, notificationsPatch, closePayload, closeRefusals, closeSummary,
    groupSecret, exportFileName, callPublic,
  };
})();
