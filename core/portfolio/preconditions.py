"""Real precondition evaluation for the W-MOS envelope's auto-fire-within-caps tier.

Computes each named precondition from a real source; ANYTHING it cannot positively
compute resolves to False (fail-safe → queues, never auto-fires). The cockpit binds
a business via make_ctx_for(slug); the dormant sweep keeps the {} default. No adapter,
dispatch, or scheduler is touched — auto-fire here still only reaches inert adapters.
"""
from __future__ import annotations

import time
from typing import Callable

from core.portfolio import budget, state

DAILY_CAP = 50
_APPROVED_STATES = {"approved", "executing", "executed"}
_APPROVAL_PRECONDS = {"campaign_approved_once", "page_approved_once", "first_of_kind_approved"}
_FLAG_PRECONDS = {"warmup_complete", "teardown_handle", "unpublish_handle"}


def _verb_ever_approved(business: str, verb: str) -> bool:
    return any(
        a.get("business") == business
        and a.get("verb") == verb
        and a.get("status") in _APPROVED_STATES
        for a in state.list_approvals()
    )


def _one(business: str, verb: str, name: str, today: str, month: str) -> bool:
    if name in _APPROVAL_PRECONDS:
        return _verb_ever_approved(business, verb)
    if name == "under_daily_cap":
        return state.send_count(business, today) < DAILY_CAP
    if name == "under_cost_ceiling":
        return not budget.would_exceed(business, 0.0, month)
    if name in _FLAG_PRECONDS:
        return state.get_flag(business, name, False)
    return False  # fail-safe: an unknown precondition never auto-passes


def evaluate(business: str, step, *, today: str | None = None, month: str | None = None) -> dict:
    today = today or time.strftime("%Y-%m-%d", time.gmtime())
    month = month or time.strftime("%Y-%m", time.gmtime())
    verb = getattr(step, "verb", "")
    return {name: _one(business, verb, name, today, month)
            for name in getattr(step, "preconditions", [])}


def make_ctx_for(business: str) -> Callable[[object], dict]:
    def ctx_for(step) -> dict:
        return evaluate(business, step)
    return ctx_for
