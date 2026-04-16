#!/usr/bin/env python3
"""
core/command.py
─────────────────────────────────────────────────────────────────────────────
Natural Language Command Interpreter.
Accepts plain-English commands → parses to structured action → executes.
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
import os
import re
import threading
from typing import Any, Dict

logger = logging.getLogger("command")

# ─── Intent parsing prompt ────────────────────────────────────────────────────

PARSE_SYSTEM = """
You are the command parser for the WheellsVerse Bot Ecosystem (70 AI automation bots).
Parse the user's input into a structured JSON action object.

AVAILABLE ACTIONS (return exactly one):
  {"action": "run_bot",       "bot": "<category/bot_name>"}
  {"action": "run_category",  "category": "<category_name>"}
  {"action": "run_pipeline",  "pipeline": "<pipeline_name>"}
  {"action": "run_all"}
  {"action": "status"}
  {"action": "list_bots"}
  {"action": "list_pipelines"}
  {"action": "list_categories"}
  {"action": "start_scheduler"}
  {"action": "stop_scheduler"}
  {"action": "show_logs"}
  {"action": "unknown", "original": "<user_text>"}

CATEGORIES: marketing, business, customer_support, sales, social_media,
            writing, assistant, problem_solving, time_management, ecommerce, specialized

PIPELINES: morning_blast, sales_engine, social_domination, content_machine,
           business_intelligence, weekly_report, growth_sprint, customer_success

EXAMPLES:
  "run all marketing bots"           → {"action": "run_category", "category": "marketing"}
  "start the morning pipeline"       → {"action": "run_pipeline", "pipeline": "morning_blast"}
  "generate content for today"       → {"action": "run_bot", "bot": "marketing/01_content_generator"}
  "show me the dashboard status"     → {"action": "status"}
  "run sales engine"                 → {"action": "run_pipeline", "pipeline": "sales_engine"}
  "run all bots"                     → {"action": "run_all"}
  "start scheduler"                  → {"action": "start_scheduler"}
  "what's running"                   → {"action": "status"}
  "run the seo optimizer"            → {"action": "run_bot", "bot": "marketing/02_seo_optimizer"}
  "launch social media bots"         → {"action": "run_category", "category": "social_media"}

