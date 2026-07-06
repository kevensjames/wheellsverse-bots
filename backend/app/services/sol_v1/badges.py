"""Sol v1 badges — a member's earned achievements, DERIVED read-only from history.

The spec (Part 4) wants a SOL Score + a badge wall. Sol already derives a 0-100
reliability score (reputation.py) from payer history; this adds the BADGE layer on
top — computed on demand from the same recorded data (circles completed, on-time
record, organizing), never stored. Like reputation and the timeline, it's a pure
projection: no writes, no money, no event hooks, nothing to invalidate.

The badge predicates are a pure function (unit-tested offline); the stats are a
handful of read queries.
"""
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.sol import SolGroup, SolMembership

# minimum counted payments before the record-quality badges can be earned (a
# handful of on-time payments is a real signal; one isn't) — mirrors reputation.
_MIN_HISTORY = 3


# ── pure: the badge catalog ─────────────────────────────────────────────────────


def award_badges(stats: dict) -> list[dict]:
    """The full badge catalog with each marked earned/not for `stats`. Returning
    the WHOLE catalog (not just earned) lets the UI show a wall with locked ones."""
    completed = stats["circles_completed"]
    organized = stats["circles_organized"]
    actionable = stats["actionable"]
    on_time = stats["on_time"]
    label = stats["reputation_label"]
    catalog = [
        ("first_circle", "First Circle",
         "Completed your first savings circle.", completed >= 1),
        ("gold_saver", "Gold Saver",
         "Completed 3 circles.", completed >= 3),
        ("elite_saver", "Elite Saver",
         "Completed 5 circles.", completed >= 5),
        ("organizer", "Organizer",
         "Started a circle of your own.", organized >= 1),
        ("reliable_saver", "Reliable Saver",
         "A strong on-time payment record.",
         actionable >= _MIN_HISTORY and label in ("good", "excellent")),
        ("perfect_payer", "Perfect Payer",
         "Every counted payment on time — no late, overdue, or disputed.",
         actionable >= _MIN_HISTORY and on_time == actionable),
    ]
    return [
        {"key": k, "label": l, "description": d, "earned": bool(e)}
        for k, l, d, e in catalog
    ]


# ── DB: the member's stats + profile ────────────────────────────────────────────


def compute_member_stats(db: Session, *, user_id: UUID, today: date) -> dict:
    """Aggregate a member's coordination history for the badge predicates + display.
    `sol_score`/label come from the existing reputation derivation."""
    from app.services.sol_v1 import reputation  # local: avoid import cycle

    rep = reputation.compute_reputation(db, user_id=user_id, today=today)
    circles_joined = db.scalar(
        select(func.count(SolMembership.id)).where(SolMembership.user_id == user_id)
    ) or 0
    circles_completed = db.scalar(
        select(func.count(SolMembership.id))
        .join(SolGroup, SolMembership.group_id == SolGroup.id)
        .where(SolMembership.user_id == user_id, SolGroup.status == "complete")
    ) or 0
    circles_organized = db.scalar(
        select(func.count(SolGroup.id)).where(SolGroup.organizer_id == user_id)
    ) or 0
    return {
        "circles_joined": int(circles_joined),
        "circles_completed": int(circles_completed),
        "circles_organized": int(circles_organized),
        "on_time": int(rep["breakdown"]["on_time"]),
        "actionable": int(rep["actionable"]),
        "sol_score": rep["score"],  # the existing 0-100 reliability score, surfaced as SOL Score
        "reputation_label": rep["label"],
    }


def member_profile(db: Session, *, user_id: UUID, today: date) -> dict:
    """The member's SOL profile: stats + earned/locked badge wall."""
    stats = compute_member_stats(db, user_id=user_id, today=today)
    return {"stats": stats, "badges": award_badges(stats)}
