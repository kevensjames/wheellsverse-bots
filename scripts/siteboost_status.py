#!/usr/bin/env python3
"""SiteBoost launch-readiness dashboard.

Single command that shows what's done, what's pending, and what's blocking.
Run this whenever you want to know where things stand without digging through
logs/files. No external deps — just stdlib + dig.

Usage:
    python3 scripts/siteboost_status.py
    python3 scripts/siteboost_status.py --json   # machine-readable

Exit codes:
    0 = ready to send (all required checks pass)
    1 = some required checks failing — see output
    2 = environment problem (e.g. missing `dig`)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _env_value(key: str) -> str:
    """Read an env var from .env (in addition to os.environ)."""
    val = os.getenv(key, "").strip()
    if val:
        return val
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f"{key}=") and "=" in line:
                return line.split("=", 1)[1].strip()
    return ""


def _file_exists(rel: str) -> bool:
    return (ROOT / rel).exists()


def _check_env() -> dict:
    """Required + optional environment variables."""
    required = {
        "GOOGLE_PLACES_API_KEY": "Places API for prospect scanning",
        "HUNTER_API_KEY": "Hunter.io for email enrichment",
        "SITEBOOST_OUTBOUND_DOMAIN": "Outbound sending domain (e.g. hello.wheellsverse.com)",
        "SITEBOOST_SMTP_USER": "Outbound SMTP username (or use Instantly)",
        "SITEBOOST_PHYSICAL_ADDRESS": "CAN-SPAM physical address",
    }
    optional = {
        "STRIPE_API_KEY": "For live Stripe products setup",
        "STRIPE_WEBHOOK_SECRET": "For webhook signature verification",
        "ANTHROPIC_API_KEY": "For live LLM-personalized site copy",
        "INSTANTLY_API_KEY": "For programmatic send (alt: CSV upload)",
        "INSTANTLY_CAMPAIGN_ID": "Instantly campaign to push leads into",
        "KDP_AUTHOR_URL": "Used by /go/amazon redirect",
    }
    return {
        "required": {k: bool(_env_value(k)) for k in required},
        "required_labels": required,
        "optional": {k: bool(_env_value(k)) for k in optional},
        "optional_labels": optional,
    }


def _check_dns(domain: str) -> dict:
    """Check the 5 critical DNS records via dig."""
    if not shutil.which("dig"):
        return {"available": False, "error": "dig not installed"}
    try:
        from scripts.verify_dns import (
            check_a_or_cname, check_mx, check_spf, check_dmarc, check_dkim,
            DEFAULT_DKIM_SELECTORS,
        )
    except ImportError:
        sys.path.insert(0, str(ROOT / "scripts"))
        from verify_dns import (
            check_a_or_cname, check_mx, check_spf, check_dmarc, check_dkim,
            DEFAULT_DKIM_SELECTORS,
        )

    return {
        "available": True,
        "domain": domain,
        "checks": {
            "A/CNAME": check_a_or_cname(domain)[0],
            "MX":      check_mx(domain)[0],
            "SPF":     check_spf(domain)[0],
            "DMARC":   check_dmarc(domain)[0],
            "DKIM":    check_dkim(domain, DEFAULT_DKIM_SELECTORS)[0],
        },
    }


def _check_files() -> dict:
    """Verify all required artifacts exist on disk."""
    artifacts = {
        "Skill manifest installed": Path.home() / ".claude/skills/market-local-prospect/SKILL.md",
        "Site templates (3)":       ROOT / "local_prospect/templates/site_service.html",
        "Intake form":              ROOT / "local_prospect/intake.html",
        "Landing page":             ROOT / "local_prospect/site/index.html",
        "Stripe setup script":      ROOT / "scripts/siteboost_stripe_setup.py",
        "Onboarding module":        ROOT / "core/siteboost_onboarding.py",
        "DNS cheatsheet":           ROOT / "data/launches/siteboost/DNS-CHEATSHEET.md",
        "Sales playbook":           ROOT / "data/launches/siteboost/SALES-PLAYBOOK.md",
        "Pytest suite":             ROOT / "tests/test_siteboost_pipeline.py",
    }
    return {label: p.exists() for label, p in artifacts.items()}


def _check_calendly_url() -> dict:
    """Detect whether the placeholder Calendly URL has been replaced."""
    placeholder = "calendly.com/jay-siteboost/15"
    files_with_placeholder = []
    for path in (ROOT / "data/launches/siteboost").rglob("*.md"):
        try:
            if placeholder in path.read_text(encoding="utf-8"):
                files_with_placeholder.append(str(path.relative_to(ROOT)))
        except Exception:
            pass
    for path in (ROOT / "core").rglob("*.py"):
        try:
            if placeholder in path.read_text(encoding="utf-8"):
                files_with_placeholder.append(str(path.relative_to(ROOT)))
        except Exception:
            pass
    return {
        "still_placeholder": bool(files_with_placeholder),
        "files": files_with_placeholder,
    }


def _check_dry_run_outputs() -> dict:
    """Has the user run the dry-run pipeline at least once?"""
    runs_dir = ROOT / "data/launches/siteboost/runs"
    if not runs_dir.exists():
        return {"count": 0, "latest": None}
    runs = sorted(runs_dir.glob("*"), reverse=True)
    return {
        "count": len(runs),
        "latest": runs[0].name if runs else None,
    }


def _check_state_stats() -> dict:
    """Persistent dedupe state — what's been sent/scanned?"""
    try:
        from core import siteboost_state
        return siteboost_state.stats()
    except Exception:
        return {"places_scanned": 0, "emails_sent": 0,
                "locations_scanned": 0, "blocked_emails": 0, "blocked_domains": 0}


