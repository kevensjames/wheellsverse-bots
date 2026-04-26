#!/usr/bin/env python3
"""
bots/core/bug_hunter/bot.py
─────────────────────────────────────────────────────────────────────────────
Bug Hunter Bot — BaseBot-compatible wrapper + argparse CLI.

CLI usage:
  python -m bots.core.bug_hunter scan              # scan bots/ and core/
  python -m bots.core.bug_hunter fix --auto        # scan + apply safe fixes
  python -m bots.core.bug_hunter report            # print last report summary
  python -m bots.core.bug_hunter watch             # start real-time watchdog
─────────────────────────────────────────────────────────────────────────────
"""

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bug_hunter")

from bots.core.bug_hunter.scanner import Scanner
from bots.core.bug_hunter.detector import Detector
from bots.core.bug_hunter.fixer import Fixer
from bots.core.bug_hunter.reporter import Reporter
from bots.core.bug_hunter.watchdog import Watchdog

try:
    from core.base_bot import BaseBot
    _HAS_BASE = True
except Exception:
    _HAS_BASE = False

SCAN_PATHS = [ROOT / "bots", ROOT / "core"]
REPORT_DIR = ROOT / "logs" / "bug_hunter"


def run_scan(auto_fix: bool = False, dry_run: bool = True) -> dict:
    from datetime import datetime
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    scanner = Scanner()
    detector = Detector()
    reporter = Reporter(REPORT_DIR)
    fixer = Fixer(dry_run=dry_run)

    all_findings = []
    for p in SCAN_PATHS:
        logger.info(f"Scanning {p} ...")
        all_findings.extend(scanner.scan_path(p))

    bugs = detector.classify(all_findings)
    summary = detector.summary(bugs)

    if auto_fix:
        fix_results = fixer.fix_all(bugs)
        fixed = sum(1 for r in fix_results if r.applied)
        summary["fixed"] = fixed
        logger.info(f"Applied {fixed} automatic fixes")

    md_path = reporter.save_markdown(bugs, summary, run_id)
    reporter.save_json(bugs, summary, run_id)
    reporter.save_latest_symlink(md_path)
    reporter.print_summary(bugs, summary)

    return summary


# ─── BaseBot subclass ─────────────────────────────────────────────────────────

if _HAS_BASE:
    class BugHunterBot(BaseBot):
        def __init__(self):
            super().__init__(name="bug_hunter", category="core")
            # BaseBot doesn't take description= as a kwarg; set it as an attribute.
            self.description = "Autonomous static bug scanner for the WheellsVerse ecosystem"

        def execute(self, **kwargs):
            return run_scan(auto_fix=False)

        def run(self, **kwargs):
            # BaseBot requires run(); delegate to execute().
            return self.execute(**kwargs)
else:
    class BugHunterBot:  # type: ignore
        name = "bug_hunter"

        def execute(self, **kwargs):
            return run_scan(auto_fix=False)

        def run(self, **kwargs):
            return self.execute(**kwargs)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def _cmd_scan(args):
    summary = run_scan(auto_fix=False)
    print(f"\nScan complete. {summary['total']} findings.")


def _cmd_fix(args):
    summary = run_scan(auto_fix=True, dry_run=not args.auto)
    if args.auto:
        print(f"\nFix run complete. {summary.get('fixed', 0)} fixes applied.")
    else:
        print(f"\nDry run complete. Pass --auto to apply fixes.")


def _cmd_report(args):
    latest = REPORT_DIR / "latest.md"
    if latest.exists():
        real = latest.resolve()
        print(f"Latest report: {real}\n")
        # Print the summary section only
        text = real.read_text(encoding="utf-8")
        in_summary = False
        for line in text.splitlines():
            if line.startswith("## Summary"):
                in_summary = True
            elif line.startswith("## ") and in_summary:
                break
            if in_summary:
                print(line)
    else:
        print("No reports found. Run 'scan' first.")


def _cmd_watch(args):
    print("Starting real-time watchdog (Ctrl+C to stop)...")
    wd = Watchdog(watch_paths=SCAN_PATHS, interval=args.interval)
    wd.start(blocking=True)


def main():
    parser = argparse.ArgumentParser(
        prog="bug_hunter",
        description="WheellsVerse Bug Hunter — static analysis + auto-fix"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("scan", help="Scan bots/ and core/ for bugs")

    fix_p = sub.add_parser("fix", help="Scan and optionally apply safe fixes")
    fix_p.add_argument("--auto", action="store_true", help="Apply fixes (default: dry run)")

    sub.add_parser("report", help="Print latest report summary")

    watch_p = sub.add_parser("watch", help="Start real-time file watchdog")
    watch_p.add_argument("--interval", type=int, default=30, help="Poll interval in seconds")

    args = parser.parse_args()

    if args.command == "scan":
        _cmd_scan(args)
    elif args.command == "fix":
        _cmd_fix(args)
    elif args.command == "report":
        _cmd_report(args)
    elif args.command == "watch":
        _cmd_watch(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
