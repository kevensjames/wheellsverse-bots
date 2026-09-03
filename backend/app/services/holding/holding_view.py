"""Holding UI view-model (Part E, §25-30) — the read-only data contract the existing /admin/holding
page renders. It does NOT create a new dashboard; it assembles the six sections from the already-built
twin + owner queue + cycle record + OperationalSelfModel + self-improvement candidates.

Section order puts TODAY FOR YOU first (§25 — more important than telemetry). The Operational Self Model
section is labelled operationally and NEVER claims sentience/consciousness (§29). All fields are sourced;
nothing is invented. Pure/injectable so it is a plain ``python3`` self-test; the HTML/route wiring is the
remaining frontend step.
"""
from __future__ import annotations

from app.services.holding.briefing import today_for_you, NO_ACTION


def build_holding_view(*, twin_snapshot: dict | None = None, self_model: dict | None = None,
                       owner_actions=None, cycle_record: dict | None = None, kai_work=None,
                       self_improvements=None, improvement_watch: dict | None = None,
                       deployment: dict | None = None) -> dict:
    """Assemble the /admin/holding view model. Every section is derived from real state (§34: no orphan
    advice). owner_actions are proposal-shaped dicts; kai_work items are work-result-shaped dicts.
    improvement_watch is the DETECT_ONLY snapshot (detection candidates); it is DETECTION only — each row
    shows PREPARATION NOT AUTHORIZED unless mode is PREPARE_ALLOWED (never 'fixing')."""
    twin = twin_snapshot or {}
    sm = self_model or {}
    owner_actions = list(owner_actions or [])
    work = list(kai_work or [])
    sis = list(self_improvements or [])
    iw = improvement_watch or {}

    # §25 TODAY FOR YOU first (reuses the certified briefing builder)
    brief = today_for_you(owner_actions=owner_actions,
                          kai_completed=[w for w in work if w.get("outcome") == "EXECUTED"],
                          kai_working_now=[w for w in work if w.get("status") == "ACTIVE"],
                          material_changes=(cycle_record or {}).get("material_changes_list", []),
                          risks=[r for c in twin.get("companies", []) for r in (c.get("risks") or [])])

    def _bucket(outcome_or_status):
        return [{"company": w.get("company_id"), "task": w.get("task_id"),
                 "capability": w.get("capability_id"), "status": w.get("outcome") or w.get("status"),
                 "reason": w.get("reason", "")} for w in work
                if (w.get("outcome") == outcome_or_status or w.get("status") == outcome_or_status)]

    return {
        # §25
        "today_for_you": brief["today_for_you"],
        "today_overflow": brief.get("today_overflow_grouped"),
        # §26 KAI working
        "kai_working": {
            "currently_working": _bucket("ACTIVE"),
            "ready_for_review": _bucket("A2_READY_FOR_REVIEW"),
            "blocked": _bucket("BLOCKED_CAPABILITY") + _bucket("BLOCKED_WORKER"),
            "owner_queued": _bucket("OWNER_QUEUED"),
        },
        # §27 self-improvement (READY_FOR_REVIEW only; no private reasoning exposed)
        "self_improvement_ready": [{"problem": s.get("problem"), "evidence": s.get("evidence"),
                                    "files_changed": s.get("files_changed"),
                                    "tests_before": s.get("tests_before"), "tests_after": s.get("tests_after"),
                                    "independent_review": s.get("security_review"),
                                    "rollback": s.get("rollback"), "owner_action": s.get("owner_action")}
                                   for s in sis if s.get("status") == "READY_FOR_REVIEW"],   # READY only (§27)
        # KAI IMPROVEMENT WATCH (DETECT_ONLY) — detection only; never "fixing". action reflects the mode.
        "improvement_watch": {
            "mode": iw.get("mode", "OFF"),
            "last_run": iw.get("last_run"),
            "action": ("PREPARATION NOT AUTHORIZED" if iw.get("mode") != "PREPARE_ALLOWED" else "PREPARE_ALLOWED"),
            "candidates": [{"signature": c.get("signature"), "problem": c.get("problem"),
                            "source": c.get("source", "NATURAL"), "signal_type": c.get("signal_type"),
                            "confirmed": c.get("confirmed"), "severity": c.get("severity"),
                            "evidence": c.get("evidence")}
                           for c in (iw.get("candidates") or [])],
        },
        # DEPLOYMENT TRUTH (§7-10) — running SHA + drift + feature registry (deployed vs ENABLED)
        "deployment": deployment or {},
        # §28 company cards
        "company_cards": [{"company_id": c.get("company_id"), "name": c.get("name"),
                           "current_goal": c.get("current_goal"), "status": c.get("status"),
                           "latest_material_change": (c.get("recent_material_changes") or [None])[-1]
                           if c.get("recent_material_changes") else None,
                           "owner_blocker": bool(c.get("owner_actions_required")),
                           "plan_freshness": c.get("source_freshness")}
                          for c in twin.get("companies", [])],
        # §62 Operational Self Model — FULL field set (labelled; never sentient). Every value is taken
        # straight from the self-model snapshot (REAL/DERIVED/UNAVAILABLE); the panel renders it verbatim.
        "operational_self_model": {
            "label": "Operational Self Model",
            "identity": sm.get("identity", "KAI"), "role": sm.get("system_role"),
            "software_version": sm.get("software_version"),
            "production_sha": sm.get("production_sha"), "staging_sha": sm.get("staging_sha"),
            "environment": sm.get("environment"), "runtime": sm.get("runtime"),
            "model": sm.get("model"), "model_provider": sm.get("model_provider"),
            "model_latency_ms": sm.get("model_latency_ms"),
            "autonomy_posture": twin.get("autonomy_overall"),  # §57 real health score is a later phase
            "autonomy_class": sm.get("autonomy_class"),
            "current_attention": sm.get("current_attention"),
            "current_mission": (cycle_record or {}).get("cycle_id"),
            "capabilities_ready": sm.get("available_capability_count"),
            "capability_catalog_total": sm.get("capability_catalog_total"),
            "workers_online": sm.get("workers_online"), "workers_known": sm.get("workers_known"),
            "last_holding_cycle": (cycle_record or {}).get("completed_at"),
            "last_verified": sm.get("last_verified"),
            "owner_required_count": sm.get("owner_required_action_count"),
            "limitations": list(sm.get("known_limitations", [])),   # LIVE-DERIVED (§63/§99)
            "claims_consciousness": False,   # invariant (§29/§141) — never sentient
        },
        # §30 autonomy (backend authoritative)
        "autonomy": {
            "global": twin.get("autonomy_overall"), "money_mode": twin.get("money_mode", "MOCK"),
            "a0_a1": "auto-eligible", "a2_certified_grants": ["SELF_IMPROVEMENT_NONPROD_CODE_FIX_V1"],
            "last_cycle": (cycle_record or {}).get("completed_at"),
            "last_cycle_verdict": (cycle_record or {}).get("verdict"),
        },
    }


if __name__ == "__main__":
    from app.services.holding.test_holding_view import run
    run()
