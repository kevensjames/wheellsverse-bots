"""RUN_INTERNAL_TEST runtime (Part C, §26-37) — the first A1 (COMPUTE_ONLY) execution capability.

KAI verifies hypotheses itself instead of handing testing back to the owner. The contract is an
allowlisted TestSuiteRegistry: the client submits a suite_id ONLY (§27-28). The server owns every
execution detail (command, cwd, timeout, env, resource ceiling); a task can NEVER supply a command,
shell, args, cwd, or env override. Test FAILURE is a valid COMPLETED execution (§32), never
misclassified as an infra error. Real parsed output — no agent summary substitutes for it (§30).

Genuinely certified: the in-process bounded-subprocess runner over known read-only suites. Dispatch to
the isolated worker plane for heavier/mutating suites is a declared follow-on (worker offline →
BLOCKED_WORKER §35). run_fn is injectable so policy/parse/failure tests are deterministic.
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path

_BACKEND = str(Path(__file__).resolve().parents[3])   # backend/

MAX_OUTPUT_BYTES = 64 * 1024
DEFAULT_TIMEOUT = 120


class TestDenied(Exception):
    """Raised for an unknown/disabled/cross-company suite or any command-injection attempt."""


@dataclass(frozen=True)
class SuiteDef:
    suite_id: str
    command: tuple          # fixed arg list — NEVER from task input (§28)
    cwd: str
    timeout: int = DEFAULT_TIMEOUT
    env_profile: tuple = ()  # server-owned (key, value) pairs; e.g. PYTHONPATH
    company_id: str = ""     # "" = holding-wide; else scoped to one company (§36)
    enabled: bool = True


# Server-owned registry. Certified suites are known READ-ONLY (they mutate nothing, need no DB).
_SUITES: dict[str, SuiteDef] = {
    "holding_self_model": SuiteDef("holding_self_model",
        ("python3", "app/services/holding/test_self_model.py"), _BACKEND,
        env_profile=(("PYTHONPATH", _BACKEND),)),
    "holding_reconciler": SuiteDef("holding_reconciler",
        ("python3", "app/services/holding/test_state_reconciler.py"), _BACKEND,
        env_profile=(("PYTHONPATH", _BACKEND),)),
    "disabled_example": SuiteDef("disabled_example", ("python3", "-c", "pass"), _BACKEND, enabled=False),
}


def register_suite(suite: SuiteDef) -> None:
    _SUITES[suite.suite_id] = suite


_SUITE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_:-]{1,63}$")   # no path chars, no shell metacharacters


def resolve_suite(suite_id, *, company_id: str = "", suites: dict | None = None) -> SuiteDef:
    """Map a suite_id to its server-owned definition. Rejects traversal/shell in the id, unknown or
    disabled suites, and a suite scoped to a different company (§36)."""
    if not isinstance(suite_id, str) or not _SUITE_ID_RE.match(suite_id):
        raise TestDenied("invalid suite_id")               # blocks '../..', 'rm -rf', metacharacters
    sd = (suites if suites is not None else _SUITES).get(suite_id)
    if sd is None:
        raise TestDenied(f"unknown suite '{suite_id}'")
    if not sd.enabled:
        raise TestDenied(f"suite '{suite_id}' disabled")
    if sd.company_id and company_id and sd.company_id != company_id:
        raise TestDenied("suite scoped to a different company")
    return sd


# task payload keys that must NEVER influence execution (§28) — presence = injection attempt
_FORBIDDEN_TASK_KEYS = {"command", "shell", "args", "argv", "cwd", "working_directory", "env",
                        "environment", "entrypoint", "cmd"}

_COUNT_RE = {k: re.compile(rf"(\d+) {k}") for k in ("passed", "failed", "skipped", "error", "errors")}


def _parse_counts(out: str) -> dict:
    def n(key):
        m = _COUNT_RE[key].search(out or "")
        return int(m.group(1)) if m else 0
    return {"passed": n("passed"), "failed": n("failed"), "skipped": n("skipped"),
            "errors": n("error") + n("errors")}


class TestSuiteRunner:
    def __init__(self, *, run_fn=None, clock=None):
        self._run = run_fn or subprocess.run
        self._clock = clock or __import__("time").monotonic

    def run(self, sd: SuiteDef, *, commit_sha: str = "UNAVAILABLE") -> dict:
        t0 = self._clock()
        try:
            res = self._run(list(sd.command), cwd=sd.cwd, env=dict(sd.env_profile) or None,
                            capture_output=True, text=True, timeout=sd.timeout)
        except subprocess.TimeoutExpired:
            return {"suite": sd.suite_id, "execution": "TIMEOUT", "test_result": "UNAVAILABLE",
                    "duration_s": round(self._clock() - t0, 3), "exit_status": None}
        out = ((getattr(res, "stdout", "") or "") + (getattr(res, "stderr", "") or ""))[:MAX_OUTPUT_BYTES]
        counts = _parse_counts(out)
        exit_status = getattr(res, "returncode", 1)
        # §32: tests failing is a COMPLETED execution with test_result FAILED — not an infra error.
        test_result = "PASSED" if exit_status == 0 else "FAILED"
        return {"suite": sd.suite_id, "execution": "COMPLETED", "test_result": test_result,
                "worker_id": "in-process-runner", "commit_sha": commit_sha,
                "tests_discovered": counts["passed"] + counts["failed"] + counts["skipped"],
                "passed": counts["passed"], "failed": counts["failed"], "skipped": counts["skipped"],
                "errors": counts["errors"], "exit_status": exit_status,
                "duration_s": round(self._clock() - t0, 3),
                "output_ref": out[:2000]}   # bounded excerpt; full output would go to an artifact store


def make_internal_test_provider(*, run_fn=None, suites: dict | None = None, clock=None):
    """Return provider(args) for the composite executor. args carries suite_id (+ company_id). Any
    command/shell/cwd/env key in the payload is a hard denial (§28). Fails closed on unknown/disabled
    suite or invalid id. Test failure returns evidence with test_result=FAILED (not an error)."""
    runner = TestSuiteRunner(run_fn=run_fn, clock=clock)

    def provider(args: dict) -> dict:
        args = args or {}
        if _FORBIDDEN_TASK_KEYS & set(args):
            raise TestDenied("command/shell/cwd/env override is not permitted")
        sd = resolve_suite(args.get("suite_id", ""), company_id=args.get("company_id", ""), suites=suites)
        commit = "UNAVAILABLE"
        try:
            from app.services.holding.repo_inspect import LocalGitProvider
            commit = LocalGitProvider(sd.cwd).repository_status().get("commit_sha", "UNAVAILABLE")
        except Exception:
            pass
        if commit in (None, "", "UNAVAILABLE"):
            # containerized deploy: .git is excluded from the image, so the local git read fails. Use the
            # platform-injected deploy SHA (Railway sets RAILWAY_GIT_COMMIT_SHA) so evidence still carries
            # the exact commit the running container was built from — the authoritative deployed SHA.
            import os
            commit = os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("GIT_COMMIT_SHA") or "UNAVAILABLE"
        ev = runner.run(sd, commit_sha=commit)
        from app.services.holding.task_resolver import redact
        return redact(ev)                                   # evidence redacted before it leaves (§29)

    return provider


if __name__ == "__main__":
    from app.services.holding.test_internal_test import run
    run()
