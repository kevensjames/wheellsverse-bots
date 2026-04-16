#!/usr/bin/env python3
"""bots/seo_command/118_content_calendar/bot.py — Content calendar bot"""
import sys
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
import calendar

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402
from core.db import get_db  # noqa: E402


class ContentCalendarBot(BaseBot):
    """Manages a 30-day SEO content editorial calendar."""

    def __init__(self):
        super().__init__("118_content_calendar", "seo_command")

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _ensure_calendar_table(self, db):
        """Ensure content_calendar table has all needed columns."""
        if "content_calendar" not in db.table_names():
            db["content_calendar"].create(
                {
                    "id": int,
                    "keyword": str,
                    "title": str,
                    "scheduled_date": str,
                    "status": str,
                    "content_type": str,
                    "estimated_word_count": int,
                    "month": str,
                    "assigned_bot": str,
                    "created_at": str,
                },
                pk="id",
            )
        else:
            existing_cols = {col.name for col in db["content_calendar"].columns}
            for col, ctype in [("content_type", str), ("estimated_word_count", int), ("month", str)]:
                if col not in existing_cols:
                    db["content_calendar"].add_column(col, ctype)

    def _get_tracked_keywords(self, db, limit=30) -> list:
        """Load up to `limit` keywords from the keywords table."""
        try:
            rows = list(db["keywords"].rows_where(order_by="last_checked DESC", limit=limit))
            return [r["keyword"] for r in rows if r.get("keyword")]
        except Exception as e:
            self.logger.warning(f"Could not load keywords from DB: {e}")
            return []

    def _month_date_range(self, month_str: str):
        """Return (first_date, last_date) as datetime objects for YYYY-MM."""
        year, mon = int(month_str[:4]), int(month_str[5:7])
        first = datetime(year, mon, 1)
        last_day = calendar.monthrange(year, mon)[1]
        last = datetime(year, mon, last_day)
        return first, last

    def _remaining_days(self, month_str: str) -> list:
        """Return list of date strings YYYY-MM-DD for remaining days in the month from today."""
        today = datetime.now().date()
        first, last = self._month_date_range(month_str)
        start = max(first.date(), today)
        days = []
        cur = start
        while cur <= last.date():
            days.append(cur.strftime("%Y-%m-%d"))
            cur += timedelta(days=1)
        return days

    # ─── Actions ──────────────────────────────────────────────────────────────

    def _action_plan(self, db, month: str) -> dict:
        """Generate a month of content ideas from tracked keywords via Claude."""
        self._ensure_calendar_table(db)
        keywords = self._get_tracked_keywords(db, limit=30)

        if not keywords:
            keywords = [
                "passive income ideas",
                "crypto investing for beginners",
                "best AI tools 2025",
                "side hustle ideas",
                "how to invest $1000",
            ]
            self.logger.warning("No tracked keywords found; using defaults.")

        keywords_str = "\n".join(f"- {k}" for k in keywords)
        first, last = self._month_date_range(month)
        days_in_month = (last - first).days + 1

        system_prompt = (
            "You are an SEO content strategist. Create a 30-day content calendar for these "
            f"keywords: {', '.join(keywords[:10])}. "
            "Return JSON array: "
            '[{"keyword": "...", "title": "...", "scheduled_date": "YYYY-MM-DD", '
            '"content_type": "article|listicle|comparison|how-to", "estimated_word_count": 1500}]'
        )

        user_prompt = (
            f"Month: {month}\n"
            f"Month runs from {first.strftime('%Y-%m-%d')} to {last.strftime('%Y-%m-%d')} "
            f"({days_in_month} days).\n\n"
            f"Tracked keywords:\n{keywords_str}\n\n"
            f"Generate exactly 30 content ideas (one per day of the month, "
            f"spread across all 30 days). Each item must have:\n"
            f"- keyword: one of the tracked keywords above\n"
            f"- title: compelling SEO-optimized title\n"
            f"- scheduled_date: YYYY-MM-DD within {month}\n"
            f"- content_type: article|listicle|comparison|how-to\n"
            f"- estimated_word_count: integer between 800 and 3000\n\n"
            f"Return ONLY the JSON array, no other text."
        )

        raw = self.claude(user_prompt, system=system_prompt, max_tokens=6000)
        raw_clean = re.sub(r"```json\s*|\s*```", "", raw).strip()

        try:
            items = json.loads(raw_clean)
        except json.JSONDecodeError:
            self.logger.warning("Claude response not valid JSON — attempting extraction")
            match = re.search(r"\[.*\]", raw_clean, re.DOTALL)
            if match:
                try:
                    items = json.loads(match.group())
                except Exception:
                    items = []
            else:
                items = []

        if not isinstance(items, list):
            items = []

        now_iso = datetime.now().isoformat()
        stored = 0
        for item in items:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            record = {
                "keyword": item.get("keyword", ""),
                "title": item.get("title", ""),
                "scheduled_date": item.get("scheduled_date", ""),
                "status": "planned",
                "content_type": item.get("content_type", "article"),
                "estimated_word_count": int(item.get("estimated_word_count", 1500)),
                "month": month,
                "assigned_bot": "",
                "created_at": now_iso,
            }
            try:
                db["content_calendar"].insert(record, alter=True)
                stored += 1
            except Exception as e:
                self.logger.warning(f"Failed to insert calendar item '{record['title'][:40]}': {e}")

        self.logger.info(f"Stored {stored} calendar items for {month}")

        # Build markdown calendar view (grouped by week)
        try:
            cal_rows = list(
                db["content_calendar"].rows_where(
                    "month = ?", [month], order_by="scheduled_date"
                )
            )
        except Exception:
            cal_rows = items  # fall back to in-memory items

        report_lines = [
            f"# Content Calendar — {month}",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Items Planned:** {stored}",
            f"**Keywords Used:** {len(set(i.get('keyword', '') for i in items))}",
            "",
            "---",
            "",
            "## Content Schedule",
            "",
            "| Date | Title | Type | Keywords | Words |",
            "|------|-------|------|----------|-------|",
        ]
        for row in cal_rows:
            date = row.get("scheduled_date", "")
            title = row.get("title", "")[:60]
            ctype = row.get("content_type", "article")
            kw = row.get("keyword", "")[:30]
            wc = row.get("estimated_word_count", 1500)
            report_lines.append(f"| {date} | {title} | {ctype} | {kw} | {wc} |")

        report_lines += ["", "---", "*Generated by WheellsVerse Content Calendar Bot*"]
        report = "\n".join(report_lines)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path_out = self.save_output(report, f"content_calendar_{month}_{ts}.md", ext="md")
        return {"file": str(path_out), "action": "plan", "month": month}

    def _action_status(self, db, month: str) -> dict:
        """Show counts by status for the given month."""
        self._ensure_calendar_table(db)
        today = datetime.now().strftime("%Y-%m-%d")

        try:
            rows = list(
                db["content_calendar"].rows_where("month = ?", [month])
            )
        except Exception as e:
            self.logger.error(f"Could not query content_calendar: {e}")
            rows = []

        # Detect overdue: planned items past their scheduled date
        counts = {"planned": 0, "writing": 0, "review": 0, "published": 0, "overdue": 0}
        overdue_items = []
        for row in rows:
            status = row.get("status", "planned")
            if (
                status in ("planned", "writing")
                and row.get("scheduled_date", "9999") < today
            ):
                counts["overdue"] += 1
                overdue_items.append(row)
                # Update DB status
                try:
                    db["content_calendar"].update(row["id"], {"status": "overdue"})
                except Exception:
                    pass
            else:
                counts[status] = counts.get(status, 0) + 1

        report_lines = [
            f"# Content Calendar Status — {month}",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Total Items:** {len(rows)}",
            "",
            "## Status Breakdown",
            "",
            "| Status | Count |",
            "|--------|-------|",
        ]
        for status, count in counts.items():
            report_lines.append(f"| {status.capitalize()} | {count} |")

        if overdue_items:
            report_lines += ["", "## Overdue Items", ""]
            for row in overdue_items[:20]:
                report_lines.append(
                    f"- **{row.get('scheduled_date', '')}** — {row.get('title', '')[:60]}"
                )
            if len(overdue_items) > 20:
                report_lines.append(f"_... and {len(overdue_items) - 20} more_")

        report_lines += ["", "---", "*Generated by WheellsVerse Content Calendar Bot*"]
        report = "\n".join(report_lines)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path_out = self.save_output(report, f"calendar_status_{month}_{ts}.md", ext="md")
        return {"file": str(path_out), "action": "status", "month": month}

    def _action_schedule(self, db, month: str) -> dict:
        """Spread unscheduled/un-dated items evenly across remaining days."""
        self._ensure_calendar_table(db)

        try:
            unscheduled = list(
                db["content_calendar"].rows_where(
                    "month = ? AND (scheduled_date IS NULL OR scheduled_date = '')",
                    [month],
                )
            )
        except Exception as e:
            self.logger.error(f"Could not query unscheduled items: {e}")
            unscheduled = []

        remaining = self._remaining_days(month)
        if not remaining:
            self.logger.warning(f"No remaining days in {month}")
            report = (
                f"# Scheduling Report — {month}\n\n"
                f"No remaining days in this month to schedule items.\n"
            )
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path_out = self.save_output(report, f"calendar_schedule_{month}_{ts}.md", ext="md")
            return {"file": str(path_out), "action": "schedule", "month": month}

        if not unscheduled:
            report = (
                f"# Scheduling Report — {month}\n\n"
                f"No unscheduled items found for {month}.\n"
            )
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path_out = self.save_output(report, f"calendar_schedule_{month}_{ts}.md", ext="md")
            return {"file": str(path_out), "action": "schedule", "month": month}

        # Distribute evenly: cycle through remaining days
        updated = 0
        assigned = []
        for i, row in enumerate(unscheduled):
            date = remaining[i % len(remaining)]
            try:
                db["content_calendar"].update(row["id"], {"scheduled_date": date})
                assigned.append((row.get("title", ""), date))
                updated += 1
            except Exception as e:
                self.logger.warning(f"Could not update schedule for item {row.get('id')}: {e}")

        report_lines = [
            f"# Scheduling Report — {month}",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Items Scheduled:** {updated}",
            f"**Days Available:** {len(remaining)}",
            "",
            "## Assignments",
            "",
            "| Title | Scheduled Date |",
            "|-------|----------------|",
        ]
        for title, date in assigned:
            report_lines.append(f"| {title[:60]} | {date} |")

        report_lines += ["", "---", "*Generated by WheellsVerse Content Calendar Bot*"]
        report = "\n".join(report_lines)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path_out = self.save_output(report, f"calendar_schedule_{month}_{ts}.md", ext="md")
        return {"file": str(path_out), "action": "schedule", "month": month}

    def _action_next(self, db, month: str) -> dict:
        """Return the next planned (not writing/published) item from the calendar."""
        self._ensure_calendar_table(db)
        today = datetime.now().strftime("%Y-%m-%d")

        try:
            rows = list(
                db["content_calendar"].rows_where(
                    "status = 'planned' AND scheduled_date >= ?",
                    [today],
                    order_by="scheduled_date",
                    limit=1,
                )
            )
        except Exception as e:
            self.logger.error(f"Could not query next calendar item: {e}")
            rows = []

        if not rows:
            # Try any planned item in the month
            try:
                rows = list(
                    db["content_calendar"].rows_where(
                        "status = 'planned' AND month = ?",
                        [month],
                        order_by="scheduled_date",
                        limit=1,
                    )
                )
            except Exception:
                rows = []

        report_lines = [
            "# Next Content Item",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
        ]

        next_item = rows[0] if rows else None
        if next_item:
            report_lines += [
                "## Up Next",
                "",
                f"- **Title:** {next_item.get('title', 'N/A')}",
                f"- **Keyword:** {next_item.get('keyword', 'N/A')}",
                f"- **Scheduled:** {next_item.get('scheduled_date', 'N/A')}",
                f"- **Type:** {next_item.get('content_type', 'article')}",
                f"- **Word Count:** {next_item.get('estimated_word_count', 1500)}",
                f"- **Status:** {next_item.get('status', 'planned')}",
            ]
        else:
            report_lines.append("_No planned content items found._")

        report_lines += ["", "---", "*Generated by WheellsVerse Content Calendar Bot*"]
        report = "\n".join(report_lines)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path_out = self.save_output(report, f"calendar_next_{ts}.md", ext="md")
        return {"file": str(path_out), "action": "next", "month": month}

    # ─── Main entry ───────────────────────────────────────────────────────────

    def run(self, action="plan", keyword=None, month=None, **kwargs):
        month = month or datetime.now().strftime("%Y-%m")
        self.logger.info(f"ContentCalendarBot action='{action}' month='{month}'")
        db = get_db()

        if action == "plan":
            return self._action_plan(db, month)
        elif action == "status":
            return self._action_status(db, month)
        elif action == "schedule":
            return self._action_schedule(db, month)
        elif action == "next":
            return self._action_next(db, month)
        else:
            raise ValueError(f"Unknown action '{action}'. Use: plan | status | schedule | next")


if __name__ == "__main__":
    bot = ContentCalendarBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
    print(f"Action: {result['action']}")
    print(f"Month: {result['month']}")
