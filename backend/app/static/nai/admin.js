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

// Mirror of apiGet for POSTs. Pass an object as `body`; gets JSON-encoded.
// Pass null/undefined for no-body POSTs (e.g. /admin/research/run-now).
async function apiPost(path, body) {
  const init = {
    method: "POST",
    headers: { "X-Admin-Token": getToken() },
  };
  if (body !== null && body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const r = await fetch(path, init);
  if (r.status === 403 || r.status === 401) {
    throw new AuthError(`auth rejected (${r.status})`);
  }
  if (!r.ok) {
    let detail = "";
    try {
      const j = await r.json();
      detail = j.detail ? `: ${j.detail}` : "";
    } catch (_) { /* non-JSON body — ignore */ }
    throw new Error(`${path} returned ${r.status}${detail}`);
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
  let active = null;
  document.querySelectorAll(".admin-tab").forEach((btn) => {
    const on = btn.dataset.tab === name;
    btn.classList.toggle("is-active", on);
    if (on) active = btn;
  });
  // On the narrow mobile tab-strip, keep the selected tab in view.
  if (active && active.scrollIntoView) {
    active.scrollIntoView({ inline: "center", block: "nearest", behavior: "smooth" });
  }
  document.querySelectorAll(".admin-pane").forEach((pane) => {
    pane.hidden = pane.id !== `admin-pane-${name}`;
  });
  if (name === "chat") {
    const input = $("#admin-chat-input");
    if (input) input.focus();
    loadPresets();
  } else if (name === "scanner") {
    // Lazy-load supreme data the first time the tab is opened.
    loadSupreme();
  } else if (name === "brief") {
    // Audit table fetches immediately; brief body waits for user click.
    loadBriefAudit();
    loadDigestLatest();
  } else if (name === "kg") {
    loadKgStats();
  } else if (name === "failures") {
    loadFailures();
  } else if (name === "research") {
    loadResearchStatus();
    loadResearchLatest();
    loadResearchHistory();
  } else if (name === "self-correction") {
    loadSelfCorrection();
  } else if (name === "planning") {
    loadPlanning();
  } else if (name === "browser") {
    loadBrowser();
  } else if (name === "learning") {
    loadLearning();
  } else if (name === "twin") {
    loadTwin();
  } else if (name === "audit") {
    loadAudit();
  }
}

// ─── operator chat ─────────────────────────────────────────────────

let adminConversationId = null;

async function adminChatPost(message) {
  const presetSel = $("#admin-preset-select");
  const selfCorrect = $("#admin-self-correct");
  const body = {
    message,
    conversation_id: adminConversationId,
    use_tools: !$("#admin-no-tools").checked,
    prefer_local: $("#admin-prefer-local").checked,
    max_tokens: 2048,
    preset_id: presetSel && presetSel.value ? presetSel.value : null,
    auto_route: !!$("#admin-auto-route")?.checked,
    self_correct: !!(selfCorrect && selfCorrect.checked),
    verify: !!$("#admin-verify")?.checked,
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

// Extract citation markers an agent emits — [PMID 123], [source: file #N],
// [From "file", chunk #N], [SEC: …], [<case>, <citation>] — into chips. The
// first three get links/labels; we keep it simple + deduped.
function parseCitations(text) {
  const cites = [];
  const seen = new Set();
  const add = (label, href) => {
    const k = label.toLowerCase();
    if (seen.has(k)) return;
    seen.add(k);
    cites.push({ label, href });
  };
  let m;
  const pmid = /\[\s*PMID:?\s*(\d+)\s*\]/gi;
  while ((m = pmid.exec(text))) add(`PMID ${m[1]}`, `https://pubmed.ncbi.nlm.nih.gov/${m[1]}/`);
  const src = /\[\s*(?:source:\s*|From\s*")\s*([^\]"#]+?)["']?\s*(?:,?\s*(?:chunk\s*)?#\s*(\d+))?\s*\]/gi;
  while ((m = src.exec(text))) { const n = (m[1] || "").trim(); if (n) add(m[2] ? `${n} #${m[2]}` : n, null); }
  return cites;
}

// Pull a self-rated [confidence: high|medium|low] tag out of an answer (grounded
// agents emit it). Returns the level + the text with every such tag removed so
// the raw tag never shows to the operator.
function extractConfidence(text) {
  const m = text.match(/\[\s*confidence:\s*(high|medium|low)\s*\]/i);
  const level = m ? m[1].toLowerCase() : null;
  const clean = text.replace(/\s*\[\s*confidence:\s*(?:high|medium|low)\s*\]\s*/gi, " ").trim();
  return { level, clean };
}

// Append the "badges" row under an assistant answer: which expert handled it
// (routed), a self-rated confidence, a grounding indicator (✓ N sources), and
// the citation chips.
function renderAssistantExtras(wrap, text, presetLabel, confLevel, verification) {
  const cites = parseCitations(text);
  if (!presetLabel && !confLevel && !verification && !cites.length) return;
  const row = document.createElement("div");
  row.className = "citation-chips";
  // Real grounded verification (verify=on) takes precedence over the agent's
  // self-rating: show "verified: <verdict>" colored by the grounded confidence.
  if (verification && verification.verdict) {
    const v = document.createElement("span");
    const lvl = verification.confidence || "low";
    v.className = `cite-chip conf-chip conf-${lvl}`;
    v.title = verification.reason || "";
    v.textContent = `verified: ${verification.verdict} (${lvl})`;
    row.appendChild(v);
  } else if (confLevel) {
    const c = document.createElement("span");
    c.className = `cite-chip conf-chip conf-${confLevel}`;
    c.textContent = `confidence: ${confLevel}`;
    row.appendChild(c);
  }
  if (presetLabel) {
    const r = document.createElement("span");
    r.className = "cite-chip routed-chip";
    r.textContent = `routed: ${presetLabel}`;
    row.appendChild(r);
  }
  if (cites.length) {
    const g = document.createElement("span");
    g.className = "cite-chip grounded-chip";
    g.textContent = `✓ ${cites.length} source${cites.length > 1 ? "s" : ""}`;
    row.appendChild(g);
  }
  cites.forEach((c) => {
    const el = document.createElement(c.href ? "a" : "span");
    el.className = "cite-chip";
    el.textContent = c.label;
    if (c.href) { el.href = c.href; el.target = "_blank"; el.rel = "noopener"; }
    row.appendChild(el);
  });
  wrap.appendChild(row);
}

function appendChatMessage(role, text, meta, presetLabel, verification) {
  const list = $("#admin-chat-messages");
  if (!list) return;
  const wrap = document.createElement("div");
  wrap.className = `admin-chat-msg admin-chat-msg-${role}`;

  let displayText = text;
  let confLevel = null;
  if (role === "assistant") {
    const c = extractConfidence(text);
    displayText = c.clean;
    confLevel = c.level;
  }

  const bubble = document.createElement("div");
  bubble.className = "admin-chat-bubble";
  bubble.textContent = displayText;
  wrap.appendChild(bubble);

  if (role === "assistant") {
    renderAssistantExtras(wrap, displayText, presetLabel, confLevel, verification);
  }

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
  autoGrowChatInput();          // shrink the box back to one line
  sendBtn.disabled = true;
  setChatStatus("thinking…");

  try {
    const resp = await adminChatPost(text);
    adminConversationId = resp.conversation_id;
    const msg = resp.message || {};
    const sc = resp.self_correction;
    const meta = [
      resp.preset_id && `preset=${resp.preset_id}`,
      msg.adapter && `adapter=${msg.adapter}`,
      msg.model && `model=${msg.model}`,
      typeof resp.total_cost_usd === "number" && `cost=$${resp.total_cost_usd.toFixed(4)}`,
      sc && `self-corrected: iters=${sc.iterations}${sc.was_revised ? " ✎revised" : ""} sev=${sc.final_severity}`,
    ].filter(Boolean).join(" · ");
    let presetLabel = null;
    if (resp.preset_id) {
      const sel = $("#admin-preset-select");
      const opt = sel && Array.from(sel.options).find((o) => o.value === resp.preset_id);
      presetLabel = opt ? opt.textContent.split(" — ")[0].trim() : resp.preset_id;
      if (resp.auto_routed) presetLabel = "🧭 " + presetLabel;
    }
    appendChatMessage("assistant", msg.content || "(empty response)", meta, presetLabel, resp.verification);
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
  const input = $("#admin-chat-input");
  if (input) { input.value = ""; autoGrowChatInput(); input.focus(); }
}

// Auto-grow the chat textarea to fit its content, capped (then it scrolls).
// Cap matches the CSS max-height so the visible box and the scroll threshold
// agree.
function autoGrowChatInput() {
  const ta = $("#admin-chat-input");
  if (!ta) return;
  ta.style.height = "auto";
  ta.style.height = Math.min(ta.scrollHeight, 160) + "px";
}

// ─── expert-agent presets ──────────────────────────────────────────

let presetsLoaded = false;

async function loadPresets() {
  if (presetsLoaded) return;
  const sel = $("#admin-preset-select");
  if (!sel) return;
  try {
    const data = await apiGet("/admin/presets");
    const presets = data.presets || [];
    // Keep the "no preset" option; append each loaded preset after.
    for (const p of presets) {
      const opt = document.createElement("option");
      opt.value = p.id;
      // Render: "💻 Software Engineer — Senior engineer. Code with..."
      const desc = p.description ? ` — ${p.description}` : "";
      opt.textContent = `${p.icon || ""} ${p.name}${desc}`.trim();
      opt.title = p.system_prompt_preview || "";
      sel.appendChild(opt);
    }
    presetsLoaded = true;
  } catch (e) {
    // Non-fatal — dropdown just stays with the "no preset" default.
    if (e instanceof AuthError) {
      clearToken();
      showAuth("Token rejected.");
    }
  }
}

// ─── knowledge graph ──────────────────────────────────────────────

async function loadKgStats() {
  const line = $("#kg-status-line");
  try {
    if (line) line.textContent = "loading…";
    const stats = await apiGet("/admin/kg/stats");
    setText("kg-entity-count", stats.entity_count);
    setText("kg-relation-count", stats.relation_count_distinct);
    const totalEdges = (stats.edge_count_by_relation || [])
      .reduce((sum, r) => sum + (r.count || 0), 0);
    setText("kg-edge-count", totalEdges);

    const tbody = $("#kg-relations-table tbody");
    if (tbody) {
      tbody.replaceChildren();
      for (const row of stats.edge_count_by_relation || []) {
        const tr = document.createElement("tr");
        tr.appendChild(td(row.relation));
        tr.appendChild(td(String(row.count)));
        tbody.appendChild(tr);
      }
      if (!(stats.edge_count_by_relation || []).length) {
        const tr = document.createElement("tr");
        const cell = td("KG is empty — teach KAI a triple above, or via chat.");
        cell.colSpan = 2;
        cell.classList.add("admin-hint");
        tr.appendChild(cell);
        tbody.appendChild(tr);
      }
    }
    if (line) line.textContent = "up-to-date";
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

async function addKgTriple(ev) {
  ev.preventDefault();
  const src = ($("#kg-src").value || "").trim();
  const rel = ($("#kg-rel").value || "").trim();
  const dst = ($("#kg-dst").value || "").trim();
  if (!src || !rel || !dst) return;
  const line = $("#kg-status-line");
  try {
    if (line) line.textContent = `adding (${src} ${rel} ${dst})…`;
    await apiPost("/admin/kg/add-edge", {
      src, relation: rel, dst, approved: true,
    });
    $("#kg-src").value = ""; $("#kg-rel").value = ""; $("#kg-dst").value = "";
    if (line) line.textContent = "triple added";
    loadKgStats();
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

// ─── failures ──────────────────────────────────────────────────────

async function loadFailures() {
  const line = $("#failures-status-line");
  try {
    if (line) line.textContent = "loading…";
    const [stats, recent] = await Promise.all([
      apiGet("/admin/failures/stats"),
      apiGet("/admin/failures/recent?limit=30"),
    ]);
    setText("failures-total", stats.total_recent);

    const catBox = $("#failures-by-cat");
    if (catBox) {
      catBox.replaceChildren();
      for (const [cat, n] of Object.entries(stats.by_category || {})) {
        const chip = document.createElement("span");
        chip.className = "severity-chip low";
        chip.textContent = `${cat}: ${n}`;
        catBox.appendChild(chip);
      }
      if (!Object.keys(stats.by_category || {}).length) {
        catBox.textContent = "no failures recorded";
      }
    }

    const toolBox = $("#failures-by-tool");
    if (toolBox) {
      toolBox.replaceChildren();
      for (const [tool, n] of Object.entries(stats.by_tool || {})) {
        const row = document.createElement("div");
        row.className = "admin-stat-row";
        const a = document.createElement("span"); a.textContent = tool;
        const b = document.createElement("strong"); b.textContent = String(n);
        row.appendChild(a); row.appendChild(b);
        toolBox.appendChild(row);
      }
    }

    const tbody = $("#failures-table tbody");
    if (tbody) {
      tbody.replaceChildren();
      for (const f of recent.failures || []) {
        const tr = document.createElement("tr");
        tr.appendChild(td((f.when || "").replace("T", " ").slice(0, 19)));
        tr.appendChild(td(f.category || ""));
        tr.appendChild(td(f.tool_name || "—"));
        tr.appendChild(td(truncate(f.prompt || "", 80)));
        tr.appendChild(td(truncate(f.detail || "", 120)));
        tbody.appendChild(tr);
      }
      if (!(recent.failures || []).length) {
        const tr = document.createElement("tr");
        const c = td("no failures recorded — KAI hasn't broken anything yet");
        c.colSpan = 5; c.classList.add("admin-hint");
        tr.appendChild(c);
        tbody.appendChild(tr);
      }
    }
    if (line) line.textContent = "up-to-date";
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

// ─── research ──────────────────────────────────────────────────────

async function loadResearchStatus() {
  const line = $("#research-status-line");
  try {
    const s = await apiGet("/admin/research/status");
    const bits = [
      s.scheduler_running ? "scheduler: on" : "scheduler: off",
      `${(s.interests || []).length} interests`,
      s.telegram_enabled ? "telegram: on" : "telegram: off",
    ];
    if (line) line.textContent = bits.join(" · ");
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

async function loadResearchLatest() {
  try {
    const data = await apiGet("/admin/research/latest");
    renderResearchLatest(data.digest);
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); }
  }
}

async function loadResearchHistory() {
  try {
    const data = await apiGet("/admin/research/digests?limit=20");
    renderResearchHistory(data.digests || []);
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); }
  }
}

function renderResearchLatest(digest) {
  const card = $("#research-latest-card");
  if (!digest) {
    if (card) card.hidden = true;
    return;
  }
  if (card) card.hidden = false;

  setText("research-latest-ts",
    (digest.generated_at || "").replace("T", " ").slice(0, 19) + " UTC");

  const sev = $("#research-severity-row");
  if (sev) {
    sev.replaceChildren();
    for (const k of ["high", "medium", "low", "none"]) {
      const n = (digest.severity_counts || {})[k] || 0;
      const chip = document.createElement("span");
      chip.className = `severity-chip ${k}`;
      chip.textContent = `${k}: ${n}`;
      sev.appendChild(chip);
    }
  }

  const box = $("#research-items");
  if (box) {
    box.replaceChildren();
    let printed = 0;
    for (const src of ["hn", "arxiv", "gh_trending"]) {
      const items = (digest.top_by_source || {})[src] || [];
      for (const it of items) {
        const row = document.createElement("div");
        row.className = "research-item-row";
        const srcBadge = document.createElement("span");
        srcBadge.className = "research-item-source";
        srcBadge.textContent = src;
        const sevBadge = document.createElement("span");
        sevBadge.className = `severity-chip ${it.severity || "none"}`;
        sevBadge.textContent = (it.score ?? 0).toFixed(2);
        const link = document.createElement("a");
        link.href = it.url || "#"; link.target = "_blank"; link.rel = "noopener";
        link.textContent = it.title || "(untitled)";
        row.appendChild(srcBadge);
        row.appendChild(sevBadge);
        row.appendChild(document.createTextNode(" "));
        row.appendChild(link);
        if (it.summary) {
          const s = document.createElement("div");
          s.style.color = "var(--muted, #8a909c)";
          s.style.fontSize = "11px";
          s.style.marginTop = "2px";
          s.textContent = truncate(it.summary, 200);
          row.appendChild(s);
        }
        box.appendChild(row);
        printed++;
      }
    }
    if (printed === 0) {
      box.textContent = "no items in this digest";
    }
  }
}

function renderResearchHistory(digests) {
  const tbody = $("#research-history-table tbody");
  if (!tbody) return;
  tbody.replaceChildren();
  for (const d of digests) {
    const tr = document.createElement("tr");
    tr.appendChild(td((d.generated_at || "").replace("T", " ").slice(0, 19)));
    tr.appendChild(td(String(d.total_items_fetched ?? 0)));
    const counts = d.severity_counts || {};
    const bits = ["high", "medium", "low"]
      .map(k => `${k}: ${counts[k] ?? 0}`)
      .join(" · ");
    tr.appendChild(td(bits));
    tbody.appendChild(tr);
  }
  if (!digests.length) {
    const tr = document.createElement("tr");
    const c = td("no digests yet — click 'run now' to generate one");
    c.colSpan = 3; c.classList.add("admin-hint");
    tr.appendChild(c);
    tbody.appendChild(tr);
  }
}

async function runResearchNow() {
  const btn = $("#research-run-now");
  const line = $("#research-status-line");
  try {
    if (btn) btn.disabled = true;
    if (line) line.textContent = "running cycle (fetching HN+arXiv+GH)…";
    const result = await apiPost("/admin/research/run-now", {});
    if (line) {
      line.textContent =
        `cycle ${result.id} · fetched ${result.total_items_fetched} · ` +
        `high ${result.high_count}`;
    }
    loadResearchLatest();
    loadResearchHistory();
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Tiny helper only the new tabs use. `td()` and `setText()` already
// exist above; we reuse those.
function truncate(s, n) {
  if (!s) return "";
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

// ─── self-correction ──────────────────────────────────────────────

async function loadSelfCorrection() {
  const line = $("#sc-status-line");
  try {
    if (line) line.textContent = "loading…";
    const [stats, events] = await Promise.all([
      apiGet("/admin/self-correction/stats"),
      apiGet("/admin/self-correction/events?limit=30"),
    ]);
    setText("sc-total", stats.total_recent);
    setText("sc-revisions", stats.revisions_applied);
    setText("sc-avg-iters", stats.avg_iterations);
    setText("sc-cost",
      typeof stats.total_cost_usd === "number"
        ? `$${stats.total_cost_usd.toFixed(4)}`
        : "—");

    const sevBox = $("#sc-by-severity");
    if (sevBox) {
      sevBox.replaceChildren();
      const entries = Object.entries(stats.by_final_severity || {});
      if (!entries.length) {
        sevBox.textContent = "no events yet";
      } else {
        for (const [sev, n] of entries) {
          const chip = document.createElement("span");
          chip.className = `severity-chip ${sev === "critical" ? "high" : sev}`;
          chip.textContent = `${sev}: ${n}`;
          sevBox.appendChild(chip);
        }
      }
    }

    const tbody = $("#sc-events-table tbody");
    if (tbody) {
      tbody.replaceChildren();
      for (const ev of events.events || []) {
        const tr = document.createElement("tr");
        tr.appendChild(td((ev.ts || "").replace("T", " ").slice(0, 19)));
        tr.appendChild(td(String(ev.iterations ?? 0)));
        tr.appendChild(td(ev.was_revised ? "✎ yes" : "—"));
        tr.appendChild(td(ev.final_severity || "none"));
        tr.appendChild(td(truncate(ev.user_message || "", 100)));
        tbody.appendChild(tr);
      }
      if (!(events.events || []).length) {
        const tr = document.createElement("tr");
        const c = td("no events yet — opt in via the self-correct checkbox in chat");
        c.colSpan = 5; c.classList.add("admin-hint");
        tr.appendChild(c);
        tbody.appendChild(tr);
      }
    }
    if (line) line.textContent = "up-to-date";
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
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

// ─── planning ──────────────────────────────────────────────────────

let planningSelectedId = null;

async function loadPlanning() {
  await Promise.all([loadPlanningStats(), loadPlanningList()]);
  if (planningSelectedId) loadPlanningDetail(planningSelectedId);
}

async function loadPlanningStats() {
  const line = $("#planning-status-line");
  try {
    const s = await apiGet("/admin/planning/stats");
    if (line) {
      line.textContent =
        `${s.total} plan(s) · ${s.active} active · ${s.blocked} blocked · ${s.done} done`;
    }
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

async function loadPlanningList() {
  const tbody = $("#planning-list-table tbody");
  if (!tbody) return;
  try {
    const data = await apiGet("/admin/planning/list?limit=100");
    tbody.replaceChildren();
    for (const p of data.plans || []) {
      const tr = document.createElement("tr");
      tr.className = "admin-row-clickable";
      if (p.id === planningSelectedId) tr.classList.add("is-active");
      tr.appendChild(td(`#${p.id}`));
      tr.appendChild(td(truncate(p.title, 48)));
      const stc = td(""); stc.appendChild(planStatusChip(p.status)); tr.appendChild(stc);
      tr.addEventListener("click", () => selectPlan(p.id));
      tbody.appendChild(tr);
    }
    if (!(data.plans || []).length) {
      const tr = document.createElement("tr");
      const c = td("no plans yet — propose one above");
      c.colSpan = 3; c.classList.add("admin-hint");
      tr.appendChild(c); tbody.appendChild(tr);
    }
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); }
  }
}

function selectPlan(id) {
  planningSelectedId = id;
  loadPlanningList();          // re-highlight the selected row
  loadPlanningDetail(id);
}

async function loadPlanningDetail(id) {
  const box = $("#planning-detail");
  if (!box) return;
  try {
    const data = await apiGet(`/admin/planning/${id}`);
    renderPlanDetail(box, data.plan, data.recent_runs || []);
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    box.replaceChildren();
    const h = document.createElement("p");
    h.className = "admin-hint"; h.textContent = `error: ${e.message}`;
    box.appendChild(h);
  }
}

function renderPlanDetail(box, plan, runs) {
  box.replaceChildren();
  const h = document.createElement("h2");
  h.textContent = `#${plan.id} ${plan.title}`;
  box.appendChild(h);
  const statusP = document.createElement("p");
  statusP.appendChild(planStatusChip(plan.status));
  box.appendChild(statusP);

  const actions = document.createElement("div");
  actions.className = "admin-chat-tools";
  const canApprove = plan.status === "draft" || plan.status === "blocked";
  const canExecute = plan.status === "approved" || plan.status === "executing";
  const canRevise = plan.status === "blocked";
  actions.appendChild(planActionBtn("Approve", canApprove, () => doPlanAction(plan.id, "approve")));
  actions.appendChild(planActionBtn("Execute next step", canExecute, () => doPlanAction(plan.id, "execute-next")));
  actions.appendChild(planActionBtn("Propose revision", canRevise, () => doPlanRevise(plan.id)));
  box.appendChild(actions);

  const stepTbl = document.createElement("table");
  stepTbl.className = "admin-table";
  stepTbl.appendChild(tableHead(["#", "action", "kind", "status", "branch"]));
  const sb = document.createElement("tbody");
  for (const s of plan.steps || []) {
    const tr = document.createElement("tr");
    tr.appendChild(td(String(s.seq)));
    tr.appendChild(td(s.action));
    tr.appendChild(td(s.kind + (s.tool_name ? `:${s.tool_name}` : "")));
    const stc = td(""); stc.appendChild(stepStatusChip(s.status)); tr.appendChild(stc);
    const branch = s.on_fail ? `fail→${s.on_fail}` : (s.on_done ? `done→${s.on_done}` : "—");
    tr.appendChild(td(branch));
    sb.appendChild(tr);
  }
  stepTbl.appendChild(sb);
  box.appendChild(stepTbl);

  if (runs.length) {
    const rh = document.createElement("h2"); rh.textContent = "Run history";
    box.appendChild(rh);
    const rt = document.createElement("table"); rt.className = "admin-table";
    rt.appendChild(tableHead(["step", "status", "output / error"]));
    const rb = document.createElement("tbody");
    for (const r of runs) {
      const tr = document.createElement("tr");
      tr.appendChild(td(`#${r.seq}`));
      tr.appendChild(td(r.status));
      tr.appendChild(td(truncate(r.error || r.output || "", 140)));
      rb.appendChild(tr);
    }
    rt.appendChild(rb); box.appendChild(rt);
  }

  const rev = document.createElement("div");
  rev.id = "planning-revision"; box.appendChild(rev);
}

function planActionBtn(label, enabled, handler) {
  const b = document.createElement("button");
  b.type = "button"; b.className = "admin-btn"; b.textContent = label;
  b.disabled = !enabled;
  if (enabled) b.addEventListener("click", handler);
  return b;
}

async function doPlanAction(id, action) {
  const line = $("#planning-status-line");
  try {
    if (line) line.textContent = `${action}…`;
    const out = await apiPost(`/admin/planning/${id}/${action}`, { approved: true });
    if (action === "execute-next" && out.result && line) {
      line.textContent = out.result.note || "step run";
    }
    await loadPlanningStats();
    await loadPlanningList();
    loadPlanningDetail(id);
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

async function doPlanRevise(id) {
  const line = $("#planning-status-line");
  try {
    if (line) line.textContent = "proposing revision…";
    const out = await apiPost(`/admin/planning/${id}/revise`, { approved: true });
    renderRevisionProposal(out);
    if (line) line.textContent = "revision proposed — review below";
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

function renderRevisionProposal(out) {
  const box = $("#planning-revision");
  if (!box) return;
  box.replaceChildren();
  const h = document.createElement("h2"); h.textContent = "Proposed revision";
  box.appendChild(h);
  const d = document.createElement("p");
  d.className = "admin-hint"; d.textContent = out.diagnosis || "";
  box.appendChild(d);
  const ol = document.createElement("ol");
  for (const s of out.proposed_steps || []) {
    const li = document.createElement("li"); li.textContent = s.action;
    ol.appendChild(li);
  }
  box.appendChild(ol);
  if ((out.proposed_steps || []).length) {
    const apply = document.createElement("button");
    apply.type = "button"; apply.className = "admin-btn";
    apply.textContent = "Apply revision (replace steps)";
    apply.addEventListener("click", () => applyRevision(out.plan_id, out.proposed_steps));
    box.appendChild(apply);
  }
}

async function applyRevision(id, steps) {
  const line = $("#planning-status-line");
  try {
    await apiPost(`/admin/planning/${id}/steps`, { steps, approved: true });
    await loadPlanningList();
    loadPlanningDetail(id);
    if (line) line.textContent = "revision applied — re-approve to run";
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

async function createPlan(ev) {
  if (ev) ev.preventDefault();
  const goal = ($("#planning-goal").value || "").trim();
  const title = ($("#planning-title").value || "").trim();
  const line = $("#planning-status-line");
  if (!goal) { if (line) line.textContent = "enter a goal first"; return; }
  const btn = $("#planning-create-btn");
  const old = btn ? btn.textContent : "";
  try {
    if (btn) { btn.disabled = true; btn.textContent = "proposing…"; }
    const out = await apiPost("/admin/planning/create", {
      goal, title: title || null, approved: true,
    });
    $("#planning-goal").value = ""; $("#planning-title").value = "";
    await loadPlanningStats();
    await loadPlanningList();
    if (out.plan && out.plan.id) selectPlan(out.plan.id);
    if (line) {
      line.textContent =
        `plan #${out.plan.id} drafted (${(out.plan.steps || []).length} steps) — review & approve`;
    }
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

async function remediatePlans() {
  const line = $("#planning-status-line");
  const btn = $("#planning-remediate-btn");
  const old = btn ? btn.textContent : "";
  try {
    if (btn) { btn.disabled = true; btn.textContent = "scanning…"; }
    const out = await apiPost("/admin/planning/remediate", { max_plans: 2, approved: true });
    await loadPlanningStats();
    await loadPlanningList();
    const plans = out.proposed_plans || [];
    if (plans.length && plans[0].plan_id) selectPlan(plans[0].plan_id);
    if (line) line.textContent = out.note || `proposed ${plans.length} plan(s)`;
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

async function scoutIntegrate(e) {
  if (e) e.preventDefault();
  const line = $("#planning-status-line");
  const btn = $("#planning-integrate-btn");
  const input = $("#planning-capability");
  const capability = input ? input.value.trim() : "";
  if (!capability) {
    if (line) line.textContent = "enter a capability to scout";
    return;
  }
  const old = btn ? btn.textContent : "";
  try {
    if (btn) { btn.disabled = true; btn.textContent = "scouting…"; }
    const out = await apiPost("/admin/planning/scout-integrate", {
      capability, max_plans: 1, approved: true,
    });
    await loadPlanningStats();
    await loadPlanningList();
    const plans = out.proposed_plans || [];
    if (plans.length && plans[0].plan_id) selectPlan(plans[0].plan_id);
    if (line) line.textContent = out.note || `proposed ${plans.length} plan(s)`;
    if (input && plans.length) input.value = "";
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

function planStatusChip(status) {
  const span = document.createElement("span");
  span.className = `severity-chip plan-${status}`;
  span.textContent = status;
  return span;
}

function stepStatusChip(status) {
  const span = document.createElement("span");
  span.className = `severity-chip step-${status}`;
  span.textContent = status;
  return span;
}

// Build a <thead> from column labels using textContent (no innerHTML) so the
// dashboard stays XSS-safe by construction.
function tableHead(cols) {
  const thead = document.createElement("thead");
  const tr = document.createElement("tr");
  for (const c of cols) {
    const th = document.createElement("th");
    th.textContent = c;
    tr.appendChild(th);
  }
  thead.appendChild(tr);
  return thead;
}

// ─── browser (computer-control) ──────────────────────────────────────

async function loadBrowser() {
  await Promise.all([loadBrowserStatus(), loadBrowserLog()]);
}

async function loadBrowserStatus() {
  const line = $("#browser-status-line");
  const box = $("#browser-config");
  try {
    const s = await apiGet("/admin/browser/status");
    if (line) {
      line.textContent = s.enabled
        ? `enabled · ${(s.allowlist || []).length} allowlisted · ${s.stats.total} action(s)`
        : "disabled (KAI_BROWSER_ENABLED off)";
    }
    if (box) {
      box.replaceChildren();
      const chip = (label, val) => {
        const span = document.createElement("span");
        span.className = "severity-chip";
        span.textContent = `${label}: ${val}`;
        return span;
      };
      box.appendChild(chip("enabled", s.enabled ? "yes" : "no"));
      box.appendChild(chip("headless", s.headless ? "yes" : "no"));
      box.appendChild(chip("allowlist", (s.allowlist || []).join(", ") || "(empty)"));
    }
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

async function loadBrowserLog() {
  const tbody = $("#browser-log-table tbody");
  if (!tbody) return;
  try {
    const data = await apiGet("/admin/browser/log?limit=100");
    tbody.replaceChildren();
    for (const a of data.actions || []) {
      const tr = document.createElement("tr");
      tr.appendChild(td((a.ts || "").replace("T", " ").slice(0, 19)));
      tr.appendChild(td(a.kind || ""));
      tr.appendChild(td(a.status || ""));
      tr.appendChild(td(truncate(a.url || "", 50)));
      tr.appendChild(td(truncate(a.detail || "", 80)));
      tbody.appendChild(tr);
    }
    if (!(data.actions || []).length) {
      const tr = document.createElement("tr");
      const c = td("no actions yet"); c.colSpan = 5; c.classList.add("admin-hint");
      tr.appendChild(c); tbody.appendChild(tr);
    }
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); }
  }
}

async function browserNavigate(ev) {
  if (ev) ev.preventDefault();
  const url = ($("#browser-url").value || "").trim();
  const line = $("#browser-status-line");
  const out = $("#browser-result");
  if (!url) { if (line) line.textContent = "enter a URL"; return; }
  const btn = $("#browser-nav-btn");
  const old = btn ? btn.textContent : "";
  try {
    if (btn) { btn.disabled = true; btn.textContent = "reading…"; }
    const data = await apiPost("/admin/browser/navigate", { url });
    renderBrowserResult(out, data.result);
    if (line) line.textContent = "read ok";
    loadBrowserLog();
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (out) {
      out.replaceChildren();
      const p = document.createElement("p");
      p.className = "admin-err"; p.textContent = e.message;
      out.appendChild(p);
    }
    if (line) line.textContent = "blocked / error";
    loadBrowserLog();
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

// NB: external page content is rendered with textContent ONLY (never
// innerHTML) so a malicious allowlisted page can't inject markup/script
// into the operator dashboard.
function renderBrowserResult(box, result) {
  if (!box) return;
  box.replaceChildren();
  if (!result) return;
  const h = document.createElement("h3");
  h.textContent = result.title || "(no title)";
  box.appendChild(h);
  const u = document.createElement("p");
  u.className = "admin-hint"; u.textContent = result.url || "";
  box.appendChild(u);
  const pre = document.createElement("pre");
  pre.className = "admin-pre";
  pre.textContent = (result.text || "").slice(0, 2000);
  box.appendChild(pre);
  if ((result.links || []).length) {
    const lh = document.createElement("p");
    lh.className = "admin-hint";
    lh.textContent = `${result.links.length} link(s):`;
    box.appendChild(lh);
    const ul = document.createElement("ul");
    for (const l of result.links.slice(0, 20)) {
      const li = document.createElement("li");
      li.textContent = `${(l.text || "").slice(0, 60)} — ${l.href || ""}`;
      ul.appendChild(li);
    }
    box.appendChild(ul);
  }
}

// Envelope B: execute a write sequence (operator-approved). External page
// content rendered via textContent only (no innerHTML).
async function browserExecute(ev) {
  if (ev) ev.preventDefault();
  const url = ($("#browser-exec-url").value || "").trim();
  const raw = ($("#browser-exec-actions").value || "").trim();
  const line = $("#browser-status-line");
  const out = $("#browser-exec-result");
  const showErr = (msg) => {
    if (!out) return;
    out.replaceChildren();
    const p = document.createElement("p");
    p.className = "admin-err"; p.textContent = msg;
    out.appendChild(p);
  };
  if (!url) { if (line) line.textContent = "enter a URL"; return; }
  let actions;
  try {
    actions = JSON.parse(raw);
    if (!Array.isArray(actions)) throw new Error("actions must be a JSON array");
  } catch (e) {
    showErr("bad actions JSON: " + e.message);
    return;
  }
  const btn = $("#browser-exec-btn");
  const old = btn ? btn.textContent : "";
  try {
    if (btn) { btn.disabled = true; btn.textContent = "executing…"; }
    const data = await apiPost("/admin/browser/execute", { url, actions, approved: true });
    if (out) {
      out.replaceChildren();
      const h = document.createElement("p");
      h.className = "admin-hint";
      h.textContent = "executed → " + ((data.final && data.final.url) || "");
      out.appendChild(h);
      const ul = document.createElement("ul");
      for (const r of data.results || []) {
        const li = document.createElement("li");
        li.textContent = `${r.ok ? "✓" : "✕"} ${r.type} ${r.selector}` +
          (r.ok ? "" : ` — ${r.error || "failed"}`);
        ul.appendChild(li);
      }
      out.appendChild(ul);
      const bn = data.blocked_navigations || [];
      if (bn.length) {
        const w = document.createElement("p");
        w.className = "admin-err";
        w.textContent = "⛔ blocked off-allowlist navigation: " +
          bn.map((x) => x.url).join(", ");
        out.appendChild(w);
      }
    }
    if (line) line.textContent = "executed";
    loadBrowserLog();
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    showErr(e.message);
    if (line) line.textContent = "error";
    loadBrowserLog();
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

// ─── learning (continuous learning) ──────────────────────────────────

async function loadLearning() {
  await Promise.all([loadLearningStats(), loadLearningLessons(), loadLearningFeedback()]);
}

async function loadLearningStats() {
  const line = $("#learning-status-line");
  const box = $("#learning-stats");
  try {
    const s = await apiGet("/admin/learning/stats");
    if (line) {
      line.textContent = `${s.feedback_total} feedback · ${s.active_lessons} active lesson(s)`;
    }
    if (box) {
      box.replaceChildren();
      const chip = (label, val) => {
        const e = document.createElement("span");
        e.className = "severity-chip";
        e.textContent = `${label}: ${val}`;
        return e;
      };
      const fb = s.feedback_by_rating || {};
      const lp = s.lessons_by_status || {};
      box.appendChild(chip("👍", fb.up || 0));
      box.appendChild(chip("👎", fb.down || 0));
      box.appendChild(chip("proposed", lp.proposed || 0));
      box.appendChild(chip("active", lp.active || 0));
    }
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

async function loadLearningLessons() {
  const tbody = $("#learning-lessons-table tbody");
  if (!tbody) return;
  try {
    const data = await apiGet("/admin/learning/lessons?limit=100");
    tbody.replaceChildren();
    for (const L of data.lessons || []) {
      const tr = document.createElement("tr");
      tr.appendChild(td(`#${L.id}`));
      tr.appendChild(td(L.text));
      const st = td(""); st.appendChild(lessonChip(L.status)); tr.appendChild(st);
      const act = td("");
      if (L.status === "proposed") {
        act.appendChild(lessonBtn("✓ activate", () => lessonAction(L.id, "activate")));
        act.appendChild(lessonBtn("✕ dismiss", () => lessonAction(L.id, "dismiss")));
      } else if (L.status === "active") {
        act.appendChild(lessonBtn("✕ dismiss", () => lessonAction(L.id, "dismiss")));
      }
      tr.appendChild(act);
      tbody.appendChild(tr);
    }
    if (!(data.lessons || []).length) {
      const tr = document.createElement("tr");
      const c = td("no lessons yet — add feedback, then ⚗ synthesize");
      c.colSpan = 4; c.classList.add("admin-hint");
      tr.appendChild(c); tbody.appendChild(tr);
    }
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); }
  }
}

async function loadLearningFeedback() {
  const tbody = $("#learning-fb-table tbody");
  if (!tbody) return;
  try {
    const data = await apiGet("/admin/learning/feedback?limit=50");
    tbody.replaceChildren();
    for (const f of data.feedback || []) {
      const tr = document.createElement("tr");
      tr.appendChild(td(f.rating === "up" ? "👍" : "👎"));
      tr.appendChild(td(truncate(f.note || "", 90)));
      tbody.appendChild(tr);
    }
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); }
  }
}

function lessonChip(status) {
  const e = document.createElement("span");
  e.className = `severity-chip lesson-${status}`;
  e.textContent = status;
  return e;
}

function lessonBtn(label, handler) {
  const b = document.createElement("button");
  b.type = "button"; b.className = "admin-btn"; b.textContent = label;
  b.addEventListener("click", handler);
  return b;
}

async function lessonAction(id, action) {
  const line = $("#learning-status-line");
  try {
    if (line) line.textContent = `${action}…`;
    await apiPost(`/admin/learning/lessons/${id}/${action}`, { approved: true });
    await loadLearningStats();
    loadLearningLessons();
    if (line) line.textContent = `lesson ${action}d`;
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

async function addFeedback(ev) {
  if (ev) ev.preventDefault();
  const rating = $("#learning-fb-rating").value;
  const note = ($("#learning-fb-note").value || "").trim();
  const line = $("#learning-status-line");
  try {
    await apiPost("/admin/learning/feedback", { rating, note });
    $("#learning-fb-note").value = "";
    await loadLearningStats();
    loadLearningFeedback();
    if (line) line.textContent = "feedback added";
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

async function synthesizeLessons() {
  const line = $("#learning-status-line");
  const btn = $("#learning-synthesize");
  const old = btn ? btn.textContent : "";
  try {
    if (btn) { btn.disabled = true; btn.textContent = "synthesizing…"; }
    const out = await apiPost("/admin/learning/synthesize", { max_lessons: 5, approved: true });
    if (line) line.textContent = out.note || `proposed ${(out.proposed || []).length}`;
    await loadLearningStats();
    loadLearningLessons();
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

async function reviewLessons() {
  const line = $("#learning-status-line");
  const btn = $("#learning-review-btn");
  const box = $("#learning-review");
  const old = btn ? btn.textContent : "";
  try {
    if (btn) { btn.disabled = true; btn.textContent = "reviewing…"; }
    const out = await apiGet("/admin/learning/review");
    renderLearningReview(box, out);
    if (line) {
      const n = (out.recommend_retire || []).length;
      line.textContent = `${out.summary.active_lessons} active lesson(s) · ${n} suggested for retirement`;
    }
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

function renderLearningReview(box, out) {
  if (!box) return;
  box.textContent = "";
  const rows = out.evaluated || [];
  if (!rows.length) {
    const p = document.createElement("p");
    p.className = "admin-hint";
    p.textContent = "No active lessons to review yet.";
    box.appendChild(p);
    return;
  }
  const pct = (v) => (v === null || v === undefined) ? "—" : `${Math.round(v * 100)}%`;
  const tbl = document.createElement("table");
  tbl.className = "admin-table";
  const thead = document.createElement("thead");
  const htr = document.createElement("tr");
  ["#", "lesson", "verdict", "👎 before→after", ""].forEach((h) => {
    const th = document.createElement("th"); th.textContent = h; htr.appendChild(th);
  });
  thead.appendChild(htr);
  tbl.appendChild(thead);
  const tb = document.createElement("tbody");
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    tr.appendChild(td(`#${r.id}`));
    tr.appendChild(td(truncate(r.text, 56)));
    tr.appendChild(td(r.verdict));
    tr.appendChild(td(`${pct(r.down_rate_before)}→${pct(r.down_rate_after)}`));
    tr.appendChild(td(r.recommend_retire ? "⚠ review for retirement" : "keep"));
    tb.appendChild(tr);
  });
  tbl.appendChild(tb);
  box.appendChild(tbl);
  const cap = document.createElement("p");
  cap.className = "admin-hint";
  cap.textContent = out.caveat || "";
  box.appendChild(cap);
}

// ─── twin (digital twin) ──────────────────────────────────────────────

async function loadTwin() {
  await Promise.all([loadTwinStats(), loadTwinProfile()]);
}

async function loadTwinStats() {
  const line = $("#twin-status-line");
  const box = $("#twin-stats");
  try {
    const s = await apiGet("/admin/twin/stats");
    if (line) line.textContent = `${s.active_entries} active entry(ies) · ${s.drafts} draft(s)`;
    if (box) {
      box.replaceChildren();
      const chip = (l, v) => {
        const e = document.createElement("span");
        e.className = "severity-chip"; e.textContent = `${l}: ${v}`;
        return e;
      };
      const sec = s.active_by_section || {};
      for (const k of ["identity", "voice", "values", "preferences", "goals"]) {
        box.appendChild(chip(k, sec[k] || 0));
      }
    }
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

async function loadTwinProfile() {
  const tbody = $("#twin-profile-table tbody");
  if (!tbody) return;
  try {
    const data = await apiGet("/admin/twin/profile?limit=200");
    tbody.replaceChildren();
    let shown = 0;
    for (const en of data.entries || []) {
      if (en.status === "archived") continue;
      shown++;
      const tr = document.createElement("tr");
      tr.appendChild(td(en.section));
      tr.appendChild(td(en.text));
      const st = td(""); st.appendChild(twinChip(en.status)); tr.appendChild(st);
      const act = td("");
      if (en.status === "proposed") {
        act.appendChild(lessonBtn("✓ activate", () => twinEntryAction(en.id, "activate")));
      }
      act.appendChild(lessonBtn("✕ archive", () => twinEntryAction(en.id, "archive")));
      tr.appendChild(act);
      tbody.appendChild(tr);
    }
    if (!shown) {
      const tr = document.createElement("tr");
      const c = td("no profile yet — add entries or ⚗ suggest from KG");
      c.colSpan = 4; c.classList.add("admin-hint");
      tr.appendChild(c); tbody.appendChild(tr);
    }
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); }
  }
}

function twinChip(status) {
  const e = document.createElement("span");
  e.className = `severity-chip twin-${status}`;
  e.textContent = status;
  return e;
}

async function twinEntryAction(id, action) {
  const line = $("#twin-status-line");
  try {
    if (line) line.textContent = `${action}…`;
    await apiPost(`/admin/twin/entries/${id}/${action}`, { approved: true });
    await loadTwinStats();
    loadTwinProfile();
    if (line) line.textContent = `entry ${action}d`;
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

async function addTwinEntry(ev) {
  if (ev) ev.preventDefault();
  const section = $("#twin-entry-section").value;
  const text = ($("#twin-entry-text").value || "").trim();
  const line = $("#twin-status-line");
  if (!text) { if (line) line.textContent = "enter some text"; return; }
  try {
    await apiPost("/admin/twin/entries", { section, text });
    $("#twin-entry-text").value = "";
    await loadTwinStats();
    loadTwinProfile();
    if (line) line.textContent = "entry added";
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

async function suggestTwin() {
  const line = $("#twin-status-line");
  const btn = $("#twin-suggest");
  const old = btn ? btn.textContent : "";
  try {
    if (btn) { btn.disabled = true; btn.textContent = "suggesting…"; }
    const out = await apiPost("/admin/twin/suggest", { max_entries: 8, approved: true });
    if (line) line.textContent = out.note || `proposed ${(out.proposed || []).length}`;
    await loadTwinStats();
    loadTwinProfile();
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

async function draftAsOperator(ev) {
  if (ev) ev.preventDefault();
  const task = ($("#twin-draft-task").value || "").trim();
  const line = $("#twin-status-line");
  const out = $("#twin-draft-result");
  if (!task) { if (line) line.textContent = "enter a task"; return; }
  const btn = $("#twin-draft-btn");
  const old = btn ? btn.textContent : "";
  try {
    if (btn) { btn.disabled = true; btn.textContent = "drafting…"; }
    const data = await apiPost("/admin/twin/draft", { task });
    if (out) {
      out.replaceChildren();
      const lbl = document.createElement("p");
      lbl.className = "admin-hint";
      lbl.textContent = "DRAFT (review before using — KAI does not send it):";
      out.appendChild(lbl);
      const pre = document.createElement("pre");
      pre.className = "admin-pre";
      pre.textContent = data.draft || "(empty)";
      out.appendChild(pre);
    }
    if (line) line.textContent = data.note || "drafted";
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (out) {
      out.replaceChildren();
      const p = document.createElement("p");
      p.className = "admin-err"; p.textContent = e.message;
      out.appendChild(p);
    }
    if (line) line.textContent = "error";
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

async function decideAsOperator(ev) {
  if (ev) ev.preventDefault();
  const question = ($("#twin-decide-question").value || "").trim();
  const line = $("#twin-status-line");
  const out = $("#twin-decide-result");
  if (!question) { if (line) line.textContent = "enter a decision"; return; }
  const btn = $("#twin-decide-btn");
  const old = btn ? btn.textContent : "";
  try {
    if (btn) { btn.disabled = true; btn.textContent = "predicting…"; }
    const data = await apiPost("/admin/twin/decide", { question });
    if (out) {
      out.replaceChildren();
      const lbl = document.createElement("p");
      lbl.className = "admin-hint";
      lbl.textContent = "ADVISORY prediction — KAI's guess at YOUR call. Nothing is executed.";
      out.appendChild(lbl);
      const dec = document.createElement("p");
      dec.innerHTML = "";
      const strong = document.createElement("strong");
      strong.textContent = data.decision || "(no decision)";
      dec.appendChild(strong);
      const conf = document.createElement("span");
      conf.className = "admin-hint";
      conf.textContent = `  · confidence: ${data.confidence || "?"}`;
      dec.appendChild(conf);
      out.appendChild(dec);
      if (data.rationale) {
        const pre = document.createElement("pre");
        pre.className = "admin-pre";
        pre.textContent = data.rationale;
        out.appendChild(pre);
      }
      if (Array.isArray(data.caveats) && data.caveats.length) {
        const cap = document.createElement("p");
        cap.className = "admin-hint";
        cap.textContent = "caveats: " + data.caveats.join("; ");
        out.appendChild(cap);
      }
    }
    if (line) line.textContent = data.note || "predicted";
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (out) {
      out.replaceChildren();
      const p = document.createElement("p");
      p.className = "admin-err"; p.textContent = e.message;
      out.appendChild(p);
    }
    if (line) line.textContent = "error";
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

// ─── audit (KAI self-audit) ──────────────────────────────────────────

function auditChip(v) {
  const e = document.createElement("span");
  e.className = "severity-chip " + (v === true ? "low" : (v === false ? "high" : ""));
  e.textContent = v === true ? "on" : (v === false ? "off" : "n/a");
  return e;
}

async function loadAudit() {
  const line = $("#audit-status-line");
  try {
    if (line) line.textContent = "auditing…";
    const a = await apiGet("/admin/audit/run");
    const s = a.summary || {};
    const rt = a.runtime || {};
    if (line) {
      line.textContent =
        `${s.scoped_enabled}/${s.scoped_total} scoped features ON · ${s.total_records} records`;
    }
    const rtbox = $("#audit-runtime");
    if (rtbox) {
      rtbox.replaceChildren();
      const chip = (l, v) => {
        const e = document.createElement("span");
        e.className = "severity-chip"; e.textContent = `${l}: ${v}`;
        return e;
      };
      rtbox.appendChild(chip("OpenAI key", rt.openai_key_set ? "yes" : "no"));
      rtbox.appendChild(chip("Anthropic key", rt.anthropic_key_set ? "yes" : "no"));
      rtbox.appendChild(chip("browser", rt.browser_enabled ? "on" : "off"));
      rtbox.appendChild(chip("browser writes", rt.browser_write_enabled ? "on" : "off"));
    }
    const tb = $("#audit-subs-table tbody");
    if (tb) {
      tb.replaceChildren();
      for (const x of a.subsystems || []) {
        const tr = document.createElement("tr");
        tr.appendChild(td(x.name));
        tr.appendChild(td(x.scope || "—"));
        const on = td(""); on.appendChild(auditChip(x.scope_enabled)); tr.appendChild(on);
        tr.appendChild(td(String(x.records)));
        tb.appendChild(tr);
      }
    }
    const ul = $("#audit-issues");
    if (ul) {
      ul.replaceChildren();
      for (const i of a.issues || []) {
        const li = document.createElement("li");
        li.textContent = i;
        ul.appendChild(li);
      }
      if (!(a.issues || []).length) {
        const li = document.createElement("li");
        li.className = "admin-hint"; li.textContent = "no issues 🎉";
        ul.appendChild(li);
      }
    }
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  }
}

// ─── operator digest (Brief tab) ─────────────────────────────────────

async function loadDigestLatest() {
  try {
    const d = await apiGet("/admin/digest/latest");
    const out = $("#digest-output");
    if (out && d.digest) out.textContent = d.digest.digest || "";
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); }
  }
}

async function runDigest() {
  const line = $("#digest-status-line");
  const out = $("#digest-output");
  const btn = $("#digest-run");
  const old = btn ? btn.textContent : "";
  try {
    if (btn) { btn.disabled = true; btn.textContent = "synthesizing…"; }
    const d = await apiPost("/admin/digest/run", { deliver: true, approved: true });
    if (out) out.textContent = d.digest || "";
    if (line) line.textContent = d.sent ? "sent to Telegram ✓" : "generated (Telegram not sent)";
  } catch (e) {
    if (e instanceof AuthError) { clearToken(); showAuth("Token rejected."); return; }
    if (line) line.textContent = `error: ${e.message}`;
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = old; }
  }
}

// ─── boot ──────────────────────────────────────────────────────────

// ── Dashboard version watcher ───────────────────────────────────────
// The dashboard is a single static page; switching tabs is client-side, so
// an already-open dashboard never re-fetches admin.html and silently runs a
// stale build after a deploy (you ship a feature, the open tab doesn't show
// it until a manual reload). We detect that: each asset is stamped
// ?v=ts-<mtime> by scripts/stamp_static_assets.py, and GET /version reports
// admin.js's current mtime as `build`. If the server's build is newer than
// the one we loaded with, show a one-click reload bar. Fail-safe: any
// parse/fetch hiccup just skips the check (never a false "reload" prompt).
const LOADED_BUILD = (() => {
  // Max of the ?v=ts-<mtime> stamps we loaded for the dashboard's own assets
  // (admin.js + admin.css), so a CSS-only deploy also triggers the banner.
  // Mirrors _dashboard_build() on the server — same max, so they're equal at
  // rest and diverge only when a file actually changes (no false positives).
  const stamps = [];
  for (const sel of ['script[src*="admin.js"]', 'link[href*="admin.css"]']) {
    const el = document.querySelector(sel);
    const attr = el && (el.getAttribute("src") || el.getAttribute("href"));
    const m = attr && attr.match(/[?&]v=ts-(\d+)/);
    if (m) stamps.push(parseInt(m[1], 10));
  }
  return stamps.length ? Math.max(...stamps) : null;
})();
let _reloadBannerShown = false;

async function checkDashboardVersion() {
  if (!LOADED_BUILD || _reloadBannerShown) return;
  try {
    const r = await fetch("/version", { cache: "no-store" });
    if (!r.ok) return;
    const data = await r.json();
    if (typeof data.build === "number" && data.build > LOADED_BUILD) {
      showReloadBanner();
    }
  } catch (_e) {
    /* offline / transient — try again on the next tick */
  }
}

function showReloadBanner() {
  if (_reloadBannerShown) return;
  _reloadBannerShown = true;
  const bar = document.createElement("div");
  bar.id = "kai-reload-banner";
  bar.style.cssText =
    "position:fixed;top:0;left:0;right:0;z-index:9999;background:#1d4ed8;" +
    "color:#fff;font:600 14px/1.4 system-ui,sans-serif;padding:10px 16px;" +
    "display:flex;align-items:center;gap:12px;box-shadow:0 2px 8px rgba(0,0,0,.3)";
  const msg = document.createElement("span");
  msg.textContent = "🔄 A newer dashboard version is available.";
  msg.style.flex = "1";
  const reload = document.createElement("button");
  reload.textContent = "Reload now";
  reload.style.cssText =
    "background:#fff;color:#1d4ed8;border:0;border-radius:6px;padding:6px 14px;" +
    "font-weight:700;cursor:pointer";
  reload.addEventListener("click", () => location.reload());
  const dismiss = document.createElement("button");
  dismiss.textContent = "✕";
  dismiss.title = "Dismiss";
  dismiss.style.cssText =
    "background:transparent;color:#fff;border:0;font-size:16px;cursor:pointer";
  dismiss.addEventListener("click", () => bar.remove());
  bar.append(msg, reload, dismiss);
  document.body.prepend(bar);
}

function initVersionWatcher() {
  // Check on load, when the tab regains focus, and on a slow background poll.
  checkDashboardVersion();
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") checkDashboardVersion();
  });
  setInterval(checkDashboardVersion, 90_000);
}

document.addEventListener("DOMContentLoaded", () => {
  initVersionWatcher();

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

  // Enter sends; Shift+Enter inserts a newline. (isComposing guards IME so
  // confirming a candidate doesn't fire a send.) The input auto-grows as you
  // type up to a few lines, then scrolls.
  const chatInput = $("#admin-chat-input");
  if (chatInput) {
    chatInput.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
        ev.preventDefault();
        sendChat();
      }
    });
    chatInput.addEventListener("input", autoGrowChatInput);
  }

  // Supreme scanner
  $("#supreme-scan-now").addEventListener("click", runSupremeScan);

  // Daily Brief
  $("#brief-generate-now").addEventListener("click", generateBrief);
  const digestRun = $("#digest-run");
  if (digestRun) digestRun.addEventListener("click", runDigest);

  // Knowledge graph
  const kgRefresh = $("#kg-refresh");
  if (kgRefresh) kgRefresh.addEventListener("click", loadKgStats);
  const kgForm = $("#kg-add-form");
  if (kgForm) kgForm.addEventListener("submit", addKgTriple);

  // Failures
  const failRefresh = $("#failures-refresh");
  if (failRefresh) failRefresh.addEventListener("click", loadFailures);

  // Research
  const researchRun = $("#research-run-now");
  if (researchRun) researchRun.addEventListener("click", runResearchNow);

  // Self-Correction
  const scRefresh = $("#sc-refresh");
  if (scRefresh) scRefresh.addEventListener("click", loadSelfCorrection);

  // Planning
  const planRefresh = $("#planning-refresh");
  if (planRefresh) planRefresh.addEventListener("click", loadPlanning);
  const planRemediate = $("#planning-remediate-btn");
  if (planRemediate) planRemediate.addEventListener("click", remediatePlans);
  const planForm = $("#planning-create-form");
  if (planForm) planForm.addEventListener("submit", createPlan);
  const planIntegrate = $("#planning-integrate-form");
  if (planIntegrate) planIntegrate.addEventListener("submit", scoutIntegrate);

  // Browser (computer-control)
  const browserRefresh = $("#browser-refresh");
  if (browserRefresh) browserRefresh.addEventListener("click", loadBrowser);
  const browserForm = $("#browser-nav-form");
  if (browserForm) browserForm.addEventListener("submit", browserNavigate);
  const browserExecForm = $("#browser-exec-form");
  if (browserExecForm) browserExecForm.addEventListener("submit", browserExecute);

  // Learning (continuous learning)
  const learnRefresh = $("#learning-refresh");
  if (learnRefresh) learnRefresh.addEventListener("click", loadLearning);
  const learnSynth = $("#learning-synthesize");
  if (learnSynth) learnSynth.addEventListener("click", synthesizeLessons);
  const learnReview = $("#learning-review-btn");
  if (learnReview) learnReview.addEventListener("click", reviewLessons);
  const learnFbForm = $("#learning-fb-form");
  if (learnFbForm) learnFbForm.addEventListener("submit", addFeedback);

  // Twin (digital twin)
  const twinRefresh = $("#twin-refresh");
  if (twinRefresh) twinRefresh.addEventListener("click", loadTwin);
  const twinSuggest = $("#twin-suggest");
  if (twinSuggest) twinSuggest.addEventListener("click", suggestTwin);
  const twinEntryForm = $("#twin-entry-form");
  if (twinEntryForm) twinEntryForm.addEventListener("submit", addTwinEntry);
  const twinDraftForm = $("#twin-draft-form");
  if (twinDraftForm) twinDraftForm.addEventListener("submit", draftAsOperator);
  const twinDecideForm = $("#twin-decide-form");
  if (twinDecideForm) twinDecideForm.addEventListener("submit", decideAsOperator);

  // Audit (KAI self-audit)
  const auditRun = $("#audit-run");
  if (auditRun) auditRun.addEventListener("click", loadAudit);

  if (getToken()) {
    refresh();
  } else {
    showAuth("");
  }

  setInterval(() => {
    if (getToken() && !$("#admin-body").hidden) refresh();
  }, REFRESH_MS);
});
