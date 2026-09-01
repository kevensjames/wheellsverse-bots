"""Holding CurrentPlan model + plan generation + reconciliation (§11-14, §18).

A company's plan is a set of typed PlanTasks across TODAY / 7 / 30 / 90-day horizons. Plans do NOT
contain generic startup advice (§12): every task ORIGINATES from a source-cited signal — a
MaterialChange, a registry incident/risk, or an owner blocker — and carries that evidence. Task
autonomy is the engine's A0-A5 routing label (§18/§45); it MAPS to the certified capability
ActionClass, which remains the authoritative security gate (no second policy system).

Reconciliation (§13) diffs the prior plan against freshly-derived candidates and assigns each task a
disposition (KEEP/UPDATE/COMPLETE/BLOCK/SUPERSEDE/REMOVE/ADD), deduped by source_key so a task never
proliferates cycle over cycle. Pure + deterministic; ``now`` is injected so tests are reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum, IntEnum

from app.services.capability.manifest import ActionClass


class AutonomyClass(IntEnum):
    """§18/§45 — the engine's autonomy ladder. Maps to ActionClass (the real gate) below."""
    A0_OBSERVE = 0
    A1_INTERNAL_SAFE = 1
    A2_REVERSIBLE_INTERNAL_WRITE = 2
    A3_EXTERNAL_HIGH_IMPACT = 3
    A4_FINANCIAL_CREDENTIAL_DESTRUCTIVE = 4
    A5_PROHIBITED = 5


# §18: conceptual map onto the CERTIFIED capability ActionClass — never a parallel policy system.
_TO_ACTION_CLASS = {
    AutonomyClass.A0_OBSERVE: ActionClass.READ_ONLY,
    AutonomyClass.A1_INTERNAL_SAFE: ActionClass.READ_ONLY,          # no external side effect
    AutonomyClass.A2_REVERSIBLE_INTERNAL_WRITE: ActionClass.REVERSIBLE_WRITE,
    AutonomyClass.A3_EXTERNAL_HIGH_IMPACT: ActionClass.HIGH_IMPACT,
    AutonomyClass.A4_FINANCIAL_CREDENTIAL_DESTRUCTIVE: ActionClass.FINANCIAL,
    AutonomyClass.A5_PROHIBITED: ActionClass.PROHIBITED,
}


def action_class_for(a: AutonomyClass) -> ActionClass:
    return _TO_ACTION_CLASS[a]


def auto_eligible(a: AutonomyClass) -> bool:
    """Only A0 (always) and A1 (after deterministic policy) may run without owner approval.
    A2 is per-grant (Wave 3); A3+ are owner-required. The final gate is still risk.evaluate_policy."""
    return a in (AutonomyClass.A0_OBSERVE, AutonomyClass.A1_INTERNAL_SAFE)


class Horizon(str, Enum):
    TODAY = "TODAY"; SEVEN_DAY = "7_DAY"; THIRTY_DAY = "30_DAY"; NINETY_DAY = "90_DAY"


class Assignee(str, Enum):
    KAI = "KAI"; OWNER = "OWNER"; WORKER = "WORKER"; EXTERNAL = "EXTERNAL"


class TaskStatus(str, Enum):
    PROPOSED = "PROPOSED"; ACTIVE = "ACTIVE"; BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"; SUPERSEDED = "SUPERSEDED"; REMOVED = "REMOVED"


class Disposition(str, Enum):
    KEEP = "KEEP"; UPDATE = "UPDATE"; COMPLETE = "COMPLETE"; BLOCK = "BLOCK"
    SUPERSEDE = "SUPERSEDE"; REMOVE = "REMOVE"; ADD = "ADD"


_SEV_PRIORITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "INFO": 3}


@dataclass
class PlanTask:
    task_id: str
    company_id: str
    goal: str
    reason: str
    source_key: str                       # dedup key — one task per source condition (§13)
    horizon: str = Horizon.TODAY.value
    expected_outcome: str = ""
    evidence: list = field(default_factory=list)   # the source-cited signal(s) (§12)
    autonomy: int = AutonomyClass.A0_OBSERVE.value
    assigned_to: str = Assignee.KAI.value
    dependencies: list = field(default_factory=list)
    status: str = TaskStatus.PROPOSED.value
    priority: int = 2
    created_at: str = ""
    review_at: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


