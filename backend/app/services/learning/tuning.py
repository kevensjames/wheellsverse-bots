"""Learning auto-tuning — measure whether ACTIVE lessons are helping, and flag
the ones that aren't for retirement.

Honest about its limits. Feedback isn't tagged to specific lessons, so this
compares the GLOBAL thumbs-down rate in the window *before* a lesson was
activated against the rate *after*. That's correlational, not causal — with
several lessons active at once you can't fully attribute a change to one
lesson. So this PROPOSES retirements (with the caveat surfaced); the operator
approves the actual dismiss via the existing audited endpoint. Nothing is
auto-dismissed.

A lesson is flagged `recommend_retire` when, after a minimum observation window
AND a minimum number of post-activation feedback samples, its down-rate is no
better than before (no_change) or worse (worsening). Lessons that are too new
or have too little feedback are reported as `insufficient_data` and flagged for
nothing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.learning import storage

DEFAULT_WINDOW_DAYS = 14
DEFAULT_MIN_AFTER_SAMPLES = 3
# Down-rate must move by more than this to count as improving/worsening (so
# tiny sample noise doesn't read as a trend).
_EPSILON = 0.05


def evaluate_lessons(
    *, window_days: int = DEFAULT_WINDOW_DAYS,
    min_after_samples: int = DEFAULT_MIN_AFTER_SAMPLES,
) -> dict[str, Any]:
    """Per-active-lesson effectiveness verdict + retirement recommendations.

    Returns {"evaluated": [...], "recommend_retire": [ids], "summary": {...},
    "caveat": str}. Pure read — no mutation, no LLM, no network.
    """
    active = storage.list_lessons(status="active", limit=500)
    feedback = storage.list_feedback(limit=500)  # newest-first, has created_at

    evaluated: list[dict[str, Any]] = []
    for lesson in active:
        activated_at = _parse_ts(lesson.meta.get("activated_at")) or _parse_ts(lesson.updated_at)
        row = _evaluate_one(lesson, activated_at, feedback, window_days, min_after_samples)
        evaluated.append(row)

    recommend = [r["id"] for r in evaluated if r["recommend_retire"]]
    by_verdict: dict[str, int] = {}
    for r in evaluated:
        by_verdict[r["verdict"]] = by_verdict.get(r["verdict"], 0) + 1

    return {
        "evaluated": evaluated,
        "recommend_retire": recommend,
        "summary": {
            "active_lessons": len(active),
            "by_verdict": by_verdict,
            "window_days": window_days,
            "min_after_samples": min_after_samples,
        },
        "caveat": (
            "Correlational, not causal: feedback isn't tagged to individual "
            "lessons, so this compares the global down-rate before vs after "
            "each lesson activated. Treat retirements as suggestions to review."
        ),
    }


# ─── internals ──────────────────────────────────────────────────────


def _evaluate_one(lesson, activated_at, feedback, window_days, min_after_samples) -> dict[str, Any]:
    base = {
        "id": lesson.id, "text": lesson.text, "source": lesson.source,
        "activated_at": activated_at.isoformat() if activated_at else None,
    }
    if activated_at is None:
        return {**base, "days_active": None, "n_after": 0,
                "down_rate_before": None, "down_rate_after": None,
                "verdict": "insufficient_data", "recommend_retire": False,
                "rationale": "no activation timestamp"}

    now = datetime.now(timezone.utc)
    days_active = (now - activated_at).total_seconds() / 86400.0
    before_start = activated_at - timedelta(days=max(1, window_days))

    before = [f for f in feedback if _in_range(f.created_at, before_start, activated_at)]
    after = [f for f in feedback if _in_range(f.created_at, activated_at, now)]

    rate_before = _down_rate(before)
    rate_after = _down_rate(after)
    n_after = len(after)

    if n_after < min_after_samples:
        verdict, recommend = "insufficient_data", False
        rationale = f"only {n_after} feedback sample(s) since activation (<{min_after_samples})"
    elif rate_before is not None and rate_after < rate_before - _EPSILON:
        verdict, recommend = "improving", False
        rationale = f"down-rate fell {rate_before:.0%}→{rate_after:.0%} after activation"
    elif rate_before is not None and rate_after > rate_before + _EPSILON:
        verdict = "worsening"
        recommend = True
        rationale = f"down-rate rose {rate_before:.0%}→{rate_after:.0%} after activation"
    else:
        # no meaningful change — only retire if we've observed long enough
        verdict = "no_change"
        recommend = days_active >= window_days
        rationale = (
            f"down-rate ~flat ({_fmt(rate_before)}→{rate_after:.0%}); "
            f"{days_active:.0f}d active"
            + (" — observed long enough to retire" if recommend else " — keep observing")
        )

    return {**base, "days_active": round(days_active, 1), "n_after": n_after,
            "down_rate_before": _round(rate_before), "down_rate_after": _round(rate_after),
            "verdict": verdict, "recommend_retire": recommend, "rationale": rationale}


def _down_rate(rows: list) -> float | None:
    if not rows:
        return None
    downs = sum(1 for f in rows if f.rating == "down")
    return downs / len(rows)


def _in_range(ts_str: str | None, start: datetime, end: datetime) -> bool:
    ts = _parse_ts(ts_str)
    return ts is not None and start <= ts < end


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        ts = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def _round(v: float | None) -> float | None:
    return round(v, 3) if isinstance(v, float) else None


def _fmt(v: float | None) -> str:
    return f"{v:.0%}" if isinstance(v, float) else "n/a"
