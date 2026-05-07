"""Single-source-of-truth wrapper for Anthropic API calls.

Every code path that previously did:

    client = anthropic.Anthropic(api_key=...)
    resp = client.messages.create(model=..., max_tokens=..., messages=...)

should call this instead:

    from core.claude_logged import create as claude_create
    resp = claude_create(model=..., max_tokens=..., messages=..., bot_name="my_bot")

Three jobs in one place:

  1. **Daily-budget guard.** Reads `_DAILY_BUDGET_USD` from env via base_bot;
     raises `BudgetExceededError` before the API call when today's spend ≥ cap.
     Without this wrapper, individual call sites bypass the cap silently.

  2. **Token logging.** Appends to data/token_usage.json with bot_name
     attribution. Required for the per-bot spend report and the
     `_get_today_anthropic_spend()` accounting that base_bot.py uses.

  3. **Credit-balance error normalization.** If Anthropic returns "credit
     balance too low", we re-raise as `BudgetExceededError` so callers can
     handle the operator condition without parsing string errors.

Returns the raw `anthropic.types.Message` object — callers using
`resp.content[0].text` don't need to change anything except the `client.`
prefix.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("claude_logged")


def create(
    *,
    model: str,
    max_tokens: int,
    messages: list,
    system: Optional[str] = None,
    bot_name: str = "unknown",
    api_key: Optional[str] = None,
    **extra: Any,
) -> Any:
    """Drop-in for `anthropic_client.messages.create(...)`.

    Differences vs raw SDK call:
      - Pre-flight daily-budget check (BudgetExceededError if blown)
      - Pre-flight credit-balance error → BudgetExceededError
      - Post-call token logging via core.base_bot._log_token_usage
    """
    # Lazy imports so this module stays cheap to import.
    from core.base_bot import (
        BudgetExceededError, _DAILY_BUDGET_USD,
        _get_today_anthropic_spend, _log_token_usage,
    )

    spend = _get_today_anthropic_spend()
    if spend >= _DAILY_BUDGET_USD:
        raise BudgetExceededError(
            f"Daily Anthropic budget (${_DAILY_BUDGET_USD:.2f}) reached "
            f"(spent ${spend:.4f}) — call from {bot_name!r} blocked"
        )

    import anthropic
    client = anthropic.Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY", ""))
    kwargs: dict = {"model": model, "max_tokens": max_tokens, "messages": messages, **extra}
    if system is not None:
        kwargs["system"] = system

    try:
        resp = client.messages.create(**kwargs)
    except anthropic.BadRequestError as e:
        msg = str(e).lower()
        if "credit balance" in msg or "credit_balance" in msg:
            raise BudgetExceededError(
                "Anthropic credit balance too low — top up at "
                "console.anthropic.com/settings/billing"
            ) from e
        raise

    # Log usage. Failures here must not break the caller.
    try:
        usage = getattr(resp, "usage", None)
        if usage is not None:
            _log_token_usage(
                "anthropic",
                model,
                getattr(usage, "input_tokens", 0) or 0,
                getattr(usage, "output_tokens", 0) or 0,
                bot_name,
            )
    except Exception as log_err:
        logger.warning(f"token logging failed for {bot_name}: {log_err}")

    return resp


def is_budget_healthy() -> bool:
    """Cheap pre-flight check: is today's Anthropic spend below the daily cap?

    Use this at the top of long-running jobs (cron-triggered autopilots) to
    skip cleanly instead of generating a cascade of credit-balance errors.

    Note: this only checks the *daily budget* heuristic. Anthropic-side credit
    balance can still be empty even if our daily-budget accounting says OK —
    that case is caught by `create()` raising `BudgetExceededError` on the
    actual API response.
    """
    try:
        from core.base_bot import _DAILY_BUDGET_USD, _get_today_anthropic_spend
        return _get_today_anthropic_spend() < _DAILY_BUDGET_USD
    except Exception:
        # If the helpers blow up, default to "healthy" so we don't accidentally
        # disable everything on an unrelated error.
        return True
