"""CI autopilot runner — the policy layer that drives the diagnostic stack.

Composes the three diagnostic layers + the autonomous repair driver and
produces a single, machine-readable decision the GitHub Actions workflow
can branch on.

Pipeline::

    test_report.json
        ↓
    analyze_ci_failure()              (ci_self_healing)
        ↓
    suggest_fix()                     (ci_auto_fix)
        ↓
    decide_action(analysis, fix)      (this module)
        ↓                ↓                  ↓
    open_pr        diagnostics_only    human_review
        ↓
    attempt_repair(apply_patch=True)  (ci_autonomous_repair)

Decision matrix
---------------

  CASE 1  open_pr            confidence ≥ 0.8  AND  risk == "low"
                             AND stage NOT in UNSAFE_STAGES
  CASE 3  human_review       stage in {planner, telemetry, unknown}
  CASE 2  diagnostics_only   anything else (default-safe)

Safety rules baked in
---------------------
  * No auto-merge anywhere — only PR creation.
  * No push to ``main`` / ``master`` (enforced inside attempt_repair via
    PROTECTED_BRANCHES; the autopilot does not override).
  * No patch application unless the test currently fails AND every
    safety guard in apply_patch_safely passes.
  * Human override is always possible: re-run the workflow with a
    different mode, or close/reject the PR.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Optional

from .ci_auto_fix import suggest_fix
from .ci_autonomous_repair import attempt_repair
from .ci_self_healing import (
    STAGE_PLANNER,
    STAGE_TELEMETRY,
    STAGE_UNKNOWN,
    analyze_ci_failure,
)


# ── Decision constants ─────────────────────────────────────────────────────


ACTION_OPEN_PR: str = "open_pr"
ACTION_DIAGNOSTICS_ONLY: str = "diagnostics_only"
ACTION_HUMAN_REVIEW: str = "human_review"

_VALID_ACTIONS = frozenset({
    ACTION_OPEN_PR, ACTION_DIAGNOSTICS_ONLY, ACTION_HUMAN_REVIEW,
})


# Stages where applying any auto-fix is risky enough that we always
# defer to a human reviewer regardless of confidence.
UNSAFE_STAGES: frozenset[str] = frozenset({
    STAGE_PLANNER, STAGE_TELEMETRY, STAGE_UNKNOWN,
})


MIN_AUTO_PR_CONFIDENCE: float = 0.8


# Modes — the runner's outermost behavior switch. ``ci`` enforces the full
# matrix; ``dry-run`` and ``diagnose`` never apply patches regardless of
# confidence (safe to run from a developer laptop or a feature branch).

MODE_CI: str = "ci"
MODE_DRY_RUN: str = "dry-run"
MODE_DIAGNOSE: str = "diagnose"

_VALID_MODES = (MODE_CI, MODE_DRY_RUN, MODE_DIAGNOSE)


# ── Logging ────────────────────────────────────────────────────────────────


_log = logging.getLogger("infra.brain.debug.autopilot")


def _setup_logging() -> None:
    if _log.handlers:
        return
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    _log.addHandler(h)
    _log.setLevel(logging.INFO)


# ── Test-report → diagnostic-input adapters ────────────────────────────────


class _SyntheticBrainTask:
    """Minimal duck-typed BrainTask reconstruction from a JSON report.

    ``analyze_ci_failure`` reads attributes ``state``, ``result``, ``plan``,
    ``id``, ``input`` from whatever it gets — a real BrainTask or this
    stand-in. Keeping the contract narrow means this stand-in can ride on
    any event-only or result-only test report.
    """

    __slots__ = ("id", "input", "state", "plan", "result")

    def __init__(self, data: dict):
        d = data or {}
        self.id = d.get("id") or d.get("task_id") or "?"
        self.input = d.get("input") or ""
        self.state = d.get("state")
        self.plan = d.get("plan") if isinstance(d.get("plan"), dict) else None
        self.result = d.get("result") if isinstance(d.get("result"), dict) else None


def _reconstruct_exception(exc_data: Any) -> Optional[BaseException]:
    """Turn ``{"type": "RuntimeError", "message": "boom"}`` back into an
    object whose ``type(...).__name__`` and ``str(...)`` look the same.
    The diagnostic layer only inspects those, so a synthetic class is safe.
    """
    if not isinstance(exc_data, dict):
        return None
    name = str(exc_data.get("type") or "Exception")
    msg = str(exc_data.get("message") or "")
    # Sanitize: only allow [A-Za-z_][A-Za-z0-9_]* as a class name.
    safe = "".join(ch for ch in name if ch.isalnum() or ch == "_") or "Exception"
    cls = type(safe, (Exception,), {})
    try:
        return cls(msg)
    except Exception:
        return Exception(f"{safe}: {msg}")


def load_test_report(path: Path) -> dict:
    """Load a CI-side failure report.

    Accepted shape (every field is optional but at least one of
    ``result``, ``events``, or ``exception`` should be present)::

        {
          "test_node_id": "infra/brain/tests/test_x.py::test_y",
          "result":   { ... BrainTask-like ... }   |  null,
          "events":   [ { "event_type": "...", ... }, ... ],
          "exception": {"type": "...", "message": "..."}  |  null,
          "input":    "the user prompt"
        }
    """
    if not path.exists():
        raise FileNotFoundError(f"test report not found: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"test report is not valid JSON: {e}") from e


# ── Decision logic ─────────────────────────────────────────────────────────


def decide_action(analysis: dict, fix: dict) -> tuple[str, str]:
    """Pure-function decision matrix. Returns ``(action, reason)``.

    The function never calls anything that touches disk or the network —
    it is a deterministic predicate over two dicts so it can be unit-tested
    in isolation.
    """
    stage = (analysis or {}).get("stage") or STAGE_UNKNOWN
    confidence = float((fix or {}).get("confidence") or 0.0)
    risk = (fix or {}).get("risk_level") or "high"

    # CASE 3 — unsafe stage trumps everything (planner errors, telemetry
    # corruption, or unclassified failures need human eyes).
    if stage in UNSAFE_STAGES:
        return (
            ACTION_HUMAN_REVIEW,
            f"stage={stage!r} requires human review",
        )

    # CASE 1 — confident + low-risk fix → open a PR (still requires human
    # approval to merge; we never auto-merge).
    if confidence >= MIN_AUTO_PR_CONFIDENCE and risk == "low":
        return (
            ACTION_OPEN_PR,
            f"confidence={confidence:.2f} >= {MIN_AUTO_PR_CONFIDENCE}, "
            f"risk={risk}, stage={stage}",
        )

    # CASE 2 — anything else: bundle the diagnostics, do not mutate the repo.
    return (
        ACTION_DIAGNOSTICS_ONLY,
        f"confidence={confidence:.2f}, risk={risk}, stage={stage}",
    )


# ── Top-level autopilot ────────────────────────────────────────────────────


def run_autopilot(
    test_report: dict,
    *,
    mode: str = MODE_DRY_RUN,
    bundle_dir: Path,
    repo_root: Optional[Path] = None,
    stability_runs: int = 3,
    repair_memory: Optional[Any] = None,
) -> dict:
    """Drive the full diagnostic + repair pipeline. Returns a decision dict.

    Parameters
    ----------
    test_report:
        Dict loaded by :func:`load_test_report`. Provides whichever of
        ``result``, ``events``, ``exception``, ``test_node_id``, ``input``
        the failing test was able to capture.
    mode:
        One of ``ci`` / ``dry-run`` / ``diagnose``. Only ``ci`` is allowed
        to apply patches. Other modes ALWAYS pass ``apply_patch=False``.
    bundle_dir:
        Where to write PR-ready bundles.
    repo_root, stability_runs:
        Forwarded to :func:`attempt_repair`.
    repair_memory:
        Optional :class:`infra.brain.learning.RepairMemory` instance.
        When supplied (the CLI auto-instantiates one), every repair
        attempt is recorded to disk and the apply gate consults the
        memory's safety score before mutating anything. ``None``
        preserves pre-learning behaviour exactly.
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {_VALID_MODES}")

    test_node_id = test_report.get("test_node_id") or "?"
    run_result = (
        _SyntheticBrainTask(test_report["result"])
        if isinstance(test_report.get("result"), dict)
        else None
    )
    events = test_report.get("events") or []
    exception = _reconstruct_exception(test_report.get("exception"))

    analysis = analyze_ci_failure(run_result, events, exception)
    fix = suggest_fix(analysis)
    action, reason = decide_action(analysis, fix)

    _log.info("autopilot mode=%s test=%s", mode, test_node_id)
    _log.info("autopilot stage=%s reason=%s",
              analysis.get("stage"), analysis.get("reason"))
    _log.info("autopilot fix_type=%s confidence=%.2f risk=%s",
              fix.get("fix_type"), float(fix.get("confidence") or 0.0),
              fix.get("risk_level"))
    _log.info("autopilot decision=%s (%s)", action, reason)

    apply_patch = (mode == MODE_CI and action == ACTION_OPEN_PR)

    if mode == MODE_DIAGNOSE:
        # Diagnose mode skips the rerun + apply pipeline entirely;
        # produces a bundle with the analysis + fix but no live test runs.
        bundle_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = _write_lightweight_bundle(
            bundle_dir=bundle_dir,
            test_node_id=test_node_id,
            analysis=analysis,
            fix=fix,
            decision_action=action,
            decision_reason=reason,
        )
        return _decision(
            action=action, reason=reason,
            analysis=analysis, fix=fix,
            bundle_path=str(bundle_path),
            patch_applied=False,
            stability_passed=None,
            test_node_id=test_node_id,
        )

    # MODE_CI or MODE_DRY_RUN — both call attempt_repair, but only CI mode
    # ever passes apply_patch=True. The repair_memory (when provided)
    # gates apply_patch_safely AND records the outcome for future scoring.
    attempt = attempt_repair(
        test_node_id=test_node_id,
        analysis=analysis,
        fix=fix,
        apply_patch=apply_patch,
        stability_runs=stability_runs,
        repo_root=repo_root,
        bundle_dir=bundle_dir,
        repair_memory=repair_memory,
    )

    # If we tried to apply but the post-repair runs were not stable,
    # attempt_repair has already reverted and set patch_applied=False.
    # In that case downgrade the action so the workflow uploads
    # diagnostics rather than opening a misleading PR.
    if action == ACTION_OPEN_PR and not attempt.patch_applied:
        _log.warning(
            "downgrading open_pr → diagnostics_only "
            "(attempt.patch_applied=False, decision=%r)",
            attempt.decision,
        )
        action = ACTION_DIAGNOSTICS_ONLY
        reason = f"repair did not stabilise: {attempt.decision}"

    stability_passed: Optional[bool] = None
    if attempt.post_repair is not None:
        stability_passed = attempt.post_repair.all_passed and attempt.post_repair.stable

    return _decision(
        action=action,
        reason=reason,
        analysis=analysis,
        fix=fix,
        bundle_path=attempt.bundle_path,
        patch_applied=attempt.patch_applied,
        stability_passed=stability_passed,
        test_node_id=test_node_id,
    )


