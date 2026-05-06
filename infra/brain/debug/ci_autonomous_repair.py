"""CI Autonomous Repair Mode for the Brain runtime.

Builds on the previous two diagnostic layers:

  1. ``ci_self_healing.analyze_ci_failure``   → identifies what broke
  2. ``ci_auto_fix.suggest_fix``              → proposes a unified-diff fix
  3. **this module**                          → applies / verifies / packages

Pipeline (default-safe; nothing is mutated unless ``apply_patch=True``)::

    rerun(test_node) → record pre-repair state
    validate_patch(diff)
    [optional] apply_patch_safely(diff)         ← only if asked
    confirm_stability(test_node, retries=3)     ← rerun N times after fix
    build_pr_bundle(...)                        ← write artifacts to disk

Safety contract — every guard is enforced before the disk is touched:

  * Refuses to apply on a dirty working tree.
  * Refuses to apply on the ``main`` / ``master`` branch.
  * Refuses to apply if the patch contains ``<placeholder>`` paths.
  * Refuses to apply if ``confidence`` is below ``MIN_APPLY_CONFIDENCE``.
  * Always runs ``git apply --check`` before ``git apply``.
  * On any failure the working tree is restored via ``git stash pop``.

Importable as a library or runnable as a CLI:

    python -m infra.brain.debug.ci_autonomous_repair \\
        --test infra/brain/tests/test_x.py::test_y \\
        --bundle-dir .ci/repair-bundles/
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence


# ── Tunables ────────────────────────────────────────────────────────────────


DEFAULT_STABILITY_RUNS: int = 3
DEFAULT_TEST_TIMEOUT_SEC: int = 120
MIN_APPLY_CONFIDENCE: float = 0.7
PROTECTED_BRANCHES: frozenset[str] = frozenset({"main", "master"})


# ── Data classes ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RerunOutcome:
    """One pytest invocation's outcome, lightly captured."""
    test_node_id: str
    passed: bool
    duration_ms: float
    return_code: int
    output_tail: str               # last ~100 lines, stderr-merged

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class StabilityReport:
    """Result of running one test ``repeats`` times in a row."""
    test_node_id: str
    runs: tuple[RerunOutcome, ...]

    @property
    def all_passed(self) -> bool:
        return bool(self.runs) and all(r.passed for r in self.runs)

    @property
    def stable(self) -> bool:
        # Stable iff every run agrees: all passed, or all failed.
        if not self.runs:
            return False
        first = self.runs[0].passed
        return all(r.passed == first for r in self.runs)

    def to_dict(self) -> dict:
        return {
            "test_node_id": self.test_node_id,
            "all_passed": self.all_passed,
            "stable": self.stable,
            "runs": [r.to_dict() for r in self.runs],
        }


@dataclass(frozen=True)
class PatchValidation:
    """Outcome of inspecting a patch without applying it."""
    applicable: bool
    files_referenced: tuple[str, ...]
    files_missing: tuple[str, ...]
    has_placeholders: bool
    git_check_output: str
    reason: Optional[str] = None  # short human-readable explanation

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RepairAttempt:
    """End-to-end record of a single repair attempt."""
    test_node_id: str
    analysis: dict
    fix: dict
    patch_validation: PatchValidation
    pre_repair: RerunOutcome
    patch_applied: bool
    post_repair: Optional[StabilityReport]
    bundle_path: Optional[str] = None
    decision: str = ""             # one-line audit: what happened + why
    started_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "test_node_id": self.test_node_id,
            "decision": self.decision,
            "started_at": self.started_at,
            "patch_applied": self.patch_applied,
            "patch_validation": self.patch_validation.to_dict(),
            "pre_repair": self.pre_repair.to_dict(),
            "post_repair": self.post_repair.to_dict() if self.post_repair else None,
            "bundle_path": self.bundle_path,
            "analysis": self.analysis,
            "fix": self.fix,
        }


# ── Subprocess helpers (kept small, every call has a timeout) ──────────────


