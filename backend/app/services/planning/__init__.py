"""KAI long-term planning.

Decompose a goal into an ordered list of steps (with optional branch
directives), execute one step at a time, and propose a revision when a step
fails. Sidecar SQLite storage (data/planning/planning.db) — no Supabase
migration risk. Scope-gated via KAI_SCOPE_PLANNING (default-off).

Public API (mirrors the other sidecar features' __init__ re-exports):
  storage     — Plan/Step/StepRun + CRUD
  planner     — generate_plan / propose_steps (goal → steps via the LLM)
  executor    — execute_next (run one step, advance state) + make_llm_runner
  revision    — propose_revision (diagnose a failure, propose revised steps)
  remediation — propose_remediations (detected issues → draft plans; proactive)
"""
from app.services.planning.storage import (  # noqa: F401
    PLAN_STATUSES,
    STEP_KINDS,
    STEP_STATUSES,
    Plan,
    Step,
    StepRun,
    add_step,
    add_step_run,
    create_plan,
    get_plan,
    get_step,
    get_step_by_seq,
    list_plans,
    list_step_runs,
    next_pending_step,
    replace_steps,
    set_step_status,
    stats,
    update_plan_status,
    update_step,
)
from app.services.planning.planner import (  # noqa: F401
    generate_plan,
    parse_steps_json,
    propose_steps,
)
from app.services.planning.executor import (  # noqa: F401
    ExecResult,
    RunOutcome,
    execute_next,
    make_llm_runner,
    parse_directive,
)
from app.services.planning.revision import propose_revision  # noqa: F401
from app.services.planning.remediation import propose_remediations  # noqa: F401

__all__ = [
    "PLAN_STATUSES",
    "STEP_KINDS",
    "STEP_STATUSES",
    "Plan",
    "Step",
    "StepRun",
    "ExecResult",
    "RunOutcome",
    "add_step",
    "add_step_run",
    "create_plan",
    "execute_next",
    "generate_plan",
    "get_plan",
    "get_step",
    "get_step_by_seq",
    "list_plans",
    "list_step_runs",
    "make_llm_runner",
    "next_pending_step",
    "parse_directive",
    "parse_steps_json",
    "propose_remediations",
    "propose_revision",
    "propose_steps",
    "replace_steps",
    "set_step_status",
    "stats",
    "update_plan_status",
    "update_step",
]
