#!/usr/bin/env python3
"""
Pre-submission readiness check for the NarAI Shopify App Store listing.

Walks through the requirements in NARAI_SHOPIFY_APP_STORE.md (§5 + §6) and
verifies each programmatically. Prints a checklist with PASS / FAIL / WARN
per item plus actionable remediation. Designed to be runnable repeatedly
without side effects.

Usage:
    python3 scripts/check_app_store_readiness.py
    python3 scripts/check_app_store_readiness.py --verbose
    python3 scripts/check_app_store_readiness.py --skip-network  # for offline runs

Exit code: 0 if all FAIL items resolved, 1 otherwise.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

REPO = Path(__file__).resolve().parent.parent
CHECKS: list[tuple[str, Callable[[argparse.Namespace], tuple[str, str]]]] = []

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"


def check(name: str):
    """Decorator: register a check function. Function returns (status, detail)."""
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


def _fetch(url: str, timeout: int = 5) -> tuple[int | None, str]:
    """Returns (status_code, error_string). status_code is None if request failed."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "narai-readiness-check"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, ""
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return None, str(e)


# ─── Required files ──────────────────────────────────────────────────────────

@check("App Store assets — icon (1200×1200 PNG)")
def check_icon(args):
    p = REPO / "app_store_assets" / "icon-1200.png"
    return (PASS, f"{p.relative_to(REPO)}") if p.exists() else (FAIL, f"missing: {p.relative_to(REPO)} — run scripts/generate_app_store_assets.py")


@check("App Store assets — feature banner (1600×900 PNG)")
def check_banner(args):
    p = REPO / "app_store_assets" / "banner-1600x900.png"
    return (PASS, f"{p.relative_to(REPO)}") if p.exists() else (FAIL, f"missing: {p.relative_to(REPO)} — run scripts/generate_app_store_assets.py")


@check("App Store assets — screenshots (≥3 × 1600×900 PNG)")
def check_screenshots(args):
    d = REPO / "app_store_assets"
    if not d.exists():
        return FAIL, f"directory missing: {d.relative_to(REPO)}"
    shots = sorted(d.glob("screenshot-*.png"))
    if len(shots) >= 3:
        return PASS, f"{len(shots)} screenshots in {d.relative_to(REPO)}"
    return FAIL, f"have {len(shots)} screenshots, need ≥3 — capture admin/install/storefront views at 1600×900"


@check("shopify.app.toml exists at repo root")
def check_app_toml(args):
    p = REPO / "shopify.app.toml"
    return (PASS, "found") if p.exists() else (FAIL, "missing — run `shopify app config link`")


@check("supabase_shopify_multitenant.sql exists")
def check_sql(args):
    p = REPO / "supabase_shopify_multitenant.sql"
    return (PASS, str(p.relative_to(REPO))) if p.exists() else (FAIL, "missing — Phase 1 schema not present")


# ─── shopify.app.toml content ────────────────────────────────────────────────

def _read_toml() -> str:
    p = REPO / "shopify.app.toml"
    return p.read_text() if p.exists() else ""


@check("shopify.app.toml — app/uninstalled webhook subscription")
def check_uninstall_webhook(args):
    content = _read_toml()
    return (PASS, "subscribed") if "app/uninstalled" in content else (FAIL, "missing — required for App Store approval")


@check("shopify.app.toml — GDPR compliance webhooks (3 required)")
def check_gdpr_webhooks(args):
    content = _read_toml()
    needed = ["customers/data_request", "customers/redact", "shop/redact"]
    missing = [t for t in needed if t not in content]
    return (PASS, "all 3 subscribed") if not missing else (FAIL, f"missing: {', '.join(missing)}")


@check("shopify.app.toml — application_url is https")
def check_app_url(args):
    content = _read_toml()
    m = re.search(r'application_url\s*=\s*"([^"]+)"', content)
    if not m:
        return FAIL, "no application_url declared"
    url = m.group(1)
    if not url.startswith("https://"):
        return FAIL, f"must be https, got: {url}"
    return PASS, url


# ─── Required URLs ───────────────────────────────────────────────────────────

@check("Privacy policy URL responds 200")
def check_privacy(args):
    if args.skip_network:
        return SKIP, "--skip-network"
    code, err = _fetch("https://wheellsverse.com/privacy")
    return (PASS, f"HTTP {code}") if code == 200 else (FAIL, f"HTTP {code or err} at https://wheellsverse.com/privacy")


