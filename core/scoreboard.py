"""Honest portfolio scoreboard — real numbers from connected surfaces only.

Design principle (anti-theater): a surface that cannot be measured is reported
as `connected: False` with `value: None`, NEVER as a fake `0`. A real `0` (e.g.
Stripe configured but no sales) is distinct from "not measured". This is the
accountability mirror for the Wheellsverse portfolio — it tells the truth even
when the truth is that nothing has shipped.

Metrics: revenue (month + all-time), MRR, users, trials, leads, emails_sent,
conversion, churn, open_bugs, deployments — each tagged {value, connected, source}.
"""
from __future__ import annotations

import time
from typing import Any


def _metric(value: Any, connected: bool, source: str, note: str = "") -> dict:
    return {"value": (value if connected else None), "connected": connected,
            "source": source, "note": note}


def _stripe_block() -> dict:
    """Live revenue via the existing core.revenue engine (Stripe + Impact)."""
    try:
        from core.revenue import get_dashboard
        d = get_dashboard(refresh_live=True) or {}
        st = d.get("stripe", {}) or {}
        connected = bool(st.get("configured"))
        period = d.get("period", {}) or {}
        return {
            "connected": connected,
            "revenue_month": period.get("month", 0),
            "revenue_all_time": period.get("all_time", 0),
            "mrr": d.get("mrr", 0),
            "users": st.get("active_subscriptions"),   # may be absent -> None
            "trials": st.get("trialing_subscriptions"),
            "churn": st.get("canceled_30d"),
        }
    except Exception as e:  # pragma: no cover - defensive
        return {"connected": False, "error": str(e)}


def _leads_block() -> dict:
    """SiteBoost lead/outreach counters (file-backed, always readable)."""
    try:
        from core.siteboost_state import stats
        s = stats() or {}
        return {"connected": True,
                "leads": int(s.get("places_scanned", 0)),
                "emails_sent": int(s.get("emails_sent", 0))}
    except Exception as e:  # pragma: no cover - defensive
        return {"connected": False, "error": str(e)}


def _conversion(users, leads, both_connected: bool):
    if not both_connected or not leads:
        return None, False
    return round((users or 0) / leads, 4), True


def snapshot() -> dict:
    """One honest read of every metric across connected surfaces."""
    rev = _stripe_block()
    leads = _leads_block()
    rc = bool(rev.get("connected"))
    lc = bool(leads.get("connected"))

    conv_val, conv_conn = _conversion(rev.get("users"), leads.get("leads"), rc and lc)

    metrics = {
        "revenue_month": _metric(rev.get("revenue_month"), rc, "stripe"),
        "revenue_all_time": _metric(rev.get("revenue_all_time"), rc, "stripe"),
        "mrr": _metric(rev.get("mrr"), rc, "stripe"),
        "users": _metric(rev.get("users"), rc and rev.get("users") is not None,
                         "stripe (active subscriptions)"),
        "trials": _metric(rev.get("trials"), rc and rev.get("trials") is not None,
                          "stripe (trialing subscriptions)"),
        "leads": _metric(leads.get("leads"), lc, "siteboost"),
        "emails_sent": _metric(leads.get("emails_sent"), lc, "siteboost"),
        "conversion": _metric(conv_val, conv_conn, "derived: users / leads"),
        "churn": _metric(rev.get("churn"), rc and rev.get("churn") is not None,
                         "stripe (canceled 30d)"),
        "open_bugs": _metric(None, False, "manual / gh issues (not wired)"),
        # honest: no deploy-count source is wired, so report unmeasured (not a fake 0).
        # Matches this module's stated principle and open_bugs above.
        "deployments": _metric(None, False, "no deploy-count source wired",
                               note="deploy count is not wired to a real source"),
    }

    # Surface connectivity — what we can and cannot see, named plainly.
    surfaces = {
        "stripe": rc,
        "siteboost": lc,
        "ds24": False,          # no client code in repo
        "stan": False,          # web-login only, no sales API
        "bigcommerce": False,   # config template only, no client
        "instantly_stats": False,
    }

    # Headline truth — the one line a founder reads first.
    headline = (
        f"MRR ${metrics['mrr']['value'] if rc else '—'} · "
        f"users {metrics['users']['value'] if metrics['users']['connected'] else '—'} · "
        f"leads {metrics['leads']['value'] if lc else '—'} · "
        f"{metrics['deployments']['value'] if metrics['deployments']['connected'] else '—'} prod deployments"
    )

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "headline": headline,
        "metrics": metrics,
        "surfaces": surfaces,
        "connected_count": sum(1 for v in surfaces.values() if v),
        "total_surfaces": len(surfaces),
    }
