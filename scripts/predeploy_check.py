#!/usr/bin/env python3
"""Fail-closed pre-deploy gate.

Run against the ENVIRONMENT you are about to deploy with (its env vars loaded).
Exits non-zero if any gate fails. It reads configuration only — it never deploys,
migrates, moves money, or mutates anything.

    set -a; source backend/.env.production; set +a      # load the target env
    python scripts/predeploy_check.py

Every check below is a reason NOT to ship. When in doubt it fails closed.
"""
from __future__ import annotations

import os
import shutil
import sys

FAILS: list[str] = []
WARNS: list[str] = []


def fail(msg: str) -> None:
    FAILS.append(msg)
    print(f"[FAIL] {msg}")


def warn(msg: str) -> None:
    WARNS.append(msg)
    print(f"[WARN] {msg}")


def ok(msg: str) -> None:
    print(f"[ok]   {msg}")


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in ("1", "true", "yes", "on")


def check_admin_token() -> None:
    tok = os.environ.get("ADMIN_TOKEN") or os.environ.get("JWT_SECRET_KEY") or ""
    weak = {"", "change_me_to_a_long_random_string"}
    if tok in weak or len(tok) < 32:
        fail("ADMIN_TOKEN missing/weak/default (<32 chars) — the whole /admin surface rests on it")
    else:
        ok("admin token present and strong")


def check_debug() -> None:
    if _truthy(os.environ.get("DEBUG")):
        fail("DEBUG is enabled — must be off in production")
    else:
        ok("DEBUG off")


def check_database_url() -> None:
    if not os.environ.get("DATABASE_URL"):
        fail("DATABASE_URL not set")
    else:
        ok("DATABASE_URL set")


def check_required_deps() -> None:
    import importlib.util as u
    for mod, pkg in [("yaml", "PyYAML"), ("alembic", "alembic"),
                     ("fastapi", "fastapi"), ("pydantic", "pydantic")]:
        if u.find_spec(mod) is None:
            fail(f"required dependency not importable: {pkg} (import '{mod}')")
        else:
            ok(f"dependency present: {pkg}")


def check_money_mode() -> None:
    """The single most dangerous ambiguity: is this environment able to move REAL
    money? Fail closed unless the mode is EXPLICIT."""
    stripe = os.environ.get("STRIPE_SECRET_KEY", "")
    if stripe:
        if stripe.startswith("sk_live_"):
            warn("STRIPE_SECRET_KEY is a LIVE key — confirm real charges are intended")
        elif stripe.startswith("sk_test_"):
            ok("Stripe in TEST mode")
        else:
            fail("STRIPE_SECRET_KEY set but mode is ambiguous (not sk_test_/sk_live_)")
    else:
        ok("Stripe not configured (no charges)")

    dwolla_prod = _truthy(os.environ.get("DWOLLA_ALLOW_PRODUCTION"))
    dwolla_key = os.environ.get("DWOLLA_KEY", "")
    if dwolla_prod:
        warn("DWOLLA_ALLOW_PRODUCTION is TRUE — real ACH is possible; confirm intent")
    elif dwolla_key:
        ok("Dwolla configured but production latch OFF (sandbox)")
    else:
        ok("Dwolla not configured")

    # webhook secrets required if the paying feature is on
    if stripe and not os.environ.get("STRIPE_WEBHOOK_SECRET"):
        fail("Stripe configured but STRIPE_WEBHOOK_SECRET missing — webhook forgery risk")


def check_destructive_scopes_off_by_default() -> None:
    """No destructive scope should be pre-enabled in a fresh prod env unless the
    operator deliberately set it. A wildcard being on is a yellow flag."""
    dangerous = [k for k in os.environ
                 if k.startswith("KAI_SCOPE_") and _truthy(os.environ[k])
                 and k in ("KAI_SCOPE_SOL", "KAI_SCOPE_DWOLLA", "KAI_SCOPE_BROWSER",
                           "KAI_SCOPE_PLANNING")]
    for k in dangerous:
        warn(f"{k}=1 (module wildcard on) — grants non-destructive module ops; destructive "
             f"subscopes still require exact names (PR #43)")
    if not dangerous:
        ok("no destructive-adjacent module wildcards pre-enabled")


def check_alert_destination() -> None:
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
        ok("operator alert destination configured (Telegram)")
    else:
        warn("no alert destination (TELEGRAM_*) — provider/deploy failures won't page anyone")


def check_disk() -> None:
    try:
        free_gb = shutil.disk_usage("/").free / 1e9
        if free_gb < 2:
            fail(f"low disk: {free_gb:.1f} GB free")
        else:
            ok(f"disk ok ({free_gb:.0f} GB free)")
    except Exception as e:  # pragma: no cover
        warn(f"could not check disk: {e}")


def main() -> int:
    print("== pre-deploy gate (fail-closed) ==\n")
    check_admin_token()
    check_debug()
    check_database_url()
    check_required_deps()
    check_money_mode()
    check_destructive_scopes_off_by_default()
    check_alert_destination()
    check_disk()
    print("\n" + "=" * 60)
    if FAILS:
        print(f"BLOCKED — {len(FAILS)} gate(s) failed, {len(WARNS)} warning(s). DO NOT DEPLOY.")
        return 1
    if WARNS:
        print(f"PROCEED WITH CAUTION — 0 failures, {len(WARNS)} warning(s) to confirm.")
        return 0
    print("PASS — all gates green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
