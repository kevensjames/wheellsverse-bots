"""Persistent Holding cycle (Part D, §17-24) — durable, bounded, kill-switchable execution of the
already-certified pure cycle (observe→twin→reconcile→plan→resolver→work→evidence→owner queue).

Does NOT rebuild the scheduler (§17) — it wraps `autonomous_work.run_cycle` and produces a durable
CycleRecord (§18), runs on a BOUNDED per-source schedule (§19), yields 0 work on a no-change cycle
(§20), caps self-improvement attempts/day (§21), never creates new A2 grant authority (§22), reconciles
ONCE on restart without replaying missed intervals (§23), and honors the autonomy kill switch (§24).

Pure/injectable (clock + engine + records passed in) so it is a plain ``python3`` self-test; the real
cron/worker-runner (kai-watch-cron / worker_jobs) drives it in production.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from app.services.holding.autonomous_work import run_cycle, HoldingAutonomousWorkEngine


class _DisabledResult:
    """ExecutionResult-shaped 'capability execution disabled' — the emergency-brake #1 response."""
    def __init__(self, reason):
        self.status = "CAPABILITY_UNAVAILABLE"; self.evidence = {}; self.reason = reason; self.correlation_id = ""


def build_live_engine(*, autonomy_on: bool | None = None, execution_on: bool | None = None,
                      a2_on: bool | None = None, company_autonomy: dict | None = None,
                      a2_framework=None) -> HoldingAutonomousWorkEngine:
    """Construct the engine the persistent cron uses, wiring the emergency brakes from config so the
    operator can stop activity without a code rollback:
      • KAI_CAPABILITY_EXECUTION_ENABLED (brake #1) OFF → the executor returns CAPABILITY_UNAVAILABLE
        for everything (no capability runs, even certified reads).
      • HOLDING_AUTONOMY_ENABLED (brake #2) OFF → global_autonomy False → the engine executes 0
        (observation/reconciliation still runs). Independent of brake #1.
      • KAI_A2_EXECUTION_ENABLED (brake #3) OFF → the A2 prepare-only framework is NOT wired → every A2
        task stays NEEDS_CERTIFICATION (no isolated-worktree write). A2 is wired ONLY when a framework is
        INJECTED here AND brake #1 AND brake #3 are on (autonomy is the step-1 kill switch). Production
        injects no framework, so A2 never runs there regardless of the flag — prepare-only, never merge.
    Overrides are for tests; production reads app.config.settings."""
    if autonomy_on is None or execution_on is None or a2_on is None:
        try:
            from app.config import settings
            autonomy_on = bool(getattr(settings, "HOLDING_AUTONOMY_ENABLED", False)) if autonomy_on is None else autonomy_on
            execution_on = bool(getattr(settings, "KAI_CAPABILITY_EXECUTION_ENABLED", False)) if execution_on is None else execution_on
            a2_on = bool(getattr(settings, "KAI_A2_EXECUTION_ENABLED", False)) if a2_on is None else a2_on
        except Exception:
            # config unavailable → fail CLOSED (every brake engaged) — never assume-on for a brake
            autonomy_on = False if autonomy_on is None else autonomy_on
            execution_on = False if execution_on is None else execution_on
            a2_on = False if a2_on is None else a2_on
    from app.services.holding.task_resolver import (TaskCapabilityResolver, make_engine_resolver,
                                                    build_holding_executor)
    if execution_on:
        execute = build_holding_executor()
    else:
        execute = lambda cap, op, inp, *, mission_id="": _DisabledResult("capability execution disabled (brake #1)")
    # brake #3: A2 prepare-only wired only when a framework is injected AND brakes #1 and #3 are both on.
    wired_a2 = a2_framework if (a2_framework is not None and execution_on and a2_on) else None
    return HoldingAutonomousWorkEngine(execute=execute, resolver=make_engine_resolver(TaskCapabilityResolver()),
                                       a2_framework=wired_a2,
                                       global_autonomy=bool(autonomy_on), company_autonomy=company_autonomy or {})

# §19 bounded per-source-volatility intervals (seconds) — 90-day planning is NOT every 15 min.
CYCLE_INTERVALS = {
    "health": 300,           # frequent
    "deployment": 3600,      # moderate
    "repository": 3600,      # moderate
    "planning_daily": 86400, # daily strategic
    "planning_90d": 604800,  # weekly (long-horizon)
}

# §21 self-improvement is bounded and yields to real holding work.
SELF_IMPROVE_DAILY_CEILING = 3


@dataclass
class CycleRecord:
    cycle_id: str
    started_at: str
    completed_at: str
    verdict: str
    companies_reviewed: int = 0
    material_changes: int = 0
    plan_changes: int = 0
    tasks_considered: int = 0
    tasks_executed: int = 0
    tasks_failed: int = 0
    tasks_blocked: int = 0
    owner_actions_created: int = 0
    owner_actions_resolved: int = 0
    autonomy_off: int = 0
    evidence_refs: list = field(default_factory=list)
    cost: str = "UNAVAILABLE"
    status: str = "OK"

    def as_dict(self) -> dict:
        return asdict(self)