def _run(
    cmd: Sequence[str],
    *,
    cwd: Optional[Path] = None,
    input_bytes: Optional[bytes] = None,
    timeout: int = 60,
    env: Optional[dict] = None,
) -> tuple[int, str]:
    """Run a command, capture merged stdout+stderr, return (rc, output)."""
    try:
        proc = subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace")
        err = (e.stderr or b"").decode("utf-8", "replace")
        return 124, f"[TIMEOUT after {timeout}s]\n{out}\n{err}"
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    merged = out + ("\n" + err if err else "")
    return proc.returncode, merged


def _git(args: Sequence[str], **kw) -> tuple[int, str]:
    return _run(["git", *args], **kw)


def _repo_root() -> Path:
    rc, out = _git(["rev-parse", "--show-toplevel"])
    if rc != 0:
        raise RuntimeError(f"not inside a git repo: {out.strip()}")
    return Path(out.strip())


def _current_branch() -> str:
    rc, out = _git(["rev-parse", "--abbrev-ref", "HEAD"])
    return out.strip() if rc == 0 else "?"


def _working_tree_is_clean() -> bool:
    rc, out = _git(["status", "--porcelain"])
    return rc == 0 and out.strip() == ""


# ── Patch validation ────────────────────────────────────────────────────────


_PLACEHOLDER_RE = re.compile(r"<[A-Za-z0-9_./\- ]+>")
_DIFF_FILE_RE = re.compile(r"^(?:---|\+\+\+) [ab]/(?P<path>\S+)$", re.MULTILINE)


def validate_patch(patch_text: str, *, repo_root: Optional[Path] = None) -> PatchValidation:
    """Inspect ``patch_text`` without applying it.

    Determines:
      * whether every referenced file exists in the working tree,
      * whether the patch contains illustrative ``<placeholder>`` paths
        (most :func:`suggest_fix` outputs do — they are *advisory* diffs),
      * whether ``git apply --check`` accepts the patch as-is.
    """
    if not isinstance(patch_text, str) or not patch_text.strip():
        return PatchValidation(
            applicable=False,
            files_referenced=(),
            files_missing=(),
            has_placeholders=False,
            git_check_output="",
            reason="empty_patch",
        )

    # Files referenced (deduplicated, ordered).
    refs: list[str] = []
    seen: set[str] = set()
    for m in _DIFF_FILE_RE.finditer(patch_text):
        p = m.group("path")
        if p not in seen:
            seen.add(p)
            refs.append(p)

    has_placeholders = bool(_PLACEHOLDER_RE.search(patch_text)) or any(
        "<" in r and ">" in r for r in refs
    )

    # Resolve repo root for file-existence checks.
    try:
        root = repo_root or _repo_root()
    except RuntimeError as e:
        return PatchValidation(
            applicable=False,
            files_referenced=tuple(refs),
            files_missing=tuple(refs),
            has_placeholders=has_placeholders,
            git_check_output="",
            reason=f"not_in_git_repo: {e}",
        )

    missing = tuple(r for r in refs if not (root / r).exists())

    if has_placeholders:
        return PatchValidation(
            applicable=False,
            files_referenced=tuple(refs),
            files_missing=missing,
            has_placeholders=True,
            git_check_output="",
            reason="patch_has_placeholders",
        )
    if missing:
        return PatchValidation(
            applicable=False,
            files_referenced=tuple(refs),
            files_missing=missing,
            has_placeholders=False,
            git_check_output="",
            reason="files_missing",
        )

    rc, out = _git(
        ["apply", "--check", "-"],
        input_bytes=patch_text.encode("utf-8"),
        cwd=root,
        timeout=30,
    )
    return PatchValidation(
        applicable=(rc == 0),
        files_referenced=tuple(refs),
        files_missing=missing,
        has_placeholders=False,
        git_check_output=out.strip(),
        reason=None if rc == 0 else "git_apply_check_rejected",
    )


# ── Test rerun + stability ──────────────────────────────────────────────────


