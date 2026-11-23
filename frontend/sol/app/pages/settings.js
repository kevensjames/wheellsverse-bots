// SOL member app — pages/settings.js
// Classic script (shared global scope); loaded in order by app.html.
//
// Settings: profile, password, two-factor sign-in, notifications, the AI assistant opt-in,
// your data (export, close account) and the first-run guide. Also the dashboard's
// verify-email banner. Routes (BASE = deployed c218dfb; PR = draft backend PR, not
// deployed). Each section degrades on 404/405 ("not available yet"), with no error alert:
//   GET   /auth/me                     BASE (email_verified_at, totp_enabled, …)
//   PATCH /account/profile {full_name} BASE api/account.py:72-84
//   POST  /auth/forgot-password        BASE api/auth.py:124-132 (no change-password route exists)
//   POST  /auth/2fa/setup|activate|disable  BASE api/auth.py:167-232
//   GET/PATCH /account/settings        BASE api/account.py:87-125 (preferences, shallow merge)
//     ai_assistant_consent             PR #35 api/account.py:60, 76-83
//   GET   /account/export              PR #33 api/account.py:164-175
//   POST  /account/close               PR #33 api/account.py:180-205
//   POST  /auth/resend-verification    PR #33 api/auth.py:127-143
// The two-factor secret and backup codes live only in this page's memory and DOM while
// they are needed; they are never stored, logged or put in the address bar.

let setState = { settings: null, settingsOk: false, settingsNA: false, aiHidden: false, enroll: null, codes: null };

function setAnnounce(msg) { const el = document.getElementById('settingsLive'); if (el) { el.textContent = ''; el.textContent = msg; } }
function setText(id, msg, show) { const el = document.getElementById(id); if (!el) return; el.textContent = msg || ''; if (show !== undefined) el.style.display = msg ? 'block' : 'none'; }
function setErr(id, msg) { setText(id, msg, true); }
function setFocus(id) { const el = document.getElementById(id); if (el) { try { el.focus(); } catch (e) {} } }
const setNA = text => `<p class="set-na">${esc(text)}</p>`;

async function loadSettings() {
  const body = document.getElementById('settingsBody');
  if (!body) return;
  setState.enroll = null; setState.codes = null;   // a new visit never shows an old secret or codes
  body.innerHTML = '<div class="spinner"></div>';
  const [meR, stR] = await Promise.allSettled([api('/auth/me'), api('/account/settings')]);
  if ((meR.status === 'rejected' && _aborted(meR.reason)) || (stR.status === 'rejected' && _aborted(stR.reason))) return;
  if (meR.status === 'fulfilled' && meR.value && typeof meR.value === 'object') me = meR.value;
  setState.settingsOk = stR.status === 'fulfilled' && !!stR.value && typeof stR.value === 'object';
  setState.settings = setState.settingsOk ? stR.value : null;
  setState.settingsNA = stR.status === 'rejected' && SolAccount.notAvailable(stR.reason);
  renderSettings();
}

