#!/usr/bin/env python3
"""bots/seo_autopilot/115_rank_tracker/bot.py — SEO rank tracker"""
import os
import sys
import re
import requests
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class RankTrackerBot(BaseBot):
    """
    Monitors keyword positions in Google search results.
    Uses Serper API if SERPER_API_KEY is available, otherwise estimates
    position via AI based on keyword competitiveness.
    """

    def __init__(self):
        super().__init__("115_rank_tracker", "seo_autopilot")

    def run(self, action="track", keyword=None, **kwargs):
        cfg = self.config
        default_domain = cfg.get("default_domain", "wheellsverse-bots.pages.dev")
        serper_key = os.getenv("SERPER_API_KEY", "")

        if action == "report":
            return self._generate_trend_report(default_domain)

        # Default: action == "track"
        return self._track_keywords(keyword, default_domain, serper_key)

    # ──────────────────────────────────────────────────────────────────────────
    # Track action
    # ──────────────────────────────────────────────────────────────────────────

    def _track_keywords(self, keyword, default_domain, serper_key):
        keywords_to_track = []

        if keyword:
            keywords_to_track = [{"keyword": keyword, "id": None}]
            self.logger.info(f"Tracking single keyword: '{keyword}'")
        else:
            # Load from SQLite
            try:
                from core.db import get_db
                db = get_db()
                if "keywords" in db.table_names():
                    rows = list(db["keywords"].rows_where(limit=50))
                    keywords_to_track = [
                        {"keyword": r.get("keyword", ""), "id": r.get("id")}
                        for r in rows if r.get("keyword")
                    ]
                    self.logger.info(f"Loaded {len(keywords_to_track)} keywords from SQLite")
                else:
                    self.logger.warning("No keywords table found in SQLite")
            except Exception as e:
                self.logger.warning(f"Could not load keywords from SQLite: {e}")

            if not keywords_to_track:
                self.logger.info("No keywords to track — using default set")
                keywords_to_track = [
                    {"keyword": kw, "id": None} for kw in [
                        "best passive income ideas 2025",
                        "crypto investing for beginners",
                        "AI tools for content creators",
                        "side hustle ideas online",
                        "how to make money blogging",
                    ]
                ]

        results = []
        now = datetime.now().isoformat()

        for kw_item in keywords_to_track:
            kw = kw_item["keyword"].strip()
            if not kw:
                continue

            position = None
            source = "unknown"

            if serper_key:
                position = self._check_serper(kw, default_domain, serper_key)
                source = "serper"
                if position is None:
                    self.logger.info(f"Domain not found in Serper results for '{kw}'")
                    position = 101  # beyond top 100
            else:
                position = self._estimate_position_ai(kw)
                source = "ai_estimate"

            result_record = {
                "keyword": kw,
                "domain": default_domain,
                "position": position,
                "source": source,
                "checked_at": now,
            }
            results.append(result_record)

            # Store in SQLite keyword_history
            try:
                from core.db import get_db
                db = get_db()
                db["keyword_history"].insert(result_record, alter=True)
            except Exception as e:
                self.logger.warning(f"Could not store rank history for '{kw}': {e}")

            self.logger.info(f"Tracked '{kw}' -> position {position} ({source})")

        # Generate markdown report
        report = self._build_tracking_report(results, default_domain, serper_key)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"rank_tracking_{ts}.md"
        path = self.save_output(report, fname, ext="md")

        self.logger.info(f"Rank tracking report saved -> {path}")
        return {
            "file": str(path),
            "action": "track",
            "keywords_tracked": len(results),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Report action
    # ──────────────────────────────────────────────────────────────────────────

    def _generate_trend_report(self, default_domain):
        self.logger.info("Generating rank trend report for last 7 days")

        history = []
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()

        try:
            from core.db import get_db
            db = get_db()
            if "keyword_history" in db.table_names():
                history = list(db["keyword_history"].rows_where(
                    "checked_at >= ?", [cutoff]
                ))
                self.logger.info(f"Loaded {len(history)} history records")
        except Exception as e:
            self.logger.warning(f"Could not load keyword_history from SQLite: {e}")

        # Group by keyword to compute position changes
        keyword_data = {}
        for row in history:
            kw = row.get("keyword", "")
            if kw not in keyword_data:
                keyword_data[kw] = []
            keyword_data[kw].append(row)

        # Sort each keyword's history by checked_at
        trends = []
        for kw, rows in keyword_data.items():
            rows_sorted = sorted(rows, key=lambda r: r.get("checked_at", ""))
            first_pos = rows_sorted[0].get("position", 0) if rows_sorted else 0
            last_pos = rows_sorted[-1].get("position", 0) if rows_sorted else 0
            change = first_pos - last_pos  # positive = moved up
            trends.append({
                "keyword": kw,
                "first_position": first_pos,
                "latest_position": last_pos,
                "change": change,
                "checks": len(rows),
            })

        trends_sorted = sorted(trends, key=lambda x: x["latest_position"])

        lines = [
            "# Keyword Rank Trend Report (Last 7 Days)",
            f"**Domain:** {default_domain}",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Keywords tracked:** {len(trends)}",
            "",
            "---",
            "",
            "## Position Changes",
            "",
            "| Keyword | First Position | Latest Position | Change | Trend |",
            "|---------|---------------|-----------------|--------|-------|",
        ]

        if trends_sorted:
            for t in trends_sorted:
                arrow = "↑" if t["change"] > 0 else ("↓" if t["change"] < 0 else "→")
                change_str = f"+{t['change']}" if t["change"] > 0 else str(t["change"])
                lines.append(
                    f"| {t['keyword']} | {t['first_position']} | "
                    f"{t['latest_position']} | {change_str} | {arrow} |"
                )
        else:
            lines.append("| _No data available for the last 7 days_ | - | - | - | - |")

        lines += [
            "",
            "---",
            "*Generated by WheellsVerse Rank Tracker Bot*",
        ]

        report = "\n".join(lines)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"rank_trend_report_{ts}.md"
        path = self.save_output(report, fname, ext="md")

        self.logger.info(f"Trend report saved -> {path}")
        return {
            "file": str(path),
            "action": "report",
            "keywords_tracked": len(trends),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Position checking helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _check_serper(self, keyword: str, domain: str, api_key: str):
        """Query Serper API and return position of domain in organic results (1-indexed)."""
        try:
            resp = requests.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json={"q": keyword, "num": 100},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            organic = data.get("organic", [])
            for idx, result in enumerate(organic, start=1):
                link = result.get("link", "")
                if domain.lower() in link.lower():
                    return idx
            return None  # domain not found in results
        except Exception as e:
            self.logger.warning(f"Serper API error for '{keyword}': {e}")
            return None

    def _estimate_position_ai(self, keyword: str) -> int:
        """Use AI to estimate a keyword's competitiveness and approximate SERP position."""
        prompt = (
            f"Estimate the Google SERP position (1-100) for the domain "
            f"'wheellsverse-bots.pages.dev' ranking for the keyword: '{keyword}'. "
            f"Consider the keyword's competitiveness and the domain's authority. "
            f"Return ONLY a single integer between 1 and 100. No explanation, no text."
        )
        try:
            raw = self.ai(
                prompt,
                system=(
                    "You are an SEO analyst. Estimate SERP positions based on keyword "
                    "competitiveness. Return only an integer 1-100."
                ),
                max_tokens=10,
                temperature=0.3,
            )
            match = re.search(r"\d+", raw)
            if match:
                pos = int(match.group())
                return max(1, min(100, pos))
        except Exception as e:
            self.logger.warning(f"AI position estimate failed for '{keyword}': {e}")
        return 50  # default fallback

    # ──────────────────────────────────────────────────────────────────────────
    # Report builder
    # ──────────────────────────────────────────────────────────────────────────

    def _build_tracking_report(self, results: list, domain: str, serper_key: str) -> str:
        source_label = "Serper API" if serper_key else "AI Estimate"
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = [
            "# Keyword Rank Tracking Report",
            f"**Date:** {ts}",
            f"**Domain:** {domain}",
            f"**Data Source:** {source_label}",
            f"**Keywords Checked:** {len(results)}",
            "",
            "---",
            "",
            "## Keyword Positions",
            "",
            "| # | Keyword | Position | Source |",
            "|---|---------|----------|--------|",
        ]

        sorted_results = sorted(results, key=lambda r: r.get("position", 999))
        for idx, r in enumerate(sorted_results, 1):
            pos = r.get("position", "N/A")
            pos_display = f"#{pos}" if isinstance(pos, int) else str(pos)
            lines.append(
                f"| {idx} | {r['keyword']} | {pos_display} | {r.get('source', 'N/A')} |"
            )

        top10 = [r for r in results if isinstance(r.get("position"), int) and r["position"] <= 10]
        top50 = [r for r in results if isinstance(r.get("position"), int) and r["position"] <= 50]

        lines += [
            "",
            "---",
            "",
            "## Summary",
            "",
            f"- **Top 10:** {len(top10)} keywords",
            f"- **Top 50:** {len(top50)} keywords",
            f"- **Total tracked:** {len(results)} keywords",
            "",
            "---",
            "*Generated by WheellsVerse Rank Tracker Bot*",
        ]

        return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", default="track", choices=["track", "report"])
    parser.add_argument("--keyword", default=None)
    args = parser.parse_args()

    bot = RankTrackerBot()
    result = bot.execute(action=args.action, keyword=args.keyword)
    print(f"Output: {result['file']}")
    print(f"Keywords tracked: {result['keywords_tracked']}")
