// SOL member app — pages/admin.js
// Phase 3 Increment 4 — Circle Catalog ADMIN console. Role-gated /admin route
// (SOL_FEATURES.catalog AND isAdmin()); admin-defined circle CRUD: list (incl.
// drafts + participation counts), create/edit, close, and a participant view.
// See docs/sol/PHASE3_API_CONTRACT.md.
//
// GATING & SAFETY: the admin surface is UX-gated on isAdmin() (from /auth/me),
// but the BACKEND enforces authz on EVERY /admin call — the client gate is not a
// security boundary. All mutations are SolGuard-guarded + backend-authoritative:
// create/edit/close POST/PATCH then RE-FETCH backend truth (no optimistic insert
// or state fabrication). The participant view renders NO member PII (position +
// status only) — a generic "Member" label, never a name or user_id.

const ADMIN_STATUS = {
  DRAFT:   { label: 'Draft',   cls: 'pending' },
  OPEN:    { label: 'Open',    cls: 'active' },
  FORMING: { label: 'Forming', cls: 'forming' },
  FULL:    { label: 'Full',    cls: 'pending' },
  CLOSED:  { label: 'Closed',  cls: 'cancelled' },
};
function adminStatus(s) { return ADMIN_STATUS[String(s || '').toUpperCase()] || { label: 'Unknown', cls: 'completed' }; }

function normalizeAdminCircle(c) {
  if (!c || typeof c !== 'object' || Array.isArray(c)) return null;
  const id = _catId(c.id) ? c.id : null;
  if (!id) return null;
  return {
    id,
    name: typeof c.name === 'string' && c.name.trim() ? c.name : 'Circle',
    status: adminStatus(c.status),
    statusRaw: String(c.status || '').toUpperCase(),
    contribution: Number.isFinite(c.contribution_cents) && c.contribution_cents >= 0 ? c.contribution_cents : null,
    entryFee: Number.isFinite(c.entry_fee_cents) && c.entry_fee_cents >= 0 ? c.entry_fee_cents : null,
    cadence: c.cadence,
    count: Number.isFinite(c.member_count) ? c.member_count : null,
    cap: Number.isFinite(c.max_members) ? c.max_members : null,
    isPrivate: c.is_private === true,
  };
}

let adminState = { circles: [], ok: false };

async function loadAdmin(userInitiated) {
  if (!featureOn('catalog') || !isAdmin()) return;   // flag + role gated (UX; backend is the real gate)
  const el = document.getElementById('adminList'); if (!el) return;
  el.innerHTML = '<div class="spinner"></div>';
  let ok = false, circles = [];
  try { const r = await api('/admin/circles'); if (Array.isArray(r)) { circles = r.map(normalizeAdminCircle).filter(Boolean); ok = true; } }
  catch (e) { if (_aborted(e)) return; ok = false; }
  adminState.circles = circles; adminState.ok = ok;
  renderAdmin();
  if (userInitiated) adminAnnounce(ok ? 'Circles refreshed.' : 'Admin circles unavailable.');
}

function adminAnnounce(msg) { const el = document.getElementById('adminLiveStatus'); if (el) { el.textContent = ''; el.textContent = msg; } }
// Re-land focus on the list after a mutation closes its dialog (the opener row/
// button is destroyed by the re-render) — mirrors goals.js goalLandFocus.
function adminLandFocus() { const el = document.getElementById('adminList'); if (el && el.focus) { try { el.focus(); } catch (e) {} } }

function adminCircleRow(c) {
  const contribution = c.contribution != null ? fmt$(c.contribution) : '—';
  const fee = c.entryFee == null ? '—' : c.entryFee > 0 ? fmt$(c.entryFee) : 'None';
  const members = (c.count != null && c.cap != null) ? `${esc(c.count)} / ${esc(c.cap)}` : '—';
  const priv = c.isPrivate ? ' 🔒' : '';
  const canClose = c.statusRaw !== 'CLOSED';
  return `<tr>
    <td>${esc(c.name)}${priv}</td>
    <td><span class="status status--${c.status.cls}">${esc(c.status.label)}</span></td>
    <td class="tnum">${contribution}</td>
    <td>${catalogCadence(c)}</td>
    <td class="tnum">${fee}</td>
    <td class="tnum">${members}</td>
    <td class="admin-row__acts">
      <button type="button" class="btn btn-ghost btn--sm" onclick="openAdminParticipants('${esc(c.id)}',event)">Participants</button>
      ${canClose ? `<button type="button" class="btn btn-ghost btn--sm" onclick="openAdminForm('edit','${esc(c.id)}',event)">Edit</button>` : ''}
      ${canClose ? `<button type="button" class="btn btn-ghost btn--sm" onclick="openAdminClose('${esc(c.id)}',event)">Close</button>` : ''}
    </td>
  </tr>`;
}

