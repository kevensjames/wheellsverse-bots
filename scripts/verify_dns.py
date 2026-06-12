#!/usr/bin/env python3
"""Verify SPF + DKIM + DMARC + MX for hello.wheellsverse.com.

Uses `dig` (stdlib subprocess) — no external Python deps. Run BEFORE sending
your first cold email. If any check fails, the email will land in spam.

Usage:
    python scripts/verify_dns.py                              # default: hello.wheellsverse.com
    python scripts/verify_dns.py --domain outbound.foo.com    # other subdomain
    python scripts/verify_dns.py --selector google,instantly  # additional DKIM selectors

Exits 0 on full pass, 1 on any failure. Suitable for CI / pre-send hook.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from typing import Optional

DEFAULT_DOMAIN = "hello.wheellsverse.com"
DEFAULT_DKIM_SELECTORS = ["google", "instantly", "default"]


def _dig(record_type: str, host: str) -> list[str]:
    """Return TXT/CNAME/MX values, stripped of quotes."""
    try:
        r = subprocess.run(
            ["dig", "+short", record_type, host],
            capture_output=True, text=True, timeout=8,
        )
        lines = [ln.strip().strip('"') for ln in r.stdout.splitlines() if ln.strip()]
        return lines
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


# ── Per-record checks ───────────────────────────────────────────────────────

def check_mx(domain: str) -> tuple[bool, str]:
    records = _dig("MX", domain)
    if not records:
        return False, "no MX records found"
    return True, f"{len(records)} MX record(s): " + ", ".join(records[:3])


def check_spf(domain: str) -> tuple[bool, str]:
    records = _dig("TXT", domain)
    spf_records = [r for r in records if r.lower().startswith("v=spf1")]
    if not spf_records:
        return False, "no SPF (v=spf1) record found"
    if len(spf_records) > 1:
        return False, f"MULTIPLE SPF records ({len(spf_records)}) — invalid, mail will fail"
    spf = spf_records[0]
    if "include:_spf.google.com" not in spf and "include:google" not in spf:
        return False, f"SPF doesn't include Google Workspace: {spf[:80]}..."
    if not (spf.rstrip().endswith("-all") or spf.rstrip().endswith("~all")):
        return False, f"SPF doesn't end with -all or ~all (open relay risk): {spf[:80]}..."
    return True, f"SPF ok: {spf[:120]}"


def check_dkim(domain: str, selectors: list[str]) -> tuple[bool, str]:
    """Check at least one DKIM selector resolves to a v=DKIM1 record."""
    found = []
    for sel in selectors:
        host = f"{sel}._domainkey.{domain}"
        records = _dig("TXT", host)
        # Some providers return DKIM via CNAME — also check CNAME
        if not records:
            cname = _dig("CNAME", host)
            if cname:
                records = cname
        if any("v=DKIM1" in r or "k=rsa" in r or "domainkey" in r.lower() for r in records):
            found.append(sel)
    if not found:
        return False, f"no DKIM record found for any of: {selectors}"
    return True, f"DKIM ok for selector(s): {', '.join(found)}"


def check_dmarc(domain: str) -> tuple[bool, str]:
    records = _dig("TXT", f"_dmarc.{domain}")
    dmarc = [r for r in records if r.lower().startswith("v=dmarc1")]
    if not dmarc:
        return False, "no DMARC record found at _dmarc." + domain
    rec = dmarc[0]
    # Policy must be at least p=none (monitoring) — anything missing = bad config
    if "p=none" not in rec and "p=quarantine" not in rec and "p=reject" not in rec:
        return False, f"DMARC has no policy directive: {rec[:120]}"
    if "rua=" not in rec:
        return True, f"DMARC ok but no reporting address (rua=) — you'll miss feedback: {rec[:120]}"
    return True, f"DMARC ok: {rec[:120]}"


def check_a_or_cname(domain: str) -> tuple[bool, str]:
    """Verify the subdomain itself resolves — needed for MTA-STS / preview hosting."""
    a = _dig("A", domain) or _dig("AAAA", domain)
    cname = _dig("CNAME", domain)
    if not (a or cname):
        return False, f"{domain} doesn't resolve (no A/AAAA/CNAME)"
    return True, "A/CNAME ok: " + (cname[0] if cname else a[0])


# ── Orchestrator ────────────────────────────────────────────────────────────

CHECKS = [
    ("A/CNAME resolves",  check_a_or_cname),
    ("MX (receiving)",    check_mx),
    ("SPF",               check_spf),
    ("DMARC",             check_dmarc),
]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--domain", default=DEFAULT_DOMAIN)
    p.add_argument("--selectors", default=",".join(DEFAULT_DKIM_SELECTORS),
                   help="Comma-separated DKIM selectors to test")
    args = p.parse_args()

    if not shutil.which("dig"):
        print("ERROR: `dig` command not found. Install with: brew install bind", file=sys.stderr)
        return 2

    domain = args.domain
    selectors = [s.strip() for s in args.selectors.split(",") if s.strip()]

    print(f"\n  DNS verification for: {domain}")
    print("  " + "─" * 60)

    failures = 0
    for label, fn in CHECKS:
        ok, msg = fn(domain)
        icon = "✓" if ok else "✗"
        print(f"  {icon} {label:20s}  {msg}")
        if not ok:
            failures += 1

    ok, msg = check_dkim(domain, selectors)
    icon = "✓" if ok else "✗"
    print(f"  {icon} {'DKIM':20s}  {msg}")
    if not ok:
        failures += 1

    print()
    if failures == 0:
        print("  ✓ ALL CHECKS PASSED — safe to send.\n")
        return 0
    print(f"  ✗ {failures} check(s) failed.")
    print(f"  Open data/launches/siteboost/DNS-CHEATSHEET.md for fix instructions.\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
