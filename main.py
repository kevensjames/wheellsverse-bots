#!/usr/bin/env python3
"""
main.py — WheellsVerse Bot Ecosystem v2.0
─────────────────────────────────────────────────────────────────────────────
Master entry point. Supports:

  python main.py                        # Interactive CLI menu
  python main.py --dashboard            # Web dashboard (http://localhost:5050)
  python main.py --dashboard --port 8080
  python main.py --status               # Show all bot statuses
  python main.py --run <bot>            # Run one bot
  python main.py --category <cat>       # Run all bots in a category
  python main.py --pipeline <name>      # Run a pipeline
  python main.py --all                  # Run all 70 bots
  python main.py --parallel             # Use parallel execution
  python main.py --schedule             # Start scheduler (blocking)
  python main.py --list                 # List all bots
  python main.py --pipelines            # List all pipelines
  python main.py --check                # Check .env & setup status
  python main.py --command "..."        # Execute a natural language command
─────────────────────────────────────────────────────────────────────────────
"""

import os
import sys
import time
import argparse
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich import print as rprint

console = Console()

BANNER = """[bold cyan]
 ██╗    ██╗██╗  ██╗███████╗███████╗██╗     ██╗     ███████╗
 ██║    ██║██║  ██║██╔════╝██╔════╝██║     ██║     ██╔════╝
 ██║ █╗ ██║███████║█████╗  █████╗  ██║     ██║     ███████╗
 ██║███╗██║██╔══██║██╔══╝  ██╔══╝  ██║     ██║     ╚════██║
 ╚███╔███╔╝██║  ██║███████╗███████╗███████╗███████╗███████║
  ╚══╝╚══╝ ╚═╝  ╚═╝╚══════╝╚══════╝╚══════╝╚══════╝╚══════╝
[/bold cyan][bold white]          V E R S E  ·  B O T  E C O S Y S T E M  v2.0[/bold white]
[dim]          70 Autonomous Bots · Pipelines · Full Dashboard[/dim]
"""

MENU = """
[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]
[bold white]  MAIN MENU[/bold white]
[bold cyan]═══════════════════════════════════════════════════════════[/bold cyan]

  [bold cyan]1[/bold cyan]  → Bot Status (show all 70 bots)
  [bold cyan]2[/bold cyan]  → Run ONE bot
  [bold cyan]3[/bold cyan]  → Run a CATEGORY of bots
  [bold cyan]4[/bold cyan]  → Run a PIPELINE (chained bots)
  [bold cyan]5[/bold cyan]  → Run ALL 70 bots
  [bold cyan]6[/bold cyan]  → Launch Web Dashboard  [dim](http://localhost:5050)[/dim]
  [bold cyan]7[/bold cyan]  → Start Scheduler
  [bold cyan]8[/bold cyan]  → Natural Language Command
  [bold cyan]9[/bold cyan]  → List all bots
  [bold cyan]0[/bold cyan]  → Check .env & setup
  [bold cyan]q[/bold cyan]  → Quit

"""

CATEGORIES = [
    "marketing", "business", "customer_support", "sales", "social_media",
    "writing", "assistant", "problem_solving", "time_management",
    "ecommerce", "specialized",
    # New categories (v2.1)
    "affiliate_scout", "tool_catalog", "agent_workforce", "aeo",
    "prompt_intel", "receptionist", "seo_autopilot", "seo_command",
    # NarAI — General Overseer (v3.0)
    "narai",
]


# ─── Env check ────────────────────────────────────────────────────────────────

def check_env():
    issues = []
    if not os.getenv("OPENAI_API_KEY"):
        issues.append("⚠  OPENAI_API_KEY not set in .env")
    if not (ROOT / ".env").exists():
        issues.append("⚠  .env file missing — copy .env.example to .env")
    if issues:
        console.print("[yellow]Setup warnings:[/yellow]")
        for i in issues:
            console.print(f"  [yellow]{i}[/yellow]")
    else:
        console.print("[green]✅ .env OK — API key found[/green]")

    bots_dir = ROOT / "bots"
    bot_count = sum(1 for _ in bots_dir.rglob("bot.py"))
    console.print(f"[cyan]📦 Bot modules found: {bot_count}[/cyan]")

    config = ROOT / "config.yaml"
    console.print(f"[cyan]⚙  config.yaml: {'✓ found' if config.exists() else '✗ missing'}[/cyan]")


# ─── Interactive menu ─────────────────────────────────────────────────────────

