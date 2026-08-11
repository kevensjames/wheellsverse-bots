"""Per-mission budget for the autonomous SWE brain — bounds one task's
autonomy so a runaway loop can never spend unbounded steps/tokens/time/money.

Locked defaults (operator decision 2026-07-21): 8 steps / 200k tokens / 900 s /
$1.00. `SpendTracker.over_daily_cap` ($2.00) remains an OUTER ceiling checked
separately; this per-mission accumulator is the real bound. `check()` is called
BEFORE each act; a breach stops the loop and is persisted as 'failed' — never
silent.

MVP note: this increment's brain runs the approved plan as a single composed
sandbox run, so max_steps bounds the plan length and max_wall maps to the
container timeout; tokens/cost stay 0 until the LLM planner / adaptive loop lands
(they are wired here so that increment needs no interface change).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetBreach(Exception):
    """A bound was exceeded. Carries the reason + a spend snapshot for audit."""

    def __init__(self, reason: str, spent: dict):
        super().__init__(reason)
        self.reason = reason
        self.spent = spent


@dataclass(slots=True)
class Budget:
    max_steps: int = 8
    max_tokens: int = 200_000
    max_wall_seconds: int = 900
    max_cost_usd: float = 1.00
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    _start: float | None = field(default=None, repr=False)

    @classmethod
    def default(cls) -> "Budget":
        return cls()

    def start(self) -> None:
        self._start = time.monotonic()

    def elapsed(self) -> float:
        return 0.0 if self._start is None else time.monotonic() - self._start

    def snapshot(self) -> dict:
        return {
            "steps": self.steps, "tokens": self.tokens,
            "cost_usd": round(self.cost_usd, 4), "elapsed_s": round(self.elapsed(), 1),
        }

    def check(self) -> None:
        """Raise BudgetBreach if any bound is exceeded. Call BEFORE each act."""
        if self.steps >= self.max_steps:
            raise BudgetBreach(f"max_steps ({self.max_steps}) reached", self.snapshot())
        if self.tokens > self.max_tokens:
            raise BudgetBreach(f"max_tokens ({self.max_tokens}) exceeded", self.snapshot())
        if self.cost_usd > self.max_cost_usd:
            raise BudgetBreach(f"max_cost_usd ({self.max_cost_usd}) exceeded", self.snapshot())
        if self._start is not None and self.elapsed() > self.max_wall_seconds:
            raise BudgetBreach(
                f"max_wall_seconds ({self.max_wall_seconds}) exceeded", self.snapshot()
            )

    def tick_step(self) -> None:
        self.steps += 1

    def charge_tokens(self, n: int) -> None:
        self.tokens += max(0, int(n))

    def charge_cost(self, usd: float) -> None:
        self.cost_usd += max(0.0, float(usd))
