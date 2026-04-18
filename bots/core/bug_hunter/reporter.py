#!/usr/bin/env python3
"""
bots/core/bug_hunter/reporter.py
─────────────────────────────────────────────────────────────────────────────
Generates Markdown and JSON reports from classified bugs.
─────────────────────────────────────────────────────────────────────────────
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from .detector import Bug, SEVERITY_RANK

logger = logging.getLogger("bug_hunter.reporter")

ROOT = Path(__file__).parent.parent.parent.parent
REPORT_DIR = ROOT / "logs" / "bug_hunter"

SEVERITY_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH":     "🟠",
    "MEDIUM":   "🟡",
    "LOW":      "🔵",
    "INFO":     "⚪",
}


class Reporter:
    def __init__(self, report_dir: Optional[Path] = None):
        self.report_dir = report_dir or REPORT_DIR
        self.report_dir.mkdir(parents=True, exist_ok=True)

    def save_json(self, bugs: List[Bug], summary: Dict[str, Any], run_id: str = "") -> Path:
        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        data = {
            "run_id": run_id,
            "timestamp": datetime.now().isoformat(),
            "summary": summary,
            "bugs": [b.to_dict() for b in bugs],
        }
        out_path = self.report_dir / f"report_{run_id}.json"
        out_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info(f"JSON report saved: {out_path}")
        return out_path

    def save_markdown(self, bugs: List[Bug], summary: Dict[str, Any], run_id: str = "") -> Path:
        run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        lines = [
            f"# Bug Hunter Report — {run_id}",
            f"",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"",
            f"## Summary",
            f"",
            f"| Severity | Count |",
            f"|----------|-------|",
        ]
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            count = summary.get("by_severity", {}).get(sev, 0)
            if count:
                lines.append(f"| {SEVERITY_EMOJI[sev]} {sev} | {count} |")
        lines += [
            f"",
            f"**Total:** {summary['total']}  |  "
            f"**Auto-fixable:** {summary.get('auto_fixable', 0)}",
            f"",
            f"### By Category",
            f"",
        ]
        for cat, count in sorted(summary.get("by_category", {}).items()):
            lines.append(f"- **{cat}**: {count}")

        lines += ["", "---", "", "## Findings", ""]

        current_sev = None
        for bug in bugs:
            if bug.severity != current_sev:
                current_sev = bug.severity
                lines.append(f"### {SEVERITY_EMOJI[bug.severity]} {bug.severity}")
                lines.append("")

            lines += [
                f"#### `{bug.id}` — {bug.title}",
                f"",
                f"- **File:** `{bug.file}:{bug.line}`",
                f"- **Category:** {bug.category}",
                f"- **Description:** {bug.description}",
                f"- **Fix:** {bug.fix_hint}",
                f"- **Auto-fixable:** {'Yes' if bug.auto_fixable else 'No'}",
                f"",
                f"```python",
                f"{bug.snippet}",
                f"```",
                f"",
            ]

        out_path = self.report_dir / f"report_{run_id}.md"
        out_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Markdown report saved: {out_path}")
        return out_path

    def save_latest_symlink(self, md_path: Path):
        """Update logs/bug_hunter/latest.md → most recent report."""
        latest = self.report_dir / "latest.md"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(md_path.name)
        except Exception as e:
            logger.warning(f"Could not update latest.md symlink: {e}")

    def print_summary(self, bugs: List[Bug], summary: Dict[str, Any]):
        print(f"\n{'─'*60}")
        print(f"  Bug Hunter — {summary['total']} findings")
        print(f"{'─'*60}")
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            count = summary.get("by_severity", {}).get(sev, 0)
            if count:
                print(f"  {SEVERITY_EMOJI[sev]} {sev:8s}  {count}")
        print(f"{'─'*60}")
        print(f"  Auto-fixable: {summary.get('auto_fixable', 0)}")
        print(f"{'─'*60}\n")
        # Print CRITICAL + HIGH details
        shown = [b for b in bugs if b.severity in ("CRITICAL", "HIGH")]
        if shown:
            print("  Critical/High findings:")
            for b in shown[:20]:
                print(f"  [{b.id}] {b.file}:{b.line}  {b.title}")
        print()
