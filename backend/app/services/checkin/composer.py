"""Compose the daily check-in message from REAL context.

Templated (not an LLM call) so it's free, instant, and works even when the cloud
brains are down — and grounded in actual signals: the operator's name + an active
goal (twin), how long they've worked together (relationship), and the recent
mood trend (eq). Every context source is fail-soft.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# A friendly, recent-mood-aware opener.
_MOOD_OPENER = {
    "stressed": "Things felt heavy lately",
    "frustrated": "It's been a frustrating stretch",
    "anxious": "There's been some weight on your mind",
    "sad": "It's been a tough stretch",
    "tired": "You've been running hard",
    "happy": "You've been in good spirits",
    "excited": "There's been real momentum",
    "motivated": "You've been locked in",
}


def _operator_name() -> str:
    try:
        from app.services.twin import storage as twin
        for e in twin.list_entries(section="identity", status="active", limit=20):
            # crude name pull: first capitalized token that looks like a name
            for tok in e.text.replace(",", " ").split():
                if tok.istitle() and tok.lower() not in ("you", "kai", "the", "your"):
                    return tok
    except Exception:
        pass
    return "Jhon"


def _active_goal() -> str:
    try:
        from app.services.twin import storage as twin
        goals = twin.list_entries(section="goals", status="active", limit=1)
        if goals:
            return goals[0].text
    except Exception:
        pass
    return ""


def _recent_mood() -> str:
    try:
        from app.services.eq import storage as eq
        return eq.stats(window=20).get("latest_mood") or ""
    except Exception:
        return ""


def _days_known() -> int:
    try:
        from app.services.relationship import storage as rel
        return rel.get_state().get("days_known", 0)
    except Exception:
        return 0


def compose_checkin() -> str:
    name = _operator_name()
    mood = _recent_mood()
    goal = _active_goal()
    days = _days_known()

    parts = [f"Good morning, {name}. ☀️"]
    if days >= 2:
        parts.append(f"We've been at this {days} days now.")
    opener = _MOOD_OPENER.get(mood)
    if opener:
        parts.append(f"{opener} — how are you feeling today?")
    else:
        parts.append("How are you feeling today?")
    if goal:
        parts.append(f"Last we talked, a goal of yours was: {goal} — want to push it forward today?")
    parts.append("What's the one thing you'd most like to get done?")
    return " ".join(parts)
