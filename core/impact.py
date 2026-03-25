#!/usr/bin/env python3
"""
core/impact.py
─────────────────────────────────────────────────────────────────────────────
Impact.com Affiliate Earnings Tracker

Pulls real-time commission data from Impact.com API for:
  • Robinhood  — $20 per funded account
  • Coinbase   — 50% of transaction fees

Credentials (set in .env):
  IMPACT_ACCOUNT_SID   — your publisher account SID (7117979)
  IMPACT_API_PASSWORD  — your API auth token/password
─────────────────────────────────────────────────────────────────────────────
"""

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")

logger = logging.getLogger("impact")

ACCOUNT_SID  = os.getenv("IMPACT_ACCOUNT_SID", "")
API_PASSWORD = os.getenv("IMPACT_API_PASSWORD", "")
BASE_URL     = f"https://api.impact.com/Mediapartners/{ACCOUNT_SID}"


def _get(endpoint: str, params: dict = None) -> dict:
    """Authenticated GET request to Impact.com API.
    Impact uses: Basic Auth with Account SID as both URL path and username,
    API Password as the secret.
    """
    if not ACCOUNT_SID or not API_PASSWORD:
        return {"error": "IMPACT_ACCOUNT_SID / IMPACT_API_PASSWORD not set in .env"}
    try:
        resp = requests.get(
            f"{BASE_URL}/{endpoint}",
            auth=(ACCOUNT_SID, API_PASSWORD),
            params=params or {},
            timeout=15,
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as e:
        logger.error(f"Impact API HTTP error: {e} — {resp.text[:200]}")
        return {"error": str(e), "detail": resp.text[:200]}
    except Exception as e:
        logger.error(f"Impact API error: {e}")
        return {"error": str(e)}


# ─── Earnings ─────────────────────────────────────────────────────────────────

def get_earnings(days: int = 30) -> Dict:
    """
    Pull commission earnings for the last N days.
    Returns total earned, by program, and daily breakdown.
    """
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
    end   = datetime.now().strftime("%Y-%m-%dT23:59:59")

    data = _get("Actions", {
        "StartDate":  start,
        "EndDate":    end,
        "PageSize":   200,
    })

    if "error" in data:
        return data

    actions    = data.get("Actions", [])
    total      = 0.0
    by_program: Dict[str, float] = {}
    by_day:     Dict[str, float] = {}
    pending    = 0.0
    locked     = 0.0

    for action in actions:
        payout    = float(action.get("Payout", 0) or 0)
        program   = action.get("CampaignName", "Unknown")
        date_str  = (action.get("EventDate", "") or "")[:10]
        status    = action.get("LockingStatus", "")

        total += payout
        by_program[program] = by_program.get(program, 0.0) + payout
        if date_str:
            by_day[date_str] = by_day.get(date_str, 0.0) + payout

        if status == "Pending":
            pending += payout
        elif status == "Locked":
            locked += payout

    return {
        "period_days":  days,
        "start_date":   start,
        "end_date":     end,
        "total_earned": round(total, 2),
        "pending":      round(pending, 2),
        "locked":       round(locked, 2),
        "by_program":   {k: round(v, 2) for k, v in sorted(by_program.items(), key=lambda x: -x[1])},
        "by_day":       dict(sorted(by_day.items())),
        "action_count": len(actions),
        "fetched_at":   datetime.now().isoformat(),
    }


def get_today_earnings() -> Dict:
    """Quick pull — today's earnings only."""
    return get_earnings(days=1)


def get_lifetime_earnings() -> Dict:
    """Pull last 365 days as a lifetime proxy."""
    return get_earnings(days=365)


# ─── Clicks & Conversions ─────────────────────────────────────────────────────

def get_clicks(days: int = 7) -> Dict:
    """Pull click stats for the last N days."""
    start = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT00:00:00")
    end   = datetime.now().strftime("%Y-%m-%dT23:59:59")

    data = _get("MediaPartnerClicks", {
        "StartDate": start,
        "EndDate":   end,
        "PageSize":  200,
    })

    if "error" in data:
        # Clicks endpoint may not be available on all accounts — return empty gracefully
        return {
            "period_days":  days,
            "total_clicks": 0,
            "by_program":   {},
            "fetched_at":   datetime.now().isoformat(),
            "note":         data.get("error", "Click data unavailable"),
        }

    clicks = data.get("Clicks", [])
    total_clicks = sum(int(c.get("Clicks", 0) or 0) for c in clicks)

    by_program: Dict[str, int] = {}
    for c in clicks:
        prog = c.get("CampaignName", "Unknown")
        by_program[prog] = by_program.get(prog, 0) + int(c.get("Clicks", 0) or 0)

    return {
        "period_days":  days,
        "total_clicks": total_clicks,
        "by_program":   by_program,
        "fetched_at":   datetime.now().isoformat(),
    }


# ─── Program List ─────────────────────────────────────────────────────────────

def get_programs() -> List[Dict]:
    """List all affiliate programs you're joined to."""
    data = _get("Campaigns", {"PageSize": 100})
    if "error" in data:
        return [data]

    programs = []
    for c in data.get("Campaigns", []):
        programs.append({
            "id":     c.get("CampaignId"),
            "name":   c.get("Name"),
            "status": c.get("MediaPartnerStatus"),
            "category": c.get("Category"),
        })
    return programs


# ─── Dashboard Summary ────────────────────────────────────────────────────────

def get_summary() -> Dict:
    """Full summary for the dashboard — earnings + clicks + programs."""
    earnings_30 = get_earnings(days=30)
    earnings_7  = get_earnings(days=7)
    clicks_7    = get_clicks(days=7)

    return {
        "last_30_days": earnings_30,
        "last_7_days":  earnings_7,
        "clicks_7_days": clicks_7,
        "configured":   bool(ACCOUNT_SID and API_PASSWORD),
    }


# ─── Singleton ────────────────────────────────────────────────────────────────

_impact = None


def get_impact():
    global _impact
    if _impact is None:
        _impact = type("Impact", (), {
            "get_earnings":         get_earnings,
            "get_today":            get_today_earnings,
            "get_lifetime":         get_lifetime_earnings,
            "get_clicks":           get_clicks,
            "get_programs":         get_programs,
            "get_summary":          get_summary,
        })()
    return _impact
