#!/usr/bin/env python3
"""
Bot #100 — Project Manager Bot
Category: Agent Workforce
Purpose: Manage project task boards with backlog, in-progress, done, and blocked
         statuses. Uses Claude for intelligent task breakdown and planning.
"""

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class PMBot(BaseBot):
    """Project manager  task boards, deadlines, and blockers powered by Claude."""

    def __init__(self):
        super().__init__("100_pm_bot", "agent_workforce")
        self.board_path = self.data_dir / "pm_board.json"

    # ─── Board persistence ──────────────────────────────────────────────────

    def _load_board(self) -> dict:
        """Load the project board from disk or create an empty one."""
        if self.board_path.exists():
            try:
                data = json.loads(self.board_path.read_text())
                if isinstance(data, dict) and "projects" in data:
                    return data
            except Exception:
                pass
        return {"projects": {}}

    def _save_board(self, board: dict) -> None:
        self.board_path.parent.mkdir(parents=True, exist_ok=True)
        self.board_path.write_text(json.dumps(board, indent=2, ensure_ascii=False))

    def _ensure_project(self, board: dict, project: str) -> dict:
        """Ensure a project exists in the board, create if not."""
        if project not in board["projects"]:
            board["projects"][project] = {"tasks": []}
            self.logger.info(f"Created new project: {project}")
        return board

    # ─── Task helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _tasks_to_table(tasks: list, project: str) -> str:
        """Convert task list to a markdown table."""
        status_emoji = {
            "backlog": "[ ]",
            "in_progress": "[~]",
            "done": "[x]",
            "blocked": "[!]",
        }
        lines = [
            f"## Project: {project}",
            "",
            "| # | Status | Title | Deadline | ID |",
            "|---|--------|-------|----------|----|",
        ]
        for i, t in enumerate(tasks, 1):
            icon = status_emoji.get(t["status"], "[ ]")
            deadline = t.get("deadline", "-") or "-"
            short_id = t["id"][:8]
            lines.append(f"| {i} | {icon} {t['status']} | {t['title']} | {deadline} | `{short_id}` |")
        return "\n".join(lines)

    # ─── Main run ───────────────────────────────────────────────────────────

    def run(self, action: str = "tasks", project: str = None,
            task_text: str = None, task_id: str = None, **kwargs):

        project = project or "Default"
        board = self._load_board()
        board = self._ensure_project(board, project)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ts_display = datetime.now().strftime("%Y-%m-%d %H:%M")

        # ── List tasks ──────────────────────────────────────────────────────
        if action == "tasks":
            self.logger.info(f"Listing tasks for project: {project}")

            tasks = board["projects"][project]["tasks"]

            if not tasks:
                output = f"# Task Board: {project}\n**Generated:** {ts_display}\n\nNo tasks found. Use action='add' to create tasks.\n"
            else:
                # Group by status
                statuses = ["backlog", "in_progress", "blocked", "done"]
                output = f"# Task Board: {project}\n**Generated:** {ts_display}\n**Total tasks:** {len(tasks)}\n\n"

                for status in statuses:
                    status_tasks = [t for t in tasks if t["status"] == status]
                    if status_tasks:
                        output += f"\n### {status.replace('_', ' ').title()} ({len(status_tasks)})\n\n"
                        output += self._tasks_to_table(status_tasks, f"{project} - {status}")
                        output += "\n"

                # Summary stats
                counts = {s: len([t for t in tasks if t["status"] == s]) for s in statuses}
                output += "\n---\n\n**Summary:** "
                output += " | ".join(f"{s.replace('_', ' ').title()}: {c}" for s, c in counts.items())
                output += "\n"

            fname = f"pm_tasks_{ts}.md"
            path = self.save_output(output, fname, ext="md")
            return {"file": str(path), "action": action, "project": project}

        # ── Add task ────────────────────────────────────────────────────────
        elif action == "add":
            task_text = task_text or "New task"
            deadline = kwargs.get("deadline", "")
            notes = kwargs.get("notes", "")

            new_task = {
                "id": str(uuid.uuid4()),
                "title": task_text,
                "status": "backlog",
                "created": datetime.now().isoformat(),
                "deadline": deadline,
                "notes": notes,
            }

            board["projects"][project]["tasks"].append(new_task)
            self._save_board(board)

            self.logger.info(f"Added task to {project}: {task_text}")

            output = f"""# Task Added
**Project:** {project}
**Title:** {task_text}
**Status:** backlog
**Deadline:** {deadline or 'Not set'}
**ID:** `{new_task['id'][:8]}`
**Created:** {ts_display}

---

{self._tasks_to_table(board['projects'][project]['tasks'], project)}

---
*Generated by WheellsVerse PM Bot*
"""
            fname = f"pm_add_{ts}.md"
            path = self.save_output(output, fname, ext="md")
            return {"file": str(path), "action": action, "project": project}

        # ── Update task status ──────────────────────────────────────────────
        elif action == "update":
            new_status = kwargs.get("status", "in_progress")
            valid_statuses = ["backlog", "in_progress", "done", "blocked"]
            if new_status not in valid_statuses:
                raise ValueError(f"Invalid status: {new_status}. Use: {valid_statuses}")

            if not task_id:
                raise ValueError("task_id is required for update action")

            tasks = board["projects"][project]["tasks"]
            found = False
            updated_task = None

            for task in tasks:
                if task["id"].startswith(task_id):
                    old_status = task["status"]
                    task["status"] = new_status
                    found = True
                    updated_task = task
                    self.logger.info(f"Updated task {task_id[:8]}: {old_status} -> {new_status}")
                    break

            if not found:
                raise ValueError(f"Task not found: {task_id}")

            self._save_board(board)

            output = f"""# Task Updated
**Project:** {project}
**Task:** {updated_task['title']}
**Old Status:** {old_status}
**New Status:** {new_status}
**ID:** `{updated_task['id'][:8]}`
**Updated:** {ts_display}

---

{self._tasks_to_table(tasks, project)}

---
*Generated by WheellsVerse PM Bot*
"""
            fname = f"pm_update_{ts}.md"
            path = self.save_output(output, fname, ext="md")
            return {"file": str(path), "action": action, "project": project}

        # ── Plan (Claude-powered task breakdown) ────────────────────────────
        elif action == "plan":
            description = task_text or project

            self.logger.info(f"Generating task plan for: {description[:60]}")

            # Get existing tasks for context
            existing = board["projects"][project]["tasks"]
            existing_str = ""
            if existing:
                existing_str = "\nEXISTING TASKS:\n" + "\n".join(
                    f"  - [{t['status']}] {t['title']}" for t in existing
                )

            system = (
                "You are an experienced project manager and technical lead. You break "
                "down projects into clear, actionable tasks with realistic deadlines. "
                "Each task should be small enough to complete in 1-3 days. You identify "
                "dependencies and blockers proactively."
            )

            prompt = f"""Break down the following project into actionable tasks.

PROJECT: {project}
DESCRIPTION: {description}
{existing_str}

Return a JSON array of tasks. Each task:
{{
  "title": "concise task title",
  "deadline": "relative deadline (e.g., 'Day 3', 'Week 2')",
  "notes": "brief description and any dependencies",
  "status": "backlog"
}}

Create 5-15 tasks that cover the full scope. Order them by priority/dependency.
Return ONLY the JSON array, no markdown."""

            import re
            raw = self.claude(prompt, system=system, max_tokens=2000)
            raw = re.sub(r"```json\s*|\s*```", "", raw).strip()

            try:
                planned_tasks = json.loads(raw)
                if not isinstance(planned_tasks, list):
                    planned_tasks = [planned_tasks]
            except json.JSONDecodeError:
                self.logger.warning("Could not parse Claude response as JSON")
                planned_tasks = [{"title": raw[:100], "deadline": "", "notes": "Unparsed plan", "status": "backlog"}]

            # Add the planned tasks to the board
            for pt in planned_tasks:
                new_task = {
                    "id": str(uuid.uuid4()),
                    "title": pt.get("title", "Untitled"),
                    "status": pt.get("status", "backlog"),
                    "created": datetime.now().isoformat(),
                    "deadline": pt.get("deadline", ""),
                    "notes": pt.get("notes", ""),
                }
                board["projects"][project]["tasks"].append(new_task)

            self._save_board(board)

            all_tasks = board["projects"][project]["tasks"]

            output = f"""# Project Plan: {project}
**Description:** {description}
**New tasks added:** {len(planned_tasks)}
**Total tasks:** {len(all_tasks)}
**Generated:** {ts_display}

---

## New Tasks

| # | Title | Deadline | Notes |
|---|-------|----------|-------|
"""
            for i, pt in enumerate(planned_tasks, 1):
                output += f"| {i} | {pt.get('title', '')} | {pt.get('deadline', '')} | {pt.get('notes', '')[:60]} |\n"

            output += f"""
---

## Full Board

{self._tasks_to_table(all_tasks, project)}

---
*Generated by WheellsVerse PM Bot*
"""
            fname = f"pm_plan_{ts}.md"
            path = self.save_output(output, fname, ext="md")
            return {"file": str(path), "action": action, "project": project}

        # ── Blockers ────────────────────────────────────────────────────────
        elif action == "blockers":
            self.logger.info(f"Identifying blockers for project: {project}")

            tasks = board["projects"][project]["tasks"]
            blocked = [t for t in tasks if t["status"] == "blocked"]
            in_progress = [t for t in tasks if t["status"] == "in_progress"]

            output = f"""# Blocker Report: {project}
**Generated:** {ts_display}
**Total tasks:** {len(tasks)}
**Blocked:** {len(blocked)}
**In Progress:** {len(in_progress)}

---

"""
            if blocked:
                output += "## Blocked Tasks\n\n"
                output += "| # | Task | Notes | Created |\n"
                output += "|---|------|-------|---------|\n"
                for i, t in enumerate(blocked, 1):
                    created = t.get("created", "")[:10]
                    notes = t.get("notes", "-") or "-"
                    output += f"| {i} | {t['title']} | {notes[:50]} | {created} |\n"
                output += "\n"
            else:
                output += "## No Blocked Tasks\n\nAll clear -- no blockers detected.\n\n"

            if in_progress:
                output += "## In Progress (Watch List)\n\n"
                output += "| # | Task | Deadline | Notes |\n"
                output += "|---|------|----------| ------|\n"
                for i, t in enumerate(in_progress, 1):
                    deadline = t.get("deadline", "-") or "-"
                    notes = t.get("notes", "-") or "-"
                    output += f"| {i} | {t['title']} | {deadline} | {notes[:50]} |\n"

            # Stale task detection (backlog with no movement)
            backlog = [t for t in tasks if t["status"] == "backlog"]
            if backlog:
                output += f"\n## Backlog ({len(backlog)} tasks waiting)\n\n"
                output += "Consider prioritizing or removing stale backlog items.\n\n"
                for i, t in enumerate(backlog[:5], 1):
                    output += f"{i}. {t['title']}\n"
                if len(backlog) > 5:
                    output += f"\n... and {len(backlog) - 5} more\n"

            output += "\n---\n*Generated by WheellsVerse PM Bot*\n"

            fname = f"pm_blockers_{ts}.md"
            path = self.save_output(output, fname, ext="md")
            return {"file": str(path), "action": action, "project": project}

        else:
            raise ValueError(f"Unknown action: {action}. Use tasks, add, update, plan, or blockers.")


# ─── CLI Entry Point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Project Manager Bot")
    parser.add_argument("--action", type=str, default="tasks",
                        choices=["tasks", "add", "update", "plan", "blockers"])
    parser.add_argument("--project", type=str, default=None)
    parser.add_argument("--task-text", type=str, default=None, dest="task_text")
    parser.add_argument("--task-id", type=str, default=None, dest="task_id")
    parser.add_argument("--status", type=str, default="in_progress")
    parser.add_argument("--deadline", type=str, default="")
    parser.add_argument("--notes", type=str, default="")
    args = parser.parse_args()

    bot = PMBot()
    result = bot.execute(action=args.action, project=args.project,
                         task_text=args.task_text, task_id=args.task_id,
                         status=args.status, deadline=args.deadline,
                         notes=args.notes)
    print(f"\nOutput: {result['file']}")
    print(f"Action: {result['action']}  |  Project: {result['project']}")
