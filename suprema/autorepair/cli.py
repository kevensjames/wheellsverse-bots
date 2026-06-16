#!/usr/bin/env python3
"""SUPREMA autorepair CLI.

Subcommands:
    scan    — run all scanners, print findings, exit 0
    fix     — scan + apply auto-safe fixers (creates per-project commits)
    status  — print last-run summary
    install — install launchd job for daily auto-run

Examples:
    python -m suprema.autorepair.cli scan
    python -m suprema.autorepair.cli scan --project wheellsverse-bots
    python -m suprema.autorepair.cli fix --dry-run
    python -m suprema.autorepair.cli fix --commit
    python -m suprema.autorepair.cli status
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make this runnable as `python -m suprema.autorepair.cli` regardless of CWD
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from suprema.autorepair import engine, notify, auto_commit


def cmd_scan(args) -> int:
    # When --json output is requested, suppress stdout log handler so the
    # output is consumable by downstream tools / CI / shells.
    if args.json:
        import os
        os.environ["SUPREMA_STDOUT"] = "0"
    findings = engine.run_scan(only_projects=args.project)
    if args.json:
        print(json.dumps([f.as_dict() for f in findings], indent=2))
        return 0

    if not findings:
        print("✓ no findings — workspace clean")
        return 0

    print(f"📋 {len(findings)} finding(s):")
    print()
    by_proj: dict = {}
    for f in findings:
        by_proj.setdefault(f.project, []).append(f)
    for proj, fs in sorted(by_proj.items()):
        print(f"  ▼ {proj}  ({len(fs)} finding{'s' if len(fs) != 1 else ''})")
        for f in fs:
            sev = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(f.severity, "⚪")
            print(f"    {sev} [{f.pattern}]  {f.location}")
            if f.evidence:
                print(f"        ↳ {f.evidence[:160]}")
        print()
    return 0


def cmd_fix(args) -> int:
    summary = engine.run_cycle(
        do_fix=True,
        dry_run=args.dry_run,
        only_projects=args.project,
        llm_triage=getattr(args, "llm_triage", False),
        triage_confidence_threshold=getattr(args, "confidence_threshold", 0.8),
    )

    # Surface triage stats if it ran
    tri = summary.get("llm_triage")
    if tri and tri.get("ran"):
        print(f"🤖 LLM triage: {tri['real_bugs']} real / "
              f"{tri['false_positives']} false-positive / "
              f"{tri['uncertain']} uncertain "
              f"({tri['tokens_used']} tokens)")

    if args.dry_run:
        print(f"(dry-run) would attempt {summary['fixes_attempted']} auto-fix(es)")
    else:
        print(f"applied {summary['fixes_succeeded']}/{summary['fixes_attempted']} "
              f"auto-fix(es)")

    # Optional: auto-commit each successful fix per-project
    if args.commit and not args.dry_run:
        commits_by_proj: dict[str, list[dict]] = {}
        for outcome in summary.get("fix_outcomes", []):
            res = outcome["result"]
            fnd = outcome["finding"]
            if not res.get("success") or not res.get("changed_files"):
                continue
            commits_by_proj.setdefault(fnd["project"], []).append(outcome)

        for proj, outs in commits_by_proj.items():
            all_files = sorted({c for o in outs for c in o["result"]["changed_files"]})
            patterns = sorted({o["finding"]["pattern"] for o in outs})
            detail = "\n".join(f"- {o['finding']['pattern']}: {o['result'].get('message','')}"
                               for o in outs)
            commit = auto_commit.commit_changes(
                engine.project_path(proj),
                all_files,
                ", ".join(patterns),
                detail,
            )
            tag = "✓" if commit.get("success") else "✗"
            print(f"  {tag} {proj}: {commit.get('message','')} {commit.get('commit_sha','')}")

    if args.notify:
        notify.emit(summary)
        print("  📨 notification emitted")

    return 0 if summary["findings_count"] == 0 or summary["fixes_succeeded"] > 0 else 1


def cmd_status(args) -> int:
    last = engine.LAST_RUN
    if not last.exists():
        print("(no prior run on record)")
        return 0
    data = json.loads(last.read_text())
    print(f"last run:     {data['started_at']}")
    print(f"elapsed:      {data['elapsed_s']}s")
    print(f"findings:     {data['findings_count']}")
    print(f"fixed:        {data['fixes_succeeded']}/{data['fixes_attempted']}")
    print(f"dry_run:      {data.get('dry_run', False)}")
    return 0


def cmd_install(args) -> int:
    from suprema.autorepair import installer
    return installer.install()


def cmd_install_hooks(args) -> int:
    from suprema.autorepair import precommit
    return precommit.install_all(only_projects=args.project)


def main() -> int:
    p = argparse.ArgumentParser(prog="suprema-autorepair")
    p.add_argument("--project", action="append", default=None,
                   help="limit to one or more projects (repeatable)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s_scan = sub.add_parser("scan", help="run scanners, print findings")
    s_scan.add_argument("--json", action="store_true", help="JSON output")
    s_scan.set_defaults(func=cmd_scan)

    s_fix = sub.add_parser("fix", help="scan + apply auto-safe fixers")
    s_fix.add_argument("--dry-run", action="store_true", help="don't write files")
    s_fix.add_argument("--commit", action="store_true",
                       help="auto-commit each fix per-project")
    s_fix.add_argument("--notify", action="store_true",
                       help="send summary to Telegram if configured")
    s_fix.add_argument("--llm-triage", action="store_true",
                       help="run Anthropic-API triage on review-tier findings "
                            "(needs ANTHROPIC_API_KEY)")
    s_fix.add_argument("--confidence-threshold", type=float, default=0.8,
                       help="LLM triage confidence threshold for promotion (default: 0.8)")
    s_fix.set_defaults(func=cmd_fix)

    s_hooks = sub.add_parser("install-hooks",
                             help="install pre-commit hook in each project")
    s_hooks.set_defaults(func=cmd_install_hooks)

    s_status = sub.add_parser("status", help="show last-run summary")
    s_status.set_defaults(func=cmd_status)

    s_install = sub.add_parser("install", help="install launchd daily job")
    s_install.set_defaults(func=cmd_install)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
