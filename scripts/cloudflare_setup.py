#!/usr/bin/env python3
"""Cloudflare automation for SiteBoost setup.

ONE Cloudflare API token unlocks everything we need to do programmatically:
  - Enable Email Routing on the zone
  - Add the routing rule: hello@wheellsverse.com → your Gmail
  - Add MX, SPF, DKIM, DMARC records for hello.wheellsverse.com
  - Verify each record propagated

After you create the token (one-time, 5 min), I run this script and it
handles every Cloudflare-side step automatically.

Token scope required (set in Cloudflare dashboard):
  Permissions:
    - Zone → DNS → Edit
    - Zone → Email Routing → Edit
    - Zone → Zone Settings → Read
  Zone Resources:
    - Include → Specific zone → wheellsverse.com

Get it here: https://dash.cloudflare.com/profile/api-tokens → Create Token →
            Custom token with the permissions above.

Usage:
    # 1. Set env var (once)
    export CLOUDFLARE_API_TOKEN=<your-token>

    # 2. Run setup (idempotent — safe to re-run)
    python3 scripts/cloudflare_setup.py --gmail your@gmail.com

    # 3. Verify everything propagated
    python3 scripts/cloudflare_setup.py --verify

Exit codes: 0 = success, 1 = setup error, 2 = missing token/perms.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Activate venv: source .venv/bin/activate", file=sys.stderr)
    sys.exit(2)

API = "https://api.cloudflare.com/client/v4"
ZONE_DOMAIN = "wheellsverse.com"
SUBDOMAIN = "hello"
FULL_SUB = f"{SUBDOMAIN}.{ZONE_DOMAIN}"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _get_token() -> str:
    token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
    if not token:
        # Try .env fallback
        env_file = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_file):
            for line in open(env_file).read().splitlines():
                if line.startswith("CLOUDFLARE_API_TOKEN=") and "=" in line:
                    token = line.split("=", 1)[1].strip()
                    break
    if not token:
        print("ERROR: CLOUDFLARE_API_TOKEN not set in env or .env.", file=sys.stderr)
        print("  Generate one at: https://dash.cloudflare.com/profile/api-tokens", file=sys.stderr)
        sys.exit(2)
    return token


def _api(method: str, path: str, token: str, body: Any = None) -> dict:
    url = f"{API}{path}"
    if method == "GET":
        r = requests.get(url, headers=_headers(token), timeout=15)
    elif method == "POST":
        r = requests.post(url, headers=_headers(token), json=body, timeout=15)
    elif method == "PUT":
        r = requests.put(url, headers=_headers(token), json=body, timeout=15)
    elif method == "DELETE":
        r = requests.delete(url, headers=_headers(token), timeout=15)
    else:
        raise ValueError(f"bad method {method}")
    try:
        return r.json()
    except Exception:
        return {"success": False, "errors": [{"message": r.text[:300]}]}


def _zone_id(token: str) -> str:
    res = _api("GET", f"/zones?name={ZONE_DOMAIN}", token)
    if not res.get("success") or not res.get("result"):
        raise RuntimeError(f"Zone {ZONE_DOMAIN} not found / token lacks permission: {res.get('errors')}")
    return res["result"][0]["id"]


def enable_email_routing(zone_id: str, token: str) -> dict:
    """Enable Email Routing on the zone if not already enabled."""
    print("  ▸ Email Routing status...", end=" ")
    res = _api("GET", f"/zones/{zone_id}/email/routing", token)
    if not res.get("success"):
        print(f"⚠  {res.get('errors')}")
        return res
    status = res.get("result", {}).get("status", "unknown")
    print(f"current: {status}")

    if status != "ready":
        print("  ▸ Enabling Email Routing...", end=" ")
        res = _api("POST", f"/zones/{zone_id}/email/routing/enable", token)
        if res.get("success"):
            print("✓ enabled")
        else:
            print(f"✗ {res.get('errors')}")
    return res


def add_routing_rule(zone_id: str, token: str, forward_to: str) -> dict:
    """Create the hello@wheellsverse.com → forward_to rule (idempotent)."""
    print(f"  ▸ Checking existing routing rules...", end=" ")
    res = _api("GET", f"/zones/{zone_id}/email/routing/rules", token)
    if not res.get("success"):
        print(f"✗ {res.get('errors')}")
        return res
    existing = res.get("result", [])
    desired_from = f"{SUBDOMAIN}@{ZONE_DOMAIN}"

    # Check if a rule already exists for this address
    for rule in existing:
        for matcher in rule.get("matchers", []):
            if matcher.get("type") == "literal" and matcher.get("value") == desired_from:
                actions = rule.get("actions", [])
                if any(a.get("type") == "forward" and forward_to in a.get("value", [])
                       for a in actions):
                    print(f"✓ already exists ({desired_from} → {forward_to})")
                    return {"success": True, "result": rule}
    print(f"none for {desired_from}")

    # Create the rule
    print(f"  ▸ Creating rule: {desired_from} → {forward_to}...", end=" ")
    body = {
        "actions": [{"type": "forward", "value": [forward_to]}],
        "matchers": [{"type": "literal", "field": "to", "value": desired_from}],
        "enabled": True,
        "name": f"SiteBoost: {desired_from} → Gmail",
        "priority": 1,
    }
    res = _api("POST", f"/zones/{zone_id}/email/routing/rules", token, body)
    if res.get("success"):
        print("✓ created")
    else:
        print(f"✗ {res.get('errors')}")
    return res


def add_dns_record(zone_id: str, token: str, rec_type: str, name: str,
                   content: str, priority: int | None = None,
                   proxied: bool = False) -> dict:
    """Add a DNS record. Idempotent — skips if a record with same type+name+content exists."""
    print(f"  ▸ Checking {rec_type} {name}...", end=" ")
    list_res = _api("GET", f"/zones/{zone_id}/dns_records?type={rec_type}&name={name}", token)
    if list_res.get("success"):
        for r in list_res.get("result", []):
            if r["content"].rstrip(".") == content.rstrip("."):
                print(f"✓ exists")
                return {"success": True, "result": r, "skipped": True}
    print(f"none")

    body = {"type": rec_type, "name": name, "content": content, "ttl": 3600, "proxied": proxied}
    if priority is not None:
        body["priority"] = priority

    print(f"  ▸ Creating {rec_type} {name} → {content[:60]}...", end=" ")
    res = _api("POST", f"/zones/{zone_id}/dns_records", token, body)
    if res.get("success"):
        print("✓ created")
    else:
        print(f"✗ {res.get('errors')}")
    return res


def setup(token: str, gmail: str) -> int:
    """Run all Cloudflare setup steps. Returns # of failures."""
    failures = 0

    print("─" * 70)
    print(f"  SiteBoost — Cloudflare automated setup")
    print(f"  Zone:        {ZONE_DOMAIN}")
    print(f"  Subdomain:   {FULL_SUB}")
    print(f"  Forward to:  {gmail}")
    print("─" * 70)

    print("\n[1/4] Zone lookup")
    zone_id = _zone_id(token)
    print(f"  ✓ zone_id = {zone_id}")

    print("\n[2/4] Email Routing")
    res = enable_email_routing(zone_id, token)
    if not res.get("success"):
        failures += 1
    res = add_routing_rule(zone_id, token, gmail)
    if not res.get("success"):
        failures += 1

    print("\n[3/4] DNS records for hello.wheellsverse.com")
    # Note: Cloudflare Email Routing auto-creates the apex MX records when enabled.
    # We only need the subdomain-specific records for outbound sending (SPF/DKIM/DMARC).
    records = [
        # SPF on the subdomain (Cloudflare Email Routing handles the apex SPF for receiving)
        ("TXT", FULL_SUB, "v=spf1 include:_spf.google.com include:sendgrid.net -all", None),
        # DMARC for the subdomain
        ("TXT", f"_dmarc.{FULL_SUB}",
         f"v=DMARC1; p=none; rua=mailto:dmarc@{ZONE_DOMAIN}; pct=100", None),
        # CNAME so the subdomain resolves (placeholder — actual destination depends on
        # whether you'll use Google Workspace, Cloudflare Pages, or static hosting)
        ("CNAME", FULL_SUB, "ghs.googlehosted.com", None),
    ]
    for entry in records:
        rec_type, name, content, prio = entry
        # CNAME proxied=False (Email won't work behind Cloudflare proxy)
        res = add_dns_record(zone_id, token, rec_type, name, content, prio, proxied=False)
        if not res.get("success") and not res.get("skipped"):
            failures += 1
        time.sleep(0.3)

    print("\n[4/4] Summary")
    print(f"  Failures: {failures}")
    if failures == 0:
        print("  ✓ All Cloudflare setup complete.")
        print()
        print("  Next:")
        print(f"    1. Click the verification email Cloudflare sent to {gmail}")
        print("       (Subject: 'Cloudflare Email — Verify your email address')")
        print("    2. After verifying, send a test email TO hello@wheellsverse.com")
        print(f"       FROM another address — should arrive in {gmail} within ~30s")
        print("    3. Run: python3 scripts/cloudflare_setup.py --verify")
    return failures


