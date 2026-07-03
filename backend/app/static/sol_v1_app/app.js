/* Sol v1 — mobile-first member app (vanilla JS, no build step).
 *
 * Auth: same-origin cookie session (POST /auth/login sets the httpOnly nai_access
 * cookie; every call uses credentials:'same-origin'; the token never touches JS,
 * so XSS can't steal it). NON-CUSTODIAL: this app only records + coordinates;
 * members pay each other directly, outside Sol.
 *
 * Safety: all user-supplied text is rendered via textContent / el(), never
 * innerHTML — there is no HTML-injection surface. User-supplied URLs are passed
 * through safeHref() (http/https only) before ever becoming an href.
 */
(function () {
  "use strict";

  // ── pure helpers (also exported for node unit tests) ─────────────────────
  function money(v) {
    var n = typeof v === "number" ? v : parseFloat(v);
    if (!isFinite(n)) return "$0.00";
    return "$" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  var _MON = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  function shortDate(iso) {
    if (!iso) return "—";
    var p = String(iso).slice(0, 10).split("-");
    if (p.length < 3) return String(iso);
    var y = +p[0], m = +p[1], d = +p[2];
    if (!m || !d) return String(iso);
    return _MON[m - 1] + " " + d + ", " + y;
  }
  function statusMeta(s) {
    switch (s) {
      case "pending": return { label: "Awaiting payment", cls: "badge--muted" };
      case "marked": return { label: "Marked paid", cls: "badge--info" };
      case "confirmed": return { label: "Confirmed", cls: "badge--ok" };
      case "disputed": return { label: "Disputed", cls: "badge--danger" };
      case "late": return { label: "Late", cls: "badge--warn" };
      default: return { label: s || "—", cls: "badge--muted" };
    }
  }
  function dueMeta(kind) {
    switch (kind) {
      case "overdue": return { label: "Overdue", cls: "badge--danger" };
      case "due_today": return { label: "Due today", cls: "badge--warn" };
      case "upcoming": return { label: "Upcoming", cls: "badge--info" };
      default: return { label: "Scheduled", cls: "badge--muted" };
    }
  }
  function repMeta(label) {
    switch (label) {
      case "excellent": return { cls: "badge--ok" };
      case "good": return { cls: "badge--ok" };
      case "fair": return { cls: "badge--warn" };
      case "poor": return { cls: "badge--danger" };
      default: return { cls: "badge--muted" };
    }
  }
  function groupStatusMeta(s) {
    switch (s) {
      case "open": return { label: "Open to join", cls: "badge--info" };
      case "locked": return { label: "Active", cls: "badge--ok" };
      case "complete": return { label: "Complete", cls: "badge--muted" };
      default: return { label: s || "—", cls: "badge--muted" };
    }
  }
  function shortId(id) { return id ? String(id).slice(0, 8) : "—"; }
  function safeHref(url) {
    // Only http(s) becomes a clickable link — blocks javascript:/data:/etc.
    var u = String(url == null ? "" : url).trim();
    return /^https?:\/\//i.test(u) ? u : null;
  }
  function parseHash(hash) {
    var h = (hash || "").replace(/^#\/?/, "");
    var qs = "";
    var qi = h.indexOf("?");
    if (qi >= 0) { qs = h.slice(qi + 1); h = h.slice(0, qi); }
    var parts = h.split("/").filter(Boolean);
    var query = {};
    qs.split("&").forEach(function (kv) {
      if (!kv) return;
      var i = kv.indexOf("=");
      var k = i >= 0 ? kv.slice(0, i) : kv;
      query[decodeURIComponent(k)] = i >= 0 ? decodeURIComponent(kv.slice(i + 1)) : "";
    });
    return { route: parts[0] || "groups", id: parts[1] || null, sub: parts[2] || null, query: query };
  }

  var HELPERS = { money: money, shortDate: shortDate, statusMeta: statusMeta, dueMeta: dueMeta,
    repMeta: repMeta, groupStatusMeta: groupStatusMeta, shortId: shortId, safeHref: safeHref, parseHash: parseHash };
  if (typeof module !== "undefined" && module.exports) { module.exports = HELPERS; return; }
  if (typeof window !== "undefined") window.SolV1Helpers = HELPERS;

  // ── DOM builder (safe: text goes through textContent) ────────────────────
  function el(tag, attrs) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v == null) return;
      if (k === "text") node.textContent = v;
      else if (k === "class") node.className = v;
      else if (k === "onclick") node.addEventListener("click", v);
      else if (k === "oninput") node.addEventListener("input", v);
      else if (k === "onsubmit") node.addEventListener("submit", v);
      else if (k === "onkeydown") node.addEventListener("keydown", v);
      else if (k in node && k !== "list") { try { node[k] = v; } catch (e) { node.setAttribute(k, v); } }
      else node.setAttribute(k, v);
    });
    for (var i = 2; i < arguments.length; i++) {
      var c = arguments[i];
      if (c == null) continue;
      if (Array.isArray(c)) c.forEach(function (x) { if (x != null) node.appendChild(typeof x === "string" ? document.createTextNode(x) : x); });
      else node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return node;
  }
  function badge(text, cls) { return el("span", { class: "badge " + cls, text: text }); }
  // Enter/Space activation for role="button" elements (keyboard a11y).
  function activate(fn) {
    return function (ev) {
      if (ev.key === "Enter" || ev.key === " " || ev.key === "Spacebar") { ev.preventDefault(); fn(ev); }
    };
  }
  function tapCard(attrs, children, onActivate, ariaLabel) {
    var a = { class: "card tap", role: "button", tabindex: "0", onclick: onActivate, onkeydown: activate(onActivate) };
    if (ariaLabel) a["aria-label"] = ariaLabel;
    Object.keys(attrs || {}).forEach(function (k) { a[k] = attrs[k]; });
    var args = ["div", a].concat(children);
    return el.apply(null, args);
  }
  // A labelled form field: associates <label for> with the input's id.
  var _fid = 0;
  function field(labelText, input, hintText) {
    var id = "solf" + (++_fid);
    input.id = id;
    return el("div", { class: "field" },
      el("label", { for: id, text: labelText }),
      input,
      hintText ? el("div", { class: "hint", text: hintText }) : null);
  }

  // ── API client ───────────────────────────────────────────────────────────
  var STATE = { me: null, gen: 0 };
  function ApiError(status, detail) { this.status = status; this.detail = detail; }

  async function api(method, path, body) {
    var opts = { method: method, credentials: "same-origin", headers: {} };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    var res;
    try {
      res = await fetch(path, opts);
    } catch (e) {
      throw new ApiError(0, "Network error — check your connection.");
    }
    if (res.status === 204) return null;
    var data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) {
      if (res.status === 401 && !path.startsWith("/auth/")) { STATE.me = null; go("#/login"); }
      var detail = (data && (data.detail || data.message)) || ("Request failed (" + res.status + ")");
      if (Array.isArray(detail)) detail = detail.map(function (d) { return d.msg || JSON.stringify(d); }).join("; ");
      throw new ApiError(res.status, detail);
    }
    return data;
  }

  // ── UI plumbing ──────────────────────────────────────────────────────────
  var mainEl, toastTimer, liveEl;
  function ensureLive() {
    if (!liveEl) {
      liveEl = el("div", { class: "sr-only", "aria-live": "polite", "aria-atomic": "true" });
      document.body.appendChild(liveEl);
    }
    return liveEl;
  }
  function render() {
    mainEl.textContent = "";
    for (var i = 0; i < arguments.length; i++) if (arguments[i]) mainEl.appendChild(arguments[i]);
    mainEl.scrollTop = 0;
    // Move focus to the screen heading so SR/keyboard users are told where they are.
    var h = mainEl.querySelector("h1");
    if (h) { h.setAttribute("tabindex", "-1"); try { h.focus({ preventScroll: true }); } catch (e) {} }
  }
  function loading() { render(el("div", { class: "spinner", role: "status", "aria-label": "Loading" })); }
  function toast(msg, isErr) {
    var live = ensureLive();
    live.setAttribute("aria-live", isErr ? "assertive" : "polite");
    live.textContent = "";
    setTimeout(function () { live.textContent = msg; }, 30);  // change fires the announcement
    var t = el("div", { class: "toast" + (isErr ? " err" : ""), text: msg });
    document.body.appendChild(t);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { t.remove(); }, isErr ? 4200 : 2400);
  }
  function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }
  function backBtn(hash, label) { return el("button", { class: "backlink", type: "button", onclick: function () { go(hash); }, text: "← " + (label || "Back") }); }
  function errorView(e, retryHash) {
    return el("div", { class: "empty" },
      el("div", { class: "big", "aria-hidden": "true", text: "⚠️" }),
      el("p", { text: (e && e.detail) || "Something went wrong." }),
      retryHash ? el("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: function () { go(retryHash); }, text: "Try again" }) : null);
  }
  function empty(emoji, title, sub) {
    return el("div", { class: "empty" }, el("div", { class: "big", "aria-hidden": "true", text: emoji }),
      el("h3", { text: title }), sub ? el("p", { class: "muted", text: sub }) : null);
  }
  function stale(gen) { return gen !== STATE.gen; }  // a newer navigation superseded this screen

  // ── auth screens ───────────────────────────────────────────────────────
  function authScreen(mode) {
    var isSignup = mode === "signup";
    var errEl = el("div", { class: "errbox", role: "alert", style: "display:none" });
    function setErr(m) { errEl.textContent = m; errEl.style.display = m ? "block" : "none"; }
    var email = el("input", { type: "email", autocomplete: "email", placeholder: "you@example.com", required: true });
    var pass = el("input", { type: "password", autocomplete: isSignup ? "new-password" : "current-password", placeholder: "••••••••", required: true });
    var name = el("input", { type: "text", autocomplete: "name", placeholder: "Your name" });
    var submit = el("button", { class: "btn btn--primary", type: "submit", text: isSignup ? "Create account" : "Sign in" });

    var form = el("form", { onsubmit: async function (ev) {
      ev.preventDefault();
      setErr(""); submit.disabled = true;
      try {
        var body = { email: email.value.trim(), password: pass.value };
        if (isSignup && name.value.trim()) body.full_name = name.value.trim();
        await api("POST", isSignup ? "/auth/signup" : "/auth/login", body);
        STATE.me = await api("GET", "/auth/me");
        go("#/groups");
      } catch (e) {
        setErr(e.detail || "Could not sign in."); submit.disabled = false;
      }
    } },
      field("Email", email),
      isSignup ? field("Name", name) : null,
      field("Password", pass),
      submit);

    var tabs = el("div", { class: "tabs" },
      el("button", { type: "button", class: isSignup ? "" : "on", onclick: function () { go("#/login"); }, text: "Sign in" }),
      el("button", { type: "button", class: isSignup ? "on" : "", onclick: function () { go("#/signup"); }, text: "Sign up" }));

    return el("div", { class: "auth" },
      el("div", { class: "logo" }, el("div", { class: "sun", "aria-hidden": "true" }), el("h1", { text: "Sol" }),
        el("p", { class: "muted small", text: "Savings circles, coordinated — never custodied." })),
      tabs, errEl, form);
  }

  // ── groups ───────────────────────────────────────────────────────────────
  async function groupsScreen() {
    var gen = STATE.gen; loading();
    try {
      var groups = await api("GET", "/sol/v1/groups");
      if (stale(gen)) return;
      var actions = el("div", { class: "btnrow", style: "margin-bottom:var(--s-4)" },
        el("button", { class: "btn btn--primary btn--sm", type: "button", onclick: function () { go("#/groups/new"); }, text: "+ New circle" }),
        el("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: function () { go("#/join"); }, text: "Join with code" }));
      if (!groups.length) return render(el("h1", { text: "Your circles" }), actions, empty("🌅", "No circles yet", "Create one or join with an invite code."));
      var list = el("div", { class: "stack" }, groups.map(function (g) { return groupCard(g); }));
      render(el("h1", { text: "Your circles" }), actions, list);
    } catch (e) { if (stale(gen)) return; render(el("h1", { text: "Your circles" }), errorView(e, "#/groups")); }
  }
  function groupCard(g) {
    var st = groupStatusMeta(g.status);
    return tapCard({}, [
      el("div", { class: "row between" }, el("h3", { text: g.name }), badge(st.label, st.cls)),
      el("div", { class: "row between small muted" },
        el("span", { text: money(g.contribution_amount) + " · " + g.frequency }),
        el("span", { text: "up to " + g.member_limit + " members" }))
    ], function () { go("#/group/" + g.id); }, "Open circle " + g.name);
  }

  async function createGroupScreen() {
    var gen = STATE.gen; loading();
    try { if (!(await ensureConsent("#/groups/new")) || stale(gen)) return; }
    catch (e) { if (stale(gen)) return; return render(el("h1", { text: "New circle" }), errorView(e, "#/groups/new")); }
    var err = el("div", { class: "errbox", role: "alert", style: "display:none" });
    var name = el("input", { type: "text", required: true, maxlength: 120, placeholder: "e.g. Rent circle" });
    var amount = el("input", { type: "number", required: true, min: "1", step: "0.01", placeholder: "100.00", inputmode: "decimal" });
    var freq = el("select", {}, el("option", { value: "weekly", text: "Weekly" }), el("option", { value: "biweekly", text: "Every 2 weeks" }), el("option", { value: "monthly", text: "Monthly" }));
    var limit = el("input", { type: "number", required: true, min: "2", max: "100", value: "5" });
    var submit = el("button", { class: "btn btn--primary", type: "submit", text: "Create circle" });
    var form = el("form", { onsubmit: async function (ev) {
      ev.preventDefault(); err.style.display = "none"; submit.disabled = true;
      try {
        var g = await api("POST", "/sol/v1/groups", {
          name: name.value.trim(), contribution_amount: amount.value,
          frequency: freq.value, member_limit: parseInt(limit.value, 10),
        });
        toast("Circle created");
        go("#/group/" + g.id);
      } catch (e) { err.textContent = e.detail; err.style.display = "block"; submit.disabled = false; }
    } },
      field("Circle name", name),
      field("Contribution per member", amount, "Members pay each other this amount each cycle."),
      field("How often", freq),
      field("Member limit", limit, "2–100 members."),
      submit);
    render(backBtn("#/groups", "Circles"), el("h1", { text: "New circle" }), ncNote(), err, form);
  }

  async function joinScreen(prefill) {
    var self = "#/join" + (prefill ? "?code=" + encodeURIComponent(prefill) : "");
    var gen = STATE.gen; loading();
    try { if (!(await ensureConsent(self)) || stale(gen)) return; }
    catch (e) { if (stale(gen)) return; return render(el("h1", { text: "Join a circle" }), errorView(e, self)); }
    var err = el("div", { class: "errbox", role: "alert", style: "display:none" });
    var code = el("input", { type: "text", required: true, maxlength: 32, placeholder: "ABCD1234", value: prefill || "", style: "text-transform:uppercase;letter-spacing:2px;font-family:var(--font-display)" });
    var submit = el("button", { class: "btn btn--primary", type: "submit", text: "Join circle" });
    var form = el("form", { onsubmit: async function (ev) {
      ev.preventDefault(); err.style.display = "none"; submit.disabled = true;
      try {
        var m = await api("POST", "/sol/v1/groups/join", { invite_code: code.value.trim() });
        toast("Joined!");
        go("#/group/" + m.group_id);
      } catch (e) { err.textContent = e.detail; err.style.display = "block"; submit.disabled = false; }
    } },
      field("Invite code", code),
      submit);
    render(backBtn("#/groups", "Circles"), el("h1", { text: "Join a circle" }), err, form);
  }

  async function groupDetailScreen(id) {
    var gen = STATE.gen; loading();
    try {
      var d = await api("GET", "/sol/v1/groups/" + id);
      if (stale(gen)) return;
      var reps = [];
      try { reps = await api("GET", "/sol/v1/groups/" + id + "/reputation"); } catch (e) { reps = []; }
      if (stale(gen)) return;
      var repByUser = {}; reps.forEach(function (r) { repByUser[r.user_id] = r; });
      var g = d.group, me = STATE.me || {};
      var isOrganizer = g.organizer_id === me.id;
      var st = groupStatusMeta(g.status);

      var nodes = [backBtn("#/groups", "Circles"),
        el("div", { class: "row between" }, el("h1", { text: g.name }), badge(st.label, st.cls)),
        el("div", { class: "card" },
          el("div", { class: "row between" }, el("span", { class: "muted small", text: "Contribution" }), el("span", { class: "amount", text: money(g.contribution_amount) })),
          el("div", { class: "row between" }, el("span", { class: "muted small", text: "Frequency" }), el("span", { text: g.frequency })),
          el("div", { class: "row between" }, el("span", { class: "muted small", text: "Members" }), el("span", { text: d.members.length + " / " + g.member_limit })))];

      if (g.status === "open") {
        var link = location.origin + "/sol-app/#/join?code=" + encodeURIComponent(g.invite_code);
        nodes.push(el("div", { class: "card" },
          el("div", { class: "section-title", text: "Invite members" }),
          el("div", { class: "row", style: "justify-content:center;margin-bottom:var(--s-3)" }, el("span", { class: "pill-code", text: g.invite_code })),
          el("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: function () { copy(link, "Invite link copied"); }, text: "Copy invite link" })));
        if (isOrganizer && d.members.length >= 2) {
          nodes.push(el("button", { class: "btn btn--primary", type: "button", style: "margin-bottom:var(--s-3)", onclick: function () { lockGroup(id); }, text: "Lock circle & set payout order" }));
        } else if (isOrganizer) {
          nodes.push(el("p", { class: "muted small", text: "Invite at least one more member, then you can lock the circle." }));
        }
      }

      nodes.push(el("div", { class: "section-title", text: "Members" }));
      nodes.push(el("div", { class: "stack" }, d.members.map(function (m) {
        var rep = repByUser[m.user_id];
        var isMe = m.user_id === me.id;
        var right = rep && rep.score != null
          ? badge(rep.score + " · " + rep.label, repMeta(rep.label).cls)
          : badge("unrated", "badge--muted");
        return el("div", { class: "card" }, el("div", { class: "row between" },
          el("div", {}, el("strong", { text: (isMe ? "You" : shortId(m.user_id)) }),
            el("span", { class: "muted small", text: (m.role === "organizer" ? " · organizer" : "") + (m.payout_position ? " · gets paid #" + m.payout_position : "") })),
          right));
      })));

      if (d.cycles.length) {
        nodes.push(el("div", { class: "section-title", text: "Payout calendar" }));
        var nextPending = d.cycles.filter(function (c) { return c.status === "pending"; })[0];
        nodes.push(el("div", { class: "stack" }, d.cycles.map(function (c) {
          var cs = c.status === "complete" ? { label: "Complete", cls: "badge--ok" } : c.status === "active" ? { label: "Active", cls: "badge--info" } : { label: "Upcoming", cls: "badge--muted" };
          var recip = d.members.filter(function (m) { return m.id === c.recipient_membership_id; })[0];
          var recipLabel = recip ? (recip.user_id === me.id ? "You receive" : shortId(recip.user_id) + " receives") : "recipient";
          var card = el("div", { class: "card" }, el("div", { class: "row between" },
            el("div", {}, el("strong", { text: "Cycle " + c.cycle_number }), el("span", { class: "muted small", text: " · due " + shortDate(c.due_date) }),
              el("div", { class: "small muted", text: recipLabel })),
            badge(cs.label, cs.cls)));
          if (isOrganizer && g.status === "locked" && nextPending && c.id === nextPending.id) {
            card.appendChild(el("button", { class: "btn btn--primary btn--sm", type: "button", style: "margin-top:var(--s-3)", onclick: function () { activateCycle(c.id, id); }, text: "Start this cycle" }));
          }
          return card;
        })));
      }
      render.apply(null, nodes);
    } catch (e) { if (stale(gen)) return; render(backBtn("#/groups", "Circles"), errorView(e, "#/group/" + id)); }
  }

  async function lockGroup(id) {
    if (!confirm("Lock the circle and randomly set the payout order? No new members can join after this.")) return;
    try { await api("POST", "/sol/v1/groups/" + id + "/lock", { order_mode: "random" }); toast("Circle locked"); go("#/group/" + id); }
    catch (e) { toast(e.detail, true); }
  }
  async function activateCycle(cycleId, groupId) {
    if (!confirm("Start this cycle? Everyone except the recipient will be asked to pay.")) return;
    try { await api("POST", "/sol/v1/cycles/" + cycleId + "/activate"); toast("Cycle started"); go("#/group/" + groupId); }
    catch (e) { toast(e.detail, true); }
  }

  // ── payments (reminders) ─────────────────────────────────────────────────
  async function payScreen() {
    var gen = STATE.gen; loading();
    try {
      var r = await api("GET", "/sol/v1/reminders");
      if (stale(gen)) return;
      var nodes = [el("h1", { text: "Payments" })];
      nodes.push(el("div", { class: "section-title", text: "You owe" }));
      nodes.push(r.as_payer.length ? el("div", { class: "stack" }, r.as_payer.map(function (i) { return reminderCard(i, true); }))
        : empty("✅", "Nothing due", "You're all caught up."));
      nodes.push(el("div", { class: "section-title", text: "Owed to you" }));
      nodes.push(r.as_payee.length ? el("div", { class: "stack" }, r.as_payee.map(function (i) { return reminderCard(i, false); }))
        : el("p", { class: "muted small", text: "No incoming payments right now." }));
      render.apply(null, nodes);
    } catch (e) { if (stale(gen)) return; render(el("h1", { text: "Payments" }), errorView(e, "#/pay")); }
  }
  function reminderCard(i, asPayer) {
    var due = dueMeta(i.kind), st = statusMeta(i.status);
    return tapCard({}, [
      el("div", { class: "row between" },
        el("span", { class: "amount", text: money(i.amount) }),
        el("span", {}, badge(due.label, due.cls))),
      el("div", { class: "row between small muted" },
        el("span", { text: (asPayer ? "to " : "from ") + shortId(i.counterparty_id) + " · due " + shortDate(i.due_date) }),
        badge(st.label, st.cls))
    ], function () { go("#/payment/" + i.payment_id); },
      (asPayer ? "Payment you owe, " : "Payment owed to you, ") + money(i.amount));
  }

  async function paymentDetailScreen(id) {
    var gen = STATE.gen; loading();
    try {
      var d = await api("GET", "/sol/v1/payments/" + id);
      if (stale(gen)) return;
      var p = d.payment, me = STATE.me || {};
      var isPayer = p.payer_id === me.id, isPayee = p.payee_id === me.id;
      var st = statusMeta(p.status);
      var nodes = [backBtn("#/pay", "Payments"),
        el("div", { class: "row between" }, el("h1", { text: money(p.amount) }), badge(st.label, st.cls)),
        el("div", { class: "card" },
          el("div", { class: "row between" }, el("span", { class: "muted small", text: isPayer ? "You pay" : "Payer" }), el("span", { text: isPayer ? shortId(p.payee_id) : shortId(p.payer_id) })),
          p.method ? el("div", { class: "row between" }, el("span", { class: "muted small", text: "Method" }), el("span", { text: p.method })) : null,
          p.payer_marked_at ? el("div", { class: "row between" }, el("span", { class: "muted small", text: "Marked paid" }), el("span", { text: shortDate(p.payer_marked_at) })) : null)];

      if (isPayer && d.pay_to && d.pay_to.length) {
        nodes.push(el("div", { class: "section-title", text: "How to pay them" }));
        nodes.push(el("div", { class: "stack" }, d.pay_to.map(function (pp) {
          return el("div", { class: "card" }, el("div", { class: "row between" },
            el("div", {}, el("strong", { text: pp.method }), pp.is_default ? el("span", { class: "muted small", text: " · default" }) : null),
            el("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: function () { copy(pp.handle, "Handle copied"); }, text: pp.handle })));
        })));
      } else if (isPayer) {
        nodes.push(el("p", { class: "muted small", text: "This member hasn't shared a payment handle yet — ask them how they'd like to be paid." }));
      }

      if (d.proofs && d.proofs.length) {
        nodes.push(el("div", { class: "section-title", text: "Proof" }));
        nodes.push(el("div", { class: "stack" }, d.proofs.map(function (pr) {
          var href = safeHref(pr.image_url);
          return el("div", { class: "card" }, href
            ? el("a", { href: href, target: "_blank", rel: "noopener noreferrer", text: "View proof · " + shortDate(pr.uploaded_at) })
            : el("span", { class: "muted small", text: "Proof attached · " + shortDate(pr.uploaded_at) }));
        })));
      }

      var actionable = p.status === "pending" || p.status === "late" || p.status === "disputed";
      if (isPayer && actionable) { nodes.push(el("hr")); nodes.push(markForm(p.id)); }
      if (isPayee && p.status === "marked") {
        nodes.push(el("hr"));
        nodes.push(el("p", { class: "muted small", text: "The payer marked this paid. Did you receive it?" }));
        nodes.push(el("div", { class: "btnrow" },
          el("button", { class: "btn btn--success", type: "button", onclick: function () { paymentAction(p.id, "confirm", "Confirmed received"); }, text: "✓ Confirm received" }),
          el("button", { class: "btn btn--danger", type: "button", onclick: function () { paymentAction(p.id, "dispute", "Disputed"); }, text: "Dispute" })));
      }
      render.apply(null, nodes);
    } catch (e) { if (stale(gen)) return; render(backBtn("#/pay", "Payments"), errorView(e, "#/payment/" + id)); }
  }
  function markForm(id) {
    var method = el("select", {}, ["zelle", "cashapp", "venmo", "cash", "other"].map(function (m) { return el("option", { value: m, text: m }); }));
    var proof = el("input", { type: "url", placeholder: "https://link-to-screenshot (optional)", maxlength: 2048 });
    var submit = el("button", { class: "btn btn--primary", type: "submit", text: "I paid this" });
    return el("form", { onsubmit: async function (ev) {
      ev.preventDefault(); submit.disabled = true;
      try {
        var body = { method: method.value };
        if (proof.value.trim()) body.proof_image_url = proof.value.trim();
        await api("POST", "/sol/v1/payments/" + id + "/mark", body);
        toast("Marked paid — waiting for the recipient to confirm");
        go("#/payment/" + id);
      } catch (e) { toast(e.detail, true); submit.disabled = false; }
    } },
      field("How did you pay?", method),
      field("Proof (optional)", proof, "Paste a link to a payment screenshot if you have one."),
      submit);
  }
  async function paymentAction(id, action, okMsg) {
    if (action === "dispute" && !confirm("Dispute this — tell the payer you did NOT receive the money?")) return;
    try { await api("POST", "/sol/v1/payments/" + id + "/" + action); toast(okMsg); go("#/payment/" + id); }
    catch (e) { toast(e.detail, true); }
  }

  // ── me: reputation + payment profiles ────────────────────────────────────
  async function meScreen() {
    var gen = STATE.gen; loading();
    try {
      var rep = await api("GET", "/sol/v1/reputation/me");
      if (stale(gen)) return;
      var profiles = await api("GET", "/sol/v1/payment-profiles");
      if (stale(gen)) return;
      var me = STATE.me || {};
      var rm = repMeta(rep.label);
      var displayName = me.full_name || me.name || me.email || "Member";
      var nodes = [el("h1", { text: "You" }),
        el("div", { class: "card" }, el("div", { class: "row between" },
          el("div", {}, el("strong", { text: displayName }), el("div", { class: "small muted", text: me.email || "" })),
          el("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: logout, text: "Sign out" }))),
        el("div", { class: "section-title", text: "Your reliability" }),
        el("div", { class: "card" }, el("div", { class: "row between" },
          el("div", { class: "row", style: "gap:var(--s-4)" },
            el("span", { class: "repdial", text: rep.score == null ? "—" : String(rep.score) }),
            el("div", {}, badge(rep.label + (rep.provisional && rep.score != null ? " · new" : ""), rm.cls),
              el("div", { class: "small muted", text: rep.actionable + " payment" + (rep.actionable === 1 ? "" : "s") + " counted" }))))),
        el("p", { class: "small muted", text: "On-time confirmed payments build your score. Disputes and overdue payments lower it." }),
        el("div", { class: "section-title", text: "How you get paid" }),
      ];
      nodes.push(profiles.length ? el("div", { class: "stack" }, profiles.map(function (pp) { return profileCard(pp); })) : el("p", { class: "muted small", text: "Add a handle so members know how to pay you." }));
      nodes.push(addProfileForm());
      nodes.push(el("hr"));
      nodes.push(el("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: function () { go("#/legal"); }, text: "How Sol handles money" }));
      render.apply(null, nodes);
    } catch (e) { if (stale(gen)) return; render(el("h1", { text: "You" }), errorView(e, "#/me")); }
  }
  function profileCard(pp) {
    return el("div", { class: "card" }, el("div", { class: "row between" },
      el("div", {}, el("strong", { text: pp.method }), pp.is_default ? el("span", { class: "muted small", text: " · default" }) : null, el("div", { class: "small muted", text: pp.handle })),
      el("button", { class: "btn btn--ghost btn--sm", type: "button", onclick: async function () {
        if (!confirm("Remove this handle?")) return;
        try { await api("DELETE", "/sol/v1/payment-profiles/" + pp.id); toast("Removed"); go("#/me"); } catch (e) { toast(e.detail, true); }
      }, text: "Remove" })));
  }
  function addProfileForm() {
    var method = el("select", {}, ["zelle", "cashapp", "venmo", "applepay", "cash"].map(function (m) { return el("option", { value: m, text: m }); }));
    var handle = el("input", { type: "text", required: true, maxlength: 128, placeholder: "phone, email, or @tag" });
    var isDef = el("input", { type: "checkbox" });
    var submit = el("button", { class: "btn btn--primary btn--sm", type: "submit", text: "Save handle" });
    return el("form", { style: "margin-top:var(--s-3)", onsubmit: async function (ev) {
      ev.preventDefault(); submit.disabled = true;
      try {
        await api("PUT", "/sol/v1/payment-profiles", { method: method.value, handle: handle.value.trim(), is_default: isDef.checked });
        toast("Saved"); go("#/me");
      } catch (e) { toast(e.detail, true); submit.disabled = false; }
    } },
      field("Payment app", method),
      field("Handle", handle, "A phone, email, or app tag — never a bank account number."),
      el("label", { class: "row small", style: "font-weight:400" }, isDef, el("span", { text: " Make this my default" })),
      submit);
  }

  // ── consent gate ─────────────────────────────────────────────────────────
  async function ensureConsent(selfHash) {
    // Returns true if the current terms are accepted (the screen may render).
    // Otherwise routes to the consent screen (which returns here on accept) and
    // returns false. Used by BOTH create + join so every entry point — button,
    // deep link, and the shared invite link — is gated identically.
    var s = await api("GET", "/sol/v1/legal/current");
    if (s.accepted) return true;
    go("#/consent?next=" + encodeURIComponent(selfHash));
    return false;
  }
  async function consentScreen(nextHash) {
    var gen = STATE.gen; loading();
    var next = nextHash || "#/groups";
    try {
      var s = await api("GET", "/sol/v1/legal/current");
      if (stale(gen)) return;
      if (s.accepted) { go(next); return; }
      var agree = el("input", { type: "checkbox" });
      var accept = el("button", { class: "btn btn--primary", type: "button", disabled: true, text: "I agree — continue" });
      agree.addEventListener("change", function () { accept.disabled = !agree.checked; });
      accept.addEventListener("click", async function () {
        accept.disabled = true;
        try { await api("POST", "/sol/v1/legal/accept", { version: s.version }); toast("Terms accepted"); go(next); }
        catch (e) { toast(e.detail, true); accept.disabled = false; }
      });
      render(backBtn("#/groups", "Circles"),
        el("h1", { text: "Before you start" }),
        el("div", { class: "card stack" },
          el("p", { text: "Sol is a coordination tool, not a bank. Sol never holds, pools, or moves your money — members pay each other directly, and Sol only records it." }),
          el("p", { text: "A savings circle depends on members paying each other. Sol does not guarantee any payment; you could receive less than you contributed, or nothing. Only join circles with people you trust." }),
          el("a", { href: "terms.html", target: "_blank", rel: "noopener noreferrer", text: "Read the full terms & risk disclosure →" })),
        el("label", { class: "row small", style: "font-weight:400;margin:var(--s-3) 0" }, agree,
          el("span", { text: " I understand and agree to the " + s.title + " (v" + s.version + ")." })),
        accept);
    } catch (e) { if (stale(gen)) return; render(el("h1", { text: "Before you start" }), errorView(e, "#/consent")); }
  }

  function legalScreen() {
    render(backBtn("#/me", "You"), el("h1", { text: "How Sol handles money" }),
      el("div", { class: "card stack" },
        el("p", { text: "Sol is a coordination tool, not a bank. Sol never accepts, holds, pools, or transfers your money." }),
        el("p", { text: "Members pay each other directly — by Zelle, CashApp, Venmo, or cash — outside of Sol. Sol only records who paid whom and helps everyone stay on schedule." }),
        el("p", { text: "When you 'mark paid,' you're telling the group you sent money directly to the recipient. When the recipient 'confirms,' they're acknowledging they received it. Sol is never in the middle of that transfer." }),
        el("p", { class: "muted small", text: "Sol does not provide financial, legal, or tax advice. Rotating savings circles carry risk: a member may not pay. Only join circles with people you trust." })));
  }

  // ── shared ───────────────────────────────────────────────────────────────
  function ncNote() {
    return el("div", { class: "card", style: "background:var(--warn-100);border-color:var(--sol-200)" },
      el("p", { class: "small", style: "margin:0", text: "Sol never holds your money. Members pay each other directly; Sol just keeps the schedule and the record." }));
  }
  function copy(txt, okMsg) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(txt).then(function () { toast(okMsg || "Copied"); }, function () { toast(txt); });
    } else { toast(txt); }
  }
  async function logout() {
    try { await api("POST", "/auth/logout"); } catch (e) { /* ignore */ }
    STATE.me = null; go("#/login");
  }

  // ── shell + router ─────────────────────────────────────────────────────
  function shell(activeTab) {
    var app = document.getElementById("app");
    app.textContent = "";
    app.appendChild(el("header", { class: "appbar" },
      el("div", { class: "brand" }, el("span", { class: "sun", "aria-hidden": "true" }), el("span", { text: "Sol" })),
      el("div", { class: "spacer" })));
    app.appendChild(el("div", { class: "ncbanner" }, el("span", { text: "Non-custodial · members pay each other directly. " }),
      el("a", { href: "#/legal", text: "Learn more" })));
    mainEl = el("main", { id: "view" });
    app.appendChild(mainEl);
    var tab = function (hash, ico, label) {
      return el("a", { href: hash, "aria-current": activeTab === hash ? "page" : null },
        el("span", { class: "ico", "aria-hidden": "true", text: ico }), el("span", { text: label }));
    };
    app.appendChild(el("nav", { class: "bottomnav", "aria-label": "Primary" },
      tab("#/groups", "🌅", "Circles"), tab("#/pay", "💸", "Payments"), tab("#/me", "🙂", "You")));
  }

  var AUTH_ROUTES = { login: 1, signup: 1 };
  var TAB_FOR = { groups: "#/groups", pay: "#/pay", me: "#/me", group: "#/groups", payment: "#/pay", "groups/new": "#/groups", join: "#/groups", legal: "#/me", consent: "#/groups" };

  async function ensureMe() {
    if (STATE.me) return true;
    try { STATE.me = await api("GET", "/auth/me"); return true; } catch (e) { return false; }
  }

  async function route() {
    STATE.gen++;  // supersede any in-flight screen
    var h = parseHash(location.hash);
    if (AUTH_ROUTES[h.route]) {
      document.getElementById("app").textContent = "";
      var wrap = el("main", {}); document.getElementById("app").appendChild(wrap);
      mainEl = wrap; render(authScreen(h.route));
      return;
    }
    var ok = await ensureMe();
    if (!ok) { go("#/login"); return; }

    var routeKey = h.route === "groups" && h.id === "new" ? "groups/new" : h.route;
    shell(TAB_FOR[routeKey] || "#/groups");

    if (h.route === "groups" && h.id === "new") return createGroupScreen();
    switch (h.route) {
      case "groups": return groupsScreen();
      case "join": return joinScreen(h.query.code);
      case "group": return h.id ? groupDetailScreen(h.id) : groupsScreen();
      case "pay": return payScreen();
      case "payment": return h.id ? paymentDetailScreen(h.id) : payScreen();
      case "me": return meScreen();
      case "legal": return legalScreen();
      case "consent": return consentScreen(h.query.next);
      default: return groupsScreen();
    }
  }

  window.addEventListener("hashchange", route);
  window.addEventListener("DOMContentLoaded", function () {
    ensureLive();
    var m = location.search.match(/[?&]invite=([^&]+)/);
    if (m && !location.hash) { location.hash = "#/join?code=" + m[1]; }
    if (!location.hash) location.hash = "#/groups";
    route();
  });
})();
