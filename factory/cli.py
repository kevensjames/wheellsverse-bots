"""Manual Factory entry point for dev/testing: `python -m factory tick <slug>`.
Uses a built-in MockRunner in F1 (no network); F2 swaps in the real claude -p
adapter. NOT the production path — the daemon (scheduler.start_worker) is."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from factory import pipeline


class MockRunner:
    def run(self, action):
        return {"ok": True, "cost_usd": 0.0, "output": "",
                "pr_url": "https://example.invalid/pr/mock" if action.verb == "commit_pr" else None}


def tick(slug: str, *, now_iso: str) -> dict:
    return asdict(pipeline.run_cycle(slug, MockRunner(), now_iso=now_iso))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="factory")
    sub = parser.add_subparsers(dest="cmd")
    t = sub.add_parser("tick")
    t.add_argument("slug")
    t.add_argument("--now", default=None, help="ISO-8601 timestamp (default: now, UTC)")
    t.add_argument("--real", action="store_true", help="use the real claude/gh runner + worktree")

    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code) if exc.code is not None else 2
    if args.cmd != "tick":
        parser.print_usage()
        return 2

    now_iso = args.now
    if now_iso is None:
        import time
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if getattr(args, "real", False):
        from factory import cycle, runner as _runner
        res = cycle.run_with_worktree(args.slug, now_iso=now_iso,
                                      make_runner=lambda wt: _runner.ClaudeCliRunner(wt))
        print(json.dumps(asdict(res), indent=2))
        return 0
    print(json.dumps(tick(args.slug, now_iso=now_iso), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
