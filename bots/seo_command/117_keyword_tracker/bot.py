#!/usr/bin/env python3
"""bots/seo_command/117_keyword_tracker/bot.py — Keyword tracker bot"""
import csv
import os
import sys
import re
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402
from core.db import get_db  # noqa: E402


class KeywordTrackerBot(BaseBot):
    """Batch tracks up to 500 keywords daily and reports position changes."""

    def __init__(self):
        super().__init__("117_keyword_tracker", "seo_command")

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _ensure_history_table(self, db):
        """Make sure keyword_history table exists with all needed columns."""
        if "keyword_history" not in db.table_names():
            db["keyword_history"].create(
                {
                    "id": int,
                    "keyword_id": int,
                    "keyword": str,
                    "position": int,
                    "date": str,
                    "search_engine": str,
                    "domain": str,
                },
                pk="id",
            )
        else:
            # Ensure extra columns are present (alter=True on insert handles it,
            # but we do it explicitly so rows_where works right away)
            existing_cols = {col.name for col in db["keyword_history"].columns}
            if "keyword" not in existing_cols:
                db["keyword_history"].add_column("keyword", str)
            if "domain" not in existing_cols:
                db["keyword_history"].add_column("domain", str)

    def _track_via_serper(self, keyword: str, domain: str, serper_key: str) -> int:
        """Query Serper API for a keyword and return position of domain (1-100, 0=not found)."""
        import requests

        url = "https://google.serper.dev/search"
        headers = {"X-API-KEY": serper_key, "Content-Type": "application/json"}
        payload = {"q": keyword, "num": 100}
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            organic = data.get("organic", [])
            for idx, result in enumerate(organic, start=1):
                link = result.get("link", "")
                if domain.lower() in link.lower():
                    return idx
            return 0
        except Exception as e:
            self.logger.warning(f"Serper API error for '{keyword}': {e}")
            return -1  # -1 signals API failure

    def _track_via_ai(self, keyword: str, domain: str) -> int:
        """Use self.ai() to estimate position when Serper is unavailable."""
        prompt = (
            f"Estimate the approximate Google search ranking position (1-100) "
            f"for the domain '{domain}' for the keyword '{keyword}'. "
            f"If the domain is unlikely to rank in the top 100, return 0. "
            f"Return ONLY a single integer, nothing else."
        )
        system = (
            "You are an SEO specialist. Based on domain authority and keyword relevance, "
            "estimate ranking positions. Return only an integer."
        )
        try:
            raw = self.ai(prompt, system=system, max_tokens=10).strip()
            return int(re.search(r"\d+", raw).group())
        except Exception as e:
            self.logger.warning(f"AI position estimate failed for '{keyword}': {e}")
            return 0

    # ─── Actions ──────────────────────────────────────────────────────────────

    def _action_import(self, db, keywords_csv: str) -> dict:
        """Import keywords from CSV file path or comma-separated string."""
        now = datetime.now().isoformat()
        keywords = []

        # Determine if it's a file path or inline CSV
        path = Path(keywords_csv.strip())
        if path.exists() and path.suffix.lower() == ".csv":
            self.logger.info(f"Reading keywords from CSV file: {path}")
            try:
                with open(path, newline="", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    for row in reader:
                        if not row:
                            continue
                        kw = row[0].strip().strip('"').strip("'")
                        if kw and kw.lower() != "keyword":
                            keywords.append(kw)
            except Exception as e:
                self.logger.error(f"Failed to read CSV file: {e}")
                raise
        else:
            # Treat as comma-separated string of keywords
            keywords = [kw.strip() for kw in keywords_csv.split(",") if kw.strip()]

        stored = 0
        for kw in keywords:
            record = {
                "keyword": kw,
                "volume": 0,
                "difficulty": 0,
                "category": "imported",
                "tracked_since": now,
                "last_checked": now,
            }
            try:
                db["keywords"].upsert(record, pk="id", alter=True)
                stored += 1
            except Exception:
                try:
                    existing = list(db["keywords"].rows_where("keyword = ?", [kw]))
                    if not existing:
                        db["keywords"].insert(record, alter=True)
                        stored += 1
                except Exception as e2:
                    self.logger.warning(f"Could not import keyword '{kw}': {e2}")

        self.logger.info(f"Imported {stored} keywords into database")

        report = (
            f"# Keyword Import Report\n"
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"**Source:** {keywords_csv[:80]}\n"
            f"**Keywords Processed:** {len(keywords)}\n"
            f"**Successfully Stored:** {stored}\n\n"
            f"## Imported Keywords\n\n"
        )
        for kw in keywords:
            report += f"- {kw}\n"
        report += "\n---\n*Generated by WheellsVerse Keyword Tracker Bot*\n"

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path_out = self.save_output(report, f"keyword_import_{ts}.md", ext="md")
        return {"file": str(path_out), "action": "import", "keywords_tracked": stored}

    def _action_track(self, db, domain: str) -> dict:
        """Track positions for up to 500 keywords."""
        self._ensure_history_table(db)
        serper_key = os.getenv("SERPER_API_KEY", "")

        try:
            rows = list(db["keywords"].rows_where(order_by="last_checked", limit=500))
        except Exception as e:
            self.logger.error(f"Could not load keywords from DB: {e}")
            rows = []

        if not rows:
            self.logger.warning("No keywords found in database. Run action='import' first.")
            report = (
                "# Keyword Tracking Report\n\n"
                "**No keywords found.** Run with `action='import'` and supply keywords first.\n"
            )
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path_out = self.save_output(report, f"keyword_track_{ts}.md", ext="md")
            return {"file": str(path_out), "action": "track", "keywords_tracked": 0}

        self.logger.info(
            f"Tracking {len(rows)} keywords for domain '{domain}' "
            f"({'Serper API' if serper_key else 'AI estimate'})"
        )

        tracked = 0
        results = []
        now_date = datetime.now().strftime("%Y-%m-%d")
        now_iso = datetime.now().isoformat()

        for row in rows:
            kw = row.get("keyword", "")
            if not kw:
                continue

            if serper_key:
                position = self._track_via_serper(kw, domain, serper_key)
                source = "serper"
                if position == -1:
                    # API failure — fall back to AI
                    position = self._track_via_ai(kw, domain)
                    source = "ai_fallback"
            else:
                position = self._track_via_ai(kw, domain)
                source = "ai_estimate"

            history_record = {
                "keyword_id": row["id"],
                "keyword": kw,
                "position": position,
                "date": now_date,
                "search_engine": "google",
                "domain": domain,
            }
            try:
                db["keyword_history"].insert(history_record, alter=True)
                tracked += 1
            except Exception as e:
                self.logger.warning(f"Failed to save history for '{kw}': {e}")

            # Update last_checked on the keyword record
            try:
                db["keywords"].update(row["id"], {"last_checked": now_iso, "position": position})
            except Exception as e:
                self.logger.warning(f"Failed to update keyword record for '{kw}': {e}")

            results.append({"keyword": kw, "position": position, "source": source})

        # Build report
        ranked = sorted([r for r in results if r["position"] > 0], key=lambda x: x["position"])
        unranked = [r for r in results if r["position"] == 0]

        report_lines = [
            "# Keyword Tracking Report",
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Domain:** {domain}",
            f"**Keywords Tracked:** {tracked}",
            f"**Source:** {'Serper API' if serper_key else 'AI Estimate'}",
            "",
            "---",
            "",
            f"## Ranked Keywords ({len(ranked)})",
            "",
        ]
        if ranked:
            report_lines.append("| # | Keyword | Position |")
            report_lines.append("|---|---------|----------|")
            for i, r in enumerate(ranked, 1):
                report_lines.append(f"| {i} | {r['keyword']} | {r['position']} |")
        else:
            report_lines.append("_No keywords ranked in top 100._")

        report_lines += [
            "",
            f"## Unranked / Not Found ({len(unranked)})",
            "",
        ]
        for r in unranked[:50]:
            report_lines.append(f"- {r['keyword']}")
        if len(unranked) > 50:
            report_lines.append(f"_... and {len(unranked) - 50} more_")

        report_lines += ["", "---", "*Generated by WheellsVerse Keyword Tracker Bot*"]
        report = "\n".join(report_lines)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path_out = self.save_output(report, f"keyword_track_{ts}.md", ext="md")
        return {"file": str(path_out), "action": "track", "keywords_tracked": tracked}

    def _action_report(self, db, domain: str) -> dict:
        """Generate a delta report comparing the last 7 days of keyword history."""
        self._ensure_history_table(db)
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")

        try:
            recent = list(
                db["keyword_history"].rows_where(
                    "date >= ? AND domain = ?", [cutoff, domain],
                    order_by="date DESC",
                )
            )
        except Exception as e:
            self.logger.error(f"Could not query keyword_history: {e}")
            recent = []

        if not recent:
            # Try without domain filter in case older records lack it
            try:
                recent = list(
                    db["keyword_history"].rows_where(
                        "date >= ?", [cutoff], order_by="date DESC"
                    )
                )
            except Exception:
                recent = []

        # Group by keyword: latest vs earliest record in the window
        kw_records: dict = {}
        for row in recent:
            kw = row.get("keyword") or str(row.get("keyword_id", "unknown"))
            if kw not in kw_records:
                kw_records[kw] = {"latest": row, "earliest": row}
            else:
                if row["date"] < kw_records[kw]["earliest"]["date"]:
                    kw_records[kw]["earliest"] = row
                if row["date"] > kw_records[kw]["latest"]["date"]:
                    kw_records[kw]["latest"] = row

        moved_up, moved_down, stable, new_entries = [], [], [], []

        for kw, data in kw_records.items():
            latest_pos = data["latest"].get("position", 0)
            earliest_pos = data["earliest"].get("position", 0)
            is_new = data["latest"]["date"] == data["earliest"]["date"]

            if is_new:
                new_entries.append({"keyword": kw, "position": latest_pos})
            elif latest_pos > 0 and earliest_pos > 0:
                delta = earliest_pos - latest_pos  # positive = moved up
                if delta > 0:
                    moved_up.append({"keyword": kw, "old": earliest_pos,
                                     "new": latest_pos, "delta": delta})
                elif delta < 0:
                    moved_down.append({"keyword": kw, "old": earliest_pos,
                                       "new": latest_pos, "delta": delta})
                else:
                    stable.append({"keyword": kw, "position": latest_pos})
            else:
                stable.append({"keyword": kw, "position": latest_pos})

        moved_up.sort(key=lambda x: x["delta"], reverse=True)
        moved_down.sort(key=lambda x: x["delta"])

        report_lines = [
            "# Keyword Position Delta Report",
            f"**Period:** {cutoff} → {today}",
            f"**Domain:** {domain}",
            f"**Total Keywords:** {len(kw_records)}",
            "",
            "---",
            "",
            f"## Moved Up — {len(moved_up)} keywords ↑",
            "",
        ]
        if moved_up:
            report_lines.append("| Keyword | Old Position | New Position | Change |")
            report_lines.append("|---------|-------------|-------------|--------|")
            for r in moved_up:
                report_lines.append(
                    f"| {r['keyword']} | {r['old']} | {r['new']} | ↑ +{r['delta']} |"
                )
        else:
            report_lines.append("_No keywords moved up._")

        report_lines += ["", f"## Moved Down — {len(moved_down)} keywords ↓", ""]
        if moved_down:
            report_lines.append("| Keyword | Old Position | New Position | Change |")
            report_lines.append("|---------|-------------|-------------|--------|")
            for r in moved_down:
                report_lines.append(
                    f"| {r['keyword']} | {r['old']} | {r['new']} | ↓ {r['delta']} |"
                )
        else:
            report_lines.append("_No keywords moved down._")

        report_lines += ["", f"## New Entries — {len(new_entries)} keywords", ""]
        for r in new_entries[:20]:
            report_lines.append(f"- **{r['keyword']}** — position {r['position']}")
        if len(new_entries) > 20:
            report_lines.append(f"_... and {len(new_entries) - 20} more_")

        report_lines += ["", f"## Stable — {len(stable)} keywords", ""]
        for r in stable[:20]:
            report_lines.append(f"- {r['keyword']} (pos {r['position']})")
        if len(stable) > 20:
            report_lines.append(f"_... and {len(stable) - 20} more_")

        report_lines += ["", "---", "*Generated by WheellsVerse Keyword Tracker Bot*"]
        report = "\n".join(report_lines)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path_out = self.save_output(report, f"keyword_delta_{ts}.md", ext="md")
        return {
            "file": str(path_out),
            "action": "report",
            "keywords_tracked": len(kw_records),
        }

    # ─── Main entry ───────────────────────────────────────────────────────────

    def run(self, action="track", keywords_csv=None, **kwargs):
        cfg = self.config
        domain = cfg.get("default_domain", "wheellsverse-bots.pages.dev")

        self.logger.info(f"KeywordTrackerBot action='{action}' domain='{domain}'")
        db = get_db()

        if action == "import":
            if not keywords_csv:
                raise ValueError("keywords_csv is required for action='import'")
            return self._action_import(db, keywords_csv)

        elif action == "track":
            return self._action_track(db, domain)

        elif action == "report":
            return self._action_report(db, domain)

        else:
            raise ValueError(f"Unknown action '{action}'. Use: import | track | report")


if __name__ == "__main__":
    bot = KeywordTrackerBot()
    result = bot.execute()
    print(f"Output: {result['file']}")
    print(f"Keywords tracked: {result['keywords_tracked']}")