Return ONLY valid JSON. No explanation. No markdown.
""".strip()


class CommandInterpreter:
    """
    Parses natural language → structured action → executes against the system.
    Uses GPT for complex parsing, regex shortcuts for common patterns.
    """

    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        return self._client

    # ─── Parse ────────────────────────────────────────────────────────────────

    def parse(self, text: str) -> Dict[str, Any]:
        """Convert natural language to structured action dict."""
        text = text.strip()
        lower = text.lower()

        # Fast-path shortcuts (no API call needed)
        if re.match(r"^(status|show status|bot status|what.?s running|overview)$", lower):
            return {"action": "status"}
        if re.match(r"^(list|list bots|show bots|all bots|bots)$", lower):
            return {"action": "list_bots"}
        if re.match(r"^(pipelines|list pipelines|show pipelines)$", lower):
            return {"action": "list_pipelines"}
        if re.match(r"^(run all|run all bots|start all|launch all)$", lower):
            return {"action": "run_all"}
        if re.match(r"^(start scheduler|run scheduler|enable scheduler)$", lower):
            return {"action": "start_scheduler"}
        if re.match(r"^(stop scheduler|disable scheduler|pause scheduler)$", lower):
            return {"action": "stop_scheduler"}
        if re.match(r"^(logs|show logs|view logs)$", lower):
            return {"action": "show_logs"}

        # Category shortcut: "run <category>" or "run all <category> bots"
        for cat in ["marketing", "business", "customer_support", "sales", "social_media",
                    "writing", "assistant", "problem_solving", "time_management",
                    "ecommerce", "specialized"]:
            if cat in lower and ("run" in lower or "launch" in lower or "start" in lower):
                return {"action": "run_category", "category": cat}

        # Pipeline shortcut: "run <pipeline>" or "start <pipeline> pipeline"
        for pl in ["morning_blast", "sales_engine", "social_domination", "content_machine",
                   "business_intelligence", "weekly_report", "growth_sprint", "customer_success"]:
            if pl.replace("_", " ") in lower or pl in lower:
                return {"action": "run_pipeline", "pipeline": pl}

        # Alias pipeline names (morning → morning_blast, etc.)
        pipeline_aliases = {
            "morning": "morning_blast",
            "sales": "sales_engine",
            "social": "social_domination",
            "content": "content_machine",
            "business": "business_intelligence",
            "weekly": "weekly_report",
            "growth": "growth_sprint",
            "customer": "customer_success",
        }
        for alias, pl_name in pipeline_aliases.items():
            if re.search(rf"\b{alias}\b", lower) and (
                "pipeline" in lower or "run" in lower or "start" in lower
            ):
                return {"action": "run_pipeline", "pipeline": pl_name}

        # GPT parsing for everything else
        try:
            resp = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": PARSE_SYSTEM},
                    {"role": "user", "content": text},
                ],
                max_tokens=120,
                temperature=0,
            )
            raw = resp.choices[0].message.content.strip()
            raw = re.sub(r"```json\s*|\s*```", "", raw).strip()
            return json.loads(raw)
        except Exception as e:
            logger.error(f"Command parse error: {e}")
            return {"action": "unknown", "original": text}

    # ─── Execute ──────────────────────────────────────────────────────────────

    def execute_async(
        self,
        command: Dict[str, Any],
        orchestrator,
        pipeline_engine,
        scheduler,
        on_complete=None,
    ) -> str:
        """
        Execute a parsed command in a background thread.
        Calls on_complete(result_str) when done.
        Returns immediately with a status message.
        """
        action = command.get("action", "unknown")

        def _run():
            result = self._do_execute(action, command, orchestrator, pipeline_engine, scheduler)
            logger.info(f"Command '{action}' result: {result}")
            if on_complete:
                on_complete(result)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        # Immediate feedback
        previews = {
            "run_bot": f"▶  Running bot: {command.get('bot', '?')}",
            "run_category": f"▶  Running category: {command.get('category', '?')}",
            "run_pipeline": f"▶  Running pipeline: {command.get('pipeline', '?')}",
            "run_all": "▶  Running all 70 bots",
            "start_scheduler": "▶  Starting scheduler",
            "stop_scheduler": "⏹  Stopping scheduler",
            "status": "📊 Fetching status",
            "list_bots": "📋 Listing bots",
            "list_pipelines": "📋 Listing pipelines",
        }
        return previews.get(action, f"⚙️  Executing: {action}")

    def execute_sync(
        self,
        command: Dict[str, Any],
        orchestrator,
        pipeline_engine,
        scheduler,
    ) -> str:
        """Execute a parsed command synchronously and return result string."""
        action = command.get("action", "unknown")
        return self._do_execute(action, command, orchestrator, pipeline_engine, scheduler)

    def _do_execute(
        self,
        action: str,
        command: Dict,
        orchestrator,
        pipeline_engine,
        scheduler,
    ) -> str:
        try:
            if action == "run_bot":
                bot = command.get("bot", "")
                orchestrator.run_bot(bot)
                return f"✅ Bot '{bot}' completed"

            elif action == "run_category":
                cat = command.get("category", "")
                orchestrator.run_category(cat, parallel=True)
                return f"✅ Category '{cat}' completed"

            elif action == "run_pipeline":
                pl = command.get("pipeline", "")
                result = pipeline_engine.run_pipeline(pl)
                ok = result.get("succeeded", 0)
                total = result.get("total_bots", 0)
                return f"✅ Pipeline '{pl}' complete — {ok}/{total} bots succeeded"

            elif action == "run_all":
                orchestrator.run_all(parallel=True)
                return "✅ All bots completed"

            elif action == "start_scheduler":
                scheduler.start(blocking=False)
                return "✅ Scheduler started"

            elif action == "stop_scheduler":
                scheduler.stop()
                return "✅ Scheduler stopped"

            elif action == "status":
                bots = orchestrator.list_bots()
                running = sum(
                    1 for n in bots
                    if orchestrator.bots.get(n) and
                    orchestrator.bots[n].get_status()["status"] == "running"
                )
                return f"📊 System status: {len(bots)} bots loaded, {running} running"

            elif action == "list_bots":
                return "\n".join(orchestrator.list_bots())

            elif action == "list_pipelines":
                return "\n".join(p["name"] for p in pipeline_engine.list_pipelines())

            elif action == "list_categories":
                return "\n".join(orchestrator.get_categories())

            elif action == "show_logs":
                return "📜 Open the Logs tab in the dashboard"

            else:
                return f"❓ Unknown command: {command.get('original', action)}"

        except Exception as e:
            logger.error(f"Command execution error: {e}")
            return f"❌ Error: {e}"
