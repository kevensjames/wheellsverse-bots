#!/usr/bin/env python3
"""SUPREMA autorepair — orchestration engine.

Walks the catalog × project matrix, runs scanners, dispatches fixers,
records findings to state, emits notifications.

Project layout assumed:
    /Volumes/Wheellsverse/narai
    /Volumes/Wheellsverse/wheellsverse-bots
    /Volumes/Wheellsverse/nexora
    /Volumes/Wheellsverse/sol
    /Volumes/Wheellsverse/toodle
    /Volumes/Wheellsverse/kdp-autopilot

Each scanner exports `scan(project_path: Path) -> list[Finding]`.
Each fixer exports `apply(project_path: Path, finding: Finding) -> FixResult`.

A Finding has a `safety` flag — only `auto-safe` findings get fixed without
human review. Everything else is recorded and reported.
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# ── Project layout ─────────────────────────────────────────────────────────
SUPREMA_ROOT = Path("/Volumes/Wheellsverse")
PROJECTS: tuple[str, ...] = (
    "narai",
    "wheellsverse-bots",
    "nexora",
    "sol",
    "toodle",
    "kdp-autopilot",
)

# Some projects have a live URL we can probe; others are spec-kit constituted
# but not yet deployed.
LIVE_URLS: dict[str, str] = {
    "wheellsverse-bots": "https://app.wheellsverse.com",
}

# ── Catalog ────────────────────────────────────────────────────────────────
# Pattern → (scanner_module, fixer_module_or_None, default_safety).
#
# safety: "auto-safe"  → engine applies fixer without asking
#         "review"     → engine reports, never applies
#         "blocked"    → engine never even suggests a fix (informational only)
CATALOG: dict[str, dict[str, Any]] = {
    "missing_pwa_manifest": {
        "scanner": "scanners.missing_pwa_manifest",
        "fixer":   "fixers.create_pwa_manifest",
        "safety":  "auto-safe",
        "title":   "PWA manifest referenced but not served",
    },
    "missing_service_worker": {
        "scanner": "scanners.missing_service_worker",
        "fixer":   "fixers.create_service_worker",
        "safety":  "auto-safe",
        "title":   "Service worker registered but not served",
    },
    "missing_favicon": {
        "scanner": "scanners.missing_favicon",
        "fixer":   "fixers.create_favicon",
        "safety":  "auto-safe",
        "title":   "Favicon 404 on page load",
    },
    "malformed_api_helper_call": {
        "scanner": "scanners.malformed_api_helper_call",
        "fixer":   "fixers.repair_api_helper_call",
        "safety":  "auto-safe",
        "title":   "api() helper called with options-bag instead of positional method",
    },
    "stale_git_sha_health": {
        "scanner": "scanners.stale_git_sha_health",
        "fixer":   None,
        "safety":  "review",
        "title":   "/api/health reports a git_sha that disagrees with the deployed image",
    },
    "dep_resolution_blocker": {
        "scanner": "scanners.dep_resolution_blocker",
        "fixer":   None,
        "safety":  "review",
        "title":   "requirements.txt has unresolvable version conflicts",
    },
    "frontend_backend_diff": {
        "scanner": "scanners.frontend_backend_diff",
        "fixer":   None,
        "safety":  "review",
        "title":   "Frontend calls endpoints with no matching backend handler",
    },
    "deploy_stale": {
        "scanner": "scanners.deploy_stale",
        "fixer":   None,
        "safety":  "blocked",
        "title":   "Production deploy has not refreshed recently",
    },
    "hardcoded_localhost": {
        "scanner": "scanners.hardcoded_localhost",
        "fixer":   None,           # review-only; auto-replace risks dev workflow
        "safety":  "review",
        "title":   "Hardcoded localhost:PORT URL in deployed frontend",
    },
    "fastapi_deprecated_event_handler": {
        "scanner": "scanners.fastapi_deprecated_event_handler",
        "fixer":   None,           # startup hooks are too sensitive for auto-rewrite
        "safety":  "review",
        "title":   "FastAPI add_event_handler / @on_event — migrate to lifespan",
    },
    "committed_runtime_state": {
        "scanner": "scanners.committed_runtime_state",
        "fixer":   "fixers.untrack_runtime_state",
        "safety":  "auto-safe",
        "title":   "Runtime state / logs / secrets committed to git",
    },
    "sync_io_in_async_handler": {
        "scanner": "scanners.sync_io_in_async_handler",
        "fixer":   None,           # rewrites are too context-sensitive for auto-fix
        "safety":  "review",
        "title":   "Synchronous blocking I/O inside an async function — blocks the event loop",
    },
    "anthropic_credit_low": {
        "scanner": "scanners.anthropic_credit_low",
        "fixer":   None,           # top-up is operator action
        "safety":  "review",
        "title":   "Anthropic API credit low / exhausted — LLM endpoints will fail",
    },
    "deploy_freshness_diff": {
        "scanner": "scanners.deploy_freshness_diff",
        "fixer":   None,           # deploys are operator-triggered
        "safety":  "review",
        "title":   "Local main is ahead of what's deployed — operator forgot to ship",
    },
}


# ── Types ──────────────────────────────────────────────────────────────────
@dataclass
class Finding:
    pattern: str          # catalog key
    project: str          # project folder name
    severity: str         # "low" | "medium" | "high"
    location: str         # human-readable location ("dashboard/index.html:15750")
    evidence: str         # ≤ 200-char snippet or fact
    fix_payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class FixResult:
    success: bool
    changed_files: list[str] = field(default_factory=list)
    message: str = ""
    risk_notes: str = ""
    # Fixers that only touch metadata (.gitignore, README, etc.) and never
    # change executable code can set this to False to skip smoke-test gating.
    # Default True so untrusted/new fixers stay safe.
    requires_smoke_test: bool = True

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


# ── Logging ────────────────────────────────────────────────────────────────
def _setup_logging() -> logging.Logger:
    log_dir = Path(__file__).parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"autorepair-{time.strftime('%Y%m%d')}.log"

    logger = logging.getLogger("suprema.autorepair")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                            "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_file)
    fh.setFormatter(fmt)
    logger.addHandler(fh)
    if os.getenv("SUPREMA_STDOUT", "1") == "1":
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        logger.addHandler(sh)
    return logger


log = _setup_logging()


# ── State persistence ──────────────────────────────────────────────────────
STATE_DIR = Path(__file__).parent / "state"
LAST_RUN = STATE_DIR / "last-run.json"
HISTORY = STATE_DIR / "history.jsonl"


def _write_state(record: dict[str, Any]) -> None:
    STATE_DIR.mkdir(exist_ok=True)
    LAST_RUN.write_text(json.dumps(record, indent=2))
    with HISTORY.open("a") as f:
        f.write(json.dumps(record) + "\n")


# ── Engine ─────────────────────────────────────────────────────────────────
def _load(name: str):
    """Import a scanner or fixer module by its dotted catalog name."""
    return importlib.import_module(f"suprema.autorepair.{name}")


def project_path(project: str) -> Path:
    return SUPREMA_ROOT / project


def discover_projects() -> list[str]:
    return [p for p in PROJECTS if project_path(p).is_dir()]


def run_scan(only_projects: Iterable[str] | None = None) -> list[Finding]:
    """Run every scanner against every project. Returns a flat list of Findings."""
    from suprema.autorepair.safety import kill_switch as ks
    if ks.disabled_globally():
        log.warning("SUPREMA_DISABLE=1 — scan returning empty findings list")
        return []

    projects = list(only_projects) if only_projects else discover_projects()
    env_skip_projects = ks.skipped_projects()
    env_skip_patterns = ks.skipped_patterns()
    all_findings: list[Finding] = []

    for pattern, meta in CATALOG.items():
        if pattern in env_skip_patterns:
            log.info(f"scanner [{pattern}] skipped via SUPREMA_SKIP")
            continue
        try:
            mod = _load(meta["scanner"])
        except Exception as e:
            log.warning(f"scanner [{pattern}] failed to import: {e}")
            continue

        for proj in projects:
            if proj in env_skip_projects:
                continue
            ppath = project_path(proj)
            if not ppath.is_dir():
                continue
            if not ks.project_enabled(ppath):
                continue
            if ks.project_skips_pattern(ppath, pattern):
                continue
            try:
                results = mod.scan(ppath, live_url=LIVE_URLS.get(proj))
            except TypeError:
                # backwards-compat: scanner without live_url kwarg
                results = mod.scan(ppath)
            except Exception as e:
                log.warning(f"scanner [{pattern}] crashed on {proj}: {e}")
                continue

            for r in results:
                if isinstance(r, Finding):
                    r.pattern = pattern
                    r.project = proj
                    all_findings.append(r)
                elif isinstance(r, dict):
                    all_findings.append(Finding(
                        pattern=pattern,
                        project=proj,
                        severity=r.get("severity", "medium"),
                        location=r.get("location", ""),
                        evidence=r.get("evidence", ""),
                        fix_payload=r.get("fix_payload", {}),
                    ))

    log.info(f"scan complete: {len(all_findings)} findings across "
             f"{len(projects)} projects, {len(CATALOG)} patterns")
    return all_findings


def run_fix(findings: list[Finding], dry_run: bool = False) -> list[tuple[Finding, FixResult]]:
    """Apply auto-safe fixes for each finding. Returns (finding, result) pairs.

    Only findings whose pattern has safety=='auto-safe' AND a registered
    fixer module get applied. Everything else is skipped with a recorded
    reason."""
    from suprema.autorepair.safety import kill_switch as ks, smoke_test
    results: list[tuple[Finding, FixResult]] = []
    if ks.force_dry_run():
        dry_run = True

    # Group findings by (project, pattern) so we run one smoke test per
    # batch of related fixes rather than per finding.
    for f in findings:
        meta = CATALOG.get(f.pattern)
        if not meta:
            results.append((f, FixResult(False, message=f"unknown pattern {f.pattern}")))
            continue

        # Per-project safety override may demote auto-safe → review
        proj_path = project_path(f.project)
        effective = ks.effective_safety(proj_path, f.pattern, meta["safety"])
        if effective != "auto-safe":
            results.append((f, FixResult(False, message=f"safety={effective} — skipped")))
            continue
        if not meta.get("fixer"):
            results.append((f, FixResult(False, message="no fixer registered")))
            continue

        if dry_run:
            results.append((f, FixResult(True, message="(dry-run) would apply fixer")))
            continue

        # Capture pre-fix snapshot so we can revert if smoke test fails
        pre_stash = smoke_test.stash_create(proj_path, f"autorepair-pre-{f.pattern}")

        try:
            mod = _load(meta["fixer"])
            res = mod.apply(proj_path, f)
            if not isinstance(res, FixResult):
                if isinstance(res, dict):
                    res = FixResult(**res)
                else:
                    res = FixResult(False, message=f"fixer returned {type(res).__name__}")

            # Smoke-test gating: only run if the fixer actually changed
            # files AND the fixer says it requires smoke-testing
            if res.success and res.changed_files and not skip_smoke() \
                    and getattr(res, "requires_smoke_test", True):
                passed, msg = smoke_test.run(proj_path)
                if not passed:
                    log.warning(f"SMOKE TEST FAILED on {f.project}:{f.pattern} → {msg}")
                    # Restore from pre-fix snapshot
                    if pre_stash and smoke_test.restore(proj_path, pre_stash):
                        res = FixResult(
                            False,
                            changed_files=[],
                            message=f"smoke test failed, reverted: {msg[:200]}",
                            risk_notes="files restored to pre-fix state via git stash",
                        )
                    else:
                        res = FixResult(
                            False,
                            changed_files=res.changed_files,
                            message=f"smoke test failed AND restore failed: {msg[:200]}",
                            risk_notes="MANUAL INTERVENTION REQUIRED — broken files on disk",
                        )

            results.append((f, res))
            log.info(f"FIX {f.project}:{f.pattern} → success={res.success} "
                     f"changed={len(res.changed_files)}")
        except Exception as e:
            log.exception(f"fixer [{meta['fixer']}] crashed on {f.project}")
            results.append((f, FixResult(False, message=f"fixer crashed: {e}")))

    return results


def skip_smoke() -> bool:
    return os.getenv("SUPREMA_SKIP_SMOKE_TEST", "").strip() in ("1", "true", "yes")


def run_cycle(do_fix: bool = True, dry_run: bool = False,
              only_projects: Iterable[str] | None = None,
              llm_triage: bool = False,
              triage_confidence_threshold: float = 0.8) -> dict[str, Any]:
    """One full cycle: scan, optionally LLM-triage review findings, optionally
    fix, write state, return summary."""
    start = time.time()
    findings = run_scan(only_projects=only_projects)

    triage_results: dict[int, Any] = {}
    if llm_triage and findings:
        from suprema.autorepair import triage
        # Triage review-tier findings only (auto-safe already fixes, blocked never fixes)
        review_indexes = [
            i for i, f in enumerate(findings)
            if CATALOG.get(f.pattern, {}).get("safety") == "review"
        ]
        if review_indexes:
            log.info(f"LLM triage starting on {len(review_indexes)} review-tier findings")
            review_dicts = [findings[i].as_dict() for i in review_indexes]
            tr_results = triage.triage_batch(
                review_dicts, project_path, CATALOG,
            )
            # Map back to original finding indexes
            for sub_idx, finding_idx in enumerate(review_indexes):
                if sub_idx in tr_results:
                    triage_results[finding_idx] = tr_results[sub_idx]

    fix_outcomes: list[tuple[Finding, FixResult]] = []
    if do_fix:
        fix_outcomes = run_fix(findings, dry_run=dry_run)

    # Attach triage verdicts to findings if we ran them
    findings_with_triage: list[dict] = []
    for i, fnd in enumerate(findings):
        d = fnd.as_dict()
        if i in triage_results:
            d["triage"] = triage_results[i].as_dict() if hasattr(
                triage_results[i], "as_dict") else triage_results[i]
        findings_with_triage.append(d)

    # Apply operator suppressions — split into visible vs hidden so the
    # panel renders cleanly but suppressed items remain auditable.
    try:
        from suprema.autorepair import suppressions
        visible, hidden = suppressions.filter_findings(findings_with_triage)
    except Exception as e:
        log.warning(f"suppressions module unavailable: {e}")
        visible, hidden = findings_with_triage, []

    summary = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)),
        "elapsed_s": round(time.time() - start, 2),
        "findings_count": len(visible),
        "findings_total": len(findings_with_triage),
        "findings_suppressed": len(hidden),
        "findings": visible,
        "findings_hidden": hidden,
        "fixes_attempted": len(fix_outcomes),
        "fixes_succeeded": sum(1 for _, r in fix_outcomes if r.success),
        "fix_outcomes": [{"finding": f.as_dict(), "result": r.as_dict()}
                         for f, r in fix_outcomes],
        "dry_run": dry_run,
        "llm_triage": {
            "ran": bool(triage_results),
            "real_bugs": sum(1 for tr in triage_results.values()
                             if getattr(tr, "verdict", "") == "real_bug"),
            "false_positives": sum(1 for tr in triage_results.values()
                                   if getattr(tr, "verdict", "") == "false_positive"),
            "uncertain": sum(1 for tr in triage_results.values()
                             if getattr(tr, "verdict", "") == "uncertain"),
            "tokens_used": sum(getattr(tr, "tokens_used", 0)
                               for tr in triage_results.values()),
            "confidence_threshold": triage_confidence_threshold,
        } if llm_triage else None,
    }
    _write_state(summary)
    log.info(f"cycle done in {summary['elapsed_s']}s — "
             f"{summary['findings_count']} findings, "
             f"{summary['fixes_succeeded']}/{summary['fixes_attempted']} auto-fixed")

    # Sync state to wheellsverse-bots so the prod /admin SUPREMA panel can
    # display this data. Non-fatal: if push fails, state still lives locally.
    if os.getenv("SUPREMA_SKIP_STATE_SYNC", "").strip() not in ("1", "true"):
        try:
            from suprema.autorepair import state_sync
            sync_result = state_sync.sync_to_wheellsverse_bots(LAST_RUN)
            if sync_result.get("ok"):
                log.info(f"state-sync: {sync_result.get('message') or 'pushed'}")
            else:
                log.warning(f"state-sync failed: {sync_result.get('reason')}")
        except Exception as e:
            log.warning(f"state-sync crashed: {e}")

    return summary


if __name__ == "__main__":
    # Quick smoke test: scan only
    summary = run_cycle(do_fix=False)
    print(json.dumps(summary, indent=2)[:2000])