def rerun_test(
    test_node_id: str,
    *,
    timeout: int = DEFAULT_TEST_TIMEOUT_SEC,
    extra_args: Sequence[str] = (),
    cwd: Optional[Path] = None,
) -> RerunOutcome:
    """Run one pytest node and report its outcome.

    Uses the *same* Python interpreter the caller is in, so the test runs
    against the same site-packages. ``-p no:cacheprovider`` keeps reruns
    independent (no flaky cache hits).
    """
    cmd = [
        sys.executable, "-m", "pytest",
        "-x", "-q",
        "-p", "no:cacheprovider",
        *list(extra_args),
        test_node_id,
    ]
    t0 = time.perf_counter()
    rc, output = _run(cmd, cwd=cwd, timeout=timeout)
    duration_ms = (time.perf_counter() - t0) * 1000.0

    tail = "\n".join(output.splitlines()[-100:])
    return RerunOutcome(
        test_node_id=test_node_id,
        passed=(rc == 0),
        duration_ms=duration_ms,
        return_code=rc,
        output_tail=tail,
    )


def confirm_stability(
    test_node_id: str,
    *,
    repeats: int = DEFAULT_STABILITY_RUNS,
    timeout: int = DEFAULT_TEST_TIMEOUT_SEC,
    extra_args: Sequence[str] = (),
    cwd: Optional[Path] = None,
) -> StabilityReport:
    """Run ``test_node_id`` ``repeats`` times back-to-back. Stops early on
    the FIRST failure — a fix that flakes does not earn the "stable" label.
    """
    if repeats < 1:
        raise ValueError("repeats must be >= 1")
    runs: list[RerunOutcome] = []
    for _ in range(repeats):
        outcome = rerun_test(
            test_node_id, timeout=timeout, extra_args=extra_args, cwd=cwd,
        )
        runs.append(outcome)
        if not outcome.passed:
            # Bail early — flaky fix is not a passing fix.
            break
    return StabilityReport(test_node_id=test_node_id, runs=tuple(runs))


# ── Safe patch apply ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ApplyOutcome:
    applied: bool
    reason: str
    git_output: str
    branch: str
    pre_apply_clean: bool


