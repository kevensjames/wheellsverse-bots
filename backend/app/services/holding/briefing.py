"""Morning briefing runner — report-only, audited, NEVER sends externally.

Schedulable (Celery beat) behind KAI_HOLDING_BRIEFING_ENABLED and callable on-demand by the
governed endpoint. It builds the source-backed briefing, records an audit event, and returns
it. Sending the briefing to any external recipient (email/Telegram/etc.) is a separate,
approval-gated action that is intentionally NOT implemented here.
"""
from __future__ import annotations
from app.services.holding.reports import build_morning_briefing
from app.services.holding.signals import collect_live_signals, health_block
from app.services.holding.entity_status import collect_live_entity_status
from app.services.holding import kpi_history
from app.services.holding.priorities import rank_key as _oa_key   # §22: the ONE ranker (no local map)

NO_ACTION = "No action required right now."       # §6 exact empty-queue message
TODAY_MAX = 7                                      # §5/§28 default owner-priority ceiling


def today_for_you(*, owner_actions=None, kai_completed=None, kai_working_now=None,
                  material_changes=None, risks=None, watching=None) -> dict:
    """§4/§5 Today brief — the 7 owner-facing sections, built from the reconciled owner queue + the
    cycle's real results. Extends (does NOT replace) the morning briefing. Owner actions are ranked
    and capped at 3–7 (§5/§28); an empty queue yields the exact NO_ACTION line (§6). Every Today item
    carries provenance back to its company + evidence (§34) — no orphan advice, nothing invented."""
    owner_actions = list(owner_actions or [])
    ranked = sorted(owner_actions, key=_oa_key)
    top = ranked[:TODAY_MAX]
    overflow = ranked[TODAY_MAX:]
    today = [{"company": a.get("entity") or a.get("company_id"),
              "title": a.get("title"), "action": a.get("proposed_action") or a.get("exact_owner_action"),
              "why": a.get("impact") or a.get("reason"), "kai_completed": a.get("kai_completed"),
              "source_key": a.get("source_key"), "evidence": a.get("evidence") or []} for a in top]
    return {
        "today_for_you": today or NO_ACTION,
        "today_overflow_grouped": (f"{len(overflow)} lower-priority item(s) grouped" if overflow else None),
        "kai_completed_since_last_visit": list(kai_completed or []),
        "kai_working_now": list(kai_working_now or []),
        "material_changes": list(material_changes or []),
        "risks": list(risks or []),
        "decisions_needed": [{"company": a.get("entity") or a.get("company_id"), "title": a.get("title"),
                              "action": a.get("proposed_action") or a.get("exact_owner_action")} for a in ranked],
        "watching": list(watching or []),
    }


def what_do_you_need_from_me(owner_actions=None) -> dict:
    """§7 — only current unresolved owner-gated actions; exact message when there are none."""
    actions = list(owner_actions or [])
    if not actions:
        return {"message": "Nothing currently requires your action.", "actions": []}
    ranked = sorted(actions, key=_oa_key)
    return {"message": f"{len(ranked)} item(s) need you.",
            "actions": [{"company": a.get("entity") or a.get("company_id"), "title": a.get("title"),
                         "action": a.get("proposed_action") or a.get("exact_owner_action"),
                         "source_key": a.get("source_key")} for a in ranked]}


def what_should_i_do_today(owner_actions=None) -> dict:
    """§8 — from the ACTUAL reconciled owner queue, never generic advice generated at query time."""
    brief = today_for_you(owner_actions=owner_actions)
    return {"today_for_you": brief["today_for_you"], "grouped": brief["today_overflow_grouped"]}


def run_morning_briefing(*, now_iso: str = "", fetch_health: bool = False,
                         audit=None, persist: bool = False) -> dict:
    """Build the briefing (report-only). If fetch_health, collect live self-observed signals
    (public probes) → ranked priorities + a health block. Movement is computed vs. the last
    STORED snapshot; only the scheduled daily run persists a new snapshot (persist=True) so
    history stays one-per-day and deltas stay meaningful. `audit` is optional callable(name,payload)."""
    signals = collect_live_signals() if fetch_health else None
    health = health_block(signals) if signals else None
    entity_status = collect_live_entity_status() if fetch_health else None   # live per-entity overlay
    prev = kpi_history.previous_snapshot()          # baseline for real movement (None → disclaimed)
    briefing = build_morning_briefing(health=health, signals=signals, prev_kpis=prev,
                                      entity_status=entity_status, now_iso=now_iso)
    if persist:
        kpi_history.record_snapshot(briefing["kpis"])   # fails soft (returns False) if DB unavailable
    if audit is not None:
        try:
            audit("holding.morning_briefing.generated",
                  {"entities": len(briefing["portfolio_status"]),
                   "priorities": len(briefing["todays_priorities"]) if isinstance(briefing["todays_priorities"], list) else 0,
                   "requires_confirmation": len(briefing["requires_confirmation"]),
                   "persisted": persist,
                   "delivery": "in-app only (no external send)"})
        except Exception:
            pass  # audit best-effort here; the endpoint enforces fail-closed audit separately
    return briefing
