/* Sol — operator dashboard (vanilla JS, no build step).
 *
 * Auth: shared X-Admin-Token header (matches ADMIN_TOKEN). The token is kept in
 * sessionStorage (cleared when the tab closes) and sent on every fetch. This
 * page is just a viewer — the real access control is server-side on
 * /admin/sol-v1/* (require_admin_token, fail-closed). Read-only; NON-CUSTODIAL.
 *
 * Safety: all values render via textContent / el() — never innerHTML.
 */
(function () {
  "use strict";

  // ── pure helpers (exported for node unit tests) ──────────────────────────
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
  function shortId(id) { return id ? String(id).slice(0, 8) : "—"; }
  function statusBadge(s) {
    switch (s) {
      case "confirmed": case "complete": case "ok": return "b-ok";
      case "marked": case "active": case "open": return "b-info";
      case "disputed": return "b-danger";
      case "late": case "overdue": case "pending": return "b-warn";
      default: return "b-muted";
    }
  }
  var HELPERS = { money: money, shortDate: shortDate, shortId: shortId, statusBadge: statusBadge };
  if (typeof module !== "undefined" && module.exports) { module.exports = HELPERS; return; }

  // ── token ────────────────────────────────────────────────────────────────
  var TKEY = "sol_admin_token";
  function getToken() { try { return sessionStorage.getItem(TKEY) || ""; } catch (e) { return ""; } }
  function setToken(t) { try { sessionStorage.setItem(TKEY, t); } catch (e) {} }

  // ── safe DOM builder ─────────────────────────────────────────────────────
  function el(tag, attrs) {
    var node = document.createElement(tag);
    attrs = attrs || {};
    Object.keys(attrs).forEach(function (k) {
      var v = attrs[k];
      if (v == null) return;
      if (k === "text") node.textContent = v;
      else if (k === "class") node.className = v;
      else if (k === "onclick") node.addEventListener("click", v);
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
  function cell() { var a = ["td", {}]; for (var i = 0; i < arguments.length; i++) a.push(arguments[i]); return el.apply(null, a); }

  // ── API ──────────────────────────────────────────────────────────────────
  var STATE = { tab: "overview", err: null };
  var appEl;
  async function api(path) {
    var res;
    try {
      res = await fetch("/admin/sol-v1" + path, { headers: { "X-Admin-Token": getToken() } });
    } catch (e) { throw new Error("Network error"); }
    if (res.status === 401 || res.status === 403) throw new Error("__AUTH__");
    if (!res.ok) {
      var d = null; try { d = await res.json(); } catch (e) {}
      throw new Error((d && d.detail) || ("Request failed (" + res.status + ")"));
    }
    return res.json();
  }

  // ── shell ────────────────────────────────────────────────────────────────
  var TABS = [
    ["overview", "Overview"], ["risk", "Risk"], ["disputes", "Disputes"],
    ["groups", "Circles"], ["activity", "Activity"],
  ];
  function shell(body) {
    appEl.textContent = "";
    var tokenInput = el("input", { type: "password", placeholder: "ADMIN_TOKEN", value: getToken() });
    var save = el("button", { class: "primary", text: "Connect", onclick: function () { setToken(tokenInput.value.trim()); render(); } });
    var refresh = el("button", { text: "↻ Refresh", onclick: render });
    appEl.appendChild(el("div", { class: "topbar" },
      el("div", { class: "brand" }, el("span", { class: "sun", "aria-hidden": "true" }), el("span", { text: "Sol — Operator" })),
      el("div", { class: "spacer" }),
      el("div", { class: "tokenbar" }, tokenInput, save, refresh)));
    appEl.appendChild(el("div", { class: "nc", text: "Non-custodial: Sol records what members pay each other directly. No money moves through Sol." }));
    var tabs = el("div", { class: "tabs" }, TABS.map(function (t) {
      return el("button", { "aria-current": STATE.tab === t[0] ? "true" : null, text: t[1],
        onclick: function () { STATE.tab = t[0]; render(); } });
    }));
    appEl.appendChild(tabs);
    if (STATE.err === "__AUTH__") {
      appEl.appendChild(el("div", { class: "err", text: "Enter a valid ADMIN_TOKEN above to view the dashboard." }));
      return;
    }
    if (STATE.err) appEl.appendChild(el("div", { class: "err", text: STATE.err }));
    appEl.appendChild(body);
  }
  function loading() { return el("div", { class: "spinner", role: "status", "aria-label": "Loading" }); }
  function emptyRow(cols, msg) { return el("tr", {}, el("td", { colspan: String(cols), class: "empty", text: msg })); }

  // ── views ──────────────────────────────────────────────────────────────
  function metricCard(num, lbl, cls) {
    return el("div", { class: "card" + (cls ? " " + cls : "") }, el("div", { class: "num", text: String(num) }), el("div", { class: "lbl", text: lbl }));
  }
  async function overviewView() {
    var o = await api("/overview");
    var wrap = el("div", {});
    wrap.appendChild(el("div", { class: "cards" },
      metricCard(o.attention.overdue, "Overdue", "attn-overdue"),
      metricCard(o.attention.disputed, "Disputed", "attn-disputed"),
      metricCard(o.groups.total, "Circles"),
      metricCard(o.members_total, "Members"),
      metricCard(money(o.recorded_confirmed_volume), "Recorded (confirmed)")));
    wrap.appendChild(el("div", { class: "section-title", text: "Circles" }));
    wrap.appendChild(el("div", { class: "cards" },
      metricCard(o.groups.open, "Open"), metricCard(o.groups.locked, "Active"), metricCard(o.groups.complete, "Complete")));
    wrap.appendChild(el("div", { class: "section-title", text: "Payments" }));
    wrap.appendChild(el("div", { class: "cards" },
      metricCard(o.payments.pending, "Pending"), metricCard(o.payments.marked, "Marked"),
      metricCard(o.payments.confirmed, "Confirmed"), metricCard(o.payments.disputed, "Disputed"),
      metricCard(o.payments.late, "Late")));
    return wrap;
  }
  function partyCells(payer, payee) {
    return [cell(el("span", { class: "mono", text: shortId(payer) })), cell(el("span", { class: "mono", text: shortId(payee) }))];
  }
  async function riskView() {
    var r = await api("/risk");
    var head = el("tr", {}, el("th", { text: "Kind" }), el("th", { text: "Circle" }), el("th", { text: "Payer" }), el("th", { text: "Payee" }), el("th", { text: "Amount" }), el("th", { text: "Due" }));
    var rows = r.items.length ? r.items.map(function (i) {
      return el("tr", {}, cell(badge(i.kind, statusBadge(i.kind))), cell(i.group_name),
        cell(el("span", { class: "mono", text: shortId(i.payer_id) })), cell(el("span", { class: "mono", text: shortId(i.payee_id) })),
        cell(money(i.amount)), cell(shortDate(i.due_date)));
    }) : [emptyRow(6, "Nothing needs attention. 🎉")];
    return el("div", { class: "tablewrap" }, el("table", {}, el("thead", {}, head), el("tbody", {}, rows)));
  }
  async function disputesView() {
    var d = await api("/disputes");
    var head = el("tr", {}, el("th", { text: "Circle" }), el("th", { text: "Payer" }), el("th", { text: "Payee" }), el("th", { text: "Amount" }), el("th", { text: "Marked" }), el("th", { text: "Disputed" }), el("th", { text: "Proofs" }));
    var rows = d.items.length ? d.items.map(function (i) {
      return el("tr", {}, cell(i.group_name), cell(el("span", { class: "mono", text: shortId(i.payer_id) })),
        cell(el("span", { class: "mono", text: shortId(i.payee_id) })), cell(money(i.amount)),
        cell(shortDate(i.payer_marked_at)), cell(shortDate(i.disputed_at)), cell(String(i.proof_count)));
    }) : [emptyRow(7, "No disputes.")];
    return el("div", { class: "tablewrap" }, el("table", {}, el("thead", {}, head), el("tbody", {}, rows)));
  }
  async function groupsView() {
    var g = await api("/groups");
    var head = el("tr", {}, el("th", { text: "Circle" }), el("th", { text: "Status" }), el("th", { text: "Members" }), el("th", { text: "Contribution" }), el("th", { text: "Cycles" }), el("th", { text: "Created" }));
    var rows = g.items.length ? g.items.map(function (i) {
      return el("tr", { class: "tap", onclick: function () { STATE.groupId = i.id; STATE.tab = "group"; render(); } },
        cell(i.name), cell(badge(i.status, statusBadge(i.status))),
        cell(i.member_count + " / " + i.member_limit), cell(money(i.contribution_amount)),
        cell(i.cycles_complete + " / " + i.cycles_total), cell(shortDate(i.created_at)));
    }) : [emptyRow(6, "No circles yet.")];
    return el("div", { class: "tablewrap" }, el("table", {}, el("thead", {}, head), el("tbody", {}, rows)));
  }
  async function groupDetailView() {
    var d = await api("/groups/" + STATE.groupId);
    var repByUser = {}; (d.reputations || []).forEach(function (r) { repByUser[r.user_id] = r; });
    var wrap = el("div", {});
    wrap.appendChild(el("button", { text: "← Circles", onclick: function () { STATE.tab = "groups"; render(); } }));
    wrap.appendChild(el("div", { class: "section-title", text: d.group.name + " · " + d.group.status }));
    wrap.appendChild(el("div", { class: "section-title", text: "Members" }));
    var mhead = el("tr", {}, el("th", { text: "Member" }), el("th", { text: "Role" }), el("th", { text: "Payout #" }), el("th", { text: "Reliability" }));
    var mrows = d.members.map(function (m) {
      var rep = repByUser[m.user_id];
      var repCell = rep && rep.score != null ? badge(rep.score + " · " + rep.label, statusBadge(rep.label === "excellent" || rep.label === "good" ? "ok" : rep.label === "fair" ? "late" : rep.label === "poor" ? "disputed" : ""))
        : badge("unrated", "b-muted");
      return el("tr", {}, cell(el("span", { class: "mono", text: shortId(m.user_id) })), cell(m.role), cell(m.payout_position == null ? "—" : String(m.payout_position)), cell(repCell));
    });
    wrap.appendChild(el("div", { class: "tablewrap" }, el("table", {}, el("thead", {}, mhead), el("tbody", {}, mrows))));
    wrap.appendChild(el("div", { class: "section-title", text: "Payments" }));
    var phead = el("tr", {}, el("th", { text: "Payer" }), el("th", { text: "Payee" }), el("th", { text: "Amount" }), el("th", { text: "Method" }), el("th", { text: "Status" }));
    var prows = d.payments.length ? d.payments.map(function (p) {
      return el("tr", {}, cell(el("span", { class: "mono", text: shortId(p.payer_id) })), cell(el("span", { class: "mono", text: shortId(p.payee_id) })),
        cell(money(p.amount)), cell(p.method || "—"), cell(badge(p.status, statusBadge(p.status))));
    }) : [emptyRow(5, "No payments yet.")];
    wrap.appendChild(el("div", { class: "tablewrap" }, el("table", {}, el("thead", {}, phead), el("tbody", {}, prows))));
    return wrap;
  }
  async function activityView() {
    var a = await api("/activity?limit=100");
    var head = el("tr", {}, el("th", { text: "When" }), el("th", { text: "Event" }), el("th", { text: "Circle" }), el("th", { text: "Payer" }), el("th", { text: "Payee" }), el("th", { text: "Amount" }));
    var rows = a.items.length ? a.items.map(function (i) {
      return el("tr", {}, cell(shortDate(i.at)), cell(badge(i.event, statusBadge(i.event === "confirmed" ? "confirmed" : i.event === "disputed" ? "disputed" : i.event === "marked" ? "marked" : ""))),
        cell(i.group_name), cell(el("span", { class: "mono", text: shortId(i.payer_id) })), cell(el("span", { class: "mono", text: shortId(i.payee_id) })), cell(money(i.amount)));
    }) : [emptyRow(6, "No activity yet.")];
    return el("div", { class: "tablewrap" }, el("table", {}, el("thead", {}, head), el("tbody", {}, rows)));
  }

  var VIEWS = { overview: overviewView, risk: riskView, disputes: disputesView, groups: groupsView, group: groupDetailView, activity: activityView };

  async function render() {
    STATE.err = null;
    shell(loading());
    try {
      var view = await (VIEWS[STATE.tab] || overviewView)();
      STATE.err = null;
      shell(view);
    } catch (e) {
      STATE.err = e.message;
      shell(el("div", {}));
    }
  }

  window.addEventListener("DOMContentLoaded", function () {
    appEl = document.getElementById("app");
    render();
  });
})();