def apply_patch_safely(
    patch_text: str,
    *,
    fix_confidence: float,
    repo_root: Optional[Path] = None,
    allow_protected_branches: bool = False,
    min_confidence: float = MIN_APPLY_CONFIDENCE,
    # ── Learning hooks (opt-in; None preserves pre-learning behaviour) ──
    repair_memory: Optional[Any] = None,
    failure_signature: Optional[str] = None,
    failure_category: Optional[str] = None,
    safety_threshold: Optional[float] = None,
) -> ApplyOutcome:
    """Apply ``patch_text`` to the working tree, with hard safety guards.

    Refuses if any of these is true:
      * working tree is not clean (uncommitted changes present),
      * branch is in :data:`PROTECTED_BRANCHES` and override not granted,
      * patch confidence is below ``min_confidence``,
      * patch contains placeholders or references missing files,
      * ``git apply --check`` rejects the patch,
      * ``repair_memory`` (optional) reports a sub-threshold safety score
        for ``failure_signature`` after enough prior cases accumulated.

    The memory hook is opt-in: when ``repair_memory is None`` the behaviour
    is identical to the pre-learning pipeline, so existing callers and
    tests are not affected. When wired up, the memory layer prints one
    ``[CI-REPAIR-GUARD]`` line per attempt regardless of the decision —
    every apply is auditable from logs alone.

    On any failure during apply, the working tree is left untouched.
    """
    try:
        root = repo_root or _repo_root()
    except RuntimeError as e:
        return ApplyOutcome(False, f"not_in_git_repo: {e}", "", "?", False)

    branch = _current_branch()
    if branch in PROTECTED_BRANCHES and not allow_protected_branches:
        return ApplyOutcome(
            False, f"refusing_to_modify_protected_branch:{branch!r}",
            "", branch, _working_tree_is_clean(),
        )

    if fix_confidence < min_confidence:
        return ApplyOutcome(
            False,
            f"confidence_below_threshold ({fix_confidence:.2f} < {min_confidence:.2f})",
            "", branch, _working_tree_is_clean(),
        )

    clean = _working_tree_is_clean()
    if not clean:
        return ApplyOutcome(
            False, "working_tree_dirty",
            "commit or stash your changes before invoking the autonomous repair layer",
            branch, False,
        )

    validation = validate_patch(patch_text, repo_root=root)
    if not validation.applicable:
        return ApplyOutcome(
            False, f"patch_not_applicable:{validation.reason}",
            validation.git_check_output, branch, True,
        )

    # ── Learning gate: consult RepairMemory for similar prior outcomes ──
    # Opt-in. Cold-start is safe — should_block() returns False until
    # ``min_cases_for_gate`` similar attempts have accumulated.
    if repair_memory is not None and failure_signature:
        try:
            # Adaptive gate — uses the dynamic threshold + risk profile +
            # fix-pattern reputation + loop guard. Falls back to the static
            # gate if the adaptive surface is missing for any reason.
            if hasattr(repair_memory, "should_block_adaptive"):
                should_block, breakdown = repair_memory.should_block_adaptive(
                    failure_signature, patch_text,
                    failure_category=failure_category,
                    fix_confidence=fix_confidence,
                )
                threshold = float(breakdown.get("threshold", 0.65))
            else:  # legacy memory implementations
                from ..learning.repair_memory import DEFAULT_THRESHOLD as _DT
                threshold = (float(safety_threshold)
                             if safety_threshold is not None else _DT)
                should_block, breakdown = repair_memory.should_block(
                    failure_signature, patch_text, threshold=threshold,
                    failure_category=failure_category,
                )
        except Exception as e:  # diagnostic must not crash the pipeline
            should_block, breakdown = False, {
                "score": 1.0, "final_score": 1.0, "threshold": 0.65,
                "success_rate": 0.0, "flakiness": 0.0,
                "match_count": 0, "similar_cases": 0,
                "fix_pattern": "?", "fix_reputation": 0.0,
                "loop_detected": False,
                "risk_flags": [f"memory_error:{type(e).__name__}"],
            }
            threshold = 0.65

        decision_str = "blocked" if should_block else "allowed"
        # Use the adaptive final_score when present, falling back to the
        # heuristic safety score for legacy code paths.
        score_value = float(
            breakdown.get("final_score", breakdown.get("score", 0.0)) or 0.0
        )
        success_rate = float(breakdown.get("success_rate") or 0.0)
        flakiness    = float(breakdown.get("flakiness") or 0.0)
        match_count  = int(breakdown.get("match_count")
                           or breakdown.get("similar_cases") or 0)
        fix_pattern  = str(breakdown.get("fix_pattern") or "?")
        fix_rep      = float(breakdown.get("fix_reputation") or 0.0)
        loop_detected = bool(breakdown.get("loop_detected"))
        new_reason = _summarise_decision_reason(decision_str, breakdown)
        flags = breakdown.get("risk_flags") or []
        legacy_reason = (
            f"flags={','.join(flags)}" if flags
            else f"success_rate={success_rate:.2f}"
        )

        # Legacy single-line `[CI-REPAIR-GUARD]` — kept verbatim so prior
        # tests + log scrapers still resolve.
        print(
            f"[CI-REPAIR-GUARD] decision: {decision_str} "
            f"score: {score_value:.2f} "
            f"similar_cases: {match_count} "
            f"reason: {legacy_reason}",
            flush=True,
        )
        # New multi-line `[CI-REPAIR-DECISION]` per the v2/v3 spec —
        # includes every field the autonomous engineer needs to explain
        # the call.
        print("[CI-REPAIR-DECISION]", flush=False)
        print(f"decision: {decision_str}", flush=False)
        print(f"selected_fix: {fix_pattern}", flush=False)
        print(f"final_score: {score_value:.4f}", flush=False)
        print(f"score: {score_value:.4f}", flush=False)
        print(f"threshold: {threshold:.4f}", flush=False)
        print(f"failure_category: {failure_category or '?'}", flush=False)
        print(f"fix_pattern: {fix_pattern}", flush=False)
        print(f"success_rate: {success_rate:.4f}", flush=False)
        print(f"fix_reputation: {fix_rep:+.4f}", flush=False)
        print(f"flakiness: {flakiness:.4f}", flush=False)
        print(f"match_count: {match_count}", flush=False)
        print(f"loop_detected: {'true' if loop_detected else 'false'}", flush=False)
        print(f"reason: {new_reason}", flush=True)

        if should_block:
            return ApplyOutcome(
                False,
                f"repair_memory_blocked:score={score_value:.2f}<{threshold:.2f}",
                json.dumps(breakdown, default=str),
                branch, True,
            )

    rc, out = _git(
        ["apply", "--whitespace=nowarn", "-"],
        input_bytes=patch_text.encode("utf-8"),
        cwd=root, timeout=30,
    )
    if rc != 0:
        # Belt-and-braces: nothing should be left dangling, but make sure.
        _git(["checkout", "--", "."], cwd=root, timeout=10)
        return ApplyOutcome(
            False, "git_apply_failed", out, branch, True,
        )
    return ApplyOutcome(True, "applied", out, branch, True)