def interactive_menu(orchestrator, pipeline_engine, scheduler):
    while True:
        console.print(MENU)
        choice = Prompt.ask("[bold cyan]Enter choice[/bold cyan]", default="1").strip().lower()

        if choice == "1":
            orchestrator.show_status()

        elif choice == "2":
            orchestrator.show_status()
            console.print("\n[bold]Enter bot full name[/bold] (e.g. marketing/01_content_generator):")
            name = Prompt.ask("Bot name")
            bots = orchestrator.list_bots()
            if name in bots:
                try:
                    orchestrator.run_bot(name)
                except Exception as e:
                    console.print(f"[red]Error: {e}[/red]")
            else:
                console.print(f"[red]Bot not found: {name}[/red]")

        elif choice == "3":
            console.print("\n[bold cyan]Available categories:[/bold cyan]")
            for c in CATEGORIES:
                console.print(f"  [cyan]{c}[/cyan]")
            cat = Prompt.ask("\nCategory name")
            parallel = Confirm.ask("Run in parallel?", default=False)
            try:
                orchestrator.run_category(cat, parallel=parallel)
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")

        elif choice == "4":
            pls = pipeline_engine.list_pipelines()
            console.print("\n[bold cyan]Available pipelines:[/bold cyan]")
            for p in pls:
                console.print(f"  [cyan]{p['name']}[/cyan]  [dim]{p['description']}[/dim]")
            pl_name = Prompt.ask("\nPipeline name")
            try:
                result = pipeline_engine.run_pipeline(pl_name)
                ok = result.get("succeeded", 0)
                total = result.get("total_bots", 0)
                console.print(f"[green]✅ Pipeline complete — {ok}/{total} bots succeeded[/green]")
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")

        elif choice == "5":
            if Confirm.ask("[red]Run ALL 70 bots?[/red] This uses API credits.", default=False):
                parallel = Confirm.ask("Run in parallel?", default=False)
                orchestrator.run_all(parallel=parallel)

        elif choice == "6":
            port = int(os.getenv("DASHBOARD_PORT", "5050"))
            console.print(f"\n[bold green]Launching dashboard → http://localhost:{port}[/bold green]")
            console.print("[dim]Press Ctrl+C to stop the dashboard and return to menu[/dim]\n")
            from core.api import launch
            try:
                launch(port=port, preload=False)
            except KeyboardInterrupt:
                pass

        elif choice == "7":
            scheduler.start(blocking=False)
            scheduler.show_schedule()
            console.print("[yellow]Scheduler running in background. Press Ctrl+C to stop.[/yellow]")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                scheduler.stop()

        elif choice == "8":
            from core.command import CommandInterpreter
            interp = CommandInterpreter()
            console.print("\n[bold cyan]Natural Language Command[/bold cyan]")
            console.print("[dim]Examples: 'Run all marketing bots', 'Start morning pipeline'[/dim]")
            cmd_text = Prompt.ask("Command")
            parsed = interp.parse(cmd_text)
            console.print(f"[dim]Parsed: {parsed}[/dim]")
            result = interp.execute_sync(parsed, orchestrator, pipeline_engine, scheduler)
            console.print(f"[green]{result}[/green]")

        elif choice == "9":
            for n in orchestrator.list_bots():
                console.print(f"  [cyan]{n}[/cyan]")

        elif choice == "0":
            check_env()

        elif choice in ("q", "quit", "exit"):
            console.print("[bold yellow]👋 Goodbye — WheellsVerse[/bold yellow]")
            break
        else:
            console.print("[red]Invalid choice[/red]")


# ─── CLI args ─────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(
        description="WheellsVerse Bot Ecosystem v2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--status",    action="store_true", help="Show all bot statuses")
    p.add_argument("--list",      action="store_true", help="List all bot names")
    p.add_argument("--pipelines", action="store_true", help="List all pipelines")
    p.add_argument("--run",       type=str, metavar="BOT",      help="Run one bot")
    p.add_argument("--category",  type=str, metavar="CAT",      help="Run all bots in a category")
    p.add_argument("--pipeline",  type=str, metavar="PIPELINE", help="Run a pipeline")
    p.add_argument("--all",       action="store_true", help="Run all 70 bots")
    p.add_argument("--parallel",  action="store_true", help="Run in parallel")
    p.add_argument("--schedule",  action="store_true", help="Start scheduler (blocking)")
    p.add_argument("--dashboard", action="store_true", help="Start web dashboard")
    p.add_argument("--port",      type=int, default=int(os.getenv("PORT", "5050")), help="Dashboard port (default: $PORT or 5050)")
    p.add_argument("--check",     action="store_true", help="Check setup & .env")
    p.add_argument("--command",   type=str, metavar="CMD", help="Execute a natural language command")
    return p.parse_args()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    console.print(BANNER)
    args = parse_args()

    if args.check:
        check_env()
        return

    if args.dashboard:
        console.print(f"[bold green]🌐 Starting dashboard → http://localhost:{args.port}[/bold green]")
        console.print("[dim]Loading all bots... (first run may take 10–15 seconds)[/dim]\n")
        from core.api import launch
        launch(port=args.port, preload=True)
        return

    # All other modes need the orchestrator
    console.print("[dim]Loading system...[/dim]")
    from core.orchestrator import get_orchestrator
    from core.pipeline import PipelineEngine
    from core.scheduler import BotScheduler

    orch  = get_orchestrator()
    pe    = PipelineEngine(orch)
    sched = BotScheduler(orch)

    if args.status:
        orch.show_status()

    elif args.list:
        for n in orch.list_bots():
            console.print(f"  {n}")

    elif args.pipelines:
        for p in pe.list_pipelines():
            console.print(f"  [cyan]{p['name']}[/cyan]  [dim]{p['description']}[/dim]")

    elif args.run:
        orch.run_bot(args.run)

    elif args.category:
        orch.run_category(args.category, parallel=args.parallel)

    elif args.pipeline:
        result = pe.run_pipeline(args.pipeline)
        console.print(f"[green]✅ Pipeline complete — {result.get('succeeded')}/{result.get('total_bots')} succeeded[/green]")

    elif args.all:
        orch.run_all(parallel=args.parallel)

    elif args.schedule:
        sched.register_all()
        sched.show_schedule()
        console.print("[yellow]Scheduler running. Press Ctrl+C to stop.[/yellow]")
        try:
            sched.start(blocking=True)
        except KeyboardInterrupt:
            sched.stop()

    elif args.command:
        from core.command import CommandInterpreter
        interp = CommandInterpreter()
        parsed = interp.parse(args.command)
        result = interp.execute_sync(parsed, orch, pe, sched)
        console.print(f"[green]{result}[/green]")

    else:
        # Interactive menu
        sched.register_all()
        interactive_menu(orch, pe, sched)


if __name__ == "__main__":
    main()
