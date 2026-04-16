#!/usr/bin/env python3
"""
core/impact.py
─────────────────────────────────────────────────────────────────────────────
Impact.com Affiliate Earnings Tracker  (v2 — upgraded)

Pulls real-time data from the Impact.com Publisher API:
  • Earnings / commissions (Actions)
  • Programs / campaigns joined
  • Ad creatives available
  • Invoices / payment history
  • Account health & status

Credentials (set in .env):
  IMPACT_ACCOUNT_SID   — Publisher Account SID
  IMPACT_API_PASSWORD  — API auth token / password

Available endpoints on this account:
  ✅ Actions, Campaigns, Ads, Invoices
  ❌ MediaPartnerClicks, TrackingLinks, Coupons (requires higher-tier access)
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("impact")

# Endpoints not permitted on this account — skip silently
_BLOCKED_ENDPOINTS = {"MediaPartnerClicks", "TrackingLinks", "Coupons",
                      "PaymentRequests", "FundingRequests", "MediaPartners"}


def _get(endpoint: str, params: dict = None) -> dict:
    """Authenticated GET to Impact.com API with smart error handling."""
    # Skip known-blocked endpoints without making a network call
    base_ep = endpoint.split("?")[0].split("/")[0]
    if base_ep in _BLOCKED_ENDPOINTS:
        return {"error": f"{base_ep} not permitted on this account", "status_code": 403, "skipped": True}

    account_sid = os.getenv("IMPACT_ACCOUNT_SID", "")
    api_password = os.getenv("IMPACT_API_PASSWORD", "")
    if not account_sid or not api_password:
        return {"error": "IMPACT_ACCOUNT_SID / IMPACT_API_PASSWORD not set in .env"}

    base_url = f"https://api.impact.com/Mediapartners/{account_sid}"
    try:
        resp = requests.get(
            f"{base_url}/{endpoint}",
            auth=(account_sid, api_password),
            params=params or {},
            timeout=15,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        if resp.status_code == 403:
            logger.warning(f"Impact.com 403 on {endpoint} — endpoint not permitted on this account")
            _BLOCKED_ENDPOINTS.add(base_ep)
        else:
            logger.error(f"Impact API {resp.status_code} on {endpoint}: {resp.text[:200]}")
        return {"error": str(e), "status_code": resp.status_code, "detail": resp.text[:200]}
    except Exception as e:
        logger.error(f"Impact API error on {endpoint}: {e}")
        return {"error": str(e)}


def _get_all_pages(endpoint: str, list_key: str, params: dict = None, max_pages: int = 10) -> List[Dict]:
    """Fetch all pages for a paginated endpoint."""
    all_items = []
    page = 1
    p = {**(params or {}), "PageSize": 200}
    while page <= max_pages:
        p["Page"] = page
        data = _get(endpoint, p)
        if "error" in data:
            break
        items = data.get(list_key, [])
        all_items.extend(items)
        total = int(data.get("@total", 0))
        if len(all_items) >= total or not items:
            break
        page += 1
    return all_items


# ─── Account Info ──────────────────────────────────────────────────────────────

def get_account_status() -> Dict:
    """Check account connectivity and return basic status."""
    account_sid = os.getenv("IMPACT_ACCOUNT_SID", "")
    api_password = os.getenv("IMPACT_API_PASSWORD", "")
    configured = bool(account_sid and api_password)
    if not configured:
        return {"connected": False, "reason": "Credentials missing in .env"}

    # Use Campaigns as a lightweight connectivity test
    data = _get("Campaigns", {"PageSize": 1})
    if "error" in data:
        return {
            "connected": False,
            "account_sid": account_sid,
            "reason": data.get("detail", data.get("error")),
        }
    return {
        "connected": True,
        "account_sid": account_sid,
        "total_programs": int(data.get("@total", 0)),
    }


# ─── Programs / Campaigns ─────────────────────────────────────────────────────

def get_programs() -> List[Dict]:
    """List all affiliate programs — all statuses."""
    items = _get_all_pages("Campaigns", "Campaigns")
    programs = []
    for c in items:
        programs.append({
            "id": c.get("CampaignId"),
            "name": c.get("Name"),
            "status": c.get("MediaPartnerStatus"),
            "category": c.get("Category"),
            "currency": c.get("Currency"),
            "description": (c.get("Description") or "")[:120],
        })
    return programs


def get_programs_summary() -> Dict:
    """Count programs by status."""
    programs = get_programs()
    by_status: Dict[str, int] = {}
    for p in programs:
        s = p.get("status", "Unknown")
        by_status[s] = by_status.get(s, 0) + 1
    return {
        "total": len(programs),
        "by_status": by_status,
        "programs": programs,
    }


# ─── Earnings ─────────────────────────────────────────────────────────────────

def get_earnings(days: int = 30) -> Dict:
    """Pull commission earnings for the last N days (max 44)."""
    days = min(days, 44)
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00Z")
    end = datetime.now().strftime("%Y-%m-%dT23:59:59Z")

    actions = _get_all_pages("Actions", "Actions", {
        "StartDate": start,
        "EndDate": end,
    })

    if isinstance(actions, dict) and "error" in actions:
        return actions  # propagate error

    total = 0.0
    by_program: Dict[str, float] = {}
    by_day: Dict[str, float] = {}
    by_status: Dict[str, float] = {}
    pending = locked = 0.0

    for action in actions:
        payout = float(action.get("Payout", 0) or 0)
        program = action.get("CampaignName", "Unknown")
        date_str = (action.get("EventDate", "") or "")[:10]
        status = action.get("LockingStatus", "Unknown")

        total += payout
        by_program[program] = by_program.get(program, 0.0) + payout
        by_status[status] = by_status.get(status, 0.0) + payout
        if date_str:
            by_day[date_str] = by_day.get(date_str, 0.0) + payout
        if status == "Pending":
            pending += payout
        elif status == "Locked":
            locked += payout

    return {
        "period_days": days,
        "start_date": start,
        "end_date": end,
        "total_earned": round(total, 2),
        "pending": round(pending, 2),
        "locked": round(locked, 2),
        "by_program": {k: round(v, 2) for k, v in sorted(by_program.items(), key=lambda x: -x[1])},
        "by_day": dict(sorted(by_day.items())),
        "by_status": {k: round(v, 2) for k, v in by_status.items()},
        "action_count": len(actions),
        "fetched_at": datetime.now().isoformat(),
    }


def get_today_earnings() -> Dict:
    return get_earnings(days=1)


def get_lifetime_earnings() -> Dict:
    return get_earnings(days=44)


# ─── Ads / Creatives ──────────────────────────────────────────────────────────

def get_ads(campaign_id: str = None) -> List[Dict]:
    """Fetch available ad creatives."""
    params = {}
    if campaign_id:
        params["CampaignId"] = campaign_id
    items = _get_all_pages("Ads", "Ads", params)
    ads = []
    for a in items:
        ads.append({
            "id": a.get("AdId"),
            "name": a.get("Name"),
            "type": a.get("Type"),
            "width": a.get("Width"),
            "height": a.get("Height"),
            "campaign": a.get("CampaignName"),
            "campaign_id": a.get("CampaignId"),
            "landing_url": a.get("LandingPageUrl"),
            "img_url": a.get("ImgUrl"),
        })
    return ads


# ─── Invoices / Payments ──────────────────────────────────────────────────────

def get_invoices(limit: int = 20) -> List[Dict]:
    """Fetch payment invoices."""
    items = _get_all_pages("Invoices", "Invoices", {"PageSize": limit}, max_pages=1)
    invoices = []
    for inv in items:
        invoices.append({
            "id": inv.get("Id"),
            "date": inv.get("InvoiceDate"),
            "amount": float(inv.get("Amount", 0) or 0),
            "currency": inv.get("Currency"),
            "status": inv.get("Status"),
            "due_date": inv.get("DueDate"),
        })
    return invoices


def get_total_paid() -> Dict:
    """Sum all paid invoices."""
    invoices = get_invoices(limit=200)
    paid = sum(i["amount"] for i in invoices if i.get("status") == "Paid")
    unpaid = sum(i["amount"] for i in invoices if i.get("status") != "Paid")
    return {
        "total_invoices": len(invoices),
        "total_paid": round(paid, 2),
        "total_unpaid": round(unpaid, 2),
        "invoices": invoices[:10],
    }


# ─── Full Dashboard Summary ───────────────────────────────────────────────────

def get_summary() -> Dict:
    """Complete dashboard summary — earnings + programs + ads + invoices + health."""
    account = get_account_status()
    earnings = get_earnings(days=30) if account.get("connected") else {"error": "Not connected"}
    earnings7 = get_earnings(days=7) if account.get("connected") else {}
    programs = get_programs_summary()
    paid = get_total_paid()
    ads = get_ads()

    # Conversion rate (actions / programs, if any)
    action_count = earnings.get("action_count", 0) if isinstance(earnings, dict) else 0
    conv_rate = round(action_count / max(programs["total"], 1) * 100, 1)

    return {
        "account": account,
        "last_30_days": earnings,
        "last_7_days": earnings7,
        "programs": programs,
        "payments": paid,
        "ads_available": len(ads),
        "conversion_rate_pct": conv_rate,
        "configured": bool(os.getenv("IMPACT_ACCOUNT_SID") and os.getenv("IMPACT_API_PASSWORD")),
        "fetched_at": datetime.now().isoformat(),
    }


# ─── Backwards-compat alias ───────────────────────────────────────────────────

def get_clicks(days: int = 7) -> Dict:
    """Alias kept for api.py compatibility — clicks not available on this account."""
    return {
        "period_days": days,
        "total_clicks": 0,
        "by_program": {},
        "fetched_at": datetime.now().isoformat(),
        "note": "MediaPartnerClicks not permitted on this account",
    }


# ─── Singleton ────────────────────────────────────────────────────────────────

_impact = None


def get_impact():
    global _impact
    if _impact is None:
        _impact = type("Impact", (), {
            "get_earnings": get_earnings,
            "get_today": get_today_earnings,
            "get_lifetime": get_lifetime_earnings,
            "get_programs": get_programs,
            "get_programs_summary": get_programs_summary,
            "get_ads": get_ads,
            "get_invoices": get_invoices,
            "get_total_paid": get_total_paid,
            "get_account_status": get_account_status,
            "get_summary": get_summary,
        })()
    return _impact
