"""KAI-native autonomous SWE brain — plans a fix and executes it through the
#41 disposable sandbox, producing a reviewable patch.

Deliberately NOT an LLM tool; reached only via the governed admin_swe_tasks
operator path after Gate 1 (plan approval). See
plans/PLAN-kai-autonomous-swe-agent.md §5.

MVP scope + the two design calls forced by #41's stateless sandbox:
  - plan(): wraps the operator-supplied command list into reviewable Steps. The
    LLM-backed planner (generate commands from the goal) and the OpenHands
    adapter are documented follow-ups behind THIS same AgentBrain interface.
  - execute(): #41's container is stateless per-invocation (source re-copied each
    run_task, nothing persists), so a per-step multi-container loop would lose
    edits between steps. The reviewed plan is therefore COMPOSED into a single
    bounded container run — state persists across steps, and we stay inside the
    #41 envelope unchanged. The patch is computed HOST-SIDE, read-only, by
    diffing the returned artifacts against the source (no writes back to the
    host, no git-in-container needed). The adaptive act -> observe -> re-plan
    loop (multiple stateful round-trips) needs a persistent-workspace runtime
    and is deferred to the OpenHands increment.

Hard rules enforced here: the brain touches the world ONLY via
runtime.run_task (no subprocess/os.system), and it NEVER writes a real branch —
it emits a diff and stops.
"""
from __future__ import annotations

import difflib
import os
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from app.services.governance.audit_log import record_action
from app.services.swe_runtime import policy as pol
from app.services.swe_runtime.budget import Budget, BudgetBreach
from app.services.swe_runtime.config import SandboxPolicy, default_policy
from app.services.swe_runtime.runtime import AgentRuntime, SweTask
from app.services.swe_runtime.sandbox import SandboxResult


@dataclass(slots=True)
class Mission:
    task_id: str
    source_dir: str          # must pass repo_allowed() — checked at the router
    goal: str
    commands: list[str] = field(default_factory=list)  # operator-supplied plan (MVP)
    image: str | None = None
    budget: Budget = field(default_factory=Budget.default)


@dataclass(slots=True)
class Step:
    n: int
    command: str
    rationale: str

    def as_dict(self) -> dict:
        return {"n": self.n, "command": self.command, "rationale": self.rationale}


@dataclass(slots=True)
class BrainResult:
    task_id: str
    status: str              # EXACTLY 'awaiting_push_approval' | 'failed'
    steps: list[Step]
    last: SandboxResult | None
    patch: str | None
    error: str | None = None


@runtime_checkable
class AgentBrain(Protocol):
    def plan(self, mission: Mission) -> list[Step]: ...          # LLM/heuristic only, NO exec
    def execute(self, mission: Mission, plan: list[Step],
                runtime: AgentRuntime) -> BrainResult: ...        # the bounded, sandboxed loop


class DefaultBrain:
    """KAI-native brain. plan() is operator-command-driven for the MVP; execute()
    runs the approved plan as one bounded, stateful sandbox run."""

    def plan(self, mission: Mission) -> list[Step]:
        # No sandbox execution here (LLM-only / heuristic) — the task lands in
        # awaiting_plan_approval for Gate 1 review. MVP: wrap the operator's
        # commands; the LLM planner that generates commands from the goal is the
        # documented next layer behind this interface.
        return [
            Step(n=i + 1, command=c, rationale="operator-supplied plan")
            for i, c in enumerate(mission.commands)
        ]

    def execute(self, mission: Mission, plan: list[Step],
                runtime: AgentRuntime) -> BrainResult:
        budget = mission.budget
        budget.start()
        if len(plan) > budget.max_steps:
            return self._failed(mission, plan,
                                f"plan has {len(plan)} steps > max_steps {budget.max_steps}")

        policy = self._policy_for(mission, budget)
        # Per-step: budget guard + local policy validation + audit. Execution is
        # the single composed container run below (the sandbox re-validates the
        # full script), but every planned command is individually audited here.
        for step in plan:
            try:
                budget.check()
            except BudgetBreach as b:
                return self._failed(mission, plan, f"budget: {b.reason}")
            try:
                pol.validate(step.command, policy)
            except pol.PolicyDenied as e:
                return self._failed(mission, plan, f"policy: {e}")
            record_action(
                action="swe_brain_step", scope="swe.brain.step", actor="agent",
                destructive=False, approved=True,
                inputs={"n": step.n, "command": step.command, "rationale": step.rationale},
                success=True,
            )
            budget.tick_step()

        task = SweTask(task_id=mission.task_id, source_dir=mission.source_dir,
                       command=_compose(plan), policy=policy)
        result = runtime.run_task(task)

        if result.disabled:
            return self._failed(mission, plan, "sandbox disabled", result)
        if result.error:
            return self._failed(mission, plan, result.error, result)
        if result.timed_out:
            return self._failed(mission, plan, "wall-clock timeout", result)
        if result.exit_code != 0:
            return self._failed(
                mission, plan, f"command exited {result.exit_code}: {result.stderr[:300]}", result
            )

        patch = _unified_diff(mission.source_dir, result.artifacts)
        if not patch.strip():
            return self._failed(mission, plan, "no changes produced", result)
        return BrainResult(mission.task_id, "awaiting_push_approval", plan, result, patch)

    @staticmethod
    def _policy_for(mission: Mission, budget: Budget) -> SandboxPolicy:
        p = default_policy()
        if mission.image:
            p.image = mission.image
        # Container wall-clock is bounded by the tighter of its own timeout and
        # the mission budget.
        p.timeout_seconds = min(p.timeout_seconds, budget.max_wall_seconds)
        return p

    @staticmethod
    def _failed(mission: Mission, plan: list[Step], error: str,
                result: SandboxResult | None = None) -> BrainResult:
        return BrainResult(mission.task_id, "failed", plan, result, None, error=error)


def _compose(plan: list[Step]) -> str:
    """The approved plan as one shell script. `set -e` aborts on the first
    failing command (operator can opt a step out with `... || true`)."""
    return "\n".join(["set -e", *(step.command for step in plan)])


def _unified_diff(source_dir: str, artifacts: dict[str, str]) -> str:
    """Read-only host-side diff: the sandbox's post-run /work (artifacts) against
    the original source. Handles modified + added text files; deletions and
    files past #41's artifact caps (2 MB / 500 files) are out of scope for the
    MVP. Every artifact path is realpath-contained to source_dir so a crafted
    key can never read outside it."""
    real_src = os.path.realpath(source_dir)
    chunks: list[str] = []
    for rel, new_content in sorted(artifacts.items()):
        target = os.path.realpath(os.path.join(source_dir, rel))
        if target != real_src and not target.startswith(real_src + os.sep):
            continue  # crafted key escaping source_dir — skip
        old_content = ""
        if os.path.isfile(target):
            try:
                with open(target, "r", encoding="utf-8", errors="replace") as f:
                    old_content = f.read()
            except OSError:
                continue
        if old_content == new_content:
            continue
        chunks.append("".join(difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{rel}", tofile=f"b/{rel}",
        )))
    return "\n".join(chunks)