# ── Rendering ───────────────────────────────────────────────────────────────

def _render_human(snapshot: dict) -> None:
    print("\n" + "═" * 70)
    print("  SiteBoost — Launch Readiness Dashboard")
    print("═" * 70)
    print(f"  Generated: {snapshot['ts']}")
    print(f"  Domain:    {snapshot['domain'] or '(not set)'}")
    print()

    # Section 1: Files
    print("  📁 ARTIFACTS")
    print("  " + "─" * 60)
    files = snapshot["files"]
    for label, ok in files.items():
        icon = "✓" if ok else "✗"
        print(f"  {icon} {label}")
    print()

    # Section 2: Environment
    print("  🔐 ENVIRONMENT (.env)")
    print("  " + "─" * 60)
    env = snapshot["env"]
    print("  Required:")
    for k, ok in env["required"].items():
        icon = "✓" if ok else "✗"
        print(f"    {icon} {k:30s}  — {env['required_labels'][k]}")
    print("  Optional:")
    for k, ok in env["optional"].items():
        icon = "✓" if ok else "·"
        print(f"    {icon} {k:30s}  — {env['optional_labels'][k]}")
    print()

    # Section 3: DNS
    print("  🌐 DNS")
    print("  " + "─" * 60)
    dns = snapshot["dns"]
    if not dns.get("available"):
        print(f"  ⚠ Skipped: {dns.get('error', 'unknown')}")
    else:
        for label, ok in dns["checks"].items():
            icon = "✓" if ok else "✗"
            print(f"  {icon} {label}")
    print()

    # Section 4: Calendly
    print("  📅 CALENDLY")
    print("  " + "─" * 60)
    cal = snapshot["calendly"]
    if cal["still_placeholder"]:
        print(f"  ✗ Placeholder URL still in {len(cal['files'])} file(s)")
        for f in cal["files"][:3]:
            print(f"      → {f}")
    else:
        print("  ✓ Calendly URL has been customized")
    print()

    # Section 5: Pipeline activity
    print("  📊 PIPELINE ACTIVITY")
    print("  " + "─" * 60)
    runs = snapshot["runs"]
    state = snapshot["state"]
    print(f"  Dry-run campaigns executed: {runs['count']}")
    if runs["latest"]:
        print(f"  Latest: {runs['latest']}")
    print(f"  Places scanned (persistent): {state['places_scanned']}")
    print(f"  Emails sent (persistent):    {state['emails_sent']}")
    print(f"  Blocklist size: {state['blocked_emails']} emails, {state['blocked_domains']} domains")
    print()

    # Final verdict
    print("  🚦 VERDICT")
    print("  " + "─" * 60)
    blockers = snapshot["blockers"]
    if not blockers:
        print("  ✓ READY TO SEND — all systems go.")
    else:
        print(f"  ⏸  BLOCKED — {len(blockers)} item(s):")
        for b in blockers:
            print(f"    • {b}")
    print()
    print("═" * 70)
    print()


def _compute_blockers(snapshot: dict) -> list[str]:
    """Derive the canonical 'why aren't we sending' list."""
    blockers = []
    env = snapshot["env"]["required"]
    for k, ok in env.items():
        if not ok:
            blockers.append(f"Set {k} in .env")
    dns = snapshot["dns"]
    if dns.get("available"):
        failing = [k for k, ok in dns["checks"].items() if not ok]
        if failing:
            blockers.append(f"DNS records pending: {', '.join(failing)}")
    cal = snapshot["calendly"]
    if cal["still_placeholder"]:
        blockers.append("Replace Calendly placeholder URL")
    files = snapshot["files"]
    missing_files = [label for label, ok in files.items() if not ok]
    if missing_files:
        blockers.append(f"Missing artifacts: {', '.join(missing_files)}")
    return blockers


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true")
    p.add_argument("--domain", default=None)
    args = p.parse_args()

    domain = (args.domain or _env_value("SITEBOOST_OUTBOUND_DOMAIN")
              or "hello.wheellsverse.com")

    snapshot = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "domain": domain,
        "files": _check_files(),
        "env": _check_env(),
        "dns": _check_dns(domain),
        "calendly": _check_calendly_url(),
        "runs": _check_dry_run_outputs(),
        "state": _check_state_stats(),
    }
    snapshot["blockers"] = _compute_blockers(snapshot)

    if args.json:
        print(json.dumps(snapshot, indent=2, default=str))
    else:
        _render_human(snapshot)

    return 0 if not snapshot["blockers"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