function renderAdmin() {
  const el = document.getElementById('adminList'); if (!el) return;
  if (!adminState.ok) {
    el.innerHTML = '<div class="empty"><p>Admin circles are unavailable right now.</p><button type="button" class="btn btn-ghost btn--sm" onclick="loadAdmin(true)">Retry</button></div>';
    return;
  }
  const rows = adminState.circles.length
    ? `<div class="table-wrap"><table><thead><tr><th>Name</th><th>Status</th><th>Contribution</th><th>Cadence</th><th>Entry fee</th><th>Members</th><th>Actions</th></tr></thead><tbody>${adminState.circles.map(adminCircleRow).join('')}</tbody></table></div>`
    : '<div class="empty"><p>No circles yet. Create one to get started.</p></div>';
  el.innerHTML = rows;
}

// ── Create / edit circle ──────────────────────────────────────────────────────
let _adminForm = { mode: 'create', id: null, trigger: null };

function openAdminForm(mode, id, ev) {
  if (!featureOn('catalog') || !isAdmin()) return;
  _adminForm = { mode: mode === 'edit' ? 'edit' : 'create', id: (mode === 'edit' && _catId(id)) ? id : null, trigger: (ev && ev.currentTarget) || document.activeElement };
  const v = _adminForm.id ? (adminState.circles.find((c) => c.id === _adminForm.id) || {}) : {};
  // If editing a circle whose cadence isn't one of the three options (e.g. a
  // CUSTOM cadence), offer a "keep" choice so saving never silently rewrites the
  // contribution timing to weekly. submitAdminForm omits cadence when 'keep'.
  const stdCad = typeof v.cadence === 'string' && ['WEEKLY', 'BIWEEKLY', 'MONTHLY'].includes(v.cadence);
  const keepOpt = (_adminForm.mode === 'edit' && v.cadence != null && !stdCad) ? '<option value="__keep" selected>Custom (unchanged)</option>' : '';
  const content = document.getElementById('adminFormContent');
  content.innerHTML = `
    <h3 id="adminFormTitle">${_adminForm.mode === 'edit' ? 'Edit circle' : 'Create a circle'}</h3>
    <form id="adminForm" onsubmit="submitAdminForm(event)">
      <label class="admin-fld"><span>Name</span><input id="afName" type="text" maxlength="80" value="${esc(v.name || '')}" required></label>
      <label class="admin-fld"><span>Contribution ($ per cycle)</span><input id="afContribution" type="text" inputmode="decimal" value="${v.contribution != null ? esc((v.contribution / 100).toFixed(2)) : ''}" required></label>
      <label class="admin-fld"><span>Entry fee ($, 0 for none)</span><input id="afEntryFee" type="text" inputmode="decimal" value="${v.entryFee != null ? esc((v.entryFee / 100).toFixed(2)) : '0.00'}"></label>
      <label class="admin-fld"><span>Max members</span><input id="afMax" type="number" min="2" max="50" value="${esc(v.cap || '')}" required></label>
      <label class="admin-fld"><span>Cadence</span><select id="afCadence">${keepOpt}<option value="WEEKLY">Weekly</option><option value="BIWEEKLY">Every 2 weeks</option><option value="MONTHLY">Monthly</option></select></label>
      <label class="admin-fld admin-fld--check"><input id="afPrivate" type="checkbox" ${v.isPrivate ? 'checked' : ''}><span>Private (invite-only)</span></label>
      <p class="err" id="adminFormErr" role="alert" style="display:none"></p>
      <div class="modal-actions"><button type="button" class="btn btn-ghost" onclick="closeAdminForm()">Cancel</button><button type="submit" class="btn btn-primary" id="adminFormSubmit">${_adminForm.mode === 'edit' ? 'Save changes' : 'Create circle'}</button></div>
    </form>`;
  if (stdCad) { const sel = document.getElementById('afCadence'); if (sel) sel.value = v.cadence; }
  SolDialog.open('adminFormDialog', { opener: _adminForm.trigger, initialFocus: '#afName', canClose: () => !SolGuard.isLocked('admin:circle:save'), onClose: () => { _adminForm = { mode: 'create', id: null, trigger: null }; } });
}

