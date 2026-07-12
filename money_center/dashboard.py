#!/usr/bin/env python3
"""
money_center/dashboard.py
─────────────────────────────────────────────────────────────────────────────
Flask web dashboard for the Money Center.
Runs on http://127.0.0.1:7777 by default (loopback only).

Usage:
  python dashboard.py
  python dashboard.py --port 8888

SECURITY: this dashboard can launch arbitrary shell commands, so it is:
  • bound to loopback (127.0.0.1) by default — pass --host to expose it, which
    then REQUIRES an operator token;
  • gated by a session login when MONEY_CENTER_TOKEN / ADMIN_TOKEN is set;
  • CSRF-protected on every state-changing (POST) route;
  • HTML-escaped on all asset/user-derived output.
─────────────────────────────────────────────────────────────────────────────
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from flask import (Flask, abort, redirect, render_template_string, request,
                   session, url_for)
from markupsafe import Markup, escape as _e

from money_center import registry as reg
from money_center import security

app = Flask(__name__)
app.secret_key = security.session_secret()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
)

# ─── CSS ─────────────────────────────────────────────────────────────────────

_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #0d0d0d; color: #e0e0e0; font-family: 'Courier New', monospace; font-size: 14px; }
a { color: #4fc3f7; text-decoration: none; }
a:hover { text-decoration: underline; }
h1 { color: #4fc3f7; margin-bottom: 1rem; font-size: 1.4rem; }
h2 { color: #81d4fa; margin-bottom: .75rem; font-size: 1.1rem; }
.container { max-width: 1200px; margin: 0 auto; padding: 1.5rem; }
.nav { background: #111; border-bottom: 1px solid #222; padding: .75rem 1.5rem; display: flex; gap: 1.5rem; align-items: center; }
.nav a { color: #aaa; font-size: .85rem; }
.nav a:hover { color: #4fc3f7; }
.nav .brand { color: #4fc3f7; font-weight: bold; font-size: 1rem; }
table { width: 100%; border-collapse: collapse; margin-bottom: 1.5rem; }
th { background: #1a1a2e; color: #81d4fa; padding: .6rem .8rem; text-align: left; border-bottom: 1px solid #333; }
td { padding: .55rem .8rem; border-bottom: 1px solid #1a1a1a; vertical-align: middle; }
tr:hover td { background: #151515; }
.dot-green { color: #4caf50; font-size: 1rem; }
.dot-red   { color: #f44336; font-size: 1rem; }
.dot-grey  { color: #666; font-size: 1rem; }
.dot-yellow{ color: #ff9800; font-size: 1rem; }
.btn { display: inline-block; padding: .3rem .75rem; border-radius: 4px; font-size: .8rem; border: none; cursor: pointer; font-family: inherit; }
.btn-start { background: #1b5e20; color: #a5d6a7; }
.btn-start:hover { background: #2e7d32; }
.btn-stop  { background: #b71c1c; color: #ef9a9a; }
.btn-stop:hover  { background: #c62828; }
.btn-edit  { background: #0d47a1; color: #90caf9; }
.btn-edit:hover  { background: #1565c0; }
.btn-del   { background: #37474f; color: #b0bec5; }
.btn-del:hover   { background: #455a64; }
.total-row td { background: #1a1a2e; font-weight: bold; color: #fff; border-top: 2px solid #4fc3f7; }
.card { background: #111; border: 1px solid #222; border-radius: 6px; padding: 1.2rem; margin-bottom: 1.2rem; }
.field-row { display: flex; gap: .5rem; margin-bottom: .4rem; }
.field-label { color: #81d4fa; min-width: 160px; font-size: .85rem; }
.field-value { color: #e0e0e0; }
.log-box { background: #0a0a0a; border: 1px solid #222; border-radius: 4px; padding: 1rem; font-size: .8rem; max-height: 400px; overflow-y: auto; white-space: pre-wrap; color: #ccc; }
form input, form select, form textarea {
  background: #1a1a1a; border: 1px solid #333; color: #e0e0e0;
  padding: .4rem .6rem; border-radius: 4px; font-family: inherit; font-size: .9rem; width: 100%;
}
form label { display: block; color: #81d4fa; margin-bottom: .25rem; font-size: .85rem; }
.form-row { margin-bottom: .9rem; }
.form-row-3 { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: .75rem; margin-bottom: .9rem; }
.flash { padding: .6rem 1rem; border-radius: 4px; margin-bottom: 1rem; }
.flash-ok  { background: #1b5e20; color: #c8e6c9; }
.flash-err { background: #b71c1c; color: #ffcdd2; }
"""