@check("Terms of service URL responds 200")
def check_terms(args):
    if args.skip_network:
        return SKIP, "--skip-network"
    code, err = _fetch("https://wheellsverse.com/terms")
    return (PASS, f"HTTP {code}") if code == 200 else (FAIL, f"HTTP {code or err} at https://wheellsverse.com/terms")


@check("App URL responds (if deployed)")
def check_app_live(args):
    if args.skip_network:
        return SKIP, "--skip-network"
    content = _read_toml()
    m = re.search(r'application_url\s*=\s*"([^"]+)"', content)
    if not m:
        return SKIP, "no application_url"
    url = m.group(1)
    code, err = _fetch(url, timeout=8)
    if code is None:
        return WARN, f"unreachable: {err[:60]} — OK if not yet deployed"
    if 200 <= code < 400:
        return PASS, f"{url} → HTTP {code}"
    return WARN, f"{url} → HTTP {code}"


# ─── Documented env vars ──────────────────────────────────────────────────────

@check(".env.example documents Shopify keys + secrets")
def check_env_example(args):
    p = REPO / ".env.example"
    if not p.exists():
        return FAIL, ".env.example missing"
    needed = [
        "SHOPIFY_API_KEY", "SHOPIFY_API_SECRET",
        "MERCHANT_TOKEN_KEY", "SHOPIFY_OAUTH_STATE_KEY",
        "STRIPE_PRICE_MERCHANT_STARTER", "STRIPE_PRICE_MERCHANT_PRO",
        "STRIPE_PRICE_MERCHANT_ELITE", "STRIPE_MERCHANT_WEBHOOK_SECRET",
    ]
    content = p.read_text()
    missing = [k for k in needed if k not in content]
    return (PASS, "all 8 declared") if not missing else (WARN, f"undocumented: {', '.join(missing)}")


# ─── Code surface presence ────────────────────────────────────────────────────

@check("OAuth route file: narai/api/routes/shopify_oauth.py")
def check_oauth_file(args):
    p = REPO / "narai/api/routes/shopify_oauth.py"
    return (PASS, "found") if p.exists() else (FAIL, "missing — Phase 2")


@check("Webhook route file: narai/api/routes/shopify_webhooks.py")
def check_webhook_file(args):
    p = REPO / "narai/api/routes/shopify_webhooks.py"
    return (PASS, "found") if p.exists() else (FAIL, "missing — Phase 3")


@check("Multi-tenant module: narai/core/shopify_mt/ (db, client, products, billing, webhooks, crypto)")
def check_mt_module(args):
    d = REPO / "narai/core/shopify_mt"
    if not d.exists():
        return FAIL, "directory missing — Phase 4/5"
    needed = ["db.py", "client.py", "products.py", "billing.py", "webhooks.py", "crypto.py"]
    missing = [f for f in needed if not (d / f).exists()]
    return (PASS, "all 6 present") if not missing else (FAIL, f"missing: {', '.join(missing)}")


@check("Admin dashboard: frontend/admin/shopify.html")
def check_admin_ui(args):
    p = REPO / "frontend/admin/shopify.html"
    return (PASS, "found") if p.exists() else (FAIL, "missing — Phase 6")


# ─── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--skip-network", action="store_true",
                    help="Skip checks that need internet (privacy URL, terms URL, app URL).")
    args = ap.parse_args()

    pad = max(len(name) for name, _ in CHECKS)
    counts = {PASS: 0, FAIL: 0, WARN: 0, SKIP: 0}

    print(f"\n  NarAI Shopify App Store — readiness check ({len(CHECKS)} items)\n")
    print(f"  {'Status':<6} {'Check':<{pad}}  Detail")
    print(f"  {'-'*6} {'-'*pad}  {'-'*40}")

    for name, fn in CHECKS:
        try:
            status, detail = fn(args)
        except Exception as e:
            status, detail = FAIL, f"check raised {type(e).__name__}: {e}"
        counts[status] += 1
        status_icon = {PASS: "✓ PASS", FAIL: "✗ FAIL", WARN: "⚠ WARN", SKIP: "  SKIP"}[status]
        print(f"  {status_icon:<6} {name:<{pad}}  {detail}")

    print(f"\n  Summary: {counts[PASS]} pass / {counts[FAIL]} fail / {counts[WARN]} warn / {counts[SKIP]} skip")
    if counts[FAIL] == 0:
        print("  ✓ Submission-ready (or only soft warnings remaining).\n")
        return 0
    print(f"  ✗ {counts[FAIL]} blocking item(s) — resolve before submitting.\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
