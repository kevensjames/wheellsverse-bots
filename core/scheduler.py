#!/usr/bin/env python3
"""
core/scheduler.py
─────────────────────────────────────────────────────────────────────────────
Task Scheduler for WheellsVerse Bot Ecosystem.
Reads each bot's config.json "schedule" field and auto-schedules execution.

Schedule formats supported:
  "@every_5min"    — runs every 5 minutes
  "@every_hour"    — runs every hour
  "@daily 09:00"   — runs daily at 09:00
  "@weekly mon 08:00" — runs every Monday at 08:00
  "cron: */10 * * * *" — raw cron expression
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
import sys
import time
import threading
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import schedule
from dotenv import load_dotenv
from rich.console import Console

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

console = Console()
logger = logging.getLogger("scheduler")


class BotScheduler:
    """
    Wraps the `schedule` library to auto-schedule all bots
    based on their config.json "schedule" fields.
    """

    def __init__(self, orchestrator=None):
        self.orchestrator = orchestrator
        self.jobs: List[Dict] = []
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False

    # ─── Setup ─────────────────────────────────────────────────────────────────

    def register_all(self):
        """Register every bot that has a schedule defined."""
        if self.orchestrator is None:
            from core.orchestrator import get_orchestrator
            self.orchestrator = get_orchestrator()

        count = 0
        for full_name, meta in self.orchestrator.registry.items():
            sched = meta.get("schedule")
            if not sched:
                continue
            try:
                self._register(full_name, sched)
                count += 1
            except Exception as e:
                logger.warning(f"Could not schedule {full_name}: {e}")

        console.print(f"[green]📅 {count} bots scheduled[/green]")

    def register_one(self, full_name: str, schedule_str: str,
                     kwargs: Optional[Dict] = None):
        """Manually register a single bot."""
        self._register(full_name, schedule_str, kwargs)

    def _register(self, full_name: str, schedule_str: str,
                  kwargs: Optional[Dict] = None):
        kwargs = kwargs or {}
        fn = self._make_job(full_name, kwargs)

        s = schedule_str.strip().lower()

        if s == "@every_5min":
            job = schedule.every(5).minutes.do(fn)
        elif s == "@every_10min":
            job = schedule.every(10).minutes.do(fn)
        elif s == "@every_30min":
            job = schedule.every(30).minutes.do(fn)
        elif s == "@every_hour":
            job = schedule.every().hour.do(fn)
        elif s == "@every_2hours":
            job = schedule.every(2).hours.do(fn)
        elif s == "@every_6hours":
            job = schedule.every(6).hours.do(fn)
        elif s.startswith("@daily"):
            parts = s.split()
            t = parts[1] if len(parts) > 1 else "09:00"
            job = schedule.every().day.at(t).do(fn)
        elif s.startswith("@weekly"):
            parts = s.split()
            day = parts[1] if len(parts) > 1 else "monday"
            t = parts[2] if len(parts) > 2 else "09:00"
            day_map = {
                "mon": "monday", "tue": "tuesday", "wed": "wednesday",
                "thu": "thursday", "fri": "friday", "sat": "saturday",
                "sun": "sunday"
            }
            day = day_map.get(day, day)
            job = getattr(schedule.every(), day).at(t).do(fn)
        elif s.startswith("@monthly"):
            # Approximate: run every 30 days
            job = schedule.every(30).days.do(fn)
        else:
            raise ValueError(f"Unknown schedule format: {schedule_str}")

        self.jobs.append({
            "bot": full_name,
            "schedule": schedule_str,
            "job": job,
            "next_run": job.next_run.isoformat() if job.next_run else "?"
        })
        logger.info(f"📅 Scheduled [{full_name}] → {schedule_str}")

    def _make_job(self, full_name: str, kwargs: Dict) -> Callable:
        def job():
            logger.info(f"⏰ Scheduled trigger: {full_name}")
            try:
                self.orchestrator.run_bot(full_name, **kwargs)
            except Exception as e:
                logger.error(f"Scheduled job failed [{full_name}]: {e}")
        return job

    # ─── Run Loop ──────────────────────────────────────────────────────────────

    def start(self, blocking: bool = True):
        """Start the scheduling loop."""
        self._running = True
        console.print("[bold green]▶  Scheduler started (Ctrl+C to stop)[/bold green]")
        if blocking:
            self._run_loop()
        else:
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self):
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        console.print("[yellow]⏹  Scheduler stopped[/yellow]")

    def _run_loop(self):
        while not self._stop_event.is_set():
            schedule.run_pending()
            time.sleep(1)

    # ─── Decision Engine integration ────────────────────────────────────────────

    def register_decision_engine(self, interval_minutes: int = 15, enabled: bool = True):
        """
        Register the Decision Engine as a recurring scheduled task.

        Reads DECISION_ENGINE_ENABLED from .env / config to allow toggling.
        interval_minutes: how often to run the full intelligence cycle (default 15).
        """
        env_enabled = os.getenv("DECISION_ENGINE_ENABLED", "true").lower()
        if not enabled or env_enabled == "false":
            logger.info("Decision engine scheduler registration skipped (disabled)")
            return

        def _run_de():
            try:
                from core.decision_engine import get_decision_engine
                from core.orchestrator import get_orchestrator
                from core.pipeline import PipelineEngine
                from core.health import get_health_registry
                from core.memory import get_memory

                orch = self.orchestrator or get_orchestrator()
                de = get_decision_engine(
                    orchestrator=orch,
                    pipeline_engine=PipelineEngine(orch),
                    health_registry=get_health_registry(),
                    memory=get_memory(),
                )
                summary = de.run()
                logger.info(
                    f"⏰ Decision engine scheduled run — "
                    f"{summary.get('total_actions', 0)} actions"
                )
            except Exception as e:
                logger.error(f"Scheduled decision engine run failed: {e}")

        job = schedule.every(interval_minutes).minutes.do(_run_de)
        self.jobs.append({
            "bot": "decision_engine",
            "schedule": f"@every_{interval_minutes}min",
            "job": job,
            "next_run": job.next_run.isoformat() if job.next_run else "?",
        })
        logger.info(f"🧠 Decision engine scheduled every {interval_minutes} minutes")
        console.print(f"[bold cyan]🧠 Decision Engine scheduled every {interval_minutes}min[/bold cyan]")

    # ─── Manual triggers ───────────────────────────────────────────────────────

    def run_now(self, full_name: str, **kwargs):
        """Immediately trigger a bot outside of its schedule."""
        if self.orchestrator:
            self.orchestrator.run_bot(full_name, **kwargs)

    def show_schedule(self):
        """Print upcoming jobs."""
        console.print("\n[bold cyan]📅 Scheduled Jobs[/bold cyan]")
        for j in self.jobs:
            console.print(f"  [cyan]{j['bot']}[/cyan]  "
                          f"[dim]{j['schedule']}[/dim]  "
                          f"[green]next: {j['next_run']}[/green]")
        if not self.jobs:
            console.print("  [dim]No jobs scheduled[/dim]")