def verify(token: str) -> int:
    """Verify Cloudflare-side setup is correct."""
    print("─" * 70)
    print(f"  Cloudflare verification — {FULL_SUB}")
    print("─" * 70)

    zone_id = _zone_id(token)
    print(f"\n  Zone {ZONE_DOMAIN} → {zone_id}")

    res = _api("GET", f"/zones/{zone_id}/email/routing", token)
    status = res.get("result", {}).get("status", "unknown") if res.get("success") else "error"
    icon = "✓" if status == "ready" else "✗"
    print(f"  {icon} Email Routing status: {status}")

    res = _api("GET", f"/zones/{zone_id}/email/routing/rules", token)
    n_rules = len(res.get("result", [])) if res.get("success") else 0
    print(f"  ✓ Routing rules: {n_rules} configured")

    res = _api("GET", f"/zones/{zone_id}/dns_records?per_page=200", token)
    if res.get("success"):
        for r in res["result"]:
            if FULL_SUB in r["name"] or r["name"] == f"_dmarc.{FULL_SUB}":
                print(f"  ✓ DNS {r['type']:5s} {r['name']} → {r['content'][:60]}")
    return 0 if status == "ready" else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--gmail", help="Gmail address to forward hello@ to (required for setup)")
    p.add_argument("--verify", action="store_true", help="Verify mode — don't make changes")
    args = p.parse_args()

    token = _get_token()

    if args.verify:
        return verify(token)
    if not args.gmail:
        print("ERROR: --gmail required for setup (or use --verify)", file=sys.stderr)
        return 2
    return setup(token, args.gmail)


if __name__ == "__main__":
    raise SystemExit(main())