# ── Bundle / decision writers ──────────────────────────────────────────────


def _write_lightweight_bundle(
    *,
    bundle_dir: Path,
    test_node_id: str,
    analysis: dict,
    fix: dict,
    decision_action: str,
    decision_reason: str,
) -> Path:
    """Bundle for ``--mode diagnose`` — no live test runs included."""
    import re
    import time
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", test_node_id)[:80]
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    out = bundle_dir / f"diagnose_{stamp}_{safe}"
    out.mkdir(parents=True, exist_ok=False)
    (out / "ANALYSIS.json").write_text(json.dumps(analysis, indent=2, default=str))
    (out / "FIX.json").write_text(json.dumps(fix, indent=2, default=str))
    (out / "DECISION.txt").write_text(
        f"action: {decision_action}\nreason: {decision_reason}\n"
        f"test:   {test_node_id}\n"
    )
    return out


def _decision(
    *,
    action: str,
    reason: str,
    analysis: dict,
    fix: dict,
    bundle_path: Optional[str],
    patch_applied: bool,
    stability_passed: Optional[bool],
    test_node_id: str,
) -> dict:
    """Compose the decision dict that the workflow consumes."""
    if action not in _VALID_ACTIONS:
        action = ACTION_DIAGNOSTICS_ONLY
    return {
        "action": action,
        "reason": reason,
        "confidence": float((fix or {}).get("confidence") or 0.0),
        "stage": (analysis or {}).get("stage") or STAGE_UNKNOWN,
        "fix_type": (fix or {}).get("fix_type") or "logic",
        "risk_level": (fix or {}).get("risk_level") or "high",
        "test_node_id": test_node_id,
        "patch_applied": bool(patch_applied),
        "stability_passed": stability_passed,
        "bundle_path": bundle_path or "",
        "requires_human_review": action == ACTION_HUMAN_REVIEW,
    }


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli(argv: Optional[list[str]] = None) -> int:
    _setup_logging()
    p = argparse.ArgumentParser(
        prog="ci_autopilot_runner",
        description="Brain CI autopilot — diagnose + (optionally) repair.",
    )
    p.add_argument(
        "--test-report", type=Path, required=True,
        help="JSON file produced by the failing test capturing its state.",
    )
    p.add_argument(
        "--mode", choices=_VALID_MODES, default=MODE_DRY_RUN,
        help="ci=apply when safe; dry-run=never apply; diagnose=skip reruns.",
    )
    p.add_argument(
        "--bundle-dir", type=Path, default=Path(".ci/repair-bundles"),
        help="Directory to write the PR-ready bundle into.",
    )
    p.add_argument(
        "--decision-file", type=Path, default=Path(".ci/decision.json"),
        help="Where to write the decision JSON for downstream workflow steps.",
    )
    p.add_argument(
        "--stability-runs", type=int, default=3,
        help="How many post-repair reruns to confirm stability.",
    )
    p.add_argument(
        "--memory-path", type=Path, default=None,
        help="Path to the repair-memory JSONL (default: .ci/repair-memory.jsonl).",
    )
    p.add_argument(
        "--no-memory", action="store_true",
        help="Disable the learning layer entirely (legacy behaviour).",
    )
    args = p.parse_args(argv)

    args.bundle_dir.mkdir(parents=True, exist_ok=True)
    args.decision_file.parent.mkdir(parents=True, exist_ok=True)

    # Auto-instantiate RepairMemory unless explicitly disabled. Cold-start
    # is safe — without prior data the memory layer never blocks an apply.
    repair_memory = None
    if not args.no_memory:
        try:
            from ..learning import RepairMemory
            repair_memory = RepairMemory(path=args.memory_path)
        except Exception as e:
            _log.warning("could not instantiate RepairMemory; "
                         "continuing without learning: %s", e)

    # Load — never crash the workflow on a missing/malformed report.
    try:
        report = load_test_report(args.test_report)
    except (FileNotFoundError, ValueError) as e:
        _log.error("could not load test report: %s", e)
        decision = {
            "action": ACTION_HUMAN_REVIEW,
            "reason": f"could_not_load_test_report: {e}",
            "confidence": 0.0,
            "stage": STAGE_UNKNOWN,
            "fix_type": "logic",
            "risk_level": "high",
            "test_node_id": "?",
            "patch_applied": False,
            "stability_passed": None,
            "bundle_path": "",
            "requires_human_review": True,
        }
        args.decision_file.write_text(json.dumps(decision, indent=2))
        print(json.dumps(decision, indent=2))
        return 0  # always 0 — the workflow consumes the decision JSON

    decision = run_autopilot(
        report,
        mode=args.mode,
        bundle_dir=args.bundle_dir,
        stability_runs=args.stability_runs,
        repair_memory=repair_memory,
    )
    args.decision_file.write_text(json.dumps(decision, indent=2))
    print(json.dumps(decision, indent=2))

    # End-of-run intelligence summary — gives operators the
    # adaptive-system snapshot without parsing the JSONL by hand.
    if repair_memory is not None:
        try:
            if hasattr(repair_memory, "print_intelligence_summary"):
                repair_memory.print_intelligence_summary()
        except Exception as e:
            _log.warning("could not print intelligence summary: %s", e)

    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    # Decision values
    "ACTION_OPEN_PR", "ACTION_DIAGNOSTICS_ONLY", "ACTION_HUMAN_REVIEW",
    "UNSAFE_STAGES", "MIN_AUTO_PR_CONFIDENCE",
    # Modes
    "MODE_CI", "MODE_DRY_RUN", "MODE_DIAGNOSE",
    # Public API
    "decide_action", "run_autopilot", "load_test_report",
]
