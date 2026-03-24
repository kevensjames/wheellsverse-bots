#!/usr/bin/env python3
"""
core/dashboard.py
─────────────────────────────────────────────────────────────────────────────
WheellsVerse Bot Dashboard
- CLI mode: rich terminal UI with live status
- Web mode: Flask API + minimal HTML dashboard on port 5050
─────────────────────────────────────────────────────────────────────────────
"""

import os
import sys
import json
import time
import threading
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

console = Console()


# ─── CLI Dashboard ─────────────────────────────────────────────────────────────

class CLIDashboard:
    """Live-updating terminal dashboard showing all bot statuses."""

    def __init__(self, orchestrator=None):
        if orchestrator is None:
            from core.orchestrator import get_orchestrator
            self.orch = get_orchestrator()
        else:
            self.orch = orchestrator

    def _build_header(self) -> Panel:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total = len(self.orch.bots)
        done = sum(1 for b in self.orch.bots.values() if b.status == "done")
        err = sum(1 for b in self.orch.bots.values() if b.status == "error")
        running = sum(1 for b in self.orch.bots.values() if b.status == "running")
        text = (f"[bold cyan]WheellsVerse Bot Ecosystem[/bold cyan]  |  "
                f"[white]{now}[/white]  |  "
                f"[cyan]Total: {total}[/cyan]  "
                f"[green]Done: {done}[/green]  "
                f"[red]Errors: {err}[/red]  "
                f"[yellow]Running: {running}[/yellow]")
        return Panel(text, style="bold")

    def _build_table(self) -> Table:
        tbl = Table(show_header=True, header_style="bold cyan",
                    expand=True, box=None)
        tbl.add_column("#", width=4, style="dim")
        tbl.add_column("Category", min_width=20)
        tbl.add_column("Bot", min_width=30)
        tbl.add_column("Status", min_width=10)
        tbl.add_column("Runs", justify="right", width=6)
        tbl.add_column("Last Run", min_width=20)

        STATUS_COLOR = {"idle": "dim", "running": "yellow",
                        "done": "green", "error": "red bold"}

        for i, (full_name, bot) in enumerate(sorted(self.orch.bots.items()), 1):
            s = bot.get_status()
            c = STATUS_COLOR.get(s["status"], "white")
            icon = {"idle": "○", "running": "◉", "done": "✓", "error": "✗"}.get(
                s["status"], "?")
            tbl.add_row(
                str(i),
                f"[cyan]{s['category']}[/cyan]",
                s["name"],
                f"[{c}]{icon} {s['status']}[/{c}]",
                str(s["run_count"]),
                s["last_run"] or "—"
            )
        return tbl

    def run_live(self, refresh_rate: float = 2.0):
        """Run the live dashboard until Ctrl+C."""
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body")
        )

        with Live(layout, refresh_per_second=1 / refresh_rate, screen=True):
            try:
                while True:
                    layout["header"].update(self._build_header())
                    layout["body"].update(
                        Panel(self._build_table(), title="🤖 Bot Status",
                              border_style="cyan")
                    )
                    time.sleep(refresh_rate)
            except KeyboardInterrupt:
                pass

    def print_once(self):
        """Print a single snapshot of the dashboard."""
        console.print(self._build_header())
        console.print(Panel(self._build_table(), title="🤖 Bot Status",
                            border_style="cyan"))


# ─── Web Dashboard ─────────────────────────────────────────────────────────────

