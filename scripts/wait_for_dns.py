#!/usr/bin/env python3
"""Wait for DNS records to propagate. Polls every 60s until all 5 checks pass.

Wraps scripts/verify_dns.py. Run this AFTER pasting the 5 records into
Cloudflare — it'll wait quietly and ding you when propagation finishes.

Default timeout: 60 minutes (Cloudflare usually propagates in 1-5 min, but
DKIM via Google Workspace can take 24-72h to fully verify everywhere).

Usage:
    python3 scripts/wait_for_dns.py
    python3 scripts/wait_for_dns.py --domain hello.wheellsverse.com --timeout 3600
    python3 scripts/wait_for_dns.py --notify    # plays a sound + macOS notification when done

Exits 0 on full pass, 1 on timeout, 2 on missing `dig`.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Reuse the per-record check functions from verify_dns.py
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_dns import (
    check_a_or_cname, check_mx, check_spf, check_dkim, check_dmarc,
    DEFAULT_DOMAIN, DEFAULT_DKIM_SELECTORS,
)


CHECKS_ORDERED = [
    ("A/CNAME",  check_a_or_cname),
    ("MX",       check_mx),
    ("SPF",      check_spf),
    ("DMARC",    check_dmarc),
]


def _macos_notify(title: str, message: str) -> None:
    """Best-effort macOS notification + system sound. No-op on other OS."""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification "{message}" with title "{title}" sound name "Glass"'],
            check=False, timeout=3,
        )
    except Exception:
        pass


def _short_status(domain: str, selectors: list[str]) -> tuple[int, int, list[str]]:
    """Return (passed, total, failing_labels)."""
    results = []
    for label, fn in CHECKS_ORDERED:
        ok, _ = fn(domain)
        results.append((label, ok))
    ok, _ = check_dkim(domain, selectors)
    results.append(("DKIM", ok))

    passed = sum(1 for _, ok in results if ok)
    failing = [label for label, ok in results if not ok]
    return passed, len(results), failing


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--domain", default=DEFAULT_DOMAIN)
    p.add_argument("--selectors", default=",".join(DEFAULT_DKIM_SELECTORS))
    p.add_argument("--timeout", type=int, default=3600,
                   help="Max seconds to wait (default 3600 = 60 min)")
    p.add_argument("--interval", type=int, default=60,
                   help="Seconds between checks (default 60)")
    p.add_argument("--notify", action="store_true",
                   help="Play sound + macOS notification when done")
    p.add_argument("--require", default="A/CNAME,MX,SPF,DMARC,DKIM",
                   help="Comma-separated subset of checks to require. "
                        "Default: all 5. Lower to e.g. 'A/CNAME,SPF,DMARC' to skip DKIM.")
    args = p.parse_args()

    if not shutil.which("dig"):
        print("ERROR: `dig` command not found. Install: brew install bind", file=sys.stderr)
        return 2

    domain = args.domain
    selectors = [s.strip() for s in args.selectors.split(",") if s.strip()]
    required = {s.strip() for s in args.require.split(",") if s.strip()}

    print(f"\n  Polling DNS for {domain}")
    print(f"  Required: {', '.join(sorted(required))}")
    print(f"  Timeout: {args.timeout}s | Interval: {args.interval}s")
    print("  " + "─" * 60)
    print("  (Ctrl+C to cancel. Each '.' = one check that hasn't passed yet.)\n")

    started = time.time()
    last_passed = -1
    attempt = 0

    while True:
        attempt += 1
        elapsed = int(time.time() - started)
        passed, total, failing = _short_status(domain, selectors)

        # Check only the required subset
        still_failing = [f for f in failing if f in required]

        # Print status line — full re-print only when something changes
        if passed != last_passed:
            print(f"\n  [{elapsed:>4}s · attempt {attempt}] {passed}/{total} checks pass. "
                  f"Still failing: {', '.join(still_failing) if still_failing else '(none)'}",
                  flush=True)
            last_passed = passed
        else:
            print(".", end="", flush=True)

        if not still_failing:
            print(f"\n\n  ✓ ALL REQUIRED CHECKS PASSING ({passed}/{total}) after {elapsed}s.")
            print(f"  hello.wheellsverse.com is propagated. Safe to send.\n")
            if args.notify:
                _macos_notify("SiteBoost DNS", "All checks passing — ready to send")
            return 0

        if elapsed >= args.timeout:
            print(f"\n\n  ✗ TIMEOUT after {args.timeout}s.")
            print(f"  Still failing: {', '.join(still_failing)}")
            print(f"  Open data/launches/siteboost/DNS-CHEATSHEET.md for fixes.\n")
            if args.notify:
                _macos_notify("SiteBoost DNS", f"Timeout — still failing: {', '.join(still_failing)}")
            return 1

        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n\n  Canceled.\n")
        sys.exit(130)