# ─── Template helpers ─────────────────────────────────────────────────────────

_BASE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Money Center</title>
  <style>""" + _CSS + """</style>
</head>
<body>
<div class="nav">
  <span class="brand">💰 Money Center</span>
  <a href="/">Assets</a>
  <a href="/report">Revenue Report</a>
  <a href="/add">Add Asset</a>
</div>
<div class="container">
{% if flash_msg %}
  <div class="flash {{ flash_cls }}">{{ flash_msg }}</div>
{% endif %}
{{ content }}
</div>
</body>
</html>"""


def _render(content: str, flash_msg: str = "", flash_cls: str = "flash-ok"):
    # autoescape=True so request-derived flash_msg/flash_cls can't inject markup;
    # `content` is HTML we assembled ourselves (with every dynamic value already
    # escaped at the build site) so it is marked safe.
    from jinja2 import Environment
    env = Environment(autoescape=True)
    tmpl = env.from_string(_BASE)
    return tmpl.render(content=Markup(content), flash_msg=flash_msg, flash_cls=flash_cls)


def _csrf() -> str:
    """Ensure the session carries a CSRF token and return it (embed in every form)."""
    if "csrf" not in session:
        session["csrf"] = security.new_csrf_token()
    return session["csrf"]


def _csrf_field() -> str:
    return f'<input type="hidden" name="csrf" value="{_e(_csrf())}">'


def _dot(status: str) -> str:
    return {
        "running": '<span class="dot-green">🟢</span>',
        "idle":    '<span class="dot-grey">⚪</span>',
        "stopped": '<span class="dot-yellow">🟡</span>',
        "error":   '<span class="dot-red">🔴</span>',
    }.get(status, '<span class="dot-grey">⚪</span>')


def _fmt_usd(n) -> str:
    try:
        return f"${float(n):,.0f}"
    except Exception:
        return str(n)


def _fmt_date(iso) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(iso)[:16]


def _ssd_error():
    ssd = reg._cfg.get("ssd_volume", "/Volumes/Wheellsverse")
    return _render(
        f'<div class="card" style="border-color:#f44336">'
        f'<h1>⚠️ SSD Not Mounted</h1>'
        f'<p style="color:#ef9a9a">The volume <code>{_e(ssd)}</code> is not accessible.<br>'
        f'Connect the SSD and reload.</p></div>'
    )


# ─── Auth / CSRF guard ─────────────────────────────────────────────────────────

_LOGIN_HTML = """
<h1>🔒 Money Center — Sign in</h1>
<div class="card" style="max-width:360px">
<form method="post" action="/login">
  {csrf}
  <div class="form-row"><label>Operator token</label>
    <input type="password" name="token" autofocus autocomplete="current-password"></div>
  <button class="btn btn-start" type="submit">Sign in</button>