function closeAdminForm(skip) {
  if (SolGuard.isLocked('admin:circle:save') && !skip) return;   // commit-until-resolved
  SolDialog.close('adminFormDialog', { restoreFocus: !skip });
}

async function submitAdminForm(ev) {
  if (ev && ev.preventDefault) ev.preventDefault();
  if (!featureOn('catalog') || !isAdmin()) return;   // defense-in-depth (UX; backend is authoritative)
  if (SolGuard.isLocked('admin:circle:save')) return;
  const err = document.getElementById('adminFormErr');
  const name = (document.getElementById('afName').value || '').trim();
  const contribution = dollarsToCents(document.getElementById('afContribution').value);
  const entryFee = dollarsToCents(document.getElementById('afEntryFee').value);
  const max = parseInt(document.getElementById('afMax').value, 10);
  const cadence = document.getElementById('afCadence').value;
  const isPrivate = document.getElementById('afPrivate').checked;
  const CENTS_MAX = 100000000;   // $1,000,000 ceiling — catch fat-fingers; backend is still authoritative
  if (!name) return _adminFormErr(err, 'Enter a circle name.');
  if (contribution == null || contribution <= 0 || contribution > CENTS_MAX) return _adminFormErr(err, 'Enter a valid contribution amount (up to $1,000,000).');
  if (entryFee == null || entryFee < 0 || entryFee > CENTS_MAX) return _adminFormErr(err, 'Enter a valid entry fee (0 for none, up to $1,000,000).');
  if (!Number.isFinite(max) || max < 2 || max > 50) return _adminFormErr(err, 'Max members must be between 2 and 50.');
  SolGuard.acquire('admin:circle:save');   // acquire AFTER synchronous validation — no stuck lock on a validation failure
  const submit = document.getElementById('adminFormSubmit'); if (submit) { submit.disabled = true; submit.textContent = 'Saving…'; }
  if (err) err.style.display = 'none';
  const bodyObj = { name, contribution_cents: contribution, entry_fee_cents: entryFee, max_members: max, is_private: isPrivate };
  if (cadence !== '__keep') bodyObj.cadence = cadence;   // 'keep' → omit so the backend preserves a non-standard (CUSTOM) cadence
  const body = JSON.stringify(bodyObj);
  const mode = _adminForm.mode, id = _adminForm.id;
  try {
    if (mode === 'edit' && id) await api(`/admin/circles/${id}`, { method: 'PATCH', body });
    else await api('/admin/circles', { method: 'POST', body });
    closeAdminForm(true);
    adminAnnounce(mode === 'edit' ? 'Circle updated.' : 'Circle created.');
    await loadAdmin();   // re-fetch backend truth — NEVER optimistically insert/patch the row
    adminLandFocus();
  } catch (e) {
    _adminFormErr(err, safeError(e));
    if (submit) { submit.disabled = false; submit.textContent = mode === 'edit' ? 'Save changes' : 'Create circle'; }
  } finally { SolGuard.release('admin:circle:save'); }
}
function _adminFormErr(err, msg) { if (err) { err.textContent = msg; err.style.display = 'block'; } }

// ── Close circle ──────────────────────────────────────────────────────────────
let _adminClose = { id: null, trigger: null };

function openAdminClose(id, ev) {
  if (!featureOn('catalog') || !isAdmin() || !_catId(id)) return;
  const c = adminState.circles.find((x) => x.id === id);
  _adminClose = { id, trigger: (ev && ev.currentTarget) || document.activeElement };
  const content = document.getElementById('adminCloseContent');
  content.innerHTML = `
    <h3 id="adminCloseTitle">Close ${esc(c ? c.name : 'this circle')}?</h3>
    <div id="adminCloseBody"><p>Closing removes this circle from the catalog so no new members can join. Existing members and any in-progress cycles are unaffected. This can't be undone from here.</p></div>
    <p class="err" id="adminCloseErr" role="alert" style="display:none"></p>
    <div class="modal-actions"><button type="button" class="btn btn-ghost" onclick="closeAdminClose()">Keep open</button><button type="button" class="btn btn-primary" id="adminCloseConfirm" onclick="doCloseCircle('${esc(id)}',this)">Close circle</button></div>`;
  SolDialog.open('adminCloseDialog', { opener: _adminClose.trigger, initialFocus: '.btn-ghost', canClose: () => !SolGuard.isLocked('admin:circle:close:' + (_adminClose.id || '')), onClose: () => { _adminClose = { id: null, trigger: null }; } });
}

