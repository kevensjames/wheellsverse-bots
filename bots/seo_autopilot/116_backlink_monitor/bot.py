#!/usr/bin/env python3
"""bots/seo_autopilot/116_backlink_monitor/bot.py — Backlink monitor"""
import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from core.base_bot import BaseBot  # noqa: E402


class BacklinkMonitorBot(BaseBot):
    """
    Monitors backlinks and referring domains for a target domain.
    Uses Ahrefs API if AHREFS_API_KEY is available, otherwise generates
    an AI-based backlink analysis for demonstration purposes.
    """

    def __init__(self):
        super().__init__("116_backlink_monitor", "seo_autopilot")

    def run(self, domain=None, action="scan", **kwargs):
        cfg = self.config
        domain = domain or cfg.get("default_domain", "wheellsverse-bots.pages.dev")

        if action == "report":
            return self._generate_report(domain)

        # Default: action == "scan"
        return self._scan_backlinks(domain)

    # ──────────────────────────────────────────────────────────────────────────
    # Scan action
    # ──────────────────────────────────────────────────────────────────────────

    def _scan_backlinks(self, domain: str):
        ahrefs_key = os.getenv("AHREFS_API_KEY", "")
        self.logger.info(f"Scanning backlinks for: {domain}")

        backlinks_data = None
        source = "unknown"

        if ahrefs_key:
            backlinks_data = self._fetch_ahrefs(domain, ahrefs_key)
            source = "ahrefs"

        if not backlinks_data:
            # AI-simulated analysis (noted in output)
            backlinks_data = self._simulate_backlink_analysis(domain)
            source = "ai_simulated"
            self.logger.info(
                "AHREFS_API_KEY not set or API call failed — using AI-simulated backlink data "
                "(demo purposes only)"
            )

        now = datetime.now().isoformat()

        # Store each backlink record in SQLite
        stored_count = 0
        try:
            from core.db import get_db
            db = get_db()
            for bl in backlinks_data.get("backlinks", []):
                record = {
                    "domain": domain,
                    "referring_domain": bl.get("referring_domain", ""),
                    "anchor_text": bl.get("anchor_text", ""),
                    "target_url": bl.get("target_url", ""),
                    "domain_rating": bl.get("domain_rating", 0),
                    "first_seen": bl.get("first_seen", now),
                    "source": source,
                    "scanned_at": now,
                }
                db["backlinks"].insert(record, alter=True)
                stored_count += 1
        except Exception as e:
            self.logger.warning(f"Could not store backlinks in SQLite: {e}")

        self.logger.info(f"Stored {stored_count} backlink records in SQLite")

        # Generate scan report
        report = self._build_scan_report(domain, backlinks_data, source)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_domain = re.sub(r"[^\w]+", "_", domain)[:40]
        fname = f"backlink_scan_{safe_domain}_{ts}.md"
        path = self.save_output(report, fname, ext="md")

        self.logger.info(f"Backlink scan report saved -> {path}")
        return {
            "file": str(path),
            "action": "scan",
            "domain": domain,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # Report action
    # ──────────────────────────────────────────────────────────────────────────

    def _generate_report(self, domain: str):
        self.logger.info(f"Generating backlink report for: {domain}")

        rows = []
        try:
            from core.db import get_db
            db = get_db()
            if "backlinks" in db.table_names():
                rows = list(db["backlinks"].rows_where(
                    "domain = ?", [domain]
                ))
                self.logger.info(f"Loaded {len(rows)} backlink records from SQLite")
        except Exception as e:
            self.logger.warning(f"Could not load backlinks from SQLite: {e}")

        # Compute summary metrics
        one_week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        referring_domains = {r.get("referring_domain", "") for r in rows if r.get("referring_domain")}
        new_this_week = [
            r for r in rows
            if r.get("first_seen", "") >= one_week_ago
        ]
        new_domains_this_week = {r.get("referring_domain", "") for r in new_this_week}

        # Count anchor text frequency
        anchor_counts = {}
        for r in rows:
            anchor = r.get("anchor_text", "").strip()
            if anchor:
                anchor_counts[anchor] = anchor_counts.get(anchor, 0) + 1
        top_anchors = sorted(anchor_counts.items(), key=lambda x: x[1], reverse=True)[:10]

        lines = [
            "# Backlink Monitor Report",
            f"**Domain:** {domain}",
            f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "---",
            "",
            "## Summary",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Backlink Records | {len(rows)} |",
            f"| Total Referring Domains | {len(referring_domains)} |",
            f"| New Referring Domains This Week | {len(new_domains_this_week)} |",
            f"| New Backlinks This Week | {len(new_this_week)} |",
            "",
            "---",
            "",
            "## Top Anchor Texts",
            "",
            "| Anchor Text | Count |",
            "|-------------|-------|",
        ]

        if top_anchors:
            for anchor, count in top_anchors:
                lines.append(f"| {anchor} | {count} |")
        else:
            lines.append("| _No data available_ | - |")

        lines += [
            "",
            "---",
            "",
            "## New Referring Domains (This Week)",
            "",
        ]

        if new_domains_this_week:
            for rd in sorted(new_domains_this_week):
                lines.append(f"- {rd}")
        else:
            lines.append("_No new referring domains recorded this week._")

        lines += [
            "",
            "---",
            "*Generated by WheellsVerse Backlink Monitor Bot*",
        ]

        report = "\n".join(lines)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_domain = re.sub(r"[^\w]+", "_", domain)[:40]
        fname = f"backlink_report_{safe_domain}_{ts}.md"
        path = self.save_output(report, fname, ext="md")

        self.logger.info(f"Backlink report saved -> {path}")
        return {
            "file": str(path),
            "action": "report",
            "domain": domain,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # API and AI helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _fetch_ahrefs(self, domain: str, api_key: str) -> dict | None:
        """Fetch backlink data from Ahrefs API v3."""
        try:
            import requests
            endpoint = "https://api.ahrefs.com/v3/site-explorer/backlinks"
            params = {
                "select": "url_from,domain_rating_source,anchor,url_to,first_seen",
                "target": domain,
                "limit": 200,
                "order_by": "domain_rating_source:desc",
                "mode": "subdomains",
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            }
            resp = requests.get(endpoint, params=params, headers=headers, timeout=20)
            resp.raise_for_status()
            data = resp.json()

            backlinks = []
            for item in data.get("backlinks", []):
                url_from = item.get("url_from", "")
                referring_domain = re.sub(r"https?://([^/]+).*", r"\1", url_from)
                backlinks.append({
                    "referring_domain": referring_domain,
                    "anchor_text": item.get("anchor", ""),
                    "target_url": item.get("url_to", ""),
                    "domain_rating": item.get("domain_rating_source", 0),
                    "first_seen": item.get("first_seen", ""),
                })

            self.logger.info(f"Fetched {len(backlinks)} backlinks from Ahrefs")
            return {
                "total": len(backlinks),
                "backlinks": backlinks,
            }

        except Exception as e:
            self.logger.warning(f"Ahrefs API error: {e}")
            return None

    def _simulate_backlink_analysis(self, domain: str) -> dict:
        """
        Use AI to generate a realistic backlink analysis.
        NOTE: This is simulated data for demonstration purposes only.
        """
        prompt = (
            f"Generate a realistic backlink analysis for the domain: {domain}\n"
            f"Return ONLY valid JSON in this exact format:\n"
            f'{{"total_referring_domains": <int>, "total_backlinks": <int>, '
            f'"backlinks": [{{"referring_domain": "example.com", "anchor_text": "...", '
            f'"target_url": "https://{domain}/", "domain_rating": <int 0-100>, '
            f'"first_seen": "2025-01-15T00:00:00Z"}}]}}\n'
            f"Include 15-25 realistic backlinks from plausible sources like Reddit, Medium, "
            f"finance blogs, YouTube descriptions, forums. "
            f"Return ONLY the JSON object, nothing else."
        )

        try:
            raw = self.ai(
                prompt,
                system=(
                    "You are an SEO analyst generating demo backlink data. "
                    "Return only valid JSON, no explanation."
                ),
                max_tokens=2000,
                temperature=0.6,
            )
            raw_clean = re.sub(r"```json\s*|\s*```", "", raw).strip()
            data = json.loads(raw_clean)
            if "backlinks" not in data:
                raise ValueError("Missing backlinks key")
            self.logger.info(
                f"AI-simulated {len(data['backlinks'])} backlinks "
                f"(NOTE: demo data, not real)"
            )
            return data
        except Exception as e:
            self.logger.warning(f"AI simulation failed: {e} — returning minimal data")
            return {
                "total_referring_domains": 5,
                "total_backlinks": 8,
                "backlinks": [
                    {
                        "referring_domain": "reddit.com",
                        "anchor_text": "passive income guide",
                        "target_url": f"https://{domain}/",
                        "domain_rating": 91,
                        "first_seen": "2025-01-10T00:00:00Z",
                    },
                    {
                        "referring_domain": "medium.com",
                        "anchor_text": "crypto investing tips",
                        "target_url": f"https://{domain}/blog/",
                        "domain_rating": 88,
                        "first_seen": "2025-02-01T00:00:00Z",
                    },
                ],
            }

    # ──────────────────────────────────────────────────────────────────────────
    # Scan report builder
    # ──────────────────────────────────────────────────────────────────────────

    def _build_scan_report(self, domain: str, data: dict, source: str) -> str:
        backlinks = data.get("backlinks", [])
        total_bl = data.get("total_backlinks", len(backlinks))
        referring_domains = {bl.get("referring_domain", "") for bl in backlinks}
        total_rd = data.get("total_referring_domains", len(referring_domains))

        source_note = ""
        if source == "ai_simulated":
            source_note = (
                "\n> **Note:** AHREFS_API_KEY not configured. "
                "The data below is AI-simulated for demonstration purposes only.\n"
            )

        lines = [
            "# Backlink Scan Report",
            f"**Domain:** {domain}",
            f"**Scanned:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Data Source:** {source}",
            source_note,
            "",
            "---",
            "",
            "## Overview",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total Backlinks | {total_bl} |",
            f"| Referring Domains | {total_rd} |",
            f"| Backlinks Analyzed | {len(backlinks)} |",
            "",
            "---",
            "",
            "## Top Backlinks",
            "",
            "| Referring Domain | Anchor Text | Target URL | DR |",
            "|-----------------|-------------|------------|----|",
        ]

        # Sort by domain rating descending
        sorted_bl = sorted(backlinks, key=lambda x: x.get("domain_rating", 0), reverse=True)
        for bl in sorted_bl[:20]:
            rd = bl.get("referring_domain", "N/A")
            anchor = bl.get("anchor_text", "N/A")[:40]
            target = bl.get("target_url", "N/A")[:60]
            dr = bl.get("domain_rating", "N/A")
            lines.append(f"| {rd} | {anchor} | {target} | {dr} |")

        if len(sorted_bl) > 20:
            lines.append(f"| _... and {len(sorted_bl) - 20} more_ | - | - | - |")

        lines += [
            "",
            "---",
            "*Generated by WheellsVerse Backlink Monitor Bot*",
        ]

        return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default=None)
    parser.add_argument("--action", default="scan", choices=["scan", "report"])
    args = parser.parse_args()

    bot = BacklinkMonitorBot()
    result = bot.execute(domain=args.domain, action=args.action)
    print(f"Output: {result['file']}")
    print(f"Domain: {result['domain']}")
