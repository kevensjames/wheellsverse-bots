"""The Factory engineering loop. run_cycle claims ONE ready task and walks it
through PIPELINE via the W-MOS action envelope. GREEN/AUTO_CAPPED stages call the
injected runner (a claude -p adapter in F2, a mock in F1); AMBER stages are queued;
RED stages are refused. Hard-gate stages (security, build) block the task — and the
PR — when the agent reports ok=False. Deterministic: all time enters via now_iso."""
from __future__ import annotations

from dataclasses import dataclass, field

from core.portfolio.actions import Action, ActionClass, dispatch
from factory import budget, project as projects, state


@dataclass(frozen=True)
class Stage:
    verb: str
    role: str
    action_class: ActionClass
    preconditions: tuple[str, ...] = ()
    hard_gate: bool = False


PIPELINE: list[Stage] = [
    Stage("architect", "architect", ActionClass.GREEN),
    Stage("implement", "engineer", ActionClass.GREEN),
    Stage("review", "reviewer", ActionClass.GREEN),
    Stage("refactor", "refactorer", ActionClass.AUTO_CAPPED, ("review_found_issues",)),
    Stage("security", "security", ActionClass.GREEN, hard_gate=True),
    Stage("test", "qa", ActionClass.GREEN),
    Stage("build", "daemon", ActionClass.GREEN, hard_gate=True),
    Stage("report", "writer", ActionClass.GREEN),
    Stage("next_tasks", "techlead", ActionClass.GREEN),
    Stage("commit_pr", "git", ActionClass.GREEN),
    Stage("deploy_staging", "devops", ActionClass.AMBER),
    Stage("deploy_prod", "devops", ActionClass.RED),
]


@dataclass
class CycleResult:
    slug: str
    cycle_id: str
    task_id: str | None
    status: str
    stages: list[dict] = field(default_factory=list)
    pr_url: str | None = None
    cost_usd: float = 0.0
    note: str = ""


def _cycle_id(slug: str, now_iso: str) -> str:
    stamp = now_iso.replace("-", "").replace(":", "").replace("T", "").rstrip("Z")
    return f"{stamp[:14]}-{slug}"


def run_cycle(slug: str, runner, *, now_iso: str, ctx: dict | None = None) -> CycleResult:
    ctx = ctx or {}
    month = now_iso[:7]
    cid = _cycle_id(slug, now_iso)

    # Stopping condition: roadmap done and nothing ready.
    if state.roadmap_complete(slug) and state.next_ready_task(slug) is None:
        projects.set_phase(slug, "done")
        return CycleResult(slug, cid, None, "done")

    task = state.next_ready_task(slug)
    if task is None:
        return CycleResult(slug, cid, None, "idle", note="no ready task")
    if not state.claim_task(slug, task["id"], cid):
        return CycleResult(slug, cid, task["id"], "idle", note="claim lost")

    cost = 0.0
    stages_out: list[dict] = []
    pr_url = None
    blocked = False

    for stage in PIPELINE:
        # Budget gate before any executable stage: if already over ceiling, stop.
        if stage.action_class in (ActionClass.GREEN, ActionClass.AUTO_CAPPED):
            if budget.would_exceed(slug, 0.0, month):
                state.release_task(slug, task["id"])
                return CycleResult(slug, cid, task["id"], "budget_queued",
                                   stages_out, cost_usd=cost, note="budget ceiling")

        action = Action(
            verb=stage.verb, agent=stage.role, action_class=stage.action_class,
            preconditions=list(stage.preconditions), business=slug,
            payload={"task": task, "cycle_id": cid},
        )
        result = dispatch(
            action, runner, ctx,
            on_queue=lambda a: state.queue_approval(a, now_iso=now_iso),
            on_audit=lambda r: state.audit(r, now_iso=now_iso),
        )
        out = result.output or {}
        step_cost = float(out.get("cost_usd", 0.0))
        if step_cost:
            cost += step_cost
            budget.record_spend(slug, step_cost, stage.verb, month)

        rec = {"verb": stage.verb, "status": result.status, "detail": result.detail}
        if result.status == "executed" and stage.verb == "commit_pr":
            pr_url = out.get("pr_url")

        adapter_failed = result.status == "failed"
        gate_failed = (
            stage.hard_gate
            and result.status == "executed"
            and not (isinstance(out, dict) and out.get("ok") is True)
        )
        if adapter_failed or gate_failed:
            rec["blocked"] = True
            stages_out.append(rec)
            blocked = True
            break
        stages_out.append(rec)

    if blocked:
        state.block_task(slug, task["id"])
        projects.bump_failure(slug)
        status = "blocked"
    else:
        state.complete_task(slug, task["id"])
        projects.reset_failure(slug)
        status = "completed"

    res = CycleResult(slug, cid, task["id"], status, stages_out, pr_url, cost)
    state.append_cycle(slug, {
        "cycle_id": cid, "slug": slug, "task_id": task["id"], "status": status,
        "stages": stages_out, "pr_url": pr_url, "cost_usd": cost, "at": now_iso,
    })
    return res