WEB_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WheellsVerse Bot Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', monospace; background: #0d1117; color: #e6edf3; }
  header { background: #161b22; padding: 16px 24px; border-bottom: 1px solid #30363d;
           display: flex; align-items: center; justify-content: space-between; }
  header h1 { font-size: 1.4rem; color: #58a6ff; }
  .stats { display: flex; gap: 20px; padding: 16px 24px; }
  .stat-card { background: #161b22; border: 1px solid #30363d; border-radius: 8px;
               padding: 12px 20px; min-width: 100px; text-align: center; }
  .stat-card .num { font-size: 2rem; font-weight: bold; }
  .stat-card .lbl { font-size: 0.75rem; color: #8b949e; margin-top: 4px; }
  .total .num { color: #58a6ff; }
  .done .num  { color: #3fb950; }
  .error .num { color: #f85149; }
  .idle .num  { color: #8b949e; }
  table { width: 100%; border-collapse: collapse; margin: 0 24px; width: calc(100% - 48px); }
  th { background: #161b22; padding: 10px 12px; text-align: left; font-size: 0.8rem;
       color: #8b949e; border-bottom: 1px solid #30363d; }
  td { padding: 10px 12px; border-bottom: 1px solid #21262d; font-size: 0.85rem; }
  tr:hover td { background: #161b22; }
  .badge { padding: 3px 8px; border-radius: 12px; font-size: 0.75rem; font-weight: 600; }
  .done   { background: #1f4a2e; color: #3fb950; }
  .error  { background: #4a1f1f; color: #f85149; }
  .running{ background: #3d3000; color: #d29922; }
  .idle   { background: #1c2128; color: #8b949e; }
  .run-btn { background: #238636; color: white; border: none; padding: 5px 12px;
             border-radius: 6px; cursor: pointer; font-size: 0.8rem; }
  .run-btn:hover { background: #2ea043; }
  #refresh { color: #8b949e; font-size: 0.8rem; }
  .panel { background: #0d1117; padding: 0 0 24px 0; }
</style>
</head>
<body>
<header>
  <h1>🤖 WheellsVerse Bot Ecosystem</h1>
  <span id="refresh">Auto-refresh: 5s</span>
</header>
<div class="stats" id="stats"></div>
<div class="panel">
  <table id="bot-table">
    <thead>
      <tr>
        <th>#</th><th>Category</th><th>Bot Name</th>
        <th>Status</th><th>Runs</th><th>Last Run</th><th>Description</th><th>Action</th>
      </tr>
    </thead>
    <tbody id="bot-rows"></tbody>
  </table>
</div>
<script>
async function fetchStatus() {
  const r = await fetch('/api/status');
  const data = await r.json();

  // Stats
  const total = data.bots.length;
  const done = data.bots.filter(b => b.status === 'done').length;
  const err = data.bots.filter(b => b.status === 'error').length;
  const running = data.bots.filter(b => b.status === 'running').length;
  const idle = data.bots.filter(b => b.status === 'idle').length;

  document.getElementById('stats').innerHTML = `
    <div class="stat-card total"><div class="num">${total}</div><div class="lbl">Total Bots</div></div>
    <div class="stat-card done"><div class="num">${done}</div><div class="lbl">Done</div></div>
    <div class="stat-card error"><div class="num">${err}</div><div class="lbl">Errors</div></div>
    <div class="stat-card idle"><div class="num">${idle}</div><div class="lbl">Idle</div></div>`;

  // Table
  let rows = '';
  data.bots.forEach((b, i) => {
    rows += `<tr>
      <td>${i+1}</td>
      <td><code>${b.category}</code></td>
      <td>${b.name}</td>
      <td><span class="badge ${b.status}">${b.status}</span></td>
      <td>${b.run_count}</td>
      <td>${b.last_run || '—'}</td>
      <td style="color:#8b949e;font-size:0.8rem">${b.description || ''}</td>
      <td><button class="run-btn" onclick="runBot('${b.full_name}')">▶ Run</button></td>
    </tr>`;
  });
  document.getElementById('bot-rows').innerHTML = rows;
  document.getElementById('refresh').textContent = 'Last: ' + new Date().toLocaleTimeString();
}

async function runBot(name) {
  await fetch('/api/run/' + encodeURIComponent(name), { method: 'POST' });
  setTimeout(fetchStatus, 2000);
}

fetchStatus();
setInterval(fetchStatus, 5000);
</script>
</body>
</html>"""


def create_web_dashboard(orchestrator=None):
    """Create and return a Flask app serving the dashboard."""
    try:
        from flask import Flask, jsonify, request
        from flask_cors import CORS
    except ImportError:
        console.print("[red]Flask not installed. Run: pip install flask flask-cors[/red]")
        return None

    if orchestrator is None:
        from core.orchestrator import get_orchestrator
        orchestrator = get_orchestrator()

    app = Flask(__name__)
    CORS(app)

    @app.route("/")
    def index():
        return WEB_HTML, 200, {"Content-Type": "text/html"}

    @app.route("/api/status")
    def status():
        bots_data = []
        for full_name, bot in sorted(orchestrator.bots.items()):
            s = bot.get_status()
            bots_data.append({
                "full_name": full_name,
                "name": s["name"],
                "category": s["category"],
                "status": s["status"],
                "run_count": s["run_count"],
                "last_run": s["last_run"],
                "description": orchestrator.registry[full_name].get("description", "")
            })
        return jsonify({"bots": bots_data, "timestamp": datetime.now().isoformat()})

    @app.route("/api/run/<path:bot_name>", methods=["POST"])
    def run_bot(bot_name):
        try:
            import threading
            t = threading.Thread(
                target=orchestrator.run_bot,
                args=(bot_name,),
                daemon=True
            )
            t.start()
            return jsonify({"status": "started", "bot": bot_name})
        except Exception as e:
            return jsonify({"status": "error", "error": str(e)}), 400

    @app.route("/api/bots")
    def list_bots():
        return jsonify(orchestrator.list_bots())

    @app.route("/api/categories")
    def list_categories():
        return jsonify(orchestrator.get_categories())

    return app


def launch_web_dashboard(orchestrator=None, port: int = None):
    """Launch the web dashboard in a background thread."""
    port = port or int(os.getenv("DASHBOARD_PORT", 5050))
    app = create_web_dashboard(orchestrator)
    if app is None:
        return

    def _run():
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    console.print(f"[bold green]🌐 Dashboard → http://localhost:{port}[/bold green]")