function closeAdminClose(skip) {
  if (SolGuard.isLocked('admin:circle:close:' + (_adminClose.id || '')) && !skip) return;
  SolDialog.close('adminCloseDialog', { restoreFocus: !skip });
}

async function doCloseCircle(id, btn) {
  if (!featureOn('catalog') || !isAdmin() || !_catId(id) || !SolGuard.acquire('admin:circle:close:' + id)) return;
  if (btn) { btn.disabled = true; btn.textContent = 'Closing…'; }
  const err = document.getElementById('adminCloseErr'); if (err) err.style.display = 'none';
  try {
    await api(`/admin/circles/${id}/close`, { method: 'POST' });   // backend-authoritative
    closeAdminClose(true);
    adminAnnounce('Circle closed.');
    await loadAdmin();   // re-fetch — no optimistic mutation
    adminLandFocus();
  } catch (e) {
    if (err) { err.textContent = safeError(e); err.style.display = 'block'; }
    if (btn) { btn.disabled = false; btn.textContent = 'Close circle'; }
  } finally { SolGuard.release('admin:circle:close:' + id); }
}

// ── Participant view (no member PII — position + status only) ──────────────────
let _adminPart = { id: null, trigger: null };

async function openAdminParticipants(id, ev) {
  if (!featureOn('catalog') || !isAdmin() || !_catId(id)) return;
  _adminPart = { id, trigger: (ev && ev.currentTarget) || document.activeElement };
  document.getElementById('adminPartContent').innerHTML = '<div class="spinner"></div>';
  SolDialog.open('adminParticipantsDialog', { opener: _adminPart.trigger, initialFocus: false, onClose: () => { _adminPart = { id: null, trigger: null }; } });
  const _m = document.querySelector('#adminParticipantsDialog .modal'); if (_m) { _m.setAttribute('tabindex', '-1'); try { _m.focus(); } catch (e) {} }
  let list = null;
  try { const r = await api(`/admin/circles/${id}/participants`); if (Array.isArray(r)) list = r; } catch (e) { if (_aborted(e)) return; list = null; }
  if (_adminPart.id !== id) return;   // dialog closed/replaced while loading
  renderAdminParticipants(list);
}

function closeAdminParticipants() { SolDialog.close('adminParticipantsDialog'); }

function renderAdminParticipants(list) {
  const content = document.getElementById('adminPartContent');
  const c = adminState.circles.find((x) => x.id === _adminPart.id);
  const closeBtn = '<div class="modal-actions"><button type="button" class="btn btn-ghost" onclick="closeAdminParticipants()">Close</button></div>';
  if (!Array.isArray(list)) {
    content.innerHTML = `<h3 id="adminPartTitle">Participants</h3><p id="adminPartBody" class="hint-muted">Couldn't load participants right now.</p>${closeBtn}`;
    setTimeout(() => { const f = content.querySelector('.btn-ghost'); if (f) f.focus(); }, 0);
    return;
  }
  // Render position + status ONLY — never a member name or user_id.
  const body = list.length
    ? `<div class="table-wrap"><table><thead><tr><th>Position</th><th>Member</th><th>Status</th></tr></thead><tbody>${list.map((p) => `<tr><td class="tnum">${(p && Number.isFinite(p.position)) ? esc(p.position) : '—'}</td><td class="hint-muted">Member</td><td>${statusChip(p && p.status)}</td></tr>`).join('')}</tbody></table></div>`
    : '<p class="hint-muted">No participants yet.</p>';
  content.innerHTML = `<h3 id="adminPartTitle">${esc(c ? c.name : 'Circle')} — participants</h3><div id="adminPartBody">${body}</div>${closeBtn}`;
  setTimeout(() => { const f = content.querySelector('.btn-ghost'); if (f) f.focus(); }, 0);
}
