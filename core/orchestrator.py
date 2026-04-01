#!/usr/bin/env python3
"""
core/orchestrator.py
─────────────────────────────────────────────────────────────────────────────
Master Orchestrator — discovers, loads, and runs all 70 bots.
Supports: run one bot, run a category, run all, parallel execution.
─────────────────────────────────────────────────────────────────────────────
"""

import importlib.util
import os
import sys
import time
import json
import concurrent.futures
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich import print as rprint

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

console = Console()


class Orchestrator:
    """
    Discovers all bot modules in the bots/ directory,
    instantiates them, and provides control methods.
    """

    def __init__(self):
        self.bots: Dict[str, Any] = {}          # name → bot instance
        self.registry: Dict[str, Dict] = {}      # name → metadata
        self.run_history: List[Dict] = []
        self._load_all_bots()

    # ─── Discovery ─────────────────────────────────────────────────────────────

    def _load_all_bots(self):
        """Scan bots/ directory and import every bot.py found."""
        bots_dir = ROOT / "bots"
        console.print("\n[bold cyan]🔍 Discovering bots...[/bold cyan]")

        loaded = 0
        failed = 0

        for category_dir in sorted(bots_dir.iterdir()):
            if not category_dir.is_dir():
                continue
            category = category_dir.name

            for bot_dir in sorted(category_dir.iterdir()):
                if not bot_dir.is_dir():
                    continue
                bot_py = bot_dir / "bot.py"
                config_json = bot_dir / "config.json"

                if not bot_py.exists():
                    continue

                # Read config
                config = {}
                if config_json.exists():
                    try:
                        with open(config_json) as f:
                            config = json.load(f)
                    except Exception:
                        pass

                bot_name = bot_dir.name
                full_name = f"{category}/{bot_name}"

                # Feature flag — skip disabled bots
                if not config.get("enabled", True):
                    continue

                try:
                    instance = self._import_bot(bot_py, bot_name, category, config)
                    self.bots[full_name] = instance
                    self.registry[full_name] = {
                        "name": bot_name,
                        "category": category,
                        "path": str(bot_py),
                        "config": config,
                        "description": config.get("description", "No description"),
                        "schedule": config.get("schedule", None),
                    }
                    loaded += 1
                except Exception as e:
                    console.print(f"  [red]✗ Failed to load {full_name}: {e}[/red]")
                    failed += 1

        console.print(f"[green]✅ {loaded} bots loaded[/green]  "
                      f"[red]{failed} failed[/red]\n")

    def _import_bot(self, bot_py: Path, name: str, category: str, config: dict):
        """Dynamically import a bot.py and return the Bot instance."""
        spec = importlib.util.spec_from_file_location(
            f"bots.{category}.{name}", str(bot_py)
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # Look for a class named "Bot" or the only class that ends with "Bot"
        bot_class = None
        for attr_name in dir(mod):
            attr = getattr(mod, attr_name)
            if (isinstance(attr, type) and
                    attr_name not in ("BaseBot", "ABC") and
                    attr_name.endswith("Bot")):
                bot_class = attr
                break

        if bot_class is None:
            raise ImportError(f"No Bot class found in {bot_py}")

        return bot_class()

    # ─── Execution ─────────────────────────────────────────────────────────────

    def run_bot(self, full_name: str, **kwargs) -> Any:
        """Run a single bot by full name (e.g. 'marketing/01_content_generator')."""
        import time as _time
        if full_name not in self.bots:
            raise KeyError(f"Bot not found: {full_name}")
        bot = self.bots[full_name]
        console.print(f"\n[bold yellow]▶  Running:[/bold yellow] {full_name}")

        # Health tracking
        try:
            from core.health import get_health_registry
            hr = get_health_registry()
            category = self.registry.get(full_name, {}).get("category", "")
            hr.record_start(full_name, category)
        except Exception:
            hr = None

        _t0 = _time.time()
        try:
            result = bot.execute(**kwargs)
            self._record(full_name, "success")
            if hr:
                hr.record_success(full_name, _time.time() - _t0)
            return result
        except Exception as e:
            self._record(full_name, "error", str(e))
            if hr:
                hr.record_failure(full_name, _time.time() - _t0, str(e))
            raise

    def run_category(self, category: str, parallel: bool = False, **kwargs) -> Dict:
        """Run all bots in a given category."""
        targets = {k: v for k, v in self.bots.items() if k.startswith(category + "/")}
        if not targets:
            raise ValueError(f"No bots found in category: {category}")

        console.print(f"\n[bold magenta]📦 Running category:[/bold magenta] {category} "
                      f"({len(targets)} bots, parallel={parallel})")

        results = {}
        if parallel:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                futures = {ex.submit(b.execute, **kwargs): k for k, b in targets.items()}
                for fut in concurrent.futures.as_completed(futures):
                    name = futures[fut]
                    try:
                        results[name] = fut.result()
                        self._record(name, "success")
                    except Exception as e:
                        results[name] = f"ERROR: {e}"
                        self._record(name, "error", str(e))
        else:
            for name, bot in targets.items():
                try:
                    results[name] = bot.execute(**kwargs)
                    self._record(name, "success")
                except Exception as e:
                    results[name] = f"ERROR: {e}"
                    self._record(name, "error", str(e))

        return results

    def run_all(self, parallel: bool = False, **kwargs) -> Dict:
        """Run all 70 bots."""
        console.print("\n[bold red]🚀 Running ALL bots[/bold red]")
        return self.run_category_list(list(self.bots.keys()), parallel, **kwargs)

    def run_category_list(self, names: List[str], parallel: bool = False, **kwargs) -> Dict:
        results = {}
        if parallel:
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
                futures = {ex.submit(self.bots[n].execute, **kwargs): n for n in names
                           if n in self.bots}
                for fut in concurrent.futures.as_completed(futures):
                    name = futures[fut]
                    try:
                        results[name] = fut.result()
                        self._record(name, "success")
                    except Exception as e:
                        results[name] = f"ERROR: {e}"
                        self._record(name, "error", str(e))
        else:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                          console=console) as prog:
                task = prog.add_task("Running bots...", total=len(names))
                for name in names:
                    if name not in self.bots:
                        continue
                    prog.update(task, description=f"[cyan]{name}[/cyan]", advance=0)
                    try:
                        results[name] = self.bots[name].execute(**kwargs)
                        self._record(name, "success")
                    except Exception as e:
                        results[name] = f"ERROR: {e}"
                        self._record(name, "error", str(e))
                    prog.advance(task)
        return results

    # ─── History ───────────────────────────────────────────────────────────────

    def _record(self, name: str, status: str, error: str = ""):
        self.run_history.append({
            "bot": name,
            "status": status,
            "error": error,
            "timestamp": datetime.now().isoformat()
        })

    # ─── Display ───────────────────────────────────────────────────────────────

    def show_status(self):
        """Print a rich table of all bots and their status."""
        table = Table(title="🤖 WheellsVerse Bot Ecosystem — Status",
                      show_header=True, header_style="bold cyan")
        table.add_column("#", style="dim", width=4)
        table.add_column("Category", style="cyan", min_width=18)
        table.add_column("Bot Name", style="white", min_width=30)
        table.add_column("Status", min_width=8)
        table.add_column("Runs", justify="right", min_width=5)
        table.add_column("Last Run", min_width=19)
        table.add_column("Description", style="dim", min_width=35)

        STATUS_COLOR = {
            "idle": "dim",
            "running": "yellow",
            "done": "green",
            "error": "red"
        }

        for i, (full_name, bot) in enumerate(sorted(self.bots.items()), 1):
            s = bot.get_status()
            color = STATUS_COLOR.get(s["status"], "white")
            table.add_row(
                str(i),
                s["category"],
                s["name"],
                f"[{color}]{s['status']}[/{color}]",
                str(s["run_count"]),
                s["last_run"] or "never",
                self.registry[full_name]["description"]
            )

        console.print(table)

    def list_bots(self) -> List[str]:
        return sorted(self.bots.keys())

    def get_categories(self) -> List[str]:
        cats = {k.split("/")[0] for k in self.bots}
        return sorted(cats)


# ─── Singleton access ──────────────────────────────────────────────────────────

_orchestrator: Optional[Orchestrator] = None

def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator
