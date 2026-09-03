"""Holding Autonomous Work Engine + continuous cycle (§16, §19-24, §33, §55).

The OPERATOR of the loop: it consumes eligible CurrentPlan tasks and, for each A0/A1 KAI task, executes
through the certified CapabilityExecutionService (NEVER an adapter directly — §19). A task only becomes
COMPLETE with real evidence returned by the service (§22 — an agent saying "done" is not enough).
Owner-required work is filtered OUT of autonomous execution and routed to the owner queue (§24). Global
and per-company kill switches gate everything (§33): with autonomy off, autonomous execution is 0.

Injectable ``execute`` + ``resolver`` keep this a pure ``python3`` self-test with no service/DB.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

from app.services.holding.plan import (
    PlanTask, AutonomyClass, Assignee, TaskStatus, Disposition, auto_eligible,
    tasks_from_changes, reconcile_plan)
from app.services.holding.state_reconciler import reconcile_result

# Terminal work outcomes (distinct from a task's plan status).
EXECUTED = "EXECUTED"                 # ran + verified evidence → task COMPLETE
BLOCKED_CAPABILITY = "BLOCKED_CAPABILITY"
BLOCKED_WORKER = "BLOCKED_WORKER"
FAILED = "FAILED"
OWNER_QUEUED = "OWNER_QUEUED"         # owner-required — did NOT execute, goes to the owner queue
AUTONOMY_OFF = "AUTONOMY_OFF"         # kill switch — no execution
NEEDS_CERTIFICATION = "NEEDS_CERTIFICATION"   # A2+ not granted / no A2 framework wired
A2_READY_FOR_REVIEW = "A2_READY_FOR_REVIEW"   # A2 prepared an isolated change; owner reviews/merges (never KAI)
BLOCKED_POLICY = "BLOCKED_POLICY"             # §55 malformed/invalid authority value — fail closed, NEVER default to A0

# §55 failure classification (bounded, deterministic).
_FAIL_CLASS = {
    "CAPABILITY_UNAVAILABLE": "CAPABILITY_DOWN", "RATE_LIMITED": "TRANSIENT",
    "TIMEOUT": "TRANSIENT", "DENIED": "POLICY", "INPUT_REJECTED": "LOGIC",
    "OPERATION_NOT_ENABLED": "POLICY", "OPERATION_UNKNOWN": "LOGIC",
    "APPROVAL_REQUIRED": "POLICY", "FAILED": "LOGIC",
}


@dataclass
class WorkResult:
    task_id: str
    company_id: str
    autonomy: int
    assigned_to: str
    outcome: str
    task_status: str                  # resulting plan-task status
    capability_id: str = ""
    operation: str = ""
    evidence_present: bool = False
    verified: bool = False
    failure_class: str = ""
    reason: str = ""
    correlation_id: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _verify(result) -> tuple[bool, bool]:
    """§22 execution truth: (evidence_present, verified). Verified requires status OK, real evidence, AND a
    TERMINAL execution. An execution that did not complete — e.g. a timed-out suite whose evidence carries
    execution!='COMPLETED' (omitting the pass/fail result) — is never a verified completion, so it does not
    mark the task COMPLETE, even though its honest execution marker is preserved for the auditor."""
    status = getattr(result, "status", None)
    evidence = getattr(result, "evidence", None)
    present = bool(evidence)
    completed = not (isinstance(evidence, dict) and evidence.get("execution") not in (None, "COMPLETED"))
    return present, (status == "OK" and present and completed)


class HoldingAutonomousWorkEngine:
    def __init__(self, *, execute=None, resolver=None, a2_framework=None,
                 global_autonomy: bool = True, company_autonomy: dict | None = None):
        # execute(capability_id, operation, input, *, mission_id) -> ExecutionResult-like (.status/.evidence)
        self._execute = execute or self._default_execute
        # resolver(task) -> (capability_id, operation, input) | None  (None ⇒ no certified path)
        self._resolve = resolver or (lambda t: None)
        self._a2 = a2_framework          # optional A2Framework; without it, A2 tasks NEEDS_CERTIFICATION
        self._global = global_autonomy
        self._company = company_autonomy or {}

    def _default_execute(self, *a, **k):
        raise RuntimeError("no CapabilityExecutionService wired; inject execute=")

    def _company_on(self, company_id: str) -> bool:
        return self._company.get(company_id, True)     # default-on per company unless explicitly off

    def eligible(self, task: PlanTask) -> bool:
        """Auto-eligible = A0/A1 AND assigned to KAI AND kill switches allow (§18/§33)."""
        return (auto_eligible(AutonomyClass(task.autonomy))
                and task.assigned_to == Assignee.KAI.value
                and self._global and self._company_on(task.company_id))

    def run_task(self, task: PlanTask) -> WorkResult:
        def wr(outcome, status, **kw):
            return WorkResult(task.task_id, task.company_id, task.autonomy, task.assigned_to,
                              outcome, status, **kw)

        # 0. parse the autonomy class ONCE, fail CLOSED on a malformed value (§55). One corrupt task must
        #    never crash the whole cycle (it would abort every sibling), and an unparseable authority value
        #    must NEVER fall back to A0 / an inferred default — it is blocked as INVALID_ACTION_CLASS.
        try:
            ac = AutonomyClass(task.autonomy)
        except (ValueError, TypeError):
            return wr(BLOCKED_POLICY, TaskStatus.BLOCKED.value, reason="INVALID_ACTION_CLASS")
        # 1. kill switches (§33) — with autonomy off, execution is 0 (observer may still read elsewhere)
        if not self._global or not self._company_on(task.company_id):
            return wr(AUTONOMY_OFF, task.status)
        # 2. owner-required work never auto-executes — route to the owner queue (§24)
        if task.assigned_to == Assignee.OWNER.value or ac >= AutonomyClass.A3_EXTERNAL_HIGH_IMPACT:
            return wr(OWNER_QUEUED, TaskStatus.BLOCKED.value)
        # 2b. ONLY KAI-assigned work auto-executes. Worker work needs the (unwired) dispatch plane;
        #     external work is owner-gated; anything else fails closed (§18/§23 — never assume KAI).
        if task.assigned_to == Assignee.WORKER.value:
            return wr(BLOCKED_WORKER, TaskStatus.BLOCKED.value, reason="requires worker dispatch (not wired)")
        if task.assigned_to == Assignee.EXTERNAL.value:
            return wr(OWNER_QUEUED, TaskStatus.BLOCKED.value, reason="external action is owner-gated")
        if task.assigned_to != Assignee.KAI.value:
            return wr(BLOCKED_CAPABILITY, TaskStatus.BLOCKED.value, reason=f"non-KAI assignee '{task.assigned_to}'")
        # 3. A2 reversible-internal-write: route through the A2 framework if wired. A2 only PREPARES an
        #    isolated change (never merges/deploys §41); a ready result is owner-reviewed, not executed.
        if ac == AutonomyClass.A2_REVERSIBLE_INTERNAL_WRITE:
            if self._a2 is None:
                return wr(NEEDS_CERTIFICATION, TaskStatus.BLOCKED.value)
            prep = self._a2.prepare(task)
            if prep.ready_for_review:
                return wr(A2_READY_FOR_REVIEW, TaskStatus.BLOCKED.value,
                          reason=f"prepared on {prep.branch}; owner reviews/merges")
            if prep.state == "OWNER_REQUIRED":
                return wr(OWNER_QUEUED, TaskStatus.BLOCKED.value, reason=prep.reason)
            if prep.state == "NEEDS_CERTIFICATION":
                return wr(NEEDS_CERTIFICATION, TaskStatus.BLOCKED.value, reason=prep.reason)
            return wr(FAILED, TaskStatus.BLOCKED.value, failure_class="LOGIC", reason=prep.reason)
        # 4. resolve a certified capability path (§19 — never call adapters directly)
        resolved = self._resolve(task)
        if not resolved:
            return wr(BLOCKED_CAPABILITY, TaskStatus.BLOCKED.value,
                      reason="no certified capability path for this task")
        cap, op, inp = resolved
        # 5. execute through the service + verify real evidence (§22)
        try:
            result = self._execute(cap, op, inp or {}, mission_id=task.task_id)
        except Exception as e:                          # §55 — a crash is a bounded LOGIC failure, no retry loop
            return wr(FAILED, TaskStatus.BLOCKED.value, capability_id=cap, operation=op,
                      failure_class="LOGIC", reason=f"execute raised: {str(e)[:120]}")
        present, verified = _verify(result)
        status = getattr(result, "status", "FAILED")
        corr = getattr(result, "correlation_id", "")
        if verified:
            return wr(EXECUTED, TaskStatus.COMPLETE.value, capability_id=cap, operation=op,
                      evidence_present=True, verified=True, correlation_id=corr)
        # §57: an unavailable/pending capability never ran → BLOCKED_CAPABILITY, not FAILED.
        if status == "CAPABILITY_UNAVAILABLE":
            return wr(BLOCKED_CAPABILITY, TaskStatus.BLOCKED.value, capability_id=cap, operation=op,
                      failure_class="CAPABILITY_DOWN",
                      reason=getattr(result, "reason", "") or "capability unavailable", correlation_id=corr)
        return wr(FAILED, TaskStatus.BLOCKED.value, capability_id=cap, operation=op,
                  evidence_present=present, verified=False,
                  failure_class=_FAIL_CLASS.get(status, "LOGIC"),
                  reason=getattr(result, "reason", "") or f"status {status}, no verified evidence",
                  correlation_id=corr)

    def run(self, tasks: list[PlanTask]) -> list[WorkResult]:
        return [self.run_task(t) for t in (tasks or [])]


# ── §16 CONTINUOUS CYCLE — OBSERVE→NORMALIZE→RECONCILE→DETECT→PLAN→CLASSIFY→EXECUTE→VERIFY→UPDATE ──
def run_cycle(prev_snapshot: dict | None, cur_snapshot: dict, *, engine: HoldingAutonomousWorkEngine,
              prior_tasks: list[PlanTask] | None = None, cycle_id: str = "cycle", now: str = "") -> dict:
    """One bounded cycle over two twin snapshots. No hidden loop — one cycle_id, fully auditable (§53).
    A materially-unchanged cycle executes NOTHING and returns NO_MATERIAL_CHANGE (§17)."""
    recon = reconcile_result(prev_snapshot, cur_snapshot)
    candidates = tasks_from_changes(recon["changes"], now=now)
    reconciled = reconcile_plan(prior_tasks or [], candidates)
    # execute the actionable dispositions (newly ADDed or still-KEEP/UPDATE); COMPLETE/BLOCK don't run
    to_run = [rt.task for rt in reconciled
              if rt.disposition in (Disposition.ADD.value, Disposition.KEEP.value, Disposition.UPDATE.value)]
    results = engine.run(to_run)
    by = {}
    for r in results:
        by.setdefault(r.outcome, 0)
        by[r.outcome] += 1
    return {
        "cycle_id": cycle_id,
        "verdict": recon["verdict"],
        "materiality_version": recon["materiality_version"],
        "material_changes": len(recon["changes"]),
        "plan_dispositions": {d: sum(1 for rt in reconciled if rt.disposition == d)
                              for d in sorted({rt.disposition for rt in reconciled})},   # sorted: deterministic audit
        "auto_executed": by.get(EXECUTED, 0),
        "owner_queued": by.get(OWNER_QUEUED, 0),
        "blocked": by.get(BLOCKED_CAPABILITY, 0) + by.get(BLOCKED_WORKER, 0)
                   + by.get(NEEDS_CERTIFICATION, 0) + by.get(BLOCKED_POLICY, 0),
        "failed": by.get(FAILED, 0),
        "autonomy_off": by.get(AUTONOMY_OFF, 0),
        "results": [r.as_dict() for r in results],
        # in-process handles for the caller's owner-queue writer (§F2): the full reconciled plan (incl.
        # BLOCK-persisted owner tasks) + the WorkResult objects. Not serialized — run_persistent_cycle
        # consumes them to prepare owner actions, then builds the CycleRecord (which omits them).
        "reconciled": reconciled,
        "work_results": results,
    }


if __name__ == "__main__":
    from app.services.holding.test_autonomous_work import run
    run()