function renderSettings() {
  const body = document.getElementById('settingsBody');
  if (!body) return;
  const m = me || {};
  const verified = !!m.email_verified_at;
  body.innerHTML = `
    <section class="set-card" id="setProfile" aria-labelledby="setProfileH">
      <h2 id="setProfileH">Profile</h2>
      <div class="field"><label for="setName">Display name</label>
        <input id="setName" class="input" type="text" maxlength="255" autocomplete="name" value="${esc(m.full_name || '')}"></div>
      <p class="err" id="setNameErr" role="alert" style="display:none"></p>
      <p class="set-na" id="setNameNote" style="display:none"></p>
      <button type="button" class="btn btn-primary btn--sm" id="setNameSave" onclick="saveDisplayName()">Save name</button>
      <div class="set-row"><span class="set-label">Email</span>
        <span class="set-value" id="setEmail">${esc(m.email || '')}</span>
        <span id="setEmailStatus">${verified ? '<span class="status status--verified">Verified</span>' : '<span class="status status--pending">Not verified</span>'}</span></div>
      ${verified ? '' : `<div class="set-inline" id="setResendWrap"><button type="button" class="btn btn-ghost btn--sm" id="setResend" onclick="resendVerification('set')">Resend email</button>
        <p class="hint-muted" id="setResendMsg" role="status" aria-live="polite"></p></div>`}
      <p class="hint-muted">To change your email address, contact support.</p>
    </section>

    <section class="set-card" id="setPassword" aria-labelledby="setPasswordH">
      <h2 id="setPasswordH">Password</h2>
      <p class="set-na">Changing your password here is not available yet. We can email you a link to set a new one.</p>
      <button type="button" class="btn btn-ghost btn--sm" id="setPwReset" onclick="emailResetLink()">Email me a reset link</button>
      <p class="hint-muted" id="setPwMsg" role="status" aria-live="polite"></p>
    </section>

    <section class="set-card" id="setTwoFactor" aria-labelledby="setTwoFactorH">
      <h2 id="setTwoFactorH" tabindex="-1">Two-factor sign-in</h2>
      <div id="set2faBody"></div>
      <p class="err" id="set2faErr" role="alert" style="display:none"></p>
      <p class="hint-muted" id="set2faMsg" role="status" aria-live="polite"></p>
    </section>

    <section class="set-card" id="setNotifications" aria-labelledby="setNotificationsH">
      <h2 id="setNotificationsH">Notifications</h2>
      <div id="setNotifBody"></div>
      <p class="err" id="setNotifErr" role="alert" style="display:none"></p>
    </section>

    <section class="set-card" id="setAi" aria-labelledby="setAiH" hidden>
      <h2 id="setAiH">AI assistant</h2>
      <div id="setAiBody"></div>
      <p class="err" id="setAiErr" role="alert" style="display:none"></p>
    </section>

    <section class="set-card" id="setData" aria-labelledby="setDataH">
      <h2 id="setDataH">Your data</h2>
      <p class="hint-muted">Download a copy of your account data as a JSON file.</p>
      <button type="button" class="btn btn-ghost btn--sm" id="setExport" onclick="downloadMyData()">Download my data</button>
      <p class="set-na" id="setExportMsg" role="status" aria-live="polite"></p>
      <p class="err" id="setExportErr" role="alert" style="display:none"></p>
      <div class="set-danger">
        <h3>Close account</h3>
        <p class="hint-muted">Closing your account is permanent. Some money records are kept.</p>
        <button type="button" class="btn btn-danger btn--sm" id="setCloseOpen" onclick="openCloseDialog()">Close account</button>
      </div>
    </section>

    <section class="set-card" id="setHelp" aria-labelledby="setHelpH">
      <h2 id="setHelpH">How MySol works</h2>
      <p class="hint-muted">A short guide to circles, payouts and the checks we run.</p>
      <button type="button" class="btn btn-ghost btn--sm" id="setGuide" onclick="openGuide()">Show the guide</button>
    </section>`;
  renderTwoFactor();
  renderNotifications();
  renderAiConsent();
}

