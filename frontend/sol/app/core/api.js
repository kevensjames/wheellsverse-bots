// SOL member app — core/api.js
// Classic script (shared global scope); loaded in order by app.html. Part of the
// buildless multi-file split (Phase 2). See docs / sol-refactor memory.

// ── API helpers ───────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const r = await fetch(API + path, {
    ...opts,
    headers: {
      'Content-Type': 'application/json',
      'Authorization': 'Bearer ' + token,
      ...(opts.headers || {})
    }
  });
  if (r.status === 204) return null;
  // 401 = access token expired. Try silently refreshing via the refresh token
  // (valid 30 days) before giving up and bouncing the user to login. This
  // keeps long-running tabs alive past the 60-min access-token TTL.
  if (r.status === 401 && !opts._retry) {
    const refreshed = await _tryRefresh();
    if (refreshed) {
      return api(path, { ...opts, _retry: true });
    }
    localStorage.removeItem('sol_token');
    localStorage.removeItem('sol_refresh');
    window.location.href = '/sol/';
    throw new Error('Session expired');
  }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(formatApiError(d, r.statusText));
  return d;
}

// Exchange refresh_token for a fresh access_token. Returns true on success.
// Called from api() on 401; never throws so callers can fall through to the
// login redirect on hard failure.
let _refreshPromise = null;
async function _tryRefresh() {
  const refresh = localStorage.getItem('sol_refresh');
  if (!refresh) return false;
  // Dedupe concurrent 401s so we don't rotate the refresh token multiple times.
  if (_refreshPromise) return _refreshPromise;
  _refreshPromise = (async () => {
    try {
      const r = await fetch(API + '/auth/refresh', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!r.ok) return false;
      const d = await r.json();
      localStorage.setItem('sol_token', d.access_token);
      localStorage.setItem('sol_refresh', d.refresh_token);
      token = d.access_token;
      return true;
    } catch {
      return false;
    } finally {
      _refreshPromise = null;
    }
  })();
  return _refreshPromise;
}

// FastAPI returns validation errors as detail=[{loc, msg, type}, ...] on 422.
// Without this helper, `new Error(d.detail)` coerces the array to a string,
// producing "[object Object],[object Object]".
function formatApiError(d, fallback) {
  if (!d || !d.detail) return fallback || 'Request failed';
  if (typeof d.detail === 'string') return d.detail;
  if (Array.isArray(d.detail)) {
    return d.detail.map(e => {
      if (typeof e === 'string') return e;
      const field = Array.isArray(e.loc) ? e.loc.filter(x => x !== 'body').join('.') : '';
      const msg = e.msg || e.message || JSON.stringify(e);
      return field ? `${field}: ${msg}` : msg;
    }).join('; ');
  }
  return d.detail.msg || JSON.stringify(d.detail);
}

// Canonical status chip — the ONE way to render a backend lifecycle enum as a
// member-facing chip. Replaces the legacy badge()/.badge-* system: maps the raw
// enum to a canonical label + a semantic .status--* variant (tinted pill + dot +
// text, never colour-only — see DESIGN_SYSTEM.md). Payment states mirror
// PAY_STATE severity (RETURNED reads as a failure). Generic across
// circle/cycle/member/payment, so PENDING stays neutral "Pending" (the Payments
// page's richer PAY_STATE uses the payment-specific "Due").
function statusChip(status) {
  const variant = {
    ACTIVE:'active', VERIFIED:'verified', SUCCESS:'active',
    FORMING:'forming', PENDING:'pending', SUBMITTED:'pending', INITIATED:'pending',
    COLLECTING:'active', SETTLING:'active', PROCESSING:'pending', COMPLETED:'completed',
    FAILED:'failed', DELINQUENT:'failed', SUSPENDED:'blocked', CLOSED:'cancelled', RETURNED:'failed',
    CANCELLED:'cancelled', PAUSED:'warning',
  };
  const label = {
    ACTIVE:'Active', VERIFIED:'Verified', SUCCESS:'Settled',
    FORMING:'Forming', PENDING:'Pending', SUBMITTED:'Under review', INITIATED:'Submitted',
    COLLECTING:'Active', SETTLING:'Active', PROCESSING:'Processing', COMPLETED:'Completed',
    FAILED:'Failed', DELINQUENT:'Action required', SUSPENDED:'Suspended', CLOSED:'Closed', RETURNED:'Returned',
  };
  const key = String(status || '').toUpperCase();
  const text = label[key] || (key ? key.charAt(0) + key.slice(1).toLowerCase() : '—');
  const v = variant[key] || 'completed';   // unknown enum → neutral grey (matches the old badge-gray default), never amber "in-progress"
  return `<span class="status status--${v}" aria-label="Status: ${esc(text)}">${esc(text)}</span>`;
}
function fmt$(c) { return '$' + (c/100).toLocaleString('en-US',{minimumFractionDigits:2}); }
// Canonical member-facing date — "Mon D, YYYY" in the user's locale. One helper
// so every surface formats a date identically (see docs/sol DATE-01). Returns ''
// for a null/invalid date so callers can guard.
function fmtDate(d, opts) {
  if (!d) return '';
  const x = new Date(d);
  if (isNaN(x.getTime())) return '';
  return x.toLocaleDateString(undefined, opts || { year: 'numeric', month: 'short', day: 'numeric' });
}
// Escape untrusted strings before interpolating into innerHTML — user-controlled
// data (circle names, notification bodies, template names) must never be able to
// inject markup/script that could read the session token from localStorage.
function esc(s){ return String(s??'').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
// Only allow http(s) links; anything else (javascript:, data:) → empty.
function safeUrl(u){ return /^https?:\/\//i.test(u||'') ? u : ''; }

async function copyInvite(groupId) {
  const input = document.getElementById('inviteUrl-' + groupId);
  if (!input) return;
  try {
    await navigator.clipboard.writeText(input.value);
    const btn = event.target;
    const orig = btn.textContent;
    btn.textContent = '✓ Copied';
    setTimeout(() => { btn.textContent = orig; }, 1500);
  } catch {
    // Fallback for older browsers / insecure contexts: select the text so
    // the user can Cmd/Ctrl+C manually.
    input.select();
  }
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  try {
    me = await api('/auth/me');
    document.getElementById('userEmail').textContent = me.email;
    loadDashboard();  // one consolidated, partial-failure-safe load feeds every card
    consumePendingInvite();  // if user arrived via ?invite=..., auto-join now
    // Returning from Stripe Checkout (?premium=success|cancel) — open the Premium
    // page so loadPremium() can show the return note and poll for activation.
    if (new URLSearchParams(location.search).get('premium')) nav('premium');
  } catch {
    localStorage.removeItem('sol_token');
    window.location.href = '/sol/';
  }
}

// Build the "Your money" panel: per-circle next-contribution date, next-payout
// estimate, and the running total this user has contributed across all active
// circles.
