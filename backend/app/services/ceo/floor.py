from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from . import store

CATASTROPHIC_KINDS = frozenset(
    {"money_transfer", "data_deletion", "prod_deploy", "secret_rotation", "mass_send", "new_account"}
)


def _f(env: str, default: float) -> float:
    try:
        return float(os.environ.get(env, default))
    except (TypeError, ValueError):
        return default


def is_killed() -> bool:
    v = (os.environ.get("KAI_CEO_KILLED") or "").strip().lower()
    return v in {"1", "true", "yes", "on"}


def is_catastrophic(action: dict) -> bool:
    kind = (action.get("kind") or "").strip()
    if kind not in CATASTROPHIC_KINDS:
        return False
    if kind == "money_transfer":
        return float(action.get("amount", 0) or 0) > _f("KAI_CEO_CATASTROPHIC_USD", 50)
    if kind == "mass_send":
        return int(action.get("recipients", 0) or 0) > int(_f("KAI_CEO_MASS_SEND_N", 25))
    return True  # prod_deploy / secret_rotation / data_deletion / new_account always escalate


def _period_start() -> str:
    period = (os.environ.get("KAI_CEO_PERIOD") or "weekly").lower()
    days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period, 7)
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def within_ceiling(amount: float) -> bool:
    ceiling = _f("KAI_CEO_BUDGET_CEILING", 0)
    spent = store.period_spend(_period_start())
    return (spent + float(amount or 0)) <= ceiling


def classify(action: dict) -> str:
    if is_catastrophic(action):
        return "catastrophic"
    amount = float(action.get("amount", 0) or 0)
    if amount > 0 and not within_ceiling(amount):
        return "over_ceiling"
    return "in_policy"
