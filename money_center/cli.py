#!/usr/bin/env python3
"""
money_center/cli.py
─────────────────────────────────────────────────────────────────────────────
Command-line interface for the Money Center.

Usage:
  python cli.py list
  python cli.py show <id>
  python cli.py start <id>
  python cli.py stop <id>
  python cli.py status
  python cli.py report
  python cli.py add
  python cli.py edit <id>
  python cli.py remove <id>
  python cli.py logs <id>
─────────────────────────────────────────────────────────────────────────────
"""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure money_center package is importable
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from money_center import registry as reg

console = Console()

# ─── Helpers ─────────────────────────────────────────────────────────────────

STATUS_COLOR = {
    "running": "bold green",
    "idle":    "dim",
    "stopped": "yellow",
    "error":   "bold red",
}

STATUS_DOT = {
    "running": "🟢",
    "idle":    "⚪",
    "stopped": "🟡",
    "error":   "🔴",
}


def _fmt_usd(n) -> str:
    try:
        return f"${float(n):,.0f}"
    except Exception:
        return str(n)


def _fmt_date(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso[:16]


def _require_asset(asset_id: str) -> dict:
    try:
        reg.require_ssd()
    except RuntimeError as e:
        console.print(f"[red]✗ {e}[/red]")
        sys.exit(1)
    asset = reg.get(asset_id)
    if asset is None:
        console.print(f"[red]✗ Asset not found: '{asset_id}'[/red]")
        sys.exit(1)
    return asset


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_list():
    """Table of all assets."""
    assets = _load_all()
    table = Table(title="💰 Money Center — Assets", show_header=True, header_style="bold cyan")
    table.add_column("ID", style="cyan", min_width=18)
    table.add_column("Name", min_width=28)
    table.add_column("Category", min_width=10)
    table.add_column("Status", min_width=10)
    table.add_column("Monthly Mid", justify="right", min_width=12)
    table.add_column("ETA (days)", justify="right", min_width=10)

    for a in assets:
        st = a.get("status", "idle")
        dot = STATUS_DOT.get(st, "⚪")
        color = STATUS_COLOR.get(st, "white")
        eta = a.get("time_to_first_revenue_days", 0)
        mid = a.get("monthly_estimate_usd", {}).get("mid", 0)
        table.add_row(
            a["id"],
            a["name"],
            a.get("category", ""),
            Text(f"{dot} {st}", style=color),
            _fmt_usd(mid),
            str(eta),
        )
    console.print(table)


def cmd_show(asset_id: str):
    """Full detail card."""
    a = _require_asset(asset_id)
    est = a.get("monthly_estimate_usd", {})
    st = a.get("status", "idle")
    lines = [
        f"[bold cyan]ID:[/bold cyan]          {a['id']}",
        f"[bold cyan]Name:[/bold cyan]        {a['name']}",
        f"[bold cyan]Category:[/bold cyan]    {a.get('category','')}",
        f"[bold cyan]Status:[/bold cyan]      {STATUS_DOT.get(st,'⚪')} {st}",
        f"[bold cyan]Description:[/bold cyan] {a.get('description','')}",
        f"[bold cyan]Revenue model:[/bold cyan] {a.get('revenue_model','')}",
        f"[bold cyan]Monthly estimate:[/bold cyan] Low {_fmt_usd(est.get('low',0))}  Mid {_fmt_usd(est.get('mid',0))}  High {_fmt_usd(est.get('high',0))}",
        f"[bold cyan]Total revenue:[/bold cyan] {_fmt_usd(a.get('total_revenue_usd',0))}",
        f"[bold cyan]ETA first revenue:[/bold cyan] {a.get('time_to_first_revenue_days',0)} days",
        f"[bold cyan]Run command:[/bold cyan] {a.get('run_command','')}",
        f"[bold cyan]Stop command:[/bold cyan] {a.get('stop_command','')}",
        f"[bold cyan]Working dir:[/bold cyan] {a.get('working_dir','')}",
        f"[bold cyan]Tags:[/bold cyan]        {', '.join(a.get('tags', []))}",
        f"[bold cyan]Notes:[/bold cyan]       {a.get('notes','')}",
        f"[bold cyan]Last run:[/bold cyan]    {_fmt_date(a.get('last_run'))}",
        f"[bold cyan]Last stop:[/bold cyan]   {_fmt_date(a.get('last_stop'))}",
        f"[bold cyan]Created:[/bold cyan]     {_fmt_date(a.get('created_at'))}",
        f"[bold cyan]Updated:[/bold cyan]     {_fmt_date(a.get('updated_at'))}",
    ]
    console.print(Panel("\n".join(lines), title=f"[bold]{a['name']}[/bold]", border_style="cyan"))


def cmd_start(asset_id: str):
    """Run the asset's run_command in background."""
    a = _require_asset(asset_id)
    cmd = a.get("run_command", "").strip()
    wdir = a.get("working_dir", str(HERE.parent))

    if not cmd:
        console.print(f"[red]✗ No run_command defined for '{asset_id}'[/red]")
        sys.exit(1)

    if a.get("status") == "running":
        console.print(f"[yellow]⚠ '{asset_id}' is already running.[/yellow]")
        return

    console.print(f"[green]▶ Starting:[/green] {cmd}")
    try:
        log_path = HERE / "logs" / f"{asset_id}.log"
        log_fd = open(log_path, "a", encoding="utf-8")
        subprocess.Popen(
            cmd, shell=True, cwd=wdir,
            stdout=log_fd, stderr=log_fd,
            env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"},
        )
        reg.update_status(asset_id, "running", "last_run")
        reg._log("info", asset_id, "start", f"Started: {cmd}")
        console.print(f"[green]✓ '{asset_id}' started. Logs → {log_path}[/green]")
    except Exception as e:
        reg.update_status(asset_id, "error")
        reg._log("error", asset_id, "start", f"Failed: {e}")
        console.print(f"[red]✗ Failed to start '{asset_id}': {e}[/red]")


def cmd_stop(asset_id: str):
    """Run the asset's stop_command."""
    a = _require_asset(asset_id)
    cmd = a.get("stop_command", "").strip()

    if not cmd:
        console.print(f"[red]✗ No stop_command defined for '{asset_id}'[/red]")
        sys.exit(1)

    if not Confirm.ask(f"[yellow]Stop '[bold]{asset_id}[/bold]'?[/yellow]"):
        console.print("[dim]Aborted.[/dim]")
        return

    console.print(f"[yellow]⏹ Stopping:[/yellow] {cmd}")
    try:
        subprocess.run(cmd, shell=True, timeout=10)
        reg.update_status(asset_id, "stopped", "last_stop")
        reg._log("info", asset_id, "stop", f"Stopped: {cmd}")
        console.print(f"[yellow]✓ '{asset_id}' stopped.[/yellow]")
    except Exception as e:
        reg._log("error", asset_id, "stop", f"Stop command failed: {e}")
        console.print(f"[red]✗ Stop failed: {e}[/red]")


def cmd_status():
    """Table with status + last_run for all assets."""
    assets = _load_all()
    table = Table(title="📊 Money Center — Status", header_style="bold cyan")
    table.add_column("ID", style="cyan", min_width=18)
    table.add_column("Name", min_width=28)
    table.add_column("Status", min_width=12)
    table.add_column("Last Run", min_width=17)
    table.add_column("Last Stop", min_width=17)

    for a in assets:
        st = a.get("status", "idle")
        color = STATUS_COLOR.get(st, "white")
        table.add_row(
            a["id"],
            a["name"],
            Text(f"{STATUS_DOT.get(st,'⚪')} {st}", style=color),
            _fmt_date(a.get("last_run")),
            _fmt_date(a.get("last_stop")),
        )
    console.print(table)


def cmd_report():
    """Revenue report grouped by category + grand total."""
    assets = _load_all()
    summary = reg.revenue_summary(assets)

    table = Table(title="💵 Revenue Forecast — Monthly", header_style="bold green")
    table.add_column("Category", style="cyan", min_width=16)
    table.add_column("Low", justify="right", min_width=10)
    table.add_column("Mid", justify="right", min_width=10, style="green")
    table.add_column("High", justify="right", min_width=10)

    for cat, est in sorted(summary["by_category"].items()):
        table.add_row(cat, _fmt_usd(est["low"]), _fmt_usd(est["mid"]), _fmt_usd(est["high"]))

    totals = summary["total"]
    table.add_section()
    table.add_row(
        "[bold]TOTAL[/bold]",
        f"[bold]{_fmt_usd(totals['low'])}[/bold]",
        f"[bold green]{_fmt_usd(totals['mid'])}[/bold green]",
        f"[bold]{_fmt_usd(totals['high'])}[/bold]",
    )
    console.print(table)
    console.print(
        f"\n[dim]Grand total mid: [bold green]{_fmt_usd(totals['mid'])}[/bold green]/mo "
        f"| Low: {_fmt_usd(totals['low'])} | High: {_fmt_usd(totals['high'])}[/dim]"
    )


def cmd_add():
    """Interactive prompt to add a new asset."""
    try:
        reg.require_ssd()
    except RuntimeError as e:
        console.print(f"[red]✗ {e}[/red]"); sys.exit(1)

    console.print("[bold cyan]➕ Add New Asset[/bold cyan]\n")
    a = reg.new_asset_template()

    a["id"] = Prompt.ask("ID (slug, e.g. my_product)")
    if reg.exists(a["id"]):
        console.print(f"[red]✗ Asset '{a['id']}' already exists.[/red]"); sys.exit(1)

    a["name"] = Prompt.ask("Name")
    a["category"] = Prompt.ask(
        "Category", choices=sorted(reg.VALID_CATEGORIES), default="service"
    )
    a["description"] = Prompt.ask("Description (one sentence)")
    a["revenue_model"] = Prompt.ask("Revenue model", default="other")

    low = float(Prompt.ask("Monthly estimate LOW (USD)", default="0"))
    mid = float(Prompt.ask("Monthly estimate MID (USD)", default="0"))
    high = float(Prompt.ask("Monthly estimate HIGH (USD)", default="0"))
    a["monthly_estimate_usd"] = {"low": low, "mid": mid, "high": high}

    a["time_to_first_revenue_days"] = int(Prompt.ask("Days to first revenue", default="30"))
    a["run_command"] = Prompt.ask("Run command")
    a["stop_command"] = Prompt.ask("Stop command")
    a["working_dir"] = Prompt.ask("Working directory", default=a["working_dir"])
    tags_str = Prompt.ask("Tags (comma-separated)", default="")
    a["tags"] = [t.strip() for t in tags_str.split(",") if t.strip()]
    a["notes"] = Prompt.ask("Notes", default="")

    errors = reg.validate(a)
    if errors:
        console.print(f"[red]✗ Validation failed: {errors}[/red]"); sys.exit(1)

    reg.upsert(a)
    reg._log("info", a["id"], "add", "Asset added via CLI")
    console.print(f"[green]✓ Asset '{a['id']}' added.[/green]")


def cmd_edit(asset_id: str):
    """Edit asset metadata field by field."""
    a = _require_asset(asset_id)
    console.print(f"[bold cyan]✏️  Editing: {asset_id}[/bold cyan]  (press Enter to keep current value)\n")

    editable = [
        ("name", "Name"),
        ("category", "Category"),
        ("description", "Description"),
        ("revenue_model", "Revenue model"),
        ("time_to_first_revenue_days", "Days to first revenue"),
        ("run_command", "Run command"),
        ("stop_command", "Stop command"),
        ("working_dir", "Working directory"),
        ("notes", "Notes"),
    ]
    for key, label in editable:
        current = str(a.get(key, ""))
        val = Prompt.ask(f"{label}", default=current)
        if key == "time_to_first_revenue_days":
            try:
                a[key] = int(val)
            except ValueError:
                a[key] = 0
        else:
            a[key] = val

    console.print("\n[dim]Monthly estimate — leave blank to keep current.[/dim]")
    est = a.get("monthly_estimate_usd", {"low": 0, "mid": 0, "high": 0})
    for k in ("low", "mid", "high"):
        v = Prompt.ask(f"  Monthly {k} (USD)", default=str(est.get(k, 0)))
        try:
            est[k] = float(v)
        except ValueError:
            pass
    a["monthly_estimate_usd"] = est

    tags_str = Prompt.ask("Tags (comma-separated)", default=",".join(a.get("tags", [])))
    a["tags"] = [t.strip() for t in tags_str.split(",") if t.strip()]

    a["updated_at"] = datetime.now(timezone.utc).isoformat()
    errors = reg.validate(a)
    if errors:
        console.print(f"[red]✗ Validation failed: {errors}[/red]"); sys.exit(1)

    reg.upsert(a)
    reg._log("info", asset_id, "edit", "Asset edited via CLI")
    console.print(f"[green]✓ '{asset_id}' updated.[/green]")


def cmd_remove(asset_id: str):
    """Remove an asset with confirmation."""
    _require_asset(asset_id)  # ensures it exists
    if not Confirm.ask(f"[red]Delete '[bold]{asset_id}[/bold]' permanently?[/red]"):
        console.print("[dim]Aborted.[/dim]"); return

    reg.remove(asset_id)
    console.print(f"[green]✓ '{asset_id}' removed.[/green]")


def cmd_logs(asset_id: str, lines: int = 50):
    """Tail last N lines of asset's log file."""
    log_path = HERE / "logs" / f"{asset_id}.log"
    if not log_path.exists():
        console.print(f"[yellow]No log file found for '{asset_id}' at {log_path}[/yellow]")
        return
    text = log_path.read_text(encoding="utf-8", errors="replace")
    tail = text.splitlines()[-lines:]
    console.print(Panel("\n".join(tail), title=f"📋 Logs: {asset_id} (last {lines} lines)", border_style="dim"))


# ─── Internal ─────────────────────────────────────────────────────────────────

def _load_all():
    try:
        reg.require_ssd()
    except RuntimeError as e:
        console.print(f"[red]✗ {e}[/red]"); sys.exit(1)
    return reg.load()


# ─── Entry point ──────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        console.print("[bold cyan]Money Center CLI[/bold cyan] — run [dim]python cli.py list[/dim] to start")
        sys.exit(0)

    command = args[0].lower()

    if command == "list":
        cmd_list()
    elif command == "show" and len(args) >= 2:
        cmd_show(args[1])
    elif command == "start" and len(args) >= 2:
        cmd_start(args[1])
    elif command == "stop" and len(args) >= 2:
        cmd_stop(args[1])
    elif command == "status":
        cmd_status()
    elif command == "report":
        cmd_report()
    elif command == "add":
        cmd_add()
    elif command == "edit" and len(args) >= 2:
        cmd_edit(args[1])
    elif command == "remove" and len(args) >= 2:
        cmd_remove(args[1])
    elif command == "logs" and len(args) >= 2:
        lines = int(args[2]) if len(args) >= 3 else 50
        cmd_logs(args[1], lines)
    else:
        console.print(
            Panel(
                "[bold]Commands:[/bold]\n"
                "  list              — all assets\n"
                "  show <id>         — full detail\n"
                "  start <id>        — run in background\n"
                "  stop <id>         — stop (with confirm)\n"
                "  status            — status + last run\n"
                "  report            — revenue forecast\n"
                "  add               — interactive add\n"
                "  edit <id>         — edit field by field\n"
                "  remove <id>       — delete (with confirm)\n"
                "  logs <id> [lines] — tail log file",
                title="[bold cyan]Money Center CLI[/bold cyan]",
                border_style="cyan",
            )
        )


if __name__ == "__main__":
    main()
