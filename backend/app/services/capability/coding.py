"""KAI Capability Fabric — Coding Worker Router + result/verification doctrine (§10–§16).

KAI orchestrates a POOL of coding workers (Claude Code, Codex, Cline, Copilot CLI, Gemini CLI,
Windsurf, jcode, …). The user never picks one for ordinary work — the router selects the best
AVAILABLE + AUTHORIZED worker by MEASURED fit/health/cost/resources, with no hard-coded winner
(§11). Nothing here grants a worker authority: a worker's output is untrusted until reviewed +
tested (§16), every write/commit/merge/deploy is a governed action class (§14), and concurrent
writers are isolated to their own worktrees (§12/§13).

Pure stdlib; testable as a plain ``python3`` script.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .manifest import CapabilityManifest, Certification, RiskClass, ActionClass


# ── §11 routing weights (sum = 1.0), configurable ─────────────────────────────
WEIGHTS = {
    "task_fit": 0.24, "reliability": 0.16, "security": 0.12, "health": 0.14,
    "context": 0.08, "tool": 0.08, "latency": 0.06, "cost": 0.05,
    "resource": 0.04, "parallel": 0.03,
}
_CERT_SCORE = {Certification.CERTIFIED: 1.0, Certification.PARTIAL: 0.6, Certification.EXPERIMENTAL: 0.4,
               Certification.EXTERNAL_BLOCKED: 0.0, Certification.REJECTED: 0.0, Certification.UPSTREAM_UNRESOLVED: 0.1}
_RISK_SCORE = {RiskClass.LOW: 1.0, RiskClass.MEDIUM: 0.75, RiskClass.HIGH: 0.4, RiskClass.RESTRICTED: 0.1}
_REPO_CTX = {"small": 20000, "medium": 80000, "large": 200000}


@dataclass
class CodingTask:
    description: str = ""
    task_type: str = "implement"        # implement / review / test / debug / inspect
    complexity: str = "medium"          # low / medium / high
    repo_size: str = "medium"           # small / medium / large
    required_tools: list[str] = field(default_factory=list)
    required_model: str | None = None   # if set, only workers on that provider (§19 no silent switch)
    cost_budget: float | None = None
    latency_target_ms: int = 0
    parallel: bool = False              # part of a bounded-parallel fan-out
    unattended: bool = True             # true → interactive-only workers are ineligible (§7/§19)
    security_sensitive: bool = False


@dataclass
class RouterDecision:
    selected: str | None
    fallbacks: list[str]
    reason: str
    risk_class: str
    rejected: list[tuple[str, str]] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)


def _eligible(m: CapabilityManifest, task: CodingTask, resources, health: dict) -> tuple[bool, str]:
    wp = m.worker_profile
    if wp is None or not m.auto_selectable():
        return False, "not an auto-selectable coding worker"
    if task.unattended and wp.interactive_only:
        return False, "interactive-only worker cannot satisfy an unattended mission"
    if task.unattended and not wp.headless_support:
        return False, "no headless/programmatic interface for an unattended mission"
    if task.required_model and wp.model_provider and wp.model_provider != task.required_model:
        return False, f"provider {wp.model_provider} != required {task.required_model} (no silent model switch)"
    if health.get(m.id) is False:
        return False, "worker unhealthy"
    rp = m.resource_profile
    if rp.ram_mb > getattr(resources, "ram_mb", 1 << 30):
        return False, "insufficient RAM"
    if task.parallel and not wp.parallel_support:
        return False, "worker does not support safe parallel execution"
    return True, ""


def _score(m: CapabilityManifest, task: CodingTask, resources, health: dict) -> tuple[float, dict]:
    wp = m.worker_profile
    modes = set(wp.coding_modes or [])
    task_fit = 0.6 if task.task_type in modes else 0.3
    if task.complexity == "high" and wp.context_window >= 120000:
        task_fit += 0.2
    if task.complexity == "low":
        task_fit += 0.1
    tool = 1.0 if not task.required_tools else (1.0 if wp.tool_support else 0.2)
    need_ctx = _REPO_CTX.get(task.repo_size, 80000)
    context = 1.0 if wp.context_window >= need_ctx else max(0.2, wp.context_window / max(1, need_ctx))
    latency = 1.0 if not wp.cloud_execution else 0.7   # local is lower-latency by default
    resource = 0.6 if m.resource_profile.heavy else 1.0
    parallel = 1.0 if (not task.parallel or wp.parallel_support) else 0.0
    factors = {
        "task_fit": round(min(1.0, task_fit), 3),
        "reliability": _CERT_SCORE.get(m.certification, 0.4),
        "security": _RISK_SCORE.get(m.risk_class, 0.5),
        "health": 1.0 if health.get(m.id, True) else 0.0,
        "context": round(context, 3),
        "tool": tool,
        "latency": latency,
        "cost": 1.0,          # provider cost hook — flat until real cost data (§22, no blind cheapest)
        "resource": resource,
        "parallel": parallel,
    }
    return round(sum(WEIGHTS[k] * factors[k] for k in WEIGHTS), 4), factors


class CodingWorkerRouter:
    """Selects the best coding worker for a task. Lives inside the Capability Brain; never bypasses it."""

    def __init__(self, weights: dict | None = None):
        self.weights = weights or WEIGHTS

    def select(self, task: CodingTask, workers: list[CapabilityManifest], resources=None,
               health: dict | None = None) -> RouterDecision:
        health = health or {}
        resources = resources or type("R", (), {"ram_mb": 1 << 30})()
        scored: list[tuple[float, CapabilityManifest]] = []
        rejected: list[tuple[str, str]] = []
        for m in workers:
            ok, why = _eligible(m, task, resources, health)
            if not ok:
                rejected.append((m.id, why)); continue
            s, _ = _score(m, task, resources, health)
            scored.append((s, m))
        if not scored:
            return RouterDecision(None, [], "no eligible coding worker for this task", "NONE", rejected)
        scored.sort(key=lambda t: t[0], reverse=True)
        best = scored[0][1]
        fallbacks = [m.id for _, m in scored[1:4]]
        return RouterDecision(
            selected=best.id, fallbacks=fallbacks,
            reason=f"Selected {best.name} for a {task.complexity} {task.task_type} task",
            risk_class=best.risk_class.value, rejected=rejected,
            scores={m.id: s for s, m in scored},
        )


# ── §14 coding action classes ─────────────────────────────────────────────────
_CODING_ACTIONS = {
    "read": ActionClass.READ_ONLY, "inspect": ActionClass.READ_ONLY,
    "patch": ActionClass.REVERSIBLE_WRITE, "edit": ActionClass.REVERSIBLE_WRITE,
    "commit": ActionClass.HIGH_IMPACT, "push": ActionClass.HIGH_IMPACT, "pr": ActionClass.HIGH_IMPACT,
    "deploy": ActionClass.HIGH_IMPACT,
    "merge": ActionClass.DESTRUCTIVE,
    "branch_protection": ActionClass.PROHIBITED,
}


def coding_action_class(operation: str) -> ActionClass:
    """Map a coding operation to its governed action class (§14). Unknown ops fail CLOSED to HIGH_IMPACT."""
    return _CODING_ACTIONS.get((operation or "").lower().strip(), ActionClass.HIGH_IMPACT)


# ── §15 worker result contract ────────────────────────────────────────────────
@dataclass
class WorkerResult:
    task: str
    worker: str
    starting_sha: str = ""
    ending_state: str = ""
    files_changed: list[str] = field(default_factory=list)
    diff_summary: str = ""
    tests_run: int = 0
    tests_passed: int = 0
    tests_failed: int = 0
    warnings: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    confidence: float | None = None
    cost: float = 0.0
    duration_ms: int = 0
    correlation_id: str = ""
    reviewed: bool = False       # set only by a SEPARATE reviewing authority (§16), never the worker
    certified: bool = False


def assert_independent_reviewer(author: str, reviewer: str) -> None:
    """§16/§89 the ONE reviewer≠author identity rule. Shared by certify_worker_result and the holding
    challenge (§88) / review-panel (§89) seams — no second copy of the rule anywhere. Raises ValueError."""
    if not reviewer or reviewer == author:
        raise ValueError(f"no identity may review or certify its own output (§16/§89): {author!r}")


def certify_worker_result(result: WorkerResult, *, reviewed_by: str, tests_ok: bool) -> WorkerResult:
    """§16 verification doctrine: a worker never certifies itself. Certification requires an
    independent review AND passing tests — 'done' without evidence is never trusted."""
    assert_independent_reviewer(result.worker, reviewed_by)
    result.reviewed = True
    result.certified = bool(tests_ok and result.tests_failed == 0 and result.tests_run > 0)
    return result


# ── §12/§13 worktree isolation ────────────────────────────────────────────────
@dataclass
class WorktreeAssignment:
    worker_id: str
    mission_id: str
    branch: str
    worktree: str
    starting_sha: str


def assign_worktrees(worker_ids: list[str], mission_id: str, base_sha: str, base_dir: str) -> list[WorktreeAssignment]:
    """One isolated worktree/branch per WRITABLE worker (§13) — no two workers share files (§12).

    The primary certified worktree is never handed to a worker. Raises on duplicate worker ids.
    """
    if len(set(worker_ids)) != len(worker_ids):
        raise ValueError("duplicate worker id — each writable worker needs its own worktree")
    out = []
    for wid in worker_ids:
        out.append(WorktreeAssignment(
            worker_id=wid, mission_id=mission_id,
            branch=f"kai/{mission_id}/{wid}",
            worktree=f"{base_dir.rstrip('/')}/{mission_id}-{wid}",
            starting_sha=base_sha,
        ))
    return out
