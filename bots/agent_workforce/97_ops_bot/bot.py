#!/usr/bin/env python3
"""
Bot #97 — Operations Routing Bot
Category: Agent Workforce
Purpose: Analyze incoming tasks via Claude and route them to the right bots
         using the orchestrator. Acts as a central task dispatcher.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class OpsBot(BaseBot):
    """Task routing and workflow management powered by Claude."""

    def __init__(self):
        super().__init__("97_ops_bot", "agent_workforce")

    def run(self, task: str = None, priority: str = "normal", **kwargs):

        task = task or "Generate a blog post about AI automation and post it to social media"
        priority = priority or "normal"

        self.logger.info(f"Analyzing task (priority={priority}): {task[:80]}...")

        # Get the orchestrator and its bot list
        from core.orchestrator import get_orchestrator
        orch = get_orchestrator()
        available_bots = sorted(orch.bots.keys())

        # Build a concise list for Claude
        bot_descriptions = []
        for name in available_bots:
            desc = orch.registry.get(name, {}).get("description", "No description")
            bot_descriptions.append(f"  - {name}: {desc}")
        bot_list_str = "\n".join(bot_descriptions)

        system = (
            "You are an operations routing agent. Given a task, return JSON with "
            "the following structure:\n"
            '{"targets": ["category/bot_name", ...], "reasoning": "...", '
            '"execution_order": "sequential"|"parallel", '
            '"notes": "any special instructions for each bot"}\n\n'
            "Only use bot names from the AVAILABLE list. Choose the minimum set "
            "of bots needed to accomplish the task. If the task is ambiguous, "
            "pick the most likely candidates and explain in reasoning."
        )

        prompt = f"""Analyze this task and determine which bots should handle it.

TASK: {task}
PRIORITY: {priority}

AVAILABLE BOTS:
{bot_list_str}

Return your routing decision as JSON."""

        # Get routing decision from Claude
        routing_raw = self.claude(prompt, system=system, max_tokens=1500)

        # Parse the JSON response
        routing_raw = re.sub(r"```json\s*|\s*```", "", routing_raw).strip()
        try:
            routing = json.loads(routing_raw)
        except json.JSONDecodeError:
            self.logger.warning("Claude returned non-JSON, wrapping raw response")
            routing = {
                "targets": [],
                "reasoning": routing_raw,
                "execution_order": "sequential",
                "notes": "Could not parse routing decision as JSON"
            }

        targets = routing.get("targets", [])
        reasoning = routing.get("reasoning", "No reasoning provided")
        exec_order = routing.get("execution_order", "sequential")
        notes = routing.get("notes", "")

        # Validate targets exist in the orchestrator
        valid_targets = [t for t in targets if t in orch.bots]
        invalid_targets = [t for t in targets if t not in orch.bots]

        if invalid_targets:
            self.logger.warning(f"Invalid bot targets (skipped): {invalid_targets}")

        # Execute the routed bots
        results = {}
        errors = {}

        if valid_targets:
            self.logger.info(f"Routing to {len(valid_targets)} bots ({exec_order}): {valid_targets}")
            for bot_name in valid_targets:
                try:
                    self.logger.info(f"Running: {bot_name}")
                    result = orch.run_bot(bot_name)
                    results[bot_name] = str(result) if result else "completed"
                except Exception as e:
                    self.logger.error(f"Bot {bot_name} failed: {e}")
                    errors[bot_name] = str(e)
        else:
            self.logger.warning("No valid targets found for routing")

        # Build output report
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        output = f"""# Operations Routing Report
**Task:** {task}
**Priority:** {priority}
**Generated:** {ts}

---

## Routing Decision

**Reasoning:** {reasoning}

**Execution Order:** {exec_order}

**Notes:** {notes}

---

## Targeted Bots

| # | Bot | Status |
|---|-----|--------|
"""
        for i, bot_name in enumerate(valid_targets, 1):
            if bot_name in errors:
                output += f"| {i} | {bot_name} | FAILED: {errors[bot_name][:60]} |\n"
            else:
                output += f"| {i} | {bot_name} | SUCCESS |\n"

        if invalid_targets:
            output += f"\n**Skipped (not found):** {', '.join(invalid_targets)}\n"

        output += """
---

## Execution Results

"""
        for bot_name, result_str in results.items():
            output += f"### {bot_name}\n```\n{result_str[:500]}\n```\n\n"

        if errors:
            output += "## Errors\n\n"
            for bot_name, err in errors.items():
                output += f"- **{bot_name}:** {err}\n"

        output += "\n---\n*Generated by WheellsVerse OpsBot*\n"

        fname = f"ops_routing_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path = self.save_output(output, fname, ext="md")

        self.logger.info(f"Routing report saved -> {path}")
        return {
            "file": str(path),
            "routed_to": valid_targets,
            "task": task,
        }


# ─── CLI Entry Point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Operations Routing Bot")
    parser.add_argument("--task", type=str, default=None)
    parser.add_argument("--priority", type=str, default="normal",
                        choices=["low", "normal", "high", "urgent"])
    args = parser.parse_args()

    bot = OpsBot()
    result = bot.execute(task=args.task, priority=args.priority)
    print(f"\nOutput: {result['file']}")
    print(f"Routed to: {result['routed_to']}")
