#!/usr/bin/env python3
"""
bots/core/bug_hunter/scheduler.py
─────────────────────────────────────────────────────────────────────────────
Integrates the bug hunter into the main WheellsVerse scheduler.
Call register() once at startup to schedule daily scans.
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("bug_hunter.scheduler")

ROOT = Path(__file__).parent.parent.parent.parent


def register(scheduler=None, time_str: str = "03:00", auto_fix: bool = False):
    """
    Register a daily bug-hunter scan with the main BotScheduler.
    Falls back to a standalone schedule job if no scheduler is provided.
    """
    try:
        import schedule as _sched

        def _run():
            _do_scan(auto_fix=auto_fix)

        _sched.every().day.at(time_str).do(_run)
        logger.info(f"Bug hunter scheduled daily at {time_str}")

        if scheduler is not None:
            scheduler.jobs.append({
                "bot": "bug_hunter",
                "schedule": f"@daily {time_str}",
                "job": None,
                "next_run": "?",
            })
    except Exception as e:
        logger.error(f"Failed to register bug hunter: {e}")


def _do_scan(
    scan_paths=None,
    auto_fix: bool = False,
    report_dir: Optional[Path] = None,
):
    """Run a full scan cycle: scan → detect → fix (optional) → report."""
    from .scanner import Scanner
    from .detector import Detector
    from .reporter import Reporter
    from .fixer import Fixer
    from datetime import datetime

    logger.info("Bug hunter scheduled scan starting")
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    scanner = Scanner()
    detector = Detector()
    reporter = Reporter(report_dir)
    fixer = Fixer(dry_run=not auto_fix)

    paths = scan_paths or [ROOT / "bots", ROOT / "core"]
    all_findings = []
    for p in paths:
        all_findings.extend(scanner.scan_path(Path(p)))

    bugs = detector.classify(all_findings)
    summary = detector.summary(bugs)

    if auto_fix:
        fix_results = fixer.fix_all(bugs)
        fixed = sum(1 for r in fix_results if r.applied)
        logger.info(f"Auto-fixed {fixed} issues")

    md_path = reporter.save_markdown(bugs, summary, run_id)
    reporter.save_json(bugs, summary, run_id)
    reporter.save_latest_symlink(md_path)
    reporter.print_summary(bugs, summary)

    logger.info(
        f"Bug hunter scan complete — {summary['total']} findings, "
        f"{summary.get('auto_fixable', 0)} auto-fixable"
    )
    return summary