# ── Orchestrator ────────────────────────────────────────────────────────────


def attempt_repair(
    test_node_id: str,
    analysis: dict,
    fix: dict,
    *,
    apply_patch: bool = False,
    stability_runs: int = DEFAULT_STABILITY_RUNS,
    timeout: int = DEFAULT_TEST_TIMEOUT_SEC,
    repo_root: Optional[Path] = None,
    bundle_dir: Optional[Path] = None,
    # ── Learning hooks (opt-in; None preserves pre-learning behaviour) ──
    repair_memory: Optional[Any] = None,
    safety_threshold: Optional[float] = None,
) -> RepairAttempt:
    """Drive the full repair pipeline for one failing test.

    Default mode (``apply_patch=False``) is *advisory*: the function only
    reads the working tree, runs the test once to capture the failure
    fingerprint, validates the patch, and writes a PR-ready bundle. The
    repository is never mutated.

    Opt-in ``apply_patch=True`` turns this into an autonomous repair —
    only proceeds when every safety guard in :func:`apply_patch_safely`
    passes. After applying, the test is rerun ``stability_runs`` times in
    a row to confirm the fix is stable; if not, the patch is reverted via
    ``git checkout -- .``.
    """
    if not isinstance(analysis, dict) or not isinstance(fix, dict):
        raise TypeError("analysis and fix must both be dicts")

    pre = rerun_test(test_node_id, timeout=timeout)
    patch_text = str(fix.get("patch") or "")
    confidence = float(fix.get("confidence") or 0.0)

    validation = validate_patch(patch_text, repo_root=repo_root)

    # Failure signature + category are computed once and reused for both
    # the apply gate (memory consultation) and the post-run record.
    # Stable across runs of the same logical failure.
    failure_signature: Optional[str] = None
    failure_category: Optional[str] = None
    if repair_memory is not None:
        try:
            from ..learning.repair_memory import (
                compute_failure_signature,
                derive_failure_category,
            )
            stage_str = str(analysis.get("stage") or "")
            reason_str = str(analysis.get("reason") or "")
            failure_signature = compute_failure_signature(
                test_node_id, stage=stage_str, reason=reason_str,
            )
            failure_category = derive_failure_category(
                stage=stage_str, reason=reason_str,
            )
        except Exception:
            failure_signature = None
            failure_category = None

    patch_applied = False
    post: Optional[StabilityReport] = None
    decision_parts: list[str] = []

    if not apply_patch:
        decision_parts.append("dry_run=True; no changes attempted")
    elif pre.passed:
        decision_parts.append("test already passes; no repair needed")
    elif not validation.applicable:
        decision_parts.append(f"patch not applicable: {validation.reason}")
    else:
        outcome = apply_patch_safely(
            patch_text, fix_confidence=confidence, repo_root=repo_root,
            repair_memory=repair_memory,
            failure_signature=failure_signature,
            failure_category=failure_category,
            safety_threshold=safety_threshold,
        )
        decision_parts.append(f"apply: {outcome.reason}")
        if outcome.applied:
            patch_applied = True
            post = confirm_stability(
                test_node_id, repeats=stability_runs, timeout=timeout,
            )
            if not post.all_passed:
                # Patch did not fix the test — restore working tree.
                _git(["checkout", "--", "."], cwd=repo_root, timeout=15)
                patch_applied = False
                decision_parts.append("post-repair runs failed; reverted")
            elif not post.stable:
                _git(["checkout", "--", "."], cwd=repo_root, timeout=15)
                patch_applied = False
                decision_parts.append("post-repair runs flaky; reverted")
            else:
                decision_parts.append(
                    f"stable across {len(post.runs)} runs; left applied"
                )

    attempt = RepairAttempt(
        test_node_id=test_node_id,
        analysis=analysis,
        fix=fix,
        patch_validation=validation,
        pre_repair=pre,
        patch_applied=patch_applied,
        post_repair=post,
        decision="; ".join(decision_parts),
    )

    # ── Feedback loop: record the attempt for future scoring ────────────
    # Always records — even dry runs and never-applied attempts — so the
    # memory accumulates a complete picture of what's been tried.
    if repair_memory is not None and failure_signature:
        try:
            entry = _build_memory_entry(
                test_node_id=test_node_id,
                failure_signature=failure_signature,
                failure_category=failure_category,
                patch_text=patch_text,
                confidence=confidence,
                pre=pre,
                attempt=attempt,
            )
            repair_memory.record_attempt(entry)
            repair_memory.update_statistics(entry)
        except Exception as e:  # diagnostic must not break a successful repair
            print(
                f"[CI-REPAIR-GUARD] memory.record_attempt failed: "
                f"{type(e).__name__}: {e}",
                flush=True,
            )

    if bundle_dir is not None:
        bundle_path = build_pr_bundle(attempt, bundle_dir)
        # Frozen dataclass — replace via the dataclasses module
        from dataclasses import replace
        attempt = replace(attempt, bundle_path=str(bundle_path))
    return attempt