</form>
</div>"""


@app.before_request
def _guard():
    # CSRF on every state-changing request (covers /login too).
    if request.method == "POST":
        if not security.csrf_valid(request.form.get("csrf", ""), session.get("csrf", "")):
            abort(400)
    # The login page is always reachable; everything else needs a session when a
    # token is configured.
    if request.endpoint in ("login", "static"):
        return
    if security.admin_token() and not session.get("mc_authed"):
        if request.method == "POST":
            abort(403)
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    token = security.admin_token()
    if request.method == "POST":
        if token and security.token_valid(request.form.get("token", ""), token):
            session["mc_authed"] = True
            return redirect(url_for("index"))
        return _render(_LOGIN_HTML.format(csrf=_csrf_field()),
                       "Invalid token.", "flash-err")
    if not token:
        # No token configured → nothing to sign in against (loopback-trusted mode).
        return redirect(url_for("index"))
    return _render(_LOGIN_HTML.format(csrf=_csrf_field()))


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    if not reg.check_ssd():
        return _ssd_error()

    assets = reg.load()
    summary = reg.revenue_summary(assets)
    totals = summary["total"]

    flash_msg = request.args.get("msg", "")
    flash_cls = request.args.get("cls", "flash-ok")
    csrf = _csrf_field()

    rows = ""
    for a in assets:
        st = a.get("status", "idle")
        est = a.get("monthly_estimate_usd", {})
        mid = _fmt_usd(est.get("mid", 0))
        eta = a.get("time_to_first_revenue_days", 0)
        aid = _e(a["id"])
        rows += f"""
        <tr>
          <td>{_dot(st)}</td>
          <td><a href="/asset/{aid}">{_e(a['name'])}</a></td>
          <td>{_e(a.get('category',''))}</td>
          <td>{mid}</td>
          <td>{_e(eta)}d</td>
          <td>
            <form method="post" action="/start/{aid}" style="display:inline">
              {csrf}
              <button class="btn btn-start">▶ Start</button>
            </form>
            <form method="post" action="/stop/{aid}" style="display:inline"
                  onsubmit="return confirm('Stop this asset?')">
              {csrf}
              <button class="btn btn-stop">⏹ Stop</button>
            </form>
            <a href="/asset/{aid}" class="btn btn-edit">👁 View</a>
            <a href="/logs/{aid}" class="btn btn-edit">📋 Logs</a>
          </td>
        </tr>"""

    total_row = f"""
    <tr class="total-row">
      <td colspan="3">TOTAL MONTHLY ESTIMATE</td>
      <td>Mid: {_fmt_usd(totals['mid'])}</td>
      <td colspan="2">Low: {_fmt_usd(totals['low'])} &nbsp; High: {_fmt_usd(totals['high'])}</td>
    </tr>"""

    content = f"""
    <h1>💰 Income Assets</h1>
    <table>
      <thead>
        <tr>
          <th>Status</th>
          <th>Name</th>
          <th>Category</th>
          <th>Monthly Mid</th>
          <th>ETA</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>{rows}{total_row}</tbody>
    </table>"""

    return _render(content, flash_msg, flash_cls)


@app.route("/asset/<asset_id>")
def asset_detail(asset_id):
    if not reg.check_ssd():
        return _ssd_error()
    a = reg.get(asset_id)
    if not a:
        abort(404)

    est = a.get("monthly_estimate_usd", {})
    st = a.get("status", "idle")
    aid = _e(asset_id)

    def row(label, value):
        return f'<div class="field-row"><span class="field-label">{label}</span><span class="field-value">{value}</span></div>'

    fields = "".join([
        row("ID", _e(a["id"])),
        row("Name", _e(a["name"])),
        row("Category", _e(a.get("category", ""))),
        row("Status", f"{_dot(st)} {_e(st)}"),
        row("Description", _e(a.get("description", ""))),
        row("Revenue model", _e(a.get("revenue_model", ""))),
        row("Monthly Low", _fmt_usd(est.get("low", 0))),
        row("Monthly Mid", _fmt_usd(est.get("mid", 0))),
        row("Monthly High", _fmt_usd(est.get("high", 0))),
        row("Total revenue", _fmt_usd(a.get("total_revenue_usd", 0))),
        row("ETA first revenue", f"{_e(a.get('time_to_first_revenue_days', 0))} days"),
        row("Run command", f"<code>{_e(a.get('run_command',''))}</code>"),
        row("Stop command", f"<code>{_e(a.get('stop_command',''))}</code>"),
        row("Working dir", f"<code>{_e(a.get('working_dir',''))}</code>"),
        row("Tags", _e(", ".join(a.get("tags", [])))),
        row("Notes", _e(a.get("notes", ""))),
        row("Last run", _fmt_date(a.get("last_run"))),
        row("Last stop", _fmt_date(a.get("last_stop"))),
        row("Created", _fmt_date(a.get("created_at"))),
        row("Updated", _fmt_date(a.get("updated_at"))),
    ])

    log_path = HERE / "logs" / f"{asset_id}.log"
    log_tail = ""
    if log_path.exists():
        text = log_path.read_text(encoding="utf-8", errors="replace")
        log_tail = "\n".join(text.splitlines()[-50:])

    csrf = _csrf_field()
    actions = f"""
    <div style="margin: 1rem 0; display: flex; gap: .75rem;">
      <form method="post" action="/start/{aid}">
        {csrf}
        <button class="btn btn-start">▶ Start</button>
      </form>
      <form method="post" action="/stop/{aid}"
            onsubmit="return confirm('Stop this asset?')">
        {csrf}
        <button class="btn btn-stop">⏹ Stop</button>
      </form>
      <a href="/edit/{aid}" class="btn btn-edit">✏️ Edit</a>
      <form method="post" action="/remove/{aid}"
            onsubmit="return confirm('Permanently delete this asset?')">
        {csrf}
        <button class="btn btn-del">🗑 Delete</button>
      </form>
    </div>"""

    log_section = f"""
    <h2>📋 Recent Logs</h2>
    <div class="log-box">{_e(log_tail) or '(no logs yet)'}</div>
    """

    content = f"""
    <h1>{_e(a['name'])}</h1>
    {actions}
    <div class="card">{fields}</div>
    {log_section}"""

    return _render(content)


@app.route("/report")
def report():
    if not reg.check_ssd():
        return _ssd_error()

    assets = reg.load()
    summary = reg.revenue_summary(assets)
    totals = summary["total"]

    rows = ""
    for cat, est in sorted(summary["by_category"].items()):
        rows += f"""<tr>
          <td>{_e(cat)}</td>
          <td>{_fmt_usd(est['low'])}</td>
          <td style="color:#4caf50;font-weight:bold">{_fmt_usd(est['mid'])}</td>
          <td>{_fmt_usd(est['high'])}</td>
        </tr>"""

    total_row = f"""<tr class="total-row">
      <td>GRAND TOTAL</td>
      <td>{_fmt_usd(totals['low'])}</td>
      <td style="color:#4caf50">{_fmt_usd(totals['mid'])}</td>
      <td>{_fmt_usd(totals['high'])}</td>
    </tr>"""

    content = f"""
    <h1>💵 Revenue Forecast — Monthly</h1>
    <table>
      <thead><tr><th>Category</th><th>Low</th><th>Mid</th><th>High</th></tr></thead>
      <tbody>{rows}{total_row}</tbody>
    </table>"""

    return _render(content)


@app.route("/add", methods=["GET", "POST"])
def add_asset():
    if not reg.check_ssd():
        return _ssd_error()

    if request.method == "POST":
        f = request.form
        try:
            low = float(f.get("est_low", 0) or 0)
            mid = float(f.get("est_mid", 0) or 0)
            high = float(f.get("est_high", 0) or 0)
        except ValueError:
            low = mid = high = 0

        now = datetime.now(timezone.utc).isoformat()
        a = {
            "id": f.get("id", "").strip(),
            "name": f.get("name", "").strip(),
            "category": f.get("category", "service"),
            "description": f.get("description", "").strip(),
            "revenue_model": f.get("revenue_model", "other").strip(),
            "monthly_estimate_usd": {"low": low, "mid": mid, "high": high},
            "time_to_first_revenue_days": int(f.get("eta_days", 30) or 30),
            "status": "idle",
            "last_run": None, "last_stop": None, "last_revenue_check": None,
            "total_revenue_usd": 0,
            "run_command": f.get("run_command", "").strip(),
            "stop_command": f.get("stop_command", "").strip(),
            "working_dir": f.get("working_dir", "").strip(),
            "tags": [t.strip() for t in f.get("tags", "").split(",") if t.strip()],
            "notes": f.get("notes", "").strip(),
            "created_at": now,
            "updated_at": now,
        }
        errors = reg.validate(a)
        if errors:
            return redirect(url_for("index", msg=" | ".join(errors), cls="flash-err"))
        if reg.exists(a["id"]):
            return redirect(url_for("index", msg=f"Asset '{a['id']}' already exists.", cls="flash-err"))
        reg.upsert(a)
        reg._log("info", a["id"], "add", "Asset added via dashboard")
        return redirect(url_for("index", msg=f"Asset '{a['id']}' added.", cls="flash-ok"))

    # GET — render form
    cats_opts = "".join(f'<option value="{_e(c)}">{_e(c)}</option>' for c in sorted(reg.VALID_CATEGORIES))
    content = f"""
    <h1>➕ Add Asset</h1>
    <div class="card">
    <form method="post">
      {_csrf_field()}
      <div class="form-row"><label>ID (slug)</label><input name="id" required placeholder="my_product"></div>
      <div class="form-row"><label>Name</label><input name="name" required placeholder="My Product"></div>
      <div class="form-row"><label>Category</label><select name="category">{cats_opts}</select></div>
      <div class="form-row"><label>Description</label><input name="description" placeholder="One sentence description"></div>
      <div class="form-row"><label>Revenue model</label><input name="revenue_model" placeholder="subscription / sales / royalty / ads / consulting / other"></div>
      <div class="form-row-3">
        <div><label>Monthly Low ($)</label><input name="est_low" type="number" step="0.01" value="0"></div>
        <div><label>Monthly Mid ($)</label><input name="est_mid" type="number" step="0.01" value="0"></div>
        <div><label>Monthly High ($)</label><input name="est_high" type="number" step="0.01" value="0"></div>
      </div>
      <div class="form-row"><label>Days to first revenue</label><input name="eta_days" type="number" value="30"></div>
      <div class="form-row"><label>Run command</label><input name="run_command" placeholder="python /path/to/run.py"></div>
      <div class="form-row"><label>Stop command</label><input name="stop_command" placeholder="pkill -f 'run.py'"></div>
      <div class="form-row"><label>Working directory</label><input name="working_dir" value="/Users/jhonwheeler/wheellsverse_bots"></div>
      <div class="form-row"><label>Tags (comma-separated)</label><input name="tags" placeholder="ai, automation, saas"></div>
      <div class="form-row"><label>Notes</label><textarea name="notes" rows="3"></textarea></div>
      <button class="btn btn-start" type="submit">✓ Save Asset</button>
      <a href="/" class="btn btn-del" style="margin-left:.5rem">Cancel</a>
    </form>
    </div>"""
    return _render(content)


@app.route("/edit/<asset_id>", methods=["GET", "POST"])
def edit_asset(asset_id):
    if not reg.check_ssd():
        return _ssd_error()

    a = reg.get(asset_id)
    if not a:
        abort(404)

    if request.method == "POST":
        f = request.form
        try:
            low = float(f.get("est_low", 0) or 0)
            mid = float(f.get("est_mid", 0) or 0)
            high = float(f.get("est_high", 0) or 0)
        except ValueError:
            low = mid = high = 0

        a.update({
            "name": f.get("name", a["name"]).strip(),
            "category": f.get("category", a["category"]),
            "description": f.get("description", "").strip(),
            "revenue_model": f.get("revenue_model", "").strip(),
            "monthly_estimate_usd": {"low": low, "mid": mid, "high": high},
            "time_to_first_revenue_days": int(f.get("eta_days", 30) or 30),
            "run_command": f.get("run_command", "").strip(),
            "stop_command": f.get("stop_command", "").strip(),
            "working_dir": f.get("working_dir", "").strip(),
            "tags": [t.strip() for t in f.get("tags", "").split(",") if t.strip()],
            "notes": f.get("notes", "").strip(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        errors = reg.validate(a)
        if errors:
            return redirect(url_for("index", msg=" | ".join(errors), cls="flash-err"))
        reg.upsert(a)
        reg._log("info", asset_id, "edit", "Asset updated via dashboard")
        return redirect(url_for("asset_detail", asset_id=asset_id, msg="Saved."))

    est = a.get("monthly_estimate_usd", {"low": 0, "mid": 0, "high": 0})
    cats_opts = "".join(
        f'<option value="{_e(c)}" {"selected" if c == a.get("category") else ""}>{_e(c)}</option>'
        for c in sorted(reg.VALID_CATEGORIES)
    )
    content = f"""
    <h1>✏️ Edit: {_e(a['name'])}</h1>
    <div class="card">
    <form method="post">
      {_csrf_field()}
      <div class="form-row"><label>Name</label><input name="name" value="{_e(a['name'])}" required></div>
      <div class="form-row"><label>Category</label><select name="category">{cats_opts}</select></div>
      <div class="form-row"><label>Description</label><input name="description" value="{_e(a.get('description',''))}"></div>
      <div class="form-row"><label>Revenue model</label><input name="revenue_model" value="{_e(a.get('revenue_model',''))}"></div>
      <div class="form-row-3">
        <div><label>Monthly Low ($)</label><input name="est_low" type="number" step="0.01" value="{_e(est.get('low',0))}"></div>
        <div><label>Monthly Mid ($)</label><input name="est_mid" type="number" step="0.01" value="{_e(est.get('mid',0))}"></div>
        <div><label>Monthly High ($)</label><input name="est_high" type="number" step="0.01" value="{_e(est.get('high',0))}"></div>
      </div>
      <div class="form-row"><label>Days to first revenue</label><input name="eta_days" type="number" value="{_e(a.get('time_to_first_revenue_days',30))}"></div>
      <div class="form-row"><label>Run command</label><input name="run_command" value="{_e(a.get('run_command',''))}"></div>
      <div class="form-row"><label>Stop command</label><input name="stop_command" value="{_e(a.get('stop_command',''))}"></div>
      <div class="form-row"><label>Working directory</label><input name="working_dir" value="{_e(a.get('working_dir',''))}"></div>
      <div class="form-row"><label>Tags (comma-separated)</label><input name="tags" value="{_e(','.join(a.get('tags',[])))}"></div>
      <div class="form-row"><label>Notes</label><textarea name="notes" rows="3">{_e(a.get('notes',''))}</textarea></div>
      <button class="btn btn-start" type="submit">✓ Save</button>
      <a href="/asset/{_e(asset_id)}" class="btn btn-del" style="margin-left:.5rem">Cancel</a>
    </form>
    </div>"""
    return _render(content)


@app.route("/start/<asset_id>", methods=["POST"])
def start_asset(asset_id):
    if not reg.check_ssd():
        return redirect(url_for("index", msg="SSD not mounted.", cls="flash-err"))

    a = reg.get(asset_id)
    if not a:
        return redirect(url_for("index", msg=f"Asset '{asset_id}' not found.", cls="flash-err"))

    cmd = a.get("run_command", "").strip()
    wdir = a.get("working_dir", str(HERE.parent))

    if not cmd:
        return redirect(url_for("index", msg=f"No run_command for '{asset_id}'.", cls="flash-err"))

    try:
        log_path = HERE / "logs" / f"{asset_id}.log"
        log_fd = open(log_path, "a", encoding="utf-8")
        subprocess.Popen(
            cmd, shell=True, cwd=wdir,
            stdout=log_fd, stderr=log_fd,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        reg.update_status(asset_id, "running", "last_run")
        reg._log("info", asset_id, "start", f"Started via dashboard: {cmd}")
        return redirect(url_for("index", msg=f"'{asset_id}' started."))
    except Exception as e:
        reg.update_status(asset_id, "error")
        reg._log("error", asset_id, "start", str(e))
        return redirect(url_for("index", msg=f"Start failed: {e}", cls="flash-err"))


@app.route("/stop/<asset_id>", methods=["POST"])
def stop_asset(asset_id):
    if not reg.check_ssd():
        return redirect(url_for("index", msg="SSD not mounted.", cls="flash-err"))

    a = reg.get(asset_id)
    if not a:
        return redirect(url_for("index", msg=f"Asset '{asset_id}' not found.", cls="flash-err"))

    cmd = a.get("stop_command", "").strip()
    if not cmd:
        return redirect(url_for("index", msg=f"No stop_command for '{asset_id}'.", cls="flash-err"))

    try:
        subprocess.run(cmd, shell=True, timeout=10)
        reg.update_status(asset_id, "stopped", "last_stop")
        reg._log("info", asset_id, "stop", f"Stopped via dashboard: {cmd}")
        return redirect(url_for("index", msg=f"'{asset_id}' stopped."))
    except Exception as e:
        reg._log("error", asset_id, "stop", str(e))
        return redirect(url_for("index", msg=f"Stop failed: {e}", cls="flash-err"))


@app.route("/remove/<asset_id>", methods=["POST"])
def remove_asset(asset_id):
    if not reg.check_ssd():
        return redirect(url_for("index", msg="SSD not mounted.", cls="flash-err"))
    reg.remove(asset_id)
    return redirect(url_for("index", msg=f"'{asset_id}' removed."))


@app.route("/logs/<asset_id>")
def logs_page(asset_id):
    if not reg.check_ssd():
        return _ssd_error()

    log_path = HERE / "logs" / f"{asset_id}.log"
    text = ""
    if log_path.exists():
        raw = log_path.read_text(encoding="utf-8", errors="replace")
        text = "\n".join(raw.splitlines()[-100:])

    content = f"""
    <h1>📋 Logs: {_e(asset_id)}</h1>
    <a href="/asset/{_e(asset_id)}" style="font-size:.85rem">← Back to asset</a>
    <div class="log-box" style="margin-top:1rem">{_e(text) or '(no logs yet)'}</div>"""
    return _render(content)


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=reg._cfg.get("dashboard_port", 7777))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    # Fail closed: a shell-executing dashboard must not be exposed to the network
    # without an operator token.
    if not security.network_bind_allowed(args.host, security.admin_token()):
        print(f"✗ Refusing to bind {args.host} without an operator token. "
              f"Set MONEY_CENTER_TOKEN (or ADMIN_TOKEN), or bind 127.0.0.1.")
        sys.exit(1)

    if not reg.check_ssd():
        ssd = reg._cfg.get("ssd_volume", "/Volumes/Wheellsverse")
        print(f"✗ SSD not mounted: '{ssd}'. Connect the drive and retry.")
        sys.exit(1)

    if not security.admin_token():
        print("⚠ No MONEY_CENTER_TOKEN set — running loopback-only with no login. "
              "Set a token to require sign-in.")
    print(f"💰 Money Center dashboard → http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
