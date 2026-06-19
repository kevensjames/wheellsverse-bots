#!/usr/bin/env python3
"""core/nexora_connect.py — Stripe Connect scaffolding (INERT by default).

Live money-movement to creators is BLOCKED on operator/legal prerequisites the
codebase cannot satisfy itself: an approved Stripe Connect platform account +
accepted Connect services agreement, and per-creator Express KYC (a Transfer can
only target a connected account with payouts_enabled=true). Until then every
function here raises ConnectNotConfigured.

Design choices (locked):
  - Express connected accounts (Stripe-hosted onboarding/KYC + 1099-K).
  - Separate charges + transfers: fan money lands on the platform; a 'paid'
    PayoutRequest triggers a Transfer to the creator's connected account.
  - disburse_payout sets status='processing' ONLY. status='paid' is written
    exclusively by the payout.paid webhook — NEVER coupled to an admin edit,
    so a single click can't move real money.
"""
import os
from typing import Dict

from core.nexora_db import get_conn


class ConnectNotConfigured(RuntimeError):
    """Raised when Stripe Connect is disabled or the platform account is absent."""


def _connect_enabled() -> bool:
    return os.getenv("STRIPE_CONNECT_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _require_enabled() -> None:
    if not _connect_enabled():
        raise ConnectNotConfigured("connect_not_configured")


def _stripe():
    import stripe
    stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
    return stripe


def _creator_row(conn, email: str):
    return conn.execute(
        "SELECT id, stripe_account_id, stripe_payouts_enabled, stripe_onboarding_status "
        "FROM nx_creators WHERE email=? OR user_email=?", (email, email)).fetchone()


def create_or_get_connected_account(creator_email: str) -> str:
    """Return the creator's Express connected-account id, creating it if absent. Idempotent."""
    _require_enabled()
    conn = get_conn()
    try:
        row = _creator_row(conn, creator_email)
        if row and row["stripe_account_id"]:
            return row["stripe_account_id"]
        acct = _stripe().Account.create(
            type="express", email=creator_email,
            capabilities={"transfers": {"requested": True}})
        conn.execute("UPDATE nx_creators SET stripe_account_id=?, stripe_onboarding_status='started' "
                     "WHERE email=? OR user_email=?", (acct["id"], creator_email, creator_email))
        conn.commit()
        return acct["id"]
    finally:
        conn.close()


def create_onboarding_link(creator_email: str, refresh_url: str, return_url: str) -> Dict:
    """Return a Stripe-hosted Express onboarding URL for the creator."""
    _require_enabled()
    acct = create_or_get_connected_account(creator_email)
    link = _stripe().AccountLink.create(
        account=acct, refresh_url=refresh_url or "", return_url=return_url or "",
        type="account_onboarding")
    return {"url": link["url"]}


def connect_status(creator_email: str) -> Dict:
    """Read-only — safe even when Connect is disabled (returns the inert state)."""
    conn = get_conn()
    try:
        row = _creator_row(conn, creator_email)
    finally:
        conn.close()
    if not row:
        return {"has_account": False, "payouts_enabled": False, "onboarding_status": "none"}
    return {
        "has_account": bool(row["stripe_account_id"]),
        "payouts_enabled": bool(row["stripe_payouts_enabled"]),
        "onboarding_status": row["stripe_onboarding_status"] or "none",
    }


def disburse_payout(payout_id: int) -> Dict:
    """Initiate a Transfer for a PayoutRequest. Refuses unless the creator's
    connected account has payouts_enabled (KYC complete). Sets status='processing';
    the payout.paid webhook later writes 'paid'. NEVER call from the admin 'paid' hook."""
    _require_enabled()
    conn = get_conn()
    try:
        p = conn.execute("SELECT * FROM nx_payouts WHERE id=?", (payout_id,)).fetchone()
        if not p:
            raise ValueError("payout not found")
        cr = conn.execute("SELECT stripe_account_id, stripe_payouts_enabled FROM nx_creators WHERE id=?",
                          (p["creator_id"],)).fetchone()
        if not cr or not cr["stripe_account_id"] or not cr["stripe_payouts_enabled"]:
            raise ConnectNotConfigured("creator payouts not enabled (KYC incomplete)")
        transfer = _stripe().Transfer.create(
            amount=int(round(p["amount"] * 100)), currency="usd",
            destination=cr["stripe_account_id"], metadata={"payout_id": str(payout_id)})
        conn.execute("UPDATE nx_payouts SET status='processing', stripe_transfer_id=? WHERE id=?",
                     (transfer["id"], payout_id))
        conn.commit()
        return {"ok": True, "transfer_id": transfer["id"], "status": "processing"}
    finally:
        conn.close()
