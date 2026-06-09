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
  $("#admin-tabs").hidden = true;
  $("#admin-auth").hidden = false;
  const errEl = $("#admin-auth-err");
  if (errEl) errEl.textContent = errMsg || "";
  $("#admin-token-input").focus();
}

function showBody() {
  $("#admin-auth").hidden = true;
  $("#admin-body").hidden = false;
  $("#admin-tabs").hidden = false;
}

// ─── tabs ──────────────────────────────────────────────────────────

function activateTab(name) {
  document.querySelectorAll(".admin-tab").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.tab === name);
  });
  document.querySelectorAll(".admin-pane").forEach((pane) => {
    pane.hidden = pane.id !== `admin-pane-${name}`;
  });
  if (name === "chat") {
    const input = $("#admin-chat-input");
    if (input) input.focus();
  } else if (name === "scanner") {
    // Lazy-load supreme data the first time the tab is opened.
    loadSupreme();
  } else if (name === "brief") {
    // Audit table fetches immediately; brief body waits for user click.
    loadBriefAudit();
  }
}

// ─── operator chat ─────────────────────────────────────────────────

let adminConversationId = null;

async function adminChatPost(message) {
  const body = {
    message,
    conversation_id: adminConversationId,
    use_tools: !$("#admin-no-tools").checked,
    prefer_local: $("#admin-prefer-local").checked,
    max_tokens: 2048,
  };
  const r = await fetch("/admin/kai-chat", {
    method: "POST",
    headers: {
      "X-Admin-Token": getToken(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (r.status === 403 || r.status === 401) {
    throw new AuthError(`auth rejected (${r.status})`);
  }
  if (!r.ok) {
    const text = await r.text();
    throw new Error(text || `chat error ${r.status}`);
  }
  return r.json();
}

function appendChatMessage(role, text, meta) {
  const list = $("#admin-chat-messages");
  if (!list) return;
  const wrap = document.createElement("div");
  wrap.className = `admin-chat-msg admin-chat-msg-${role}`;

  const bubble = document.createElement("div");
  bubble.className = "admin-chat-bubble";
  bubble.textContent = text;
  wrap.appendChild(bubble);

  if (meta) {
    const m = document.createElement("div");
    m.className = "admin-chat-meta";
    m.textContent = meta;
    wrap.appendChild(m);
  }

  list.appendChild(wrap);
  list.scrollTop = list.scrollHeight;
}

function setChatStatus(text) {
  const el = $("#admin-chat-status");
  if (el) el.textContent = text || "";
}

async function sendChat(e) {
  if (e) e.preventDefault();
  const input = $("#admin-chat-input");
  const sendBtn = $("#admin-chat-send");
  const text = (input.value || "").trim();
  if (!text) return;

  appendChatMessage("user", text);
  input.value = "";
  sendBtn.disabled = true;
  setChatStatus("thinking…");

  try {
    const resp = await adminChatPost(text);
    adminConversationId = resp.conversation_id;
    const msg = resp.message || {};
    const meta = [
      msg.adapter && `adapter=${msg.adapter}`,
      msg.model && `model=${msg.model}`,
      typeof resp.total_cost_usd === "number" && `cost=$${resp.total_cost_usd.toFixed(4)}`,
    ].filter(Boolean).join(" · ");
    appendChatMessage("assistant", msg.content || "(empty response)", meta);
    setChatStatus("");
  } catch (err) {
    if (err instanceof AuthError) {
      clearToken();
      showAuth("Token rejected. Re-enter to continue.");
    } else {
      appendChatMessage("assistant", `⚠️ ${err.message}`);
      setChatStatus("");
    }
  } finally {
    sendBtn.disabled = false;
    input.focus();
  }
}

function resetChat() {
  adminConversationId = null;
  const list = $("#admin-chat-messages");
  if (list) list.replaceChildren();
  setChatStatus("");
  $("#admin-chat-input").focus();
}

// ─── supreme scanner ───────────────────────────────────────────────

const SEVERITY_ORDER = ["critical", "high", "medium", "low"];
const SEVERITY_EMOJI = { critical: "🔴", high: "🟠", medium: "🟡", low: "🟢" };

async function loadSupreme() {
  try {
    const [status, latest, history] = await Promise.all([
      apiGet("/admin/supreme/status"),
      apiGet("/admin/supreme/latest"),
      apiGet("/admin/supreme/history?limit=20"),
    ]);
    renderSupremeStatus(status);
    renderSupremeLatest(latest.proposal);
    renderSupremeHistory(history.proposals);
  } catch (e) {
    if (e instanceof AuthError) {
      clearToken();
      showAuth("Token rejected.");
    } else {
      const line = $("#supreme-status-line");
      if (line) line.textContent = `error: ${e.message}`;
    }
  }
}

function renderSupremeStatus(s) {
  const line = $("#supreme-status-line");
  if (!line) return;
  const parts = [
    s.scheduler_running ? "scheduler ON" : "scheduler OFF (set KAI_SUPREME_ENABLED=1)",
    `interval ${Math.round((s.scan_interval_seconds || 0) / 60)}min`,
    s.map_loaded ? `map v${s.map_version}` : "no map",
    `alerts ≥ ${s.telegram_notify_severity}`,
  ];
  line.textContent = parts.join(" · ");
}

function renderSupremeLatest(proposal) {
  const sevRow = $("#supreme-severity-row");
  const findings = $("#supreme-findings");
  const tsEl = $("#supreme-latest-ts");
  if (!sevRow || !findings || !tsEl) return;
  sevRow.replaceChildren();
  findings.replaceChildren();

  if (!proposal) {
    tsEl.textContent = "no scans yet — click 'scan now' to start";
    return;
  }
  tsEl.textContent = fmtTime(proposal.scanned_at) + " · " + (proposal.finding_count ?? 0) + " findings";
  tsEl.title = proposal.scanned_at || "";

  // Severity chips
  const counts = proposal.severity_counts || {};
  let any = false;
  for (const sev of SEVERITY_ORDER) {
    const n = counts[sev] || 0;
    if (!n) continue;
    any = true;
    const chip = document.createElement("span");
    chip.className = "tier-chip";
    chip.textContent = `${SEVERITY_EMOJI[sev] || ""} ${sev} ${n}`;
    chip.style.background = severityColor(sev);
    chip.style.color = "#fff";
    sevRow.appendChild(chip);
  }
  if (!any) {
    const ok = document.createElement("span");
    ok.className = "tier-chip";
    ok.textContent = "✓ all clear";
    ok.style.background = "#23a36b";
    ok.style.color = "#fff";
    sevRow.appendChild(ok);
  }

  // Findings list — sorted by severity then category
  const sorted = (proposal.findings || []).slice().sort((a, b) => {
    const ai = SEVERITY_ORDER.indexOf(a.severity);
    const bi = SEVERITY_ORDER.indexOf(b.severity);
    return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
  });
  for (const f of sorted) {
    findings.appendChild(renderFinding(f));
  }
}

function renderFinding(f) {
  const wrap = document.createElement("div");
  wrap.className = "supreme-finding";
  wrap.style.borderLeft = `3px solid ${severityColor(f.severity)}`;

  const header = document.createElement("div");
  header.className = "supreme-finding-header";
  const sev = document.createElement("span");
  sev.className = "supreme-finding-sev";
  sev.style.color = severityColor(f.severity);
  sev.textContent = (SEVERITY_EMOJI[f.severity] || "") + " " + (f.severity || "").toUpperCase();
  header.appendChild(sev);

  const cat = document.createElement("span");
  cat.className = "supreme-finding-cat";
  cat.textContent = f.category || "";
  header.appendChild(cat);

  const title = document.createElement("div");
  title.className = "supreme-finding-title";
  title.textContent = f.title || "";

  wrap.appendChild(header);
  wrap.appendChild(title);

  if (f.detail) {
    const d = document.createElement("div");
    d.className = "supreme-finding-detail";
    d.textContent = f.detail;
    wrap.appendChild(d);
  }
  if (f.proposed_fix) {
    const pf = document.createElement("div");
    pf.className = "supreme-finding-fix";
    pf.textContent = "→ Fix: " + f.proposed_fix;
    wrap.appendChild(pf);
  }
  if (f.evidence) {
    const ev = document.createElement("pre");
    ev.className = "supreme-finding-evidence";
    ev.textContent = f.evidence;
    wrap.appendChild(ev);
  }
  return wrap;
}

function severityColor(sev) {
  return ({ critical: "#ff3b3b", high: "#ff8c1a", medium: "#f0c419", low: "#23a36b" })[sev] || "#666";
}

function renderSupremeHistory(rows) {
  const tbody = $("#supreme-history-table tbody");
  if (!tbody) return;
  tbody.replaceChildren();
  if (!rows.length) {
    tbody.appendChild(emptyRow(3, "no scans recorded yet"));
    return;
  }
  for (const r of rows) {
    const tr = document.createElement("tr");

    const whenCell = td(fmtTime(r.scanned_at));
    if (r.scanned_at) whenCell.title = r.scanned_at;
    tr.appendChild(whenCell);
    tr.appendChild(td(String(r.finding_count || 0)));

    const sevCell = document.createElement("td");
    const counts = r.severity_counts || {};
    let chipAdded = false;
    for (const sev of SEVERITY_ORDER) {
      const n = counts[sev] || 0;
      if (!n) continue;
      const c = document.createElement("span");
      c.className = "tier-chip";
      c.style.background = severityColor(sev);
      c.style.color = "#fff";
      c.style.marginRight = "4px";
      c.textContent = `${sev} ${n}`;
      sevCell.appendChild(c);
      chipAdded = true;
    }
    if (!chipAdded) sevCell.textContent = "all clear";
    tr.appendChild(sevCell);

    tbody.appendChild(tr);
  }
}

// ─── daily brief ──────────────────────────────────────────────────

async function generateBrief() {
  const btn = $("#brief-generate-now");
  const line = $("#brief-status-line");
  if (!btn) return;
  btn.disabled = true;
  const old = btn.textContent;
  btn.textContent = "generating…";
  try {
    const r = await fetch("/admin/briefing/generate", {
      method: "POST",
      headers: { "X-Admin-Token": getToken() },
    });
    if (r.status === 403) {
      // Could be auth OR scope-not-enabled — show the message body so the
      // operator knows which env var to flip.
      const body = await r.json().catch(() => ({}));
      if (line) line.textContent = body.detail || "auth/scope rejected";
      return;
    }
    if (r.status === 401) {
      clearToken();
      showAuth("Token rejected.");
      return;
    }
    if (!r.ok) {
      const text = await r.text();
      if (line) line.textContent = `error ${r.status}: ${text.slice(0, 120)}`;
      return;
    }
    const brief = await r.json();
    renderBrief(brief);
    await loadBriefAudit();
    if (line) line.textContent = "generated";
  } catch (e) {
    if (line) line.textContent = `error: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = old;
  }
}

function renderBrief(brief) {
  if (!brief) return;

  // Headline
  $("#brief-headline-card").hidden = false;
  $("#brief-headline").querySelector("strong").textContent = brief.headline || "";
  const at = brief.generated_at ? `generated ${fmtTime(brief.generated_at)}` : "";
  $("#brief-generated-at").textContent = at;

  // Body cards
  $("#brief-body").hidden = false;
  $("#brief-users-total").textContent = brief.users.total;
  $("#brief-users-24h").textContent = brief.users.last_24h;
  $("#brief-users-7d").textContent = brief.users.last_7d;
  $("#brief-subs-active").textContent = brief.revenue.active_subs;
  $("#brief-subs-new24h").textContent = brief.revenue.new_subs_24h;
  $("#brief-spend-today").textContent = fmtUSD(brief.spend.today_usd);
  $("#brief-spend-7d").textContent = fmtUSD(brief.spend.last_7d_usd);

  // Scanner snapshot
  const sc = brief.scanner || {};
  const scCard = $("#brief-scanner-card");
  const scSum = $("#brief-scanner-summary");
  const scHead = $("#brief-scanner-headlines");
  scSum.replaceChildren();
  scHead.replaceChildren();
  if (!sc.has_scan) {
    scCard.hidden = true;
  } else {
    scCard.hidden = false;
    const counts = sc.severity_counts || {};
    for (const sev of SEVERITY_ORDER) {
      const n = counts[sev] || 0;
      if (!n) continue;
      const chip = document.createElement("span");
      chip.className = "tier-chip";
      chip.style.background = severityColor(sev);
      chip.style.color = "#fff";
      chip.textContent = `${SEVERITY_EMOJI[sev] || ""} ${sev} ${n}`;
      scSum.appendChild(chip);
    }
    for (const f of (sc.headline_findings || [])) {
      const row = document.createElement("div");
      row.className = "supreme-finding";
      row.style.borderLeft = `3px solid ${severityColor(f.severity)}`;
      row.textContent = `[${(f.severity || "").toUpperCase()}] ${f.title || ""}`;
      scHead.appendChild(row);
    }
  }

  // Recent errors
  const errs = brief.errors || {};
  const errCard = $("#brief-errors-card");
  const errBox = $("#brief-errors");
  errBox.replaceChildren();
  if (!errs.failure_count_24h) {
    errCard.hidden = true;
  } else {
    errCard.hidden = false;
    for (const e of (errs.recent || [])) {
      const row = document.createElement("div");
      row.className = "brief-error-row";
      const meta = document.createElement("div");
      meta.className = "brief-error-meta";
      meta.textContent = `${fmtTime(e.at)} · ${e.adapter}/${e.model || "?"}`;
      const msg = document.createElement("div");
      msg.textContent = e.error || "";
      row.appendChild(meta);
      row.appendChild(msg);
      errBox.appendChild(row);
    }
  }
}

async function loadBriefAudit() {
  try {
    const data = await apiGet("/admin/briefing/audit?limit=20");
    renderBriefAudit(data.actions || []);
  } catch (e) {
    // Non-fatal; audit table just stays empty.
  }
}

function renderBriefAudit(rows) {
  const tbody = $("#brief-audit-table tbody");
  if (!tbody) return;
  tbody.replaceChildren();
  if (!rows.length) {
    tbody.appendChild(emptyRow(5, "no actions logged yet"));
    return;
  }
  for (const r of rows) {
    const tr = document.createElement("tr");
    const whenCell = td(fmtTime(r.ts));
    if (r.ts) whenCell.title = r.ts;
    tr.appendChild(whenCell);
    tr.appendChild(td(r.action || ""));
    tr.appendChild(td(r.scope || ""));
    tr.appendChild(td(r.actor || ""));
    const ok = r.success ? "✓" : "✗";
    const okCell = td(ok);
    if (!r.success && r.error) okCell.title = r.error;
    tr.appendChild(okCell);
    tbody.appendChild(tr);
  }
}

async function runSupremeScan() {
  const btn = $("#supreme-scan-now");
  const line = $("#supreme-status-line");
  if (!btn) return;
  btn.disabled = true;
  const oldText = btn.textContent;
  btn.textContent = "scanning…";
  try {
    const r = await fetch("/admin/supreme/scan", {
      method: "POST",
      headers: { "X-Admin-Token": getToken() },
    });
    if (r.status === 403 || r.status === 401) throw new AuthError("auth rejected");
    if (!r.ok) throw new Error(`scan ${r.status}`);
    const data = await r.json();
    if (line) line.textContent = `scan complete · ${data.finding_count} findings · ${data.proposal_name}`;
    await loadSupreme();
  } catch (e) {
    if (e instanceof AuthError) {
      clearToken();
      showAuth("Token rejected.");
    } else if (line) {
      line.textContent = `error: ${e.message}`;
    }
  } finally {
    btn.disabled = false;
    btn.textContent = oldText;
  }
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

  // Tabs
  document.querySelectorAll(".admin-tab").forEach((btn) => {
    btn.addEventListener("click", () => activateTab(btn.dataset.tab));
  });

  // Chat
  $("#admin-chat-form").addEventListener("submit", sendChat);
  $("#admin-chat-new").addEventListener("click", resetChat);

  // Cmd/Ctrl + Enter sends — Enter alone inserts a newline (preserves the
  // multiline-prompt pattern from the main /kai-ui/chat.html input).
  $("#admin-chat-input").addEventListener("keydown", (ev) => {
    if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) {
      ev.preventDefault();
      sendChat();
    }
  });

  // Supreme scanner
  $("#supreme-scan-now").addEventListener("click", runSupremeScan);

  // Daily Brief
  $("#brief-generate-now").addEventListener("click", generateBrief);

  if (getToken()) {
    refresh();
  } else {
    showAuth("");
  }

  setInterval(() => {
    if (getToken() && !$("#admin-body").hidden) refresh();
  }, REFRESH_MS);
});