// ── Profile ───────────────────────────────────────────────────────────────────
async function saveDisplayName() {
  const input = document.getElementById('setName');
  if (!input) return;
  const name = input.value.trim();
  setErr('setNameErr', ''); setText('setNameNote', '', true);
  // The backend writes full_name to a NOT NULL column: never send an empty or null name.
  if (!name) { setErr('setNameErr', 'Enter a name.'); input.focus(); return; }
  if ([...name].length > 255) { setErr('setNameErr', 'Use 255 characters or fewer.'); input.focus(); return; }
  if (!SolGuard.acquire('settings:name')) return;
  const btn = document.getElementById('setNameSave'); if (btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
  try {
    const d = await api('/account/profile', { method: 'PATCH', body: JSON.stringify({ full_name: name }) });
    const saved = d && typeof d.full_name === 'string' ? d.full_name : name;
    if (me) me.full_name = saved;
    input.value = saved;
    setAnnounce('Name saved.');
  } catch (e) {
    if (SolAccount.notAvailable(e)) setText('setNameNote', 'Changing your name is not available yet.', true);
    else setErr('setNameErr', (e && e.message) || "We couldn't save your name. Please try again.");
  } finally {
    SolGuard.release('settings:name');
    if (btn) { btn.disabled = false; btn.textContent = 'Save name'; }
  }
}

// ── Password: there is no change-password route; the reset email is the way ─────
async function emailResetLink() {
  if (!me || !me.email || !SolGuard.acquire('settings:pwreset')) return;
  const btn = document.getElementById('setPwReset'); if (btn) btn.disabled = true;
  setText('setPwMsg', '');
  try {
    await api('/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email: me.email }) });
    setText('setPwMsg', 'Check your email for a link to set a new password.');
  } catch (e) {
    setText('setPwMsg', SolAccount.rateLimited(e) ? 'Too many requests. Please try again later.' : "We couldn't send the link. Please try again.");
  } finally {
    SolGuard.release('settings:pwreset');
    if (btn) btn.disabled = false;
  }
}

// ── Two-factor ────────────────────────────────────────────────────────────────
function renderTwoFactor() {
  const el = document.getElementById('set2faBody');
  if (!el) return;
  const on = !!(me && me.totp_enabled);
  const state = `<p class="set-row"><span class="set-label">Status</span><strong id="set2faState">${on ? 'On' : 'Off'}</strong></p>`;
  if (setState.codes) {
    el.innerHTML = `${state}
      <div class="set-warn" role="note">
        <h3 id="set2faCodesH" tabindex="-1">Save your backup codes</h3>
        <p>Store these codes somewhere safe. Each code works once, if you lose your phone. You will not see them again.</p>
        <ul class="set-codes" id="set2faCodes">${setState.codes.map(c => `<li><code>${esc(c)}</code></li>`).join('')}</ul>
        <div class="set-inline">
          <button type="button" class="btn btn-ghost btn--sm" id="set2faCopyCodes" onclick="copyBackupCodes()">Copy codes</button>
          <button type="button" class="btn btn-primary btn--sm" id="set2faSaved" onclick="backupCodesSaved()">I saved my codes</button>
        </div>
      </div>`;
    return;
  }
  if (setState.enroll) {
    const qr = setState.enroll.qr ? `<img id="set2faQr" class="set-qr" src="${esc(setState.enroll.qr)}" alt="QR code to add MySol to your authenticator app" width="160" height="160">` : '';
    el.innerHTML = `${state}
      <h3 id="set2faSetupH" tabindex="-1">Set up your authenticator app</h3>
      <ol class="set-steps">
        <li>Open your authenticator app and add an account. ${qr ? 'Scan the QR code, or type this key:' : 'Type this key:'}
          ${qr}
          <p><code class="set-secret" id="set2faSecret">${esc(SolAccount.groupSecret(setState.enroll.secret))}</code>
          <button type="button" class="btn btn-ghost btn--sm" id="set2faCopySecret" onclick="copyTwoFactorKey()">Copy key</button></p></li>
        <li><div class="field"><label for="set2faCode">Enter the 6-digit code the app shows</label>
          <input id="set2faCode" class="input set-code" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="6"></div></li>
      </ol>
      <div class="set-inline">
        <button type="button" class="btn btn-primary btn--sm" id="set2faConfirm" onclick="confirmTwoFactor()">Turn on</button>
        <button type="button" class="btn btn-ghost btn--sm" id="set2faCancel" onclick="cancelTwoFactor()">Cancel</button>
      </div>`;
    return;
  }
  if (on) {
    const left = me && Number.isInteger(me.totp_backup_codes_remaining) ? me.totp_backup_codes_remaining : null;
    el.innerHTML = `${state}
      ${left !== null ? `<p class="hint-muted">Backup codes left: <span class="tnum">${esc(left)}</span></p>` : ''}
      <p class="hint-muted">To turn off two-factor sign-in, enter your password and a code from your app. This signs you out on all devices.</p>
      <div class="field"><label for="set2faPw">Password</label><input id="set2faPw" class="input" type="password" autocomplete="current-password"></div>
      <div class="field"><label for="set2faOffCode">6-digit code from your app</label><input id="set2faOffCode" class="input set-code" type="text" inputmode="numeric" autocomplete="one-time-code" maxlength="6"></div>
      <button type="button" class="btn btn-ghost btn--sm" id="set2faOff" onclick="disableTwoFactor()">Turn off two-factor</button>`;
    return;
  }
  el.innerHTML = `${state}
    <p class="hint-muted">Two-factor sign-in asks for a code from an authenticator app each time you sign in.</p>
    <button type="button" class="btn btn-primary btn--sm" id="set2faStart" onclick="startTwoFactor()">Turn on two-factor</button>`;
}
function twoFactorError(e, fallback) {
  if (SolAccount.notAvailable(e)) return 'Two-factor sign-in is not available yet.';
  if (SolAccount.rateLimited(e)) return 'Too many tries. Please wait a few minutes and try again.';
  const m = (e && e.message) || '';
  if (/invalid code/i.test(m)) return 'That code did not work. Check the time on your phone and try again.';
  if (/invalid password/i.test(m)) return 'That password is not right.';
  return m || fallback;
}
async function startTwoFactor() {
  if (!SolGuard.acquire('settings:2fa')) return;
  setErr('set2faErr', ''); setText('set2faMsg', '');
  try {
    const d = await api('/auth/2fa/setup', { method: 'POST' });
    const secret = d && typeof d.secret === 'string' ? d.secret : '';
    if (!secret) throw new Error("We couldn't start two-factor setup. Please try again.");
    const qr = typeof d.qr_data_url === 'string' && /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(d.qr_data_url) ? d.qr_data_url : null;
    setState.enroll = { secret, qr };
    renderTwoFactor();
    setFocus('set2faSetupH');
  } catch (e) {
    if (e && e.status === 409) { if (me) me.totp_enabled = true; renderTwoFactor(); setText('set2faMsg', 'Two-factor sign-in is already on.'); }
    else if (SolAccount.notAvailable(e)) setText('set2faMsg', 'Two-factor sign-in is not available yet.');
    else setErr('set2faErr', twoFactorError(e, "We couldn't start two-factor setup. Please try again."));
  } finally { SolGuard.release('settings:2fa'); }
}
async function confirmTwoFactor() {
  const input = document.getElementById('set2faCode');
  const code = input ? input.value.trim() : '';
  setErr('set2faErr', '');
  if (!/^\d{6}$/.test(code)) { setErr('set2faErr', 'Enter the 6-digit code from your app.'); if (input) input.focus(); return; }
  if (!SolGuard.acquire('settings:2fa')) return;
  const btn = document.getElementById('set2faConfirm'); if (btn) btn.disabled = true;
  try {
    const d = await api('/auth/2fa/activate', { method: 'POST', body: JSON.stringify({ code }) });
    const codes = d && Array.isArray(d.backup_codes) ? d.backup_codes.filter(c => typeof c === 'string') : [];
    setState.enroll = null;   // the secret leaves the page
    setState.codes = codes.length ? codes : null;
    if (me) { me.totp_enabled = true; me.totp_backup_codes_remaining = codes.length; }
    renderTwoFactor();
    setAnnounce('Two-factor sign-in is on.');
    setFocus(setState.codes ? 'set2faCodesH' : 'setTwoFactorH');
  } catch (e) {
    if (e && e.status === 400) { setState.enroll = null; renderTwoFactor(); setErr('set2faErr', 'Your setup expired. Please start again.'); }
    else if (e && e.status === 409) { setState.enroll = null; if (me) me.totp_enabled = true; renderTwoFactor(); setText('set2faMsg', 'Two-factor sign-in is already on.'); }
    else { setErr('set2faErr', twoFactorError(e, "We couldn't turn on two-factor. Please try again.")); if (input) { input.value = ''; input.focus(); } }
  } finally {
    SolGuard.release('settings:2fa');
    const b = document.getElementById('set2faConfirm'); if (b) b.disabled = false;
  }
}
function cancelTwoFactor() {
  setState.enroll = null;
  setErr('set2faErr', '');
  renderTwoFactor();
  setFocus('set2faStart');
}
async function copyText(text, okMsg) {
  try { await navigator.clipboard.writeText(text); setAnnounce(okMsg); return true; }
  catch (e) { setAnnounce('Copying is not available here. Select the text and copy it.'); return false; }
}
function copyTwoFactorKey() { if (setState.enroll) copyText(setState.enroll.secret, 'Key copied.'); }
function copyBackupCodes() { if (setState.codes) copyText(setState.codes.join('\n'), 'Backup codes copied.'); }
function backupCodesSaved() {
  setState.codes = null;   // shown once: the codes leave the page
  renderTwoFactor();
  setFocus('setTwoFactorH');
}
async function disableTwoFactor() {
  const pw = document.getElementById('set2faPw'), codeEl = document.getElementById('set2faOffCode');
  const password = pw ? pw.value : '', code = codeEl ? codeEl.value.trim() : '';
  setErr('set2faErr', ''); setText('set2faMsg', '');
  if (!password) { setErr('set2faErr', 'Enter your password.'); if (pw) pw.focus(); return; }
  if (!/^\d{6}$/.test(code)) { setErr('set2faErr', 'Enter the 6-digit code from your app.'); if (codeEl) codeEl.focus(); return; }
  if (!SolGuard.acquire('settings:2fa')) return;
  const btn = document.getElementById('set2faOff'); if (btn) btn.disabled = true;
  try {
    await api('/auth/2fa/disable', { method: 'POST', body: JSON.stringify({ password, code }) });
    if (me) me.totp_enabled = false;
    renderTwoFactor();
    // The backend ends every session, this one included (services/auth.py:412).
    setText('set2faMsg', 'Two-factor sign-in is off. For your safety, you were signed out on all devices. You may be asked to sign in again soon.');
    setFocus('setTwoFactorH');
  } catch (e) {
    setErr('set2faErr', twoFactorError(e, "We couldn't turn off two-factor. Please try again."));
  } finally {
    SolGuard.release('settings:2fa');
    if (pw) pw.value = '';
    const b = document.getElementById('set2faOff'); if (b) b.disabled = false;
  }
}

// ── Notifications (preferences.notifications; nothing in the backend reads it yet) ──
function renderNotifications() {
  const el = document.getElementById('setNotifBody');
  if (!el) return;
  if (setState.settingsNA) { el.innerHTML = setNA('Notification settings are not available yet.'); return; }
  if (!setState.settingsOk) { el.innerHTML = `<p class="hint-muted">We couldn't load your notification settings.</p><button type="button" class="btn btn-ghost btn--sm" onclick="loadSettings()">Retry</button>`; return; }
  const on = SolAccount.emailNotificationsOn(setState.settings.preferences);
  el.innerHTML = `<div class="set-check"><input type="checkbox" id="setNotifEmail"${on ? ' checked' : ''} onchange="saveNotifications(this)">
      <label for="setNotifEmail">Email updates about my circles and payments</label></div>
    <p class="hint-muted">We save this choice to your account. MySol does not use it to stop emails yet.</p>`;
}
async function saveNotifications(box) {
  if (!box || !setState.settingsOk) return;
  if (!SolGuard.acquire('settings:notif')) { box.checked = !box.checked; return; }
  setErr('setNotifErr', '');
  box.disabled = true;
  try {
    const d = await api('/account/settings', { method: 'PATCH', body: JSON.stringify(SolAccount.notificationsPatch(setState.settings.preferences, box.checked)) });
    if (d && typeof d === 'object' && d.preferences) setState.settings = Object.assign({}, setState.settings, d);
    setAnnounce('Notification setting saved.');
  } catch (e) {
    box.checked = !box.checked;
    if (SolAccount.notAvailable(e)) { setState.settingsNA = true; renderNotifications(); }
    else setErr('setNotifErr', (e && e.message) || "We couldn't save this setting. Please try again.");
  } finally {
    SolGuard.release('settings:notif');
    box.disabled = false;
  }
}

// ── AI assistant opt-in (PR #35): shown only when the settings carry the key ────
function renderAiConsent() {
  const sec = document.getElementById('setAi'), el = document.getElementById('setAiBody');
  if (!sec || !el) return;
  const s = setState.settings;
  const has = !setState.aiHidden && setState.settingsOk && s && typeof s.ai_assistant_consent === 'boolean';
  sec.hidden = !has;
  if (!has) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="set-check"><input type="checkbox" id="setAiConsent"${s.ai_assistant_consent ? ' checked' : ''} onchange="saveAiConsent(this)">
      <label for="setAiConsent">Let the assistant use AI to answer my questions</label></div>
    <p class="hint-muted">Off by default. With it off, the assistant still answers common questions from your account data.</p>`;
}
function _unknownKey(e, key) {
  if (!e || e.status !== 422) return false;
  if (Array.isArray(e.detail)) return e.detail.some(d => d && d.type === 'extra_forbidden' && Array.isArray(d.loc) && d.loc.includes(key));
  return new RegExp(key + '.*(extra|not permitted)', 'i').test(e.message || '');
}
async function saveAiConsent(box) {
  if (!box) return;
  if (!SolGuard.acquire('settings:ai')) { box.checked = !box.checked; return; }
  setErr('setAiErr', '');
  box.disabled = true;
  try {
    const d = await api('/account/settings', { method: 'PATCH', body: JSON.stringify({ ai_assistant_consent: box.checked }) });
    if (d && typeof d === 'object') setState.settings = Object.assign({}, setState.settings, d);
    setAnnounce(box.checked ? 'AI answers are on.' : 'AI answers are off.');
  } catch (e) {
    box.checked = !box.checked;
    if (_unknownKey(e, 'ai_assistant_consent') || SolAccount.notAvailable(e)) {
      setState.aiHidden = true;   // the backend does not know this setting: hide it
      renderAiConsent();
      setAnnounce('The AI assistant setting is not available yet.');
    } else setErr('setAiErr', (e && e.message) || "We couldn't save this setting. Please try again.");
  } finally {
    SolGuard.release('settings:ai');
    box.disabled = false;
  }
}

// ── Your data: export (PR #33) ────────────────────────────────────────────────
async function downloadMyData() {
  if (!SolGuard.acquire('settings:export')) return;
  const btn = document.getElementById('setExport'); if (btn) btn.disabled = true;
  setText('setExportMsg', ''); setErr('setExportErr', '');
  try {
    const data = await api('/account/export');
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = SolAccount.exportFileName(new Date()); a.hidden = true;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
    setText('setExportMsg', 'Your data file is downloading.');
  } catch (e) {
    if (_aborted(e)) return;
    if (SolAccount.notAvailable(e)) setText('setExportMsg', 'Downloading your data is not available yet.');
    else if (SolAccount.rateLimited(e)) setText('setExportMsg', 'You downloaded your data several times recently. Please try again later.');
    else setErr('setExportErr', (e && e.message) || "We couldn't prepare your data. Please try again.");
  } finally {
    SolGuard.release('settings:export');
    if (btn) btn.disabled = false;
  }
}

// ── Close account (PR #33) ────────────────────────────────────────────────────
function closeFormReset() {
  ['closePw', 'closeCode', 'closePhrase'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  setText('closeNote', ''); setErr('closeErr', '');
  const ul = document.getElementById('closeReasons'); if (ul) ul.innerHTML = '';
  closeFormChanged();
}
function closeFormChanged() {
  const pw = (document.getElementById('closePw') || {}).value || '';
  const phrase = (document.getElementById('closePhrase') || {}).value || '';
  const code = ((document.getElementById('closeCode') || {}).value || '').trim();
  const needCode = !!(me && me.totp_enabled);
  const btn = document.getElementById('closeConfirm');
  if (btn && !SolGuard.isLocked('settings:close')) btn.disabled = !(pw && phrase === 'DELETE' && (!needCode || /^\d{6}$/.test(code)));
}
function openCloseDialog() {
  const field = document.getElementById('closeCodeField');
  if (field) field.hidden = !(me && me.totp_enabled);
  closeFormReset();
  SolDialog.open('closeAccountDialog', {
    opener: document.getElementById('setCloseOpen'),
    initialFocus: '#closePw',
    canClose: () => !SolGuard.isLocked('settings:close'),
    onClose: () => closeFormReset(),
  });
}
function closeCloseDialog() {
  if (SolGuard.isLocked('settings:close')) return;
  SolDialog.close('closeAccountDialog');
}
async function confirmCloseAccount(e) {
  if (e) e.preventDefault();
  closeFormChanged();
  const btn = document.getElementById('closeConfirm');
  if (!btn || btn.disabled || !SolGuard.acquire('settings:close')) return;
  const totpOn = !!(me && me.totp_enabled);
  const body = SolAccount.closePayload((document.getElementById('closePw') || {}).value, (document.getElementById('closeCode') || {}).value, totpOn);
  setText('closeNote', ''); setErr('closeErr', '');
  const ul = document.getElementById('closeReasons'); if (ul) ul.innerHTML = '';
  btn.disabled = true; btn.textContent = 'Closing…';
  let closed = false;
  try {
    const d = await api('/account/close', { method: 'POST', body: JSON.stringify(body) });
    closed = true;
    const note = d && d.retention && typeof d.retention.note === 'string' ? d.retention.note + ' ' : '';
    setText('closeNote', 'Your account is closed. ' + note + 'Signing you out…');
    const pw = document.getElementById('closePw'); if (pw) pw.value = '';
    logout();
  } catch (err) {
    const d = err && err.detail;
    if (SolAccount.notAvailable(err)) setText('closeNote', 'Closing your account here is not available yet. Contact support if you need help.');
    else if (err && err.status === 403 && d && d.error === 'account_close_disabled') setText('closeNote', typeof d.message === 'string' ? d.message : 'Closing an account is not available yet.');
    else if (err && err.status === 409) {
      setErr('closeErr', d && typeof d.message === 'string' ? d.message : 'Your account cannot be closed yet.');
      if (ul) ul.innerHTML = SolAccount.closeRefusals(d).map(r => `<li>${esc(r)}</li>`).join('');
    } else if (SolAccount.rateLimited(err)) setErr('closeErr', 'Too many tries. Please try again later.');
    else {
      const m = (err && err.message) || '';
      if (/2FA code required/i.test(m)) { const f = document.getElementById('closeCodeField'); if (f) f.hidden = false; setErr('closeErr', 'Enter the 6-digit code from your authenticator app.'); }
      else if (/invalid password/i.test(m)) setErr('closeErr', 'That password is not right.');
      else if (/invalid code/i.test(m)) setErr('closeErr', 'That code did not work.');
      else setErr('closeErr', m || "We couldn't close your account. Please try again.");
    }
  } finally {
    SolGuard.release('settings:close');
    if (!closed) { btn.textContent = 'Close my account'; closeFormChanged(); }
  }
}

// ── Dashboard: verify-email banner ────────────────────────────────────────────
function renderVerifyBanner() {
  const el = document.getElementById('dashVerify');
  if (!el) return;
  if (!me || me.email_verified_at || !me.email) { el.innerHTML = ''; return; }
  el.innerHTML = `<section class="verify-banner" aria-labelledby="verifyBannerTitle">
      <div class="verify-banner__text"><h2 id="verifyBannerTitle" class="verify-banner__title">Please verify your email address</h2>
        <p>Open the link we sent to <strong>${esc(me.email)}</strong> to confirm this address is yours.</p>
        <p class="hint-muted" id="verifyMsg" role="status" aria-live="polite"></p></div>
      <button type="button" class="btn btn-ghost btn--sm" id="verifyResend" onclick="resendVerification('verify')">Resend email</button>
    </section>`;
}
// POST /auth/resend-verification (PR #33): 202 sent, 200 already verified, 3/hour.
// scope 'verify' = the dashboard banner, 'set' = the Settings profile card.
async function resendVerification(scope) {
  const btn = document.getElementById(scope === 'set' ? 'setResend' : 'verifyResend');
  const msgId = scope === 'set' ? 'setResendMsg' : 'verifyMsg';
  if (!SolGuard.acquire('verify:resend')) return;
  if (btn) btn.disabled = true;
  setText(msgId, '');
  let hide = false;
  try {
    const d = await api('/auth/resend-verification', { method: 'POST' });
    if (d && d.already_verified === true) { setText(msgId, 'Your email is already verified.'); hide = true; }
    else setText(msgId, 'We sent a new link. Check your inbox.');
  } catch (e) {
    if (SolAccount.notAvailable(e)) { setText(msgId, 'Resending is not available yet. If you need a new link, contact support.'); hide = true; }
    else if (SolAccount.rateLimited(e)) setText(msgId, 'You asked for several emails. Please try again later.');
    else setText(msgId, "We couldn't send the email. Please try again.");
  } finally {
    SolGuard.release('verify:resend');
    if (btn) { if (hide) btn.hidden = true; btn.disabled = false; }
  }
}