# ── §12 PLAN GENERATION — from source-cited material changes, never generic advice ───────────────
# Each MaterialChange type → (autonomy, assignee, goal template). INFO/recovery changes make no work.
_CHANGE_TASKS = {
    "INCIDENT_OPENED":        (AutonomyClass.A0_OBSERVE, Assignee.KAI, "Investigate incident on {scope}"),
    "STATUS_CHANGED":         (AutonomyClass.A0_OBSERVE, Assignee.KAI, "Investigate status change on {scope}"),
    "WORKER_PLANE_DEGRADED":  (AutonomyClass.A0_OBSERVE, Assignee.KAI, "Diagnose offline worker plane"),
    "CAPABILITY_UNAVAILABLE": (AutonomyClass.A0_OBSERVE, Assignee.KAI, "Check unavailable capabilities"),
    "AUTONOMY_CHANGED":       (AutonomyClass.A0_OBSERVE, Assignee.KAI, "Review autonomy degradation"),
    "OWNER_BLOCKER_ADDED":    (AutonomyClass.A3_EXTERNAL_HIGH_IMPACT, Assignee.OWNER, "Owner decision required on {scope}"),
}


def tasks_from_changes(changes: list, *, now: str = "") -> list[PlanTask]:
    """Deterministically derive candidate PlanTasks from MaterialChange dicts. Only actionable
    (non-recovery) changes yield tasks; each task cites its change as evidence (§12). Deduped by key."""
    seen: dict[str, PlanTask] = {}
    for c in changes or []:
        ct = c.get("change_type")
        spec = _CHANGE_TASKS.get(ct)
        if not spec:
            continue                                        # recovery / INFO → nothing to do
        autonomy, assignee, goal_t = spec
        scope = c.get("scope", "holding")
        source_key = f"{ct}:{scope}"
        if source_key in seen:                              # §13: never proliferate — one task per key
            continue
        seen[source_key] = PlanTask(
            task_id=source_key, company_id=(scope if scope != "holding" else "holding"),
            goal=goal_t.format(scope=scope), reason=c.get("reason", ct), source_key=source_key,
            expected_outcome="Condition understood / resolved or escalated with evidence",
            evidence=[c], autonomy=int(autonomy), assigned_to=assignee.value,
            priority=_SEV_PRIORITY.get(c.get("severity"), 2), created_at=now, status=TaskStatus.PROPOSED.value)
    return list(seen.values())


# ── §13 PLAN RECONCILIATION — disposition per task, dedup, no proliferation ──────────────────────
@dataclass
class ReconciledTask:
    task: PlanTask
    disposition: str

    def as_dict(self) -> dict:
        return {"disposition": self.disposition, "task": self.task.as_dict()}


def reconcile_plan(prior: list[PlanTask], candidates: list[PlanTask]) -> list[ReconciledTask]:
    """Diff the prior plan against freshly-derived candidates. Deterministic dispositions:
      KEEP     prior condition still present, unchanged
      UPDATE   prior condition present but goal/reason changed
      COMPLETE prior condition no longer derived this cycle (it resolved)
      ADD      newly-derived candidate with no prior task
    Owner-assigned tasks are NOT auto-completed just because they weren't re-derived — they persist
    (BLOCK) until the owner resolves them. Deduped by source_key so nothing proliferates."""
    prior_by = {t.source_key: t for t in prior}
    cand_by = {t.source_key: t for t in candidates}
    out: list[ReconciledTask] = []
    for key, ptask in prior_by.items():
        cand = cand_by.get(key)
        if cand is not None:
            changed = (cand.goal != ptask.goal) or (cand.reason != ptask.reason)
            out.append(ReconciledTask(cand if changed else ptask,
                                      Disposition.UPDATE.value if changed else Disposition.KEEP.value))
        elif ptask.assigned_to == Assignee.OWNER.value and ptask.status not in (
                TaskStatus.COMPLETE.value, TaskStatus.REMOVED.value):
            out.append(ReconciledTask(ptask, Disposition.BLOCK.value))     # awaits the owner, keep
        else:
            done = PlanTask(**{**ptask.as_dict(), "status": TaskStatus.COMPLETE.value})
            out.append(ReconciledTask(done, Disposition.COMPLETE.value))
    for key, ctask in cand_by.items():
        if key not in prior_by:
            out.append(ReconciledTask(ctask, Disposition.ADD.value))
    return out


if __name__ == "__main__":
    from app.services.holding.test_plan import run
    run()
