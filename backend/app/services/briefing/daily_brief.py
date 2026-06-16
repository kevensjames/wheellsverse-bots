"""Generate today's operator brief.

Pulls from KAI's own data sources — no external API calls, no LLM
round-trip. Composes a short structured summary:

  - users: signups in last 24h / 7d, current tier mix
  - revenue: active subs, new subs 24h
  - spend: today + 7d $ by adapter
  - scanner: latest Supreme severity counts + last scan time
  - errors: tail of llm_call_log failures in last 24h

Decorated with @audited so every brief generation appears in
data/governance/audit.jsonl — the operator can see exactly when KAI
last ran the report and who triggered it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.models.profile import Profile
from app.models.subscription import Subscription
from app.services.governance import audited
from app.services.supreme import latest_proposals

logger = logging.getLogger(__name__)


@audited(scope="briefing.daily", destructive=False)
def generate_daily_brief(session: Session) -> dict[str, Any]:
    """Compose today's brief. Pure-read, no side effects beyond the
    audit-log entry."""
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)

    return {
        "generated_at": now.isoformat(),
        "users": _user_block(session, day_ago, week_ago),
        "revenue": _revenue_block(session, day_ago),
        "spend": _spend_block(session),
        "scanner": _scanner_block(),
        "errors": _error_block(session),
        "headline": None,  # filled in below
    } | {"headline": _compose_headline(session, day_ago)}


def _user_block(session: Session, day_ago, week_ago) -> dict[str, Any]:
    total = session.query(func.count(Profile.id)).scalar() or 0
    last_24h = (
        session.query(func.count(Profile.id))
        .filter(Profile.created_at >= day_ago).scalar() or 0
    )
    last_7d = (
        session.query(func.count(Profile.id))
        .filter(Profile.created_at >= week_ago).scalar() or 0
    )
    by_tier = dict(
        session.query(Profile.tier, func.count(Profile.id))
        .group_by(Profile.tier).all()
    )
    return {
        "total": int(total),
        "last_24h": int(last_24h),
        "last_7d": int(last_7d),
        "by_tier": {k: int(v) for k, v in by_tier.items()},
    }


def _revenue_block(session: Session, day_ago) -> dict[str, Any]:
    active = (
        session.query(func.count(Subscription.id))
        .filter(Subscription.status == "active").scalar() or 0
    )
    new_24h = (
        session.query(func.count(Subscription.id))
        .filter(
            Subscription.status == "active",
            Subscription.created_at >= day_ago,
        ).scalar() or 0
    )
    return {"active_subs": int(active), "new_subs_24h": int(new_24h)}


def _spend_block(session: Session) -> dict[str, Any]:
    today_rows = session.execute(text(
        """
        SELECT adapter, COALESCE(SUM(cost_usd), 0) AS total, COUNT(*) AS calls
        FROM llm_call_log
        WHERE created_at >= DATE_TRUNC('day', NOW())
        GROUP BY adapter
        ORDER BY total DESC
        """
    )).all()
    week_total = session.execute(text(
        """
        SELECT COALESCE(SUM(cost_usd), 0)
        FROM llm_call_log
        WHERE created_at >= NOW() - INTERVAL '7 days'
        """
    )).scalar() or 0
    return {
        "today_usd": sum(float(r.total) for r in today_rows),
        "today_by_adapter": [
            {"adapter": r.adapter, "cost_usd": float(r.total), "calls": int(r.calls)}
            for r in today_rows
        ],
        "last_7d_usd": float(week_total),
    }


def _scanner_block() -> dict[str, Any]:
    latest = latest_proposals(n=1)
    if not latest:
        return {"has_scan": False}
    p = latest[0]
    return {
        "has_scan": True,
        "scanned_at": p.get("scanned_at"),
        "finding_count": p.get("finding_count", 0),
        "severity_counts": p.get("severity_counts", {}),
        # Surface only the high+critical titles — the brief is for
        # at-a-glance reading, not full incident review.
        "headline_findings": [
            {"severity": f["severity"], "title": f["title"]}
            for f in (p.get("findings") or [])
            if f.get("severity") in ("high", "critical")
        ][:5],
    }


def _error_block(session: Session) -> dict[str, Any]:
    """Recent LLM failures — the kind that won't show on the chat dashboard
    until they pile up enough to affect a real user."""
    rows = session.execute(text(
        """
        SELECT adapter, model, error_message, created_at
        FROM llm_call_log
        WHERE success = FALSE
          AND created_at >= NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC
        LIMIT 5
        """
    )).all()
    return {
        "failure_count_24h": len(rows),
        "recent": [
            {
                "adapter": r.adapter, "model": r.model,
                "error": (r.error_message or "")[:200],
                "at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


def _compose_headline(session: Session, day_ago) -> str:
    """One-line summary the operator can read in 2 seconds. The dashboard
    UI promotes this to a banner above the structured detail."""
    new_users = (
        session.query(func.count(Profile.id))
        .filter(Profile.created_at >= day_ago).scalar() or 0
    )
    new_subs = (
        session.query(func.count(Subscription.id))
        .filter(
            Subscription.status == "active",
            Subscription.created_at >= day_ago,
        ).scalar() or 0
    )
    today_spend = session.execute(text(
        """
        SELECT COALESCE(SUM(cost_usd), 0)
        FROM llm_call_log
        WHERE created_at >= DATE_TRUNC('day', NOW())
        """
    )).scalar() or 0
    latest = latest_proposals(n=1)
    sev_high = 0
    if latest:
        sev_high = (
            latest[0].get("severity_counts", {}).get("high", 0)
            + latest[0].get("severity_counts", {}).get("critical", 0)
        )

    parts = [
        f"{new_users} signup{'s' if new_users != 1 else ''} / "
        f"{new_subs} paid in last 24h",
        f"${float(today_spend):.2f} spend today",
    ]
    if sev_high:
        parts.append(f"⚠️ {sev_high} high+ finding(s) on last scan")
    else:
        parts.append("✓ scanner clean")
    return " · ".join(parts)
