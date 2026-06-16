"""Daily Brief — first NarAI feature ported into KAI through the governance
layer.

See narai/api/routes/briefing.py for the original 5-endpoint surface.
KAI's port collapses that to one well-scoped action: generate today's
operator brief from KAI's own data (signups, spend, Supreme findings,
recent errors) — no external API calls, no LLM round-trip unless asked.

Why this module first:
  - Pure-read, exercises governance's audit log without triggering the
    destructive-approval path
  - Self-contained (no DB schema changes)
  - High operator value: one click → know what happened in the empire
  - Template for the remaining NarAI modules (each gets its own
    @audited scope, each surfaces a panel in /admin)
"""
from app.services.briefing.daily_brief import generate_daily_brief

__all__ = ["generate_daily_brief"]