def _secs_between(a_iso: str, b_iso: str) -> float:
    from datetime import datetime
    try:
        return abs((datetime.fromisoformat(b_iso.replace("Z", "")) -
                    datetime.fromisoformat(a_iso.replace("Z", ""))).total_seconds())
    except Exception:
        return float("inf")   # unparseable → treat as long-overdue (run)


def category_due(category: str, last_run_iso: str, now_iso: str) -> bool:
    """§19: is this source category due? Never-run or unparseable → due; else interval-gated."""
    interval = CYCLE_INTERVALS.get(category, 3600)
    if not last_run_iso:
        return True
    return _secs_between(last_run_iso, now_iso) >= interval


def self_improve_allowed(attempts_today: int, *, ceiling: int = SELF_IMPROVE_DAILY_CEILING) -> bool:
    """§21: bounded daily self-improvement attempts, below critical holding work."""
    return int(attempts_today or 0) < ceiling


def restart_reconcile_count(missed_intervals: int) -> int:
    """§23: after a restart, reconcile ONCE — never replay every missed interval."""
    return 1 if (missed_intervals or 0) >= 0 else 1


def run_persistent_cycle(prev_snapshot, cur_snapshot, *, engine, cycle_id: str, now: str,
                         prior_tasks=None, companies_reviewed: int = 0, owner_writer=None) -> CycleRecord:
    """One durable cycle. The engine carries the kill switches (§24: global/company autonomy off →
    the engine returns AUTONOMY_OFF and executes 0, while observation/reconciliation still runs).
    A no-change cycle yields 0 work (§20). §F2: genuine owner-required work is persisted into the
    EXISTING owner queue for visibility (writer-only — KAI never auto-closes). owner_writer is
    injectable for tests; default upserts into proposals_store."""
    res = run_cycle(prev_snapshot, cur_snapshot, engine=engine, prior_tasks=prior_tasks, cycle_id=cycle_id,
                    now=now)
    results = res.get("results", [])
    evidence = [r.get("correlation_id") for r in results if r.get("outcome") == "EXECUTED" and r.get("correlation_id")]
    # §F2 — surface genuine owner-required work into the queue the owner views. Writer-only:
    # create-if-absent / update-safe-fields-if-open / skip-if-terminal; never resolves or closes. A
    # persistence failure is recorded (degraded status) and NEVER treated as permission to proceed —
    # owner work was already blocked (never executed) in run_cycle regardless of the write.
    owner_status = None
    try:
        from app.services.holding.owner_queue import prepare_owner_actions, persist_owner_actions
        actions = prepare_owner_actions(res.get("reconciled", []), res.get("work_results", []), now=now)
        if actions:
            pr = persist_owner_actions(actions, writer=owner_writer, now=now)
            if not pr.get("ok", True):
                owner_status = "OWNER_QUEUE_PERSIST_FAILED"
    except Exception:
        owner_status = "OWNER_QUEUE_PERSIST_FAILED"
    return CycleRecord(
        cycle_id=cycle_id, started_at=now, completed_at=now, verdict=res["verdict"],
        companies_reviewed=companies_reviewed, material_changes=res["material_changes"],
        plan_changes=sum(v for k, v in res["plan_dispositions"].items() if k != "KEEP"),  # KEEP = unchanged, not a change
        tasks_considered=len(results),
        tasks_executed=res["auto_executed"], tasks_failed=res["failed"], tasks_blocked=res["blocked"],
        owner_actions_created=res["owner_queued"], autonomy_off=res.get("autonomy_off", 0),
        evidence_refs=evidence, status=(owner_status or res["verdict"]))


# ── §30 scheduler wiring — a celery-beat entry for the bounded cycle, built by a PURE function so its ────
# darkness is unit-testable without importing celery. Gated by the DEDICATED flag KAI_HOLDING_CYCLE_ENABLED
# (default OFF → {} → no entry → the cron is DARK), decoupled from watch so enabling watch does NOT also
# schedule the read-only cycle. NO new daemon (§79): the tick runs EXACTLY ONE existing cycle
# (run_manual_cycle) on the existing celery-beat scheduler. Deploy-not-enable: the tick reuses
# build_live_engine, whose 3 fail-closed brakes stay authoritative — scheduling grants NO execution
# authority (with the brakes off, a no-change cycle yields 0 work).
HOLDING_CYCLE_BEAT_MINUTES = 15   # matches the documented watch cadence (status.cron_status)


def beat_schedule_entry(settings) -> dict:
    """Return the {name: entry} celery-beat mapping for the bounded holding cycle, or {} when the schedule
    is DARK (KAI_HOLDING_CYCLE_ENABLED off, or config unreadable → fail closed to dark). Pure: no side
    effects; celery is imported only when an entry is actually produced."""
    try:
        on = bool(getattr(settings, "KAI_HOLDING_CYCLE_ENABLED", False))
    except Exception:
        on = False
    if not on:
        return {}
    from celery.schedules import crontab
    return {"holding-cycle": {"task": "app.workers.holding_tasks.holding_cycle_tick",
                              "schedule": crontab(minute=f"*/{HOLDING_CYCLE_BEAT_MINUTES}")}}


if __name__ == "__main__":
    from app.services.holding.test_holding_cycle import run
    run()
