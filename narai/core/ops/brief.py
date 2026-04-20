"""Daily brief — synthesize tasks, habits, sales pipeline, trading, market into
a short morning briefing via NarAI router."""
from __future__ import annotations

from typing import Any

from narai.core import router, skills


async def _safe_call(coro):
    try:
        return await coro
    except Exception as e:
        return {"error": str(e)}


async def generate_daily_brief(include_market: bool = True) -> dict[str, Any]:
    from narai.core.ops.tasks import TaskManager
    from narai.core.ops.habits import HabitTracker
    from narai.core.sales.pipeline import Pipeline

    tm = TaskManager()
    ht = HabitTracker()
    pl = Pipeline()

    tasks = await _safe_call(tm.list(include_done=False, limit=10))
    habits = await _safe_call(ht.status())
    pipeline = await _safe_call(pl.summary())

    market = ""
    if include_market:
        try:
            from narai.core.trading import forecast
            btc = forecast("BTC-USD", horizon_days=3)
            spy = forecast("SPY", horizon_days=3)
            market = (
                f"BTC: {btc.direction} · {(btc.confidence*100):.0f}% conf · ${btc.last_close:.0f}\n"
                f"SPY: {spy.direction} · {(spy.confidence*100):.0f}% conf · ${spy.last_close:.2f}"
            )
        except Exception as e:
            market = f"(market data unavailable: {e})"

    # Format sections
    def fmt_tasks(xs):
        if isinstance(xs, dict) and "error" in xs:
            return f"(tasks unavailable: {xs['error']})"
        if not xs:
            return "No open tasks."
        lines = []
        for t in xs:
            due = f" · due {t.get('due','')[:10]}" if t.get("due") else ""
            lines.append(f"• [P{t.get('priority',3)}] {t.get('title','')}{due}")
        return "\n".join(lines)

    def fmt_habits(xs):
        if isinstance(xs, dict) and "error" in xs:
            return f"(habits unavailable: {xs['error']})"
        if not xs:
            return "No habits tracked."
        return "\n".join(f"• {h['name']} — streak {h['streak']}d · today {'✓' if h['done_today'] else '✗'}" for h in xs)

    def fmt_pipeline(p):
        if isinstance(p, dict) and "error" in p:
            return f"(pipeline unavailable: {p['error']})"
        return (f"Open pipeline: ${p.get('open_amount',0):.0f} · "
                f"Won: ${p.get('won_amount',0):.0f} · "
                f"{p.get('total_deals',0)} deals")

    prompt = (
        "Produce a concise, high-signal morning brief. Sections: "
        "(1) Today's top priorities (pick 3 from the tasks below), "
        "(2) Habit check, (3) Sales snapshot, (4) Market read, (5) One nudge for the day. "
        "Output as short bullets, <150 words total.\n\n"
        f"--- Open tasks ---\n{fmt_tasks(tasks)}\n\n"
        f"--- Habits ---\n{fmt_habits(habits)}\n\n"
        f"--- Sales ---\n{fmt_pipeline(pipeline)}\n\n"
        f"--- Market ---\n{market or '(skipped)'}\n"
    )
    system = skills.build_system_prompt(
        base=("You are NarAI generating J.K. Blaze's daily brief. "
              "Voice: direct, energizing, zero filler."),
    )
    result = await router.call(prompt, tier="fast", system=system)

    return {
        "brief": result.get("content", ""),
        "model": result.get("model", ""),
        "sources": {
            "tasks": tasks,
            "habits": habits,
            "pipeline": pipeline,
            "market_raw": market,
        },
    }
