"""infra.brain.debug — diagnostic-only helpers (no runtime modifications).

The modules here are imported by CI tests when they need to triage a
failure. None of them mutate the brain's hot path; importing this
package costs nothing and changes nothing.
"""
from .ci_self_healing import (
    STAGE_EXECUTOR,
    STAGE_PLANNER,
    STAGE_ROUTER,
    STAGE_TELEMETRY,
    STAGE_TOOL,
    STAGE_UNKNOWN,
    analyze_ci_failure,
    build_debug_trace,
    ci_wrap_run_task,
    format_report,
    print_report,
)
from .ci_auto_fix import suggest_fix
from .ci_autonomous_repair import (
    ApplyOutcome,
    DEFAULT_STABILITY_RUNS,
    DEFAULT_TEST_TIMEOUT_SEC,
    MIN_APPLY_CONFIDENCE,
    PROTECTED_BRANCHES,
    PatchValidation,
    RepairAttempt,
    RerunOutcome,
    StabilityReport,
    apply_patch_safely,
    attempt_repair,
    build_pr_bundle,
    confirm_stability,
    rerun_test,
    validate_patch,
)

__all__ = [
    # ── ci_self_healing ─────────────────────────────────────────────────
    "analyze_ci_failure",
    "build_debug_trace",
    "ci_wrap_run_task",
    "format_report",
    "print_report",
    "STAGE_PLANNER",
    "STAGE_EXECUTOR",
    "STAGE_TOOL",
    "STAGE_TELEMETRY",
    "STAGE_ROUTER",
    "STAGE_UNKNOWN",
    # ── ci_auto_fix ─────────────────────────────────────────────────────
    "suggest_fix",
    # ── ci_autonomous_repair ────────────────────────────────────────────
    "validate_patch",
    "rerun_test",
    "confirm_stability",
    "apply_patch_safely",
    "attempt_repair",
    "build_pr_bundle",
    "RerunOutcome",
    "StabilityReport",
    "PatchValidation",
    "ApplyOutcome",
    "RepairAttempt",
    "DEFAULT_STABILITY_RUNS",
    "DEFAULT_TEST_TIMEOUT_SEC",
    "MIN_APPLY_CONFIDENCE",
    "PROTECTED_BRANCHES",
]