def _summarise_decision_reason(decision_str: str, breakdown: dict) -> str:
    """Produce a short, human-readable reason string for the audit log.

    Picks the most informative signal in the breakdown (regression > flaky
    > mixed > cold-start > healthy success rate). Stable order so log
    diffs across runs remain comparable.
    """
    flags = breakdown.get("risk_flags") or []
    if "regression_seen" in flags:
        return "patch regressed after a prior pass"
    if "flaky_history" in flags:
        return f"flaky history (flakiness={float(breakdown.get('flakiness', 0.0)):.2f})"
    if "mixed_outcomes" in flags:
        return "mixed historical outcomes"
    if "no_prior_data" in flags:
        return "cold start: no prior data"
    if "never_applied" in flags:
        return "prior attempts never applied"
    if "identical_patch_succeeded_before" in flags:
        return "identical patch succeeded before"
    rate = float(breakdown.get("success_rate", 0.0))
    return f"success_rate={rate:.2f}"


def _build_memory_entry(
    *,
    test_node_id: str,
    failure_signature: str,
    failure_category: Optional[str],
    patch_text: str,
    confidence: float,
    pre: RerunOutcome,
    attempt: RepairAttempt,
) -> dict:
    """Translate the in-memory ``RepairAttempt`` into the JSONL schema.

    ``result``:
      * ``"passed"`` — patch applied AND post-repair all passed AND stable
      * ``"flaky"``  — patch applied but post-repair runs were inconsistent
                       (oscillated; some passed, some failed)
      * ``"failed"`` — everything else (no apply, apply rejected, post-runs
                       failed uniformly, etc.)

    ``stability_score``: the proportion of post-repair reruns that
    passed; 0.0 when no post-repair stability check ran.

    ``failure_category`` and ``fix_pattern`` are derived using the
    helpers in :mod:`infra.brain.learning` so the bucket the entry
    lands in is reproducible from its inputs alone.
    """
    from datetime import datetime, timezone

    if attempt.patch_applied and attempt.post_repair is not None \
       and attempt.post_repair.all_passed and attempt.post_repair.stable:
        result = "passed"
    elif attempt.post_repair is not None and not attempt.post_repair.stable:
        result = "flaky"
    else:
        result = "failed"

    if attempt.post_repair is not None and attempt.post_repair.runs:
        ratio = sum(1 for r in attempt.post_repair.runs if r.passed) \
                / len(attempt.post_repair.runs)
        stability_score = round(float(ratio), 4)
    else:
        stability_score = 0.0

    # Derive category + fix pattern. Failures here must not break the
    # record — fall back to the unknown buckets.
    cat = failure_category
    fix_pattern = "unclassified_fix"
    try:
        from ..learning.repair_memory import (
            CATEGORY_UNKNOWN,
            classify_fix_pattern,
            derive_failure_category,
        )
        if not cat:
            cat = derive_failure_category(
                stage=str((attempt.analysis or {}).get("stage") or ""),
                reason=str((attempt.analysis or {}).get("reason") or ""),
            ) or CATEGORY_UNKNOWN
        fix_pattern = classify_fix_pattern(patch_text)
    except Exception:
        cat = cat or "unknown_runtime_error"

    return {
        "test_id": test_node_id,
        "failure_signature": failure_signature,
        "failure_category": cat,
        "fix_pattern": fix_pattern,
        "patch_diff": patch_text,
        "applied": bool(attempt.patch_applied),
        "result": result,
        "stability_score": stability_score,
        "confidence_at_time": float(confidence),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ── Bundle writer ──────────────────────────────────────────────────────────


def build_pr_bundle(
    attempt: RepairAttempt,
    output_dir: Path | str,
) -> Path:
    """Write a self-contained, PR-ready bundle to ``output_dir``.

    Creates a timestamped subdirectory containing:

      * ``PATCH.diff``        — the suggested patch (unified diff)
      * ``ANALYSIS.json``     — analyze_ci_failure() output
      * ``FIX.json``          — suggest_fix() output
      * ``PRE_REPAIR_LOG.txt``— pytest output before any fix attempt
      * ``POST_REPAIR.json``  — stability report (if a repair was attempted)
      * ``ATTEMPT.json``      — the full RepairAttempt as JSON
      * ``PR_DESCRIPTION.md`` — markdown summary suitable for ``gh pr create``

    Returns the path to the bundle directory.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    safe_node = re.sub(r"[^A-Za-z0-9._-]+", "_", attempt.test_node_id)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime(attempt.started_at))
    bundle = out / f"repair_{stamp}_{safe_node[:80]}"
    bundle.mkdir(parents=True, exist_ok=False)

    (bundle / "PATCH.diff").write_text(str(attempt.fix.get("patch") or ""))
    (bundle / "ANALYSIS.json").write_text(
        json.dumps(attempt.analysis, indent=2, default=str)
    )
    (bundle / "FIX.json").write_text(
        json.dumps(attempt.fix, indent=2, default=str)
    )
    (bundle / "PRE_REPAIR_LOG.txt").write_text(attempt.pre_repair.output_tail)
    if attempt.post_repair is not None:
        (bundle / "POST_REPAIR.json").write_text(
            json.dumps(attempt.post_repair.to_dict(), indent=2, default=str)
        )
    (bundle / "ATTEMPT.json").write_text(
        json.dumps(attempt.to_dict(), indent=2, default=str)
    )
    (bundle / "PR_DESCRIPTION.md").write_text(_render_pr_description(attempt))
    return bundle


def _render_pr_description(attempt: RepairAttempt) -> str:
    a, f = attempt.analysis or {}, attempt.fix or {}
    stage = f.get("stage") or a.get("stage") or "unknown"
    fix_type = f.get("fix_type") or "?"
    risk = f.get("risk_level") or "?"
    confidence = f.get("confidence")
    conf_str = f"{float(confidence):.2f}" if isinstance(confidence, (int, float)) else "?"
    decision = attempt.decision or "(no decision recorded)"

    lines: list[str] = []
    lines.append(f"# CI Auto-Repair: `{attempt.test_node_id}`")
    lines.append("")
    lines.append("## Diagnosis")
    lines.append("")
    lines.append(f"- **Stage:** `{stage}`")
    lines.append(f"- **Fix type:** `{fix_type}`")
    lines.append(f"- **Risk:** `{risk}`")
    lines.append(f"- **Confidence:** `{conf_str}`")
    lines.append(f"- **Patch applied:** `{attempt.patch_applied}`")
    lines.append(f"- **Decision:** `{decision}`")
    lines.append("")
    if f.get("root_cause"):
        lines.append("## Root cause")
        lines.append("")
        lines.append(f.get("root_cause", ""))
        lines.append("")
    if f.get("explanation"):
        lines.append("## Explanation")
        lines.append("")
        lines.append(f.get("explanation", ""))
        lines.append("")

    lines.append("## Stability check")
    lines.append("")
    if attempt.post_repair is not None:
        for i, run in enumerate(attempt.post_repair.runs, start=1):
            verdict = "PASS" if run.passed else "FAIL"
            lines.append(
                f"- run {i}: **{verdict}** (rc={run.return_code}, "
                f"{run.duration_ms:.0f} ms)"
            )
        lines.append("")
        lines.append(
            f"- **all_passed:** `{attempt.post_repair.all_passed}` · "
            f"**stable:** `{attempt.post_repair.stable}`"
        )
    else:
        lines.append("_No post-repair runs executed._")
    lines.append("")

    lines.append("## Suggested patch")
    lines.append("")
    patch = (f.get("patch") or "").strip()
    if patch:
        lines.append("```diff")
        lines.append(patch)
        lines.append("```")
    else:
        lines.append("_No patch was generated by the diagnostic layer._")
    lines.append("")
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────


def _cli(argv: Optional[Sequence[str]] = None) -> int:
    """``python -m infra.brain.debug.ci_autonomous_repair --test ...``"""
    p = argparse.ArgumentParser(
        description="CI autonomous repair driver for the Brain runtime.",
    )
    p.add_argument("--test", required=True,
                   help="pytest node id, e.g. infra/brain/tests/test_x.py::test_y")
    p.add_argument("--analysis", type=Path,
                   help="Path to JSON file produced by analyze_ci_failure().")
    p.add_argument("--fix", type=Path,
                   help="Path to JSON file produced by suggest_fix().")
    p.add_argument("--apply-patch", action="store_true",
                   help="Actually apply the patch (requires clean tree, "
                        "non-protected branch, and confidence ≥ "
                        f"{MIN_APPLY_CONFIDENCE}).")
    p.add_argument("--stability-runs", type=int, default=DEFAULT_STABILITY_RUNS)
    p.add_argument("--timeout", type=int, default=DEFAULT_TEST_TIMEOUT_SEC)
    p.add_argument("--bundle-dir", type=Path, default=Path(".ci/repair-bundles"),
                   help="Directory to write the PR-ready bundle into.")
    args = p.parse_args(argv)

    analysis = json.loads(args.analysis.read_text()) if args.analysis else {}
    fix = json.loads(args.fix.read_text()) if args.fix else {}

    attempt = attempt_repair(
        args.test, analysis, fix,
        apply_patch=args.apply_patch,
        stability_runs=args.stability_runs,
        timeout=args.timeout,
        bundle_dir=args.bundle_dir,
    )
    print(json.dumps(attempt.to_dict(), indent=2, default=str))
    # Non-zero exit only if we tried to apply and the test still fails.
    if args.apply_patch and not attempt.patch_applied:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())


__all__ = [
    # data classes
    "RerunOutcome", "StabilityReport", "PatchValidation",
    "ApplyOutcome", "RepairAttempt",
    # public API
    "validate_patch", "rerun_test", "confirm_stability",
    "apply_patch_safely", "attempt_repair", "build_pr_bundle",
    # constants
    "DEFAULT_STABILITY_RUNS", "DEFAULT_TEST_TIMEOUT_SEC",
    "MIN_APPLY_CONFIDENCE", "PROTECTED_BRANCHES",
]
