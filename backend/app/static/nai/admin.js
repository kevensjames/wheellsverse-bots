// KAI operator dashboard.
//
// Auth: shared X-Admin-Token header. We store the token in sessionStorage
// (not localStorage) so closing the tab requires re-auth — same defense the
// rest of the admin endpoints assume.
//
// This page does ZERO destructive actions by design. It's a read-only
// pane of glass. Comp/refund/ban deep-links to Stripe + Supabase.

const TOKEN_KEY = "kai_admin_token";
const REFRESH_MS = 30_000;

const $ = (sel) => document.querySelector(sel);

function getToken() {
  return sessionStorage.getItem(TOKEN_KEY) || "";
}

function setToken(t) {
  sessionStorage.setItem(TOKEN_KEY, t);
}

function clearToken() {
  sessionStorage.removeItem(TOKEN_KEY);
}

async function apiGet(path) {
  const r = await fetch(path, {
    method: "GET",
    headers: { "X-Admin-Token": getToken() },
  });
  if (r.status === 403 || r.status === 401) {
    throw new AuthError(`auth rejected (${r.status})`);
  }
  if (!r.ok) {
    throw new Error(`${path} returned ${r.status}`);
  }
  return r.json();
}

class AuthError extends Error {}

function fmtUSD(n) {
  if (typeof n !== "number" || isNaN(n)) return "—";
  if (n === 0) return "$0.00";
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  const now = new Date();
  const ms = now - d;
  if (ms < 60_000) return `${Math.round(ms / 1000)}s ago`;
  if (ms < 3_600_000) return `${Math.round(ms / 60_000)}m ago`;
  if (ms < 86_400_000) return `${Math.round(ms / 3_600_000)}h ago`;
  return `${Math.round(ms / 86_400_000)}d ago`;
}

function setText(sel, v) {
  const el = $(sel);
  if (el) el.textContent = v;
}

function renderStats(s) {
  setText("#stat-users-total", s.users.total);
  setText("#stat-users-24h", s.users.last_24h);
  setText("#stat-users-7d", s.users.last_7d);
  setText("#stat-subs-active", s.subscriptions.active);
  setText("#stat-subs-24h", s.subscriptions.new_24h);

  // Tier breakdown as inline chips. Order: ultra, max, pro, free.
  // Built with DOM methods (not innerHTML) to keep XSS surface at zero
  // even though the data source is our own database.
  const order = ["ultra", "max", "pro", "free"];
  const tiers = s.users.by_tier || {};
  const tierEl = $("#stat-users-by-tier");
  if (tierEl) {
    tierEl.replaceChildren();
    const present = order.filter((t) => t in tiers);
    if (present.length === 0) {
      const em = document.createElement("em");
      em.textContent = "no breakdown";
      tierEl.appendChild(em);
    } else {
      for (const t of present) {
        const chip = document.createElement("span");
        chip.className = `tier-chip tier-${t}`;
        chip.textContent = `${t} ${tiers[t]}`;
        tierEl.appendChild(chip);
      }
    }
  }

  setText("#admin-as-of", fmtTime(s.as_of));
}

function renderSpend(s) {
  setText("#stat-spend-today", fmtUSD(s.today_total_usd));
  setText("#stat-spend-7d", fmtUSD(s.last_7d_total_usd));
  setText("#stat-failures", s.failures_24h);

  const tbody = $("#admin-spend-table tbody");
  if (!tbody) return;
  tbody.replaceChildren();
  const total = s.last_7d_total_usd || 0;
  if (!s.last_7d.length) {
    tbody.appendChild(emptyRow(4, "no calls in last 7d"));
    return;
  }
  for (const row of s.last_7d) {
    const share = total > 0 ? ((row.cost_usd / total) * 100).toFixed(1) : "0.0";
    const tr = document.createElement("tr");
    tr.appendChild(td(row.adapter));
    tr.appendChild(td(row.calls.toLocaleString()));
    tr.appendChild(td(fmtUSD(row.cost_usd)));
    tr.appendChild(td(`${share}%`));
    tbody.appendChild(tr);
  }
}

function td(text, className) {
  const el = document.createElement("td");
  el.textContent = text;
  if (className) el.className = className;
  return el;
}

function emptyRow(cols, text) {
  const tr = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = cols;
  cell.className = "dim";
  cell.textContent = text;
  tr.appendChild(cell);
  return tr;
}

function renderUsers(payload) {
  const tbody = $("#admin-users-table tbody");
  if (!tbody) return;
  tbody.replaceChildren();
  if (!payload.users.length) {
    tbody.appendChild(emptyRow(3, "no signups yet"));
    return;
  }
  for (const u of payload.users) {
    const tr = document.createElement("tr");

    const whenCell = td(fmtTime(u.created_at));
    if (u.created_at) whenCell.title = u.created_at;   // setter, not interpolation
    tr.appendChild(whenCell);

    tr.appendChild(td(u.email || ""));

    const tierCell = document.createElement("td");
    const chip = document.createElement("span");
    // Whitelist class suffix — defends against a stray DB value sneaking
    // CSS-injection / attribute-breakout into the class string.
    const tierKey = ["ultra", "max", "pro", "free"].includes(u.tier) ? u.tier : "free";
    chip.className = `tier-chip tier-${tierKey}`;
    chip.textContent = u.tier || "free";
    tierCell.appendChild(chip);
    tr.appendChild(tierCell);

    tbody.appendChild(tr);
  }
}

async function refresh() {
  try {
    // Parallel fetch — these endpoints are independent.
    const [stats, spend, users] = await Promise.all([
      apiGet("/admin/stats"),
      apiGet("/admin/spend"),
      apiGet("/admin/recent-users?limit=20"),
    ]);
    renderStats(stats);
    renderSpend(spend);
    renderUsers(users);
    showBody();
  } catch (e) {
    if (e instanceof AuthError) {
      clearToken();
      showAuth(`Token rejected. Re-enter or check ADMIN_TOKEN env on the server.`);
      return;
    }
    setText("#admin-as-of", `error: ${e.message}`);
  }
}

function showAuth(errMsg) {
  $("#admin-body").hidden = true;
  $("#admin-auth").hidden = false;
  const errEl = $("#admin-auth-err");
  if (errEl) errEl.textContent = errMsg || "";
  $("#admin-token-input").focus();
}

function showBody() {
  $("#admin-auth").hidden = true;
  $("#admin-body").hidden = false;
}

// ─── boot ──────────────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
  $("#admin-auth-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const t = $("#admin-token-input").value.trim();
    if (!t) return;
    setToken(t);
    refresh();
  });

  $("#admin-refresh").addEventListener("click", refresh);

  $("#admin-logout").addEventListener("click", () => {
    clearToken();
    showAuth("");
  });

  if (getToken()) {
    refresh();
  } else {
    showAuth("");
  }

  setInterval(() => {
    if (getToken() && !$("#admin-body").hidden) refresh();
  }, REFRESH_MS);
});
