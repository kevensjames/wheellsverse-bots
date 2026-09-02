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

from app.services.holding.autonomous_work import run_cycle

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
                         prior_tasks=None, companies_reviewed: int = 0) -> CycleRecord:
    """One durable cycle. The engine carries the kill switches (§24: global/company autonomy off →
    the engine returns AUTONOMY_OFF and executes 0, while observation/reconciliation still runs).
    A no-change cycle yields 0 work (§20)."""
    res = run_cycle(prev_snapshot, cur_snapshot, engine=engine, prior_tasks=prior_tasks, cycle_id=cycle_id,
                    now=now)
    results = res.get("results", [])
    evidence = [r.get("correlation_id") for r in results if r.get("outcome") == "EXECUTED" and r.get("correlation_id")]
    return CycleRecord(
        cycle_id=cycle_id, started_at=now, completed_at=now, verdict=res["verdict"],
        companies_reviewed=companies_reviewed, material_changes=res["material_changes"],
        plan_changes=sum(res["plan_dispositions"].values()), tasks_considered=len(results),
        tasks_executed=res["auto_executed"], tasks_failed=res["failed"], tasks_blocked=res["blocked"],
        owner_actions_created=res["owner_queued"], autonomy_off=res.get("autonomy_off", 0),
        evidence_refs=evidence, status=res["verdict"])


if __name__ == "__main__":
    from app.services.holding.test_holding_cycle import run
    run()
