"""Single-operator vs multi-user gate for the companion sidecars.

The eq (mood), relationship, twin, and persona subsystems model ONE operator and
persist to global, UNtenanted SQLite stores (no user_id). They are safe for a
personal single-operator KAI, but a hard tenant-isolation + GDPR hazard in a
multi-user SaaS:

  - user A's messages would shape a shared mood/relationship that colors user B's
    chat (the per-message hook `_eq_analyze_and_record` has no user_id to key on);
  - `eq.record_mood` writes raw message excerpts to an admin-readable eq.db with
    no user_id — so it can't be isolated per tenant or deleted on account
    deletion (GDPR Art. 17).

So they activate ONLY when the operator explicitly declares a single-operator
install (KAI_SINGLE_OPERATOR_MODE=1). In the default multi-user mode they stay
off regardless of the KAI_SCOPE_* scopes — even if a scope is fat-fingered on,
no per-user PII lands in an untenanted store. Retrofitting real per-user tenancy
into these subsystems is the eventual path; this guard makes multi-user safe now.
"""
from __future__ import annotations

import os


def single_operator_mode() -> bool:
    return (os.environ.get("KAI_SINGLE_OPERATOR_MODE") or "").strip().lower() in (
        "1", "true", "yes", "on")
